"""Traducir entero el guion de un juego desde la interfaz, como `vn-audiolibro traducir-guion`.

El diálogo es modal: mientras traduce no se puede jugar, porque los dos arrancan `llama-server` y
no caben juntos en un equipo de 8 GB.
"""

import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.guion.modelos import GuionNoEncontradoError
from vn_audiolibro.guion.previa import PreparadorGuion
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.sesion import traductor_guion
from vn_audiolibro.textos import _, ngettext
from vn_audiolibro.traduccion.gemini import POR_DIA, TAMANO_LOTE
from vn_audiolibro.traduccion.modelos import Motor, TraduccionFallidaError

_registro = logging.getLogger(__name__)

AbrirTraductor = Callable[[Perfil, Callable[[str], None]], AbstractContextManager[PreparadorGuion]]

CANCELADO = "cancelado"


def duracion(segundos: float) -> str:
    """Duración legible y redondeada: «menos de 1 min», «25 min», «3 h 05 min»."""
    minutos = round(segundos / 60)
    if minutos < 1:
        return _("menos de 1 min")
    if minutos < 60:
        return _("{minutos} min").format(minutos=minutos)
    return _("{horas} h {minutos:02d} min").format(horas=minutos // 60, minutos=minutos % 60)


class TraducirGuion(QDialog):
    """Traduce en segundo plano lo que falte del guion, con el progreso y el tiempo que queda.

    Se puede parar en cualquier momento: lo traducido queda en la caché y la próxima vez sigue
    por donde se quedó.
    """

    estado = Signal(str)
    inicio = Signal(int)
    """Párrafos que faltaban al empezar."""
    progreso = Signal(int, int)
    """Párrafos hechos (ahora o antes) y total."""
    traducido = Signal()
    terminado = Signal(str)
    """Vacío si se ha terminado; si no, el error o `CANCELADO`."""

    def __init__(
        self,
        perfil: Perfil,
        abrir: AbrirTraductor = traductor_guion,
        reloj: Callable[[], float] = time.monotonic,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Traducir el guion"))
        self.resize(520, 240)
        self._perfil = perfil
        self._abrir = abrir
        self._reloj = reloj
        self._cancelar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._traduciendo = False
        self._empezado = 0.0
        self._pendientes = 0
        self._traducidos = 0
        self.traducidos_al_terminar: int | None = None

        if perfil.traductor is Motor.GEMINI:
            como = _(
                "Con Gemini se traducen {lineas} líneas por petición. El plan gratuito permite unas "
                "{peticiones} peticiones al día: si se agotan, sigue otro día."
            ).format(lineas=TAMANO_LOTE, peticiones=POR_DIA)
        else:
            como = _("Con el traductor local puede tardar varias horas en un guion largo.")
        self.explicacion = QLabel(
            _(
                "Traduce entero el guion de «{nombre}» antes de jugar: al jugar, todo saldrá de la "
                "caché al momento.\n\n{como} Puedes parar cuando quieras y seguir otro día: lo "
                "traducido se conserva. Mientras traduce no se puede jugar."
            ).format(nombre=perfil.nombre, como=como)
        )
        self.explicacion.setWordWrap(True)
        self.barra = QProgressBar()
        self.barra.setVisible(False)
        self.mensaje = QLabel()
        self.mensaje.setWordWrap(True)
        self.tiempo = QLabel()
        self.boton_empezar = QPushButton(_("Empezar"))
        self.boton_empezar.setDefault(True)
        self.boton_cerrar = QPushButton(_("Cerrar"))
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.boton_cerrar)
        botones.addWidget(self.boton_empezar)
        columna = QVBoxLayout(self)
        columna.addWidget(self.explicacion)
        columna.addWidget(self.barra)
        columna.addWidget(self.mensaje)
        columna.addWidget(self.tiempo)
        columna.addStretch()
        columna.addLayout(botones)

        self._reloj_pantalla = QTimer(self)
        self._reloj_pantalla.setInterval(1000)
        self._reloj_pantalla.timeout.connect(self._mostrar_tiempo)
        self.boton_empezar.clicked.connect(self.empezar)
        self.boton_cerrar.clicked.connect(self._cerrar_o_parar)
        self.estado.connect(self.mensaje.setText)
        self.inicio.connect(self._al_empezar)
        self.progreso.connect(self._mostrar_progreso)
        self.traducido.connect(self._contar)
        self.terminado.connect(self._al_terminar)

    @property
    def traduciendo(self) -> bool:
        """De `empezar` hasta que se atiende `terminado`."""
        return self._traduciendo

    def empezar(self) -> None:
        if self._traduciendo:
            return
        self.esperar()
        self._traduciendo = True
        self._cancelar.clear()
        self._traducidos = 0
        self.traducidos_al_terminar = None
        self.boton_empezar.setEnabled(False)
        self.boton_cerrar.setText(_("Parar"))
        self.tiempo.clear()
        self._hilo = threading.Thread(target=self._traducir, name="traducir-guion", daemon=True)
        self._hilo.start()

    def esperar(self, timeout_s: float | None = None) -> None:
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def _traducir(self) -> None:
        try:
            with self._abrir(self._perfil, self.estado.emit) as preparador:
                self.estado.emit(_("Buscando lo que falta por traducir…"))
                self.inicio.emit(preparador.pendientes())
                traducidos = preparador.traducir_todo(
                    self.progreso.emit, self._cancelar.is_set, self.traducido.emit
                )
        except (GuionNoEncontradoError, DescargaFallidaError, TraduccionFallidaError) as error:
            _registro.warning("No se pudo traducir el guion de %s: %s", self._perfil.nombre, error)
            self.terminado.emit(str(error))
            return
        except Exception as error:
            _registro.exception("Fallo inesperado al traducir el guion de %s", self._perfil.nombre)
            self.terminado.emit(str(error) or type(error).__name__)
            return
        self.traducidos_al_terminar = traducidos
        self.terminado.emit(CANCELADO if self._cancelar.is_set() else "")

    def _al_empezar(self, pendientes: int) -> None:
        self._pendientes = pendientes
        self._empezado = self._reloj()
        self.barra.setVisible(True)
        self.barra.setRange(0, 0)
        self.estado.emit(_("Traduciendo…"))
        self._reloj_pantalla.start()
        self._mostrar_tiempo()

    def _mostrar_progreso(self, hechos: int, total: int) -> None:
        self.barra.setRange(0, total)
        self.barra.setValue(hechos)
        self.barra.setFormat(
            _("{hechos} de {total} párrafos ({porcentaje} %)").format(
                hechos=hechos, total=total, porcentaje=100 * hechos // max(total, 1)
            )
        )

    def _contar(self) -> None:
        self._traducidos += 1
        self._mostrar_tiempo()

    def restante_s(self) -> float | None:
        """Lo que falta al ritmo de lo traducido hasta ahora, o None si aún no hay ritmo."""
        if not self._traducidos:
            return None
        por_parrafo = (self._reloj() - self._empezado) / self._traducidos
        return por_parrafo * max(self._pendientes - self._traducidos, 0)

    def _mostrar_tiempo(self) -> None:
        transcurrido = duracion(self._reloj() - self._empezado)
        restante = self.restante_s()
        if restante is None:
            texto = _("Tiempo: {transcurrido}").format(transcurrido=transcurrido)
        else:
            texto = _("Tiempo: {transcurrido} · Falta, más o menos: {restante}").format(
                transcurrido=transcurrido, restante=duracion(restante)
            )
        self.tiempo.setText(texto)

    def _al_terminar(self, error: str) -> None:
        self._traduciendo = False
        self._reloj_pantalla.stop()
        self.boton_cerrar.setText(_("Cerrar"))
        self.boton_cerrar.setEnabled(True)
        self.boton_empezar.setEnabled(True)
        if error == CANCELADO:
            self.boton_empezar.setText(_("Seguir"))
            self.mensaje.setText(_("Parado. La próxima vez seguirá por donde lo ha dejado."))
        elif error:
            self.boton_empezar.setText(_("Reintentar"))
            self.mensaje.setText(error)
        else:
            self.barra.setVisible(False)
            self.boton_empezar.setEnabled(False)
            traducidos = self.traducidos_al_terminar or 0
            texto = ngettext(
                "Listo: {n} párrafo traducido. El guion está entero en la caché.",
                "Listo: {n} párrafos traducidos. El guion está entero en la caché.",
                traducidos,
            )
            self.mensaje.setText(texto.format(n=traducidos))

    def _cerrar_o_parar(self) -> None:
        if self._traduciendo:
            self._cancelar.set()
            self.boton_cerrar.setEnabled(False)
            self.mensaje.setText(_("Parando…"))
        else:
            self.reject()

    def reject(self) -> None:
        """Cerrar la ventana mientras traduce lo para y espera a que se detenga el traductor."""
        if self._traduciendo:
            self._cancelar.set()
            self.esperar(30)
            self._traduciendo = False
            self._reloj_pantalla.stop()
        super().reject()
