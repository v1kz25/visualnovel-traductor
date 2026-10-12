"""Aviso de versión nueva en la ventana principal: una franja discreta, encima de todo lo demás."""

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from html import escape
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget

from vn_audiolibro.actualizaciones import Busqueda, Consultar, Release, buscar, toca_buscar
from vn_audiolibro.configuracion import cargar_ajustes, guardar_ajustes
from vn_audiolibro.textos import _

NOTAS = "notas"
"""Enlace de la franja que abre las novedades en la propia app."""


def preguntar_si_avisar(padre: QWidget, ruta_ajustes: Path | None = None) -> None:
    """La primera vez, pregunta si se busca al arrancar si hay versiones nuevas.

    La app funciona sin conexión: no se conecta a GitHub sin que el usuario lo haya aceptado.
    """
    ajustes = cargar_ajustes(ruta_ajustes)
    if ajustes.avisar_versiones is not None:
        return
    respuesta = QMessageBox.question(
        padre,
        _("Versiones nuevas"),
        _(
            "¿Quieres que la app te avise cuando haya una versión nueva?\n\n"
            "Para saberlo, consultará GitHub como mucho una vez al día al abrirse. No descarga ni "
            "instala nada. Se puede cambiar cuando quieras en «Avisar de versiones nuevas»."
        ),
    )
    guardar_ajustes(
        replace(ajustes, avisar_versiones=respuesta == QMessageBox.StandardButton.Yes), ruta_ajustes
    )


class BuscadorVersiones(QObject):
    """Busca en segundo plano si hay una versión nueva y avisa con `encontrada` en el hilo de Qt."""

    encontrada = Signal(object)
    """La `Release` de la que hay que avisar."""
    terminada = Signal()
    _resultado = Signal(object)

    def __init__(
        self,
        actual: str,
        consultar: Consultar,
        ruta_ajustes: Path | None = None,
        reloj: Callable[[], float] = time.time,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._actual = actual
        self._consultar = consultar
        self._ruta_ajustes = ruta_ajustes
        self._reloj = reloj
        self._resultado.connect(self._al_terminar)

    def iniciar(self) -> bool:
        """Lanza la búsqueda si toca (activada y no hecha hoy). Devuelve si se ha lanzado."""
        ajustes = cargar_ajustes(self._ruta_ajustes)
        ahora = self._reloj()
        if not toca_buscar(ajustes, ahora):
            return False

        def trabajar() -> None:
            self._resultado.emit(buscar(ajustes, ahora, self._actual, self._consultar))

        threading.Thread(target=trabajar, name="version-nueva", daemon=True).start()
        return True

    def _al_terminar(self, busqueda: Busqueda) -> None:
        # Se vuelven a leer por si mientras tanto ha cambiado otro ajuste (el idioma, la caché…).
        actuales = cargar_ajustes(self._ruta_ajustes)
        guardar_ajustes(
            replace(
                actuales,
                ultima_busqueda=busqueda.ajustes.ultima_busqueda,
                version_avisada=busqueda.ajustes.version_avisada,
            ),
            self._ruta_ajustes,
        )
        if busqueda.nueva is not None:
            self.encontrada.emit(busqueda.nueva)
        self.terminada.emit()


class AvisoVersion(QFrame):
    """Franja que dice que hay una versión nueva, con sus novedades y el enlace para descargarla."""

    def __init__(
        self, abrir_url: Callable[[QUrl], object] = QDesktopServices.openUrl, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._abrir_url = abrir_url
        self.release: Release | None = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.texto = QLabel()
        self.texto.setTextFormat(Qt.TextFormat.RichText)
        self.texto.linkActivated.connect(self._al_pulsar_enlace)
        self.cerrar = QPushButton(_("Cerrar"))
        self.cerrar.clicked.connect(self.hide)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(8, 4, 8, 4)
        fila.addWidget(self.texto, 1)
        fila.addWidget(self.cerrar)
        self.hide()

    def mostrar(self, release: Release) -> None:
        self.release = release
        aviso = escape(_("Hay una versión nueva: {version}.").format(version=release.version))
        novedades = escape(_("Novedades"))
        descargar = escape(_("Descargar"))
        self.texto.setText(
            f'{aviso} <a href="{NOTAS}">{novedades}</a> · <a href="{escape(release.url)}">{descargar}</a>'
        )
        self.show()

    def _al_pulsar_enlace(self, enlace: str) -> None:
        if self.release is None:
            return
        if enlace == NOTAS:
            self.ver_notas()
        else:
            self._abrir_url(QUrl(self.release.url))

    def ver_notas(self) -> None:
        if self.release is None:
            return
        caja = QMessageBox(self)
        caja.setWindowTitle(_("Novedades de la versión {version}").format(version=self.release.version))
        caja.setTextFormat(Qt.TextFormat.MarkdownText)
        caja.setText(self.release.notas or _("Esta versión no tiene notas."))
        caja.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        caja.open()
