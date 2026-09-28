"""Convierte el icono SVG de la app en PNG para el ejecutable (PyInstaller lo pasa a .ico)."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from vn_audiolibro.ui.acceso import icono_svg

app = QGuiApplication([])
imagen = QImage(256, 256, QImage.Format.Format_ARGB32)
imagen.fill(Qt.GlobalColor.transparent)
pintor = QPainter(imagen)
QSvgRenderer(icono_svg()).render(pintor)
pintor.end()
if not imagen.save(sys.argv[1]):
    sys.exit(f"No se pudo guardar {sys.argv[1]}")
