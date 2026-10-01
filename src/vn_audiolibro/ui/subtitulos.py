"""Subtítulos encima del juego: la traducción en una ventana sin marco, siempre encima.

La ventana es transparente al ratón (los clics llegan al juego) y no coge el foco. Sigue a la
ventana del juego si se mueve y solo se ve mientras el juego es la ventana activa: si se
minimiza, se cambia a otra ventana o se cierra, se oculta.

Con el juego en pantalla completa exclusiva puede no verse nada encima: entonces hay que poner
el juego en modo ventana o ventana sin bordes.
"""

import logging
from typing import Protocol

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from vn_audiolibro.captura.modelos import (
    Rectangulo,
    VentanaMinimizadaError,
    VentanaNoEncontradaError,
    ZonaRelativa,
)
from vn_audiolibro.perfiles.modelos import AjustesSubtitulos, Perfil, PosicionSubtitulos
from vn_audiolibro.plataforma import gestor_ventanas

_registro = logging.getLogger(__name__)

INTERVALO_MS = 250
"""Cada cuánto se mira dónde está el juego y si sigue activo."""
MARGEN = 0.4
"""Relleno alrededor del texto, en tamaños de letra."""


class PantallaSubtitulos(Protocol):
    """Lo que la ventana principal usa de los subtítulos."""

    def mostrar(self, texto: str) -> None: ...

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
    """Ventana de subtítulos sobre el juego `id_ventana`."""

    def __init__(
        self,
        ajustes: AjustesSubtitulos,
        zona: ZonaRelativa,
        ventanas: FuenteVentanas,
        id_ventana: int,
        intervalo_ms: int = INTERVALO_MS,
    ) -> None:
        super().__init__(None)
        self._ajustes = ajustes
        self._zona = zona
        self._ventanas = ventanas
        self._id_ventana = id_ventana
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
        columna = QVBoxLayout(self)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.addWidget(self.texto)
        self._reloj = QTimer(self)
        self._reloj.setInterval(intervalo_ms)
        self._reloj.timeout.connect(self.seguir)
        self._reloj.start()

    def mostrar(self, texto: str) -> None:
        """Cambia el subtítulo y lo coloca sobre el juego."""
        self.texto.setText(texto)
        self.seguir()

    def seguir(self) -> None:
        """Coloca los subtítulos sobre el juego, o los oculta si el juego no está a la vista."""
        if not self.texto.text() or self._ventanas.activa() != self._id_ventana:
            self.hide()
            return
        try:
            juego = _a_logico(self._ventanas.geometria(self._id_ventana))
        except (VentanaNoEncontradaError, VentanaMinimizadaError):
            self.hide()
            return
        ancho = round(self._zona.ancho * juego.ancho)
        alto = self.texto.heightForWidth(ancho) if ancho > 0 else 0
        sitio = rectangulo_subtitulos(juego, self._zona, self._ajustes.posicion, max(alto, 1))
        self.setGeometry(QRect(sitio.x, sitio.y, sitio.ancho, sitio.alto))
        if self.isHidden():
            self.show()

    def cerrar(self) -> None:
        """Para el seguimiento y cierra la ventana."""
        self._reloj.stop()
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
