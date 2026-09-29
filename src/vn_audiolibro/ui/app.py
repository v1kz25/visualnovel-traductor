"""Arranque de la interfaz gráfica."""

import sys

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from vn_audiolibro import preparacion, textos
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.rutas import APP
from vn_audiolibro.ui.acceso import icono_svg, ofrecer_acceso_windows
from vn_audiolibro.ui.preparacion import PrimerArranque
from vn_audiolibro.ui.principal import TITULO, VentanaPrincipal


def icono() -> QIcon:
    pixmap = QPixmap()
    pixmap.loadFromData(icono_svg())
    return QIcon(pixmap)


def instalar_traduccion(app: QCoreApplication) -> QTranslator | None:
    """Pone en el idioma de la app los textos propios de Qt (Guardar, Cancelar, Sí, No…).

    Devuelve el traductor, que hay que conservar mientras viva la aplicación, o None si Qt no
    trae la traducción.
    """
    traductor = QTranslator(app)
    carpeta = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not traductor.load(f"qtbase_{textos.activo()}", carpeta):
        return None
    app.installTranslator(traductor)
    return traductor


def preparar() -> None:
    """Si falta algún componente o hay un problema grave del sistema, lo explica antes de abrir.

    En la versión de Windows ofrece además, la primera vez, añadir la app al menú Inicio.
    """
    faltan = preparacion.pendientes()
    avisos = preparacion.comprobar_sistema()
    if faltan or any(aviso.grave for aviso in avisos):
        PrimerArranque(faltan, avisos, acceso=ofrecer_acceso_windows()).exec()


def ejecutar(argv: list[str] | None = None) -> int:
    """Abre la ventana principal y devuelve el código de salida de Qt."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(TITULO)
    # Así GNOME asocia la ventana con su acceso directo (icono y nombre en el dock).
    QApplication.setDesktopFileName(APP)
    QApplication.setWindowIcon(icono())
    instalar_traduccion(app)
    preparar()
    ventana = VentanaPrincipal(AlmacenPerfiles())
    ventana.show()
    return app.exec()
