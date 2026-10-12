"""Subtítulos encima del juego: la traducción en una ventana sin marco, siempre encima.

La ventana es transparente al ratón (los clics llegan al juego) y no coge el foco. Sigue a la
ventana del juego si se mueve y solo se ve mientras el juego es la ventana activa: si se
minimiza, se cambia a otra ventana o se cierra, se oculta. Al pasar el ratón por encima aparecen
los controles de la partida (`ControlesFlotantes`).

Con el juego en pantalla completa exclusiva puede no verse nada encima: entonces hay que poner
el juego en modo ventana o ventana sin bordes.
"""

import logging
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCursor, QFont, QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from vn_audiolibro.atajos.modelos import Accion
from vn_audiolibro.captura.modelos import (
    Rectangulo,
    VentanaMinimizadaError,
    VentanaNoEncontradaError,
    ZonaRelativa,
)
from vn_audiolibro.perfiles.modelos import AjustesSubtitulos, Perfil, PosicionSubtitulos
from vn_audiolibro.plataforma import gestor_ventanas
from vn_audiolibro.textos import _
from vn_audiolibro.ui.controles import ControlesFlotantes

_registro = logging.getLogger(__name__)

INTERVALO_MS = 250
"""Cada cuánto se mira dónde está el juego y si sigue activo."""
MARGEN = 0.4
"""Relleno alrededor del texto, en tamaños de letra."""
VUELTAS_CONTROLES = 6
"""Vueltas del reloj (1,5 s) sin el ratón encima tras las que se van los controles flotantes."""


class PantallaSubtitulos(Protocol):
    """Lo que la ventana principal usa de los subtítulos."""

    def mostrar(self, texto: str) -> None: ...

    def alternar(self) -> None: ...

    def conectar(self, al_control: Callable[[Accion], None]) -> None: ...

    def cerrar(self) -> None: ...


class FuenteVentanas(Protocol):
    """Lo que los subtítulos necesitan saber del juego (el gestor de ventanas del sistema)."""

    def geometria(self, id_ventana: int) -> Rectangulo: ...

    def activa(self) -> int | None: ...


def rectangulo_subtitulos(
    juego: Rectangulo, zona: ZonaRelativa, posicion: PosicionSubtitulos, alto: int
) -> Rectangulo:
    """Dónde van los subtítulos, en coordenadas de pantalla.

    Ocupan el ancho de la zona de texto. Encima o debajo de ella, con el `alto` que necesita el
    texto; si no caben dentro del juego por ese lado, van por el otro. Al tapar, ocupan la zona.
    """
    caja = zona.en_pixeles(juego.ancho, juego.alto)
    x, y = juego.x + caja.x, juego.y + caja.y
    if posicion is PosicionSubtitulos.TAPAR:
        return Rectangulo(x, y, caja.ancho, caja.alto)
    encima = y - alto
    debajo = y + caja.alto
    cabe_encima = encima >= juego.y
    cabe_debajo = debajo + alto <= juego.y + juego.alto
    if posicion is PosicionSubtitulos.ENCIMA:
        arriba = encima if cabe_encima or not cabe_debajo else debajo
    else:
        arriba = debajo if cabe_debajo or not cabe_encima else encima
    return Rectangulo(x, max(juego.y, arriba), caja.ancho, alto)


