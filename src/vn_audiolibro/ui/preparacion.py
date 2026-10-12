"""Diálogo del primer arranque: avisos del sistema y descarga de los componentes con su progreso."""

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vn_audiolibro.configuracion import formato_tamano
from vn_audiolibro.descargas import DescargaCanceladaError
from vn_audiolibro.preparacion import AVISO_COPYRIGHT, Aviso, Componente
from vn_audiolibro.textos import N_, _

_registro = logging.getLogger(__name__)

PENDIENTE, DESCARGANDO, LISTO, ERROR = N_("Pendiente"), N_("Descargando…"), N_("Listo"), N_("Error")
"""Estados de cada componente; se traducen al mostrarlos, con `_()`."""


class PrimerArranque(QDialog):
    """Explica qué se va a descargar, con su licencia y tamaño, y lo descarga mostrando el progreso.

    Se puede cancelar a mitad (no quedan ficheros a medias) y reintentar si algo falla. Si se
    cierra sin descargar, la app abre igual y los componentes se descargan al jugar.
    """

    progreso = Signal(int, int)
    """Bytes descargados del componente en curso y su total."""
    estado = Signal(int, str)
    """Fila del componente y su nuevo estado."""
    terminado = Signal(str)
    """Vacío si todo se descargó; si no, el error o «cancelado»."""

    def __init__(
        self,
        pendientes: list[Componente],
        avisos: list[Aviso],
        acceso: Callable[[], Path] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """`acceso`, si se da, crea el acceso directo del menú Inicio: se ofrece con una casilla."""
        super().__init__(parent)
        self.setWindowTitle(_("Preparar vn-audiolibro"))
        self.resize(660, 460)
        self._pendientes = pendientes
        self._cancelar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._descargando = False

        columna = QVBoxLayout(self)
        for aviso in avisos:
            etiqueta = QLabel(("⚠ " if aviso.grave else _("Aviso: ")) + aviso.texto)
            etiqueta.setWordWrap(True)
            etiqueta.setStyleSheet("color: #c0392b" if aviso.grave else "")
            columna.addWidget(etiqueta)
        total = sum(componente.tamano for componente in pendientes)
        explicacion = QLabel(
            _(
                "Para funcionar sin conexión, la app necesita descargar estos componentes una sola vez "
                "({total} en total). Después no hace falta Internet."
            ).format(total=formato_tamano(total))
            if pendientes
            else _("Todos los componentes están descargados.")
        )
        explicacion.setWordWrap(True)
        columna.addWidget(explicacion)

        self.tabla = QTableWidget(len(pendientes), 4)
        self.tabla.setHorizontalHeaderLabels([_("Componente"), _("Licencia"), _("Tamaño"), _("Estado")])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for indice in (1, 2, 3):
            self.tabla.horizontalHeader().setSectionResizeMode(
                indice, QHeaderView.ResizeMode.ResizeToContents
            )
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for fila, componente in enumerate(pendientes):
            nombre = QTableWidgetItem(componente.nombre)
            nombre.setToolTip(componente.uso)
            for columna_tabla, elemento in enumerate(
                (
                    nombre,
                    QTableWidgetItem(componente.licencia),
                    QTableWidgetItem(formato_tamano(componente.tamano)),
                )
            ):
                self.tabla.setItem(fila, columna_tabla, elemento)
            self.tabla.setItem(fila, 3, QTableWidgetItem(_(PENDIENTE)))
        columna.addWidget(self.tabla, 1)

        self.barra = QProgressBar()
        self.barra.setVisible(False)
        self.mensaje = QLabel()
        self.mensaje.setWordWrap(True)
        copyright_ = QLabel(_(AVISO_COPYRIGHT))
        copyright_.setWordWrap(True)
        copyright_.setStyleSheet("color: gray")
        self.boton_descargar = QPushButton(_("Descargar"))
        self.boton_cerrar = QPushButton(_("Ahora no"))
        fila_botones = QHBoxLayout()
        fila_botones.addStretch()
        fila_botones.addWidget(self.boton_cerrar)
        fila_botones.addWidget(self.boton_descargar)
        columna.addWidget(self.barra)
        columna.addWidget(self.mensaje)
        columna.addWidget(copyright_)
        self._acceso = acceso
        self.casilla_acceso = QCheckBox(_("Añadir vn-audiolibro al menú Inicio"))
        self.casilla_acceso.setChecked(True)
        self.casilla_acceso.setVisible(acceso is not None)
        columna.addWidget(self.casilla_acceso)
        columna.addLayout(fila_botones)

        self.boton_descargar.setEnabled(bool(pendientes))
        self.boton_descargar.setDefault(True)
        self.boton_descargar.clicked.connect(self.descargar)
        self.boton_cerrar.clicked.connect(self._cerrar_o_cancelar)
        self.progreso.connect(self._mostrar_progreso)
        self.estado.connect(self._mostrar_estado)
        self.terminado.connect(self._al_terminar)

    @property
    def descargando(self) -> bool:
        """De `descargar` hasta que se atiende `terminado`, sin depender de cuándo sale el hilo.

        El hilo emite `terminado` como última acción, pero puede seguir vivo un instante después:
        si se mirase `is_alive()`, un reintento inmediato se ignoraría (#57).
        """
        return self._descargando

    def descargar(self) -> None:
        """Descarga en segundo plano los componentes que falten."""
        if self.descargando:
            return
        self.esperar()  # el hilo anterior ya emitió `terminado`: solo le queda salir
        self._descargando = True
        self._cancelar.clear()
        self.boton_descargar.setEnabled(False)
        self.boton_cerrar.setText(_("Cancelar"))
        self.barra.setVisible(True)
        self.mensaje.clear()
        self._hilo = threading.Thread(target=self._descargar_todo, name="descargas", daemon=True)
        self._hilo.start()

    def esperar(self, timeout_s: float | None = None) -> None:
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def _descargar_todo(self) -> None:
        for fila, componente in enumerate(self._pendientes):
            if componente.instalado():
                self.estado.emit(fila, LISTO)
                continue
            self.estado.emit(fila, DESCARGANDO)
            try:
                componente.instalar(self._al_progreso, self._cancelar.is_set)
            except DescargaCanceladaError:
                self.estado.emit(fila, PENDIENTE)
                self.terminado.emit("cancelado")
                return
            except Exception as error:
                _registro.exception("No se pudo descargar %s", componente.nombre)
                self.estado.emit(fila, ERROR)
                mensaje = _("No se pudo descargar «{componente}»: {error}")
                self.terminado.emit(mensaje.format(componente=componente.nombre, error=error))
                return
            self.estado.emit(fila, LISTO)
        self.terminado.emit("")

    def _al_progreso(self, hecho: int, total: int | None) -> None:
        self.progreso.emit(hecho, total or 0)

    def _mostrar_progreso(self, hecho: int, total: int) -> None:
        if total:
            # QProgressBar usa int de 32 bits: se trabaja en KB para que quepan descargas de GB.
            self.barra.setRange(0, total // 1024)
            self.barra.setValue(hecho // 1024)
        else:
            self.barra.setRange(0, 0)  # sin tamaño conocido: barra en movimiento
        progreso = _("{hecho} de {total}").format(hecho=formato_tamano(hecho), total=formato_tamano(total))
        self.barra.setFormat(progreso if total else "")

    def _mostrar_estado(self, fila: int, estado: str) -> None:
        self.tabla.setItem(fila, 3, QTableWidgetItem(_(estado)))

    def _al_terminar(self, error: str) -> None:
        self._descargando = False
        self.barra.setVisible(False)
        self.boton_cerrar.setText(_("Ahora no"))
        if not error:
            self.mensaje.setText(_("Todo listo."))
            self.accept()
            return
        self.boton_descargar.setText(_("Reintentar"))
        self.boton_descargar.setEnabled(True)
        self.mensaje.setText(_("Descarga cancelada.") if error == "cancelado" else error)

    def _cerrar_o_cancelar(self) -> None:
        if self.descargando:
            self._cancelar.set()
        else:
            self.reject()

    def done(self, resultado: int) -> None:
        """Al cerrar, de cualquier forma, crea el acceso directo si está marcada la casilla."""
        acceso, self._acceso = self._acceso, None  # solo una vez
        if acceso is not None and self.casilla_acceso.isChecked():
            try:
                _registro.info("Acceso directo creado en %s", acceso())
            except Exception:
                _registro.warning("No se pudo crear el acceso directo", exc_info=True)
        super().done(resultado)

    def reject(self) -> None:
        """Cerrar la ventana durante una descarga la cancela y espera a que se detenga."""
        if self.descargando:
            self._cancelar.set()
            self.esperar(10)
            self._descargando = False
        super().reject()
