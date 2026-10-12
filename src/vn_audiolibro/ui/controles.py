"""Controles flotantes de la partida: aparecen al pasar el ratón por los subtítulos.

Son una ventana aparte, pequeña y siempre encima, que sí recibe clics (los subtítulos son
transparentes al ratón) pero no coge el foco: el juego sigue siendo la ventana activa.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from vn_audiolibro.atajos.modelos import Accion
from vn_audiolibro.textos import _


class ControlesFlotantes(QWidget):
    """Pausar o seguir, repetir, saltar y ocultar o mostrar los subtítulos."""

    pulsado = Signal(str)
    """La `Accion` del botón pulsado."""

    def __init__(self) -> None:
        super().__init__(None)
        bandera = Qt.WindowType
        self.setWindowFlags(
            bandera.FramelessWindowHint
            | bandera.WindowStaysOnTopHint
            | bandera.Tool
            | bandera.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # entre los botones, el juego
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "QPushButton { background-color: rgba(0, 0, 0, 200); color: white; border: none; "
            "padding: 4px 10px; border-radius: 4px; } "
            "QPushButton:hover { background-color: rgba(60, 60, 60, 230); }"
        )
        self.botones = {
            Accion.PAUSA: QPushButton(_("Pausa")),
            Accion.REPETIR: QPushButton(_("Repetir")),
            Accion.SALTAR: QPushButton(_("Saltar")),
            Accion.SUBTITULOS: QPushButton(_("Ocultar")),
        }
        self.botones[Accion.PAUSA].setToolTip(_("Pausar o seguir"))
        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(4)
        for accion, boton in self.botones.items():
            boton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            boton.clicked.connect(lambda _marcado=False, accion=accion: self.pulsado.emit(accion.value))
            fila.addWidget(boton)

    def subtitulos_ocultos(self, ocultos: bool) -> None:
        """El botón de los subtítulos dice lo que hará al pulsarlo."""
        self.botones[Accion.SUBTITULOS].setText(_("Mostrar") if ocultos else _("Ocultar"))