class Subtitulos(QWidget):
    """Ventana de subtítulos sobre el juego `id_ventana`, con sus controles flotantes.

    Al pasar el ratón por los subtítulos aparecen encima los controles de la partida. Si se
    ocultan, queda una marca pequeña en su lugar; al pasar el ratón por ella vuelven los controles.
    """

    def __init__(
        self,
        ajustes: AjustesSubtitulos,
        zona: ZonaRelativa,
        ventanas: FuenteVentanas,
        id_ventana: int,
        intervalo_ms: int = INTERVALO_MS,
        cursor: Callable[[], QPoint] = QCursor.pos,
    ) -> None:
        super().__init__(None)
        self._ajustes = ajustes
        self._zona = zona
        self._ventanas = ventanas
        self._id_ventana = id_ventana
        self._cursor = cursor
        self.ocultos = False
        """Si el usuario los ha ocultado; el texto se sigue actualizando."""
        bandera = Qt.WindowType
        self.setWindowFlags(
            bandera.FramelessWindowHint
            | bandera.WindowStaysOnTopHint
            | bandera.Tool
            | bandera.WindowTransparentForInput
            | bandera.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.texto = QLabel()
        self.texto.setWordWrap(True)
        self.texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fuente = QFont(self.texto.font())
        fuente.setPointSize(ajustes.tamano)
        self.texto.setFont(fuente)
        opacidad = 1.0 if ajustes.posicion is PosicionSubtitulos.TAPAR else ajustes.opacidad
        relleno = round(MARGEN * ajustes.tamano)
        self.texto.setStyleSheet(
            f"background-color: rgba(0, 0, 0, {round(opacidad * 255)}); color: white; "
            f"padding: {relleno}px; border-radius: {relleno // 2}px;"
        )
        self.marca = QLabel(_("Subtítulos ocultos · pasa el ratón para ver los controles"))
        self.marca.setStyleSheet(
            "background-color: rgba(0, 0, 0, 140); color: rgba(255, 255, 255, 200); "
            "padding: 2px 8px; border-radius: 4px;"
        )
        self.marca.hide()
        columna = QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.addWidget(self.texto)
        columna.addWidget(self.marca)
        self.controles = ControlesFlotantes()
        self._sin_raton = 0
        """Vueltas del reloj seguidas sin el ratón encima; al llegar a `VUELTAS_CONTROLES`, se van."""
        self._reloj = QTimer(self)
        self._reloj.setInterval(intervalo_ms)
        self._reloj.timeout.connect(self.seguir)
        self._reloj.start()

    def conectar(self, al_control: Callable[[Accion], None]) -> None:
        """`al_control` recibe la acción de cada botón de los controles flotantes."""
        self.controles.pulsado.connect(lambda accion: al_control(Accion(accion)))

    def mostrar(self, texto: str) -> None:
        """Cambia el subtítulo y lo coloca sobre el juego."""
        self.texto.setText(texto)
        self.seguir()

    def alternar(self) -> None:
        """Oculta los subtítulos o los vuelve a mostrar (con el atajo o el botón)."""
        self.ocultos = not self.ocultos
        self.controles.subtitulos_ocultos(self.ocultos)
        self.seguir()

    def seguir(self) -> None:
        """Coloca los subtítulos sobre el juego, o los oculta si el juego no está a la vista."""
        juego = self._juego_a_la_vista()
        if juego is None or not (self.texto.text() or self.ocultos):
            self.hide()
            self.controles.hide()
            return
        self.texto.setVisible(not self.ocultos)
        self.marca.setVisible(self.ocultos)
        if self.ocultos:
            alto = self.marca.sizeHint().height()
            sitio = rectangulo_subtitulos(juego, self._zona, self._ajustes.posicion, alto)
            sitio = Rectangulo(sitio.x, sitio.y, min(sitio.ancho, self.marca.sizeHint().width()), alto)
        else:
            ancho = round(self._zona.ancho * juego.ancho)
            alto = self.texto.heightForWidth(ancho) if ancho > 0 else 0
            sitio = rectangulo_subtitulos(juego, self._zona, self._ajustes.posicion, max(alto, 1))
        self.setGeometry(QRect(sitio.x, sitio.y, sitio.ancho, sitio.alto))
        if self.isHidden():
            self.show()
        self._seguir_raton(juego)

    def _juego_a_la_vista(self) -> Rectangulo | None:
        """Dónde está el juego (en píxeles de Qt), o None si no es la ventana activa o no está."""
        if self._ventanas.activa() != self._id_ventana:
            return None
        try:
            return _a_logico(self._ventanas.geometria(self._id_ventana))
        except (VentanaNoEncontradaError, VentanaMinimizadaError):
            return None

    def _seguir_raton(self, juego: Rectangulo) -> None:
        """Muestra los controles con el ratón encima de los subtítulos (o de los propios controles)."""
        raton = self._cursor()
        encima = self.geometry().contains(raton) or (
            self.controles.isVisible() and self.controles.geometry().contains(raton)
        )
        if not encima:
            self._sin_raton += 1
            if self._sin_raton >= VUELTAS_CONTROLES:
                self.controles.hide()
            return
        self._sin_raton = 0
        tamano = self.controles.sizeHint()
        subtitulos = self.geometry()
        x = max(juego.x, subtitulos.right() + 1 - tamano.width())
        y = subtitulos.top() - tamano.height()
        if y < juego.y:  # no cabe encima dentro del juego: debajo
            y = subtitulos.bottom() + 1
        self.controles.setGeometry(QRect(x, y, tamano.width(), tamano.height()))
        self.controles.show()

    def cerrar(self) -> None:
        """Para el seguimiento y cierra la ventana y los controles."""
        self._reloj.stop()
        self.controles.close()
        self.close()


def _a_logico(rectangulo: Rectangulo) -> Rectangulo:
    """De píxeles físicos (los del sistema) a los lógicos de Qt, que cambian con el escalado."""
    pantalla = QGuiApplication.primaryScreen()
    escala = pantalla.devicePixelRatio() if pantalla is not None else 1.0
    if escala == 1:
        return rectangulo
    return Rectangulo(
        round(rectangulo.x / escala),
        round(rectangulo.y / escala),
        max(1, round(rectangulo.ancho / escala)),
        max(1, round(rectangulo.alto / escala)),
    )


def abrir_subtitulos(perfil: Perfil) -> PantallaSubtitulos | None:
    """Subtítulos sobre la ventana del juego, o None si están desactivados o no se encuentra."""
    if not perfil.subtitulos.activo:
        return None
    try:
        gestor = gestor_ventanas()
        ventana = gestor.buscar(perfil.ventana)
    except Exception:
        # Sin subtítulos se puede jugar igual: la sesión ya avisa si no encuentra la ventana.
        _registro.warning("No se pueden mostrar los subtítulos", exc_info=True)
        return None
    return Subtitulos(perfil.subtitulos, perfil.zona, gestor, ventana.id)
