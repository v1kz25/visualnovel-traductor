"""Autocomprobación del ejecutable empaquetado: que no falte nada de lo que se carga al usar la app.

Al empaquetar (PyInstaller, AppImage) es fácil perder una biblioteca nativa, un fichero de datos
o los metadatos de un paquete, y el fallo solo aparece al usar esa parte. Esto la carga toda sin
necesitar los modelos, el juego ni la red, para comprobarlo en la CI tras construir el paquete.
"""

import sys
from collections.abc import Callable
from importlib.metadata import version
from importlib.resources import files

Comprobacion = tuple[str, Callable[[], str]]
"""Nombre y función que devuelve un detalle, o lanza una excepción si falla."""


def _metadatos() -> str:
    return version("vn-audiolibro")


def _onnxruntime() -> str:
    import onnxruntime

    proveedores = onnxruntime.get_available_providers()
    if "CPUExecutionProvider" not in proveedores:
        raise RuntimeError(f"sin CPUExecutionProvider: {proveedores}")
    return str(onnxruntime.__version__)


def _opencv() -> str:
    import cv2

    return str(cv2.__version__)


def _rapidocr() -> str:
    from rapidocr import RapidOCR  # noqa: F401 - lo que importa el reconocedor
    from rapidocr._version import __version__ as version_rapidocr

    for fichero in ("config.yaml", "default_models.yaml"):
        if not files("rapidocr").joinpath(fichero).is_file():
            raise FileNotFoundError(f"falta {fichero} de rapidocr")
    return str(version_rapidocr)


def _opencc() -> str:
    from vn_audiolibro.ocr.normalizacion import normalizar

    convertido = normalizar("学习", "zh-Hant")
    if convertido != "學習":
        raise RuntimeError(f"conversión inesperada: {convertido}")
    return convertido


def _piper() -> str:
    from piper.phonemize_espeak import EspeakPhonemizer

    fonetizador = EspeakPhonemizer()
    fonemas = {idioma: fonetizador.phonemize(idioma, "hola") for idioma in ("es", "en")}
    if not all(frases and frases[0] for frases in fonemas.values()):
        raise RuntimeError("espeak-ng no ha devuelto fonemas en español e inglés")
    return "".join(fonemas["es"][0])


def _soundfile() -> str:
    import soundfile

    return str(soundfile.__libsndfile_version__)


def _sounddevice() -> str:
    import sounddevice

    return str(sounddevice.get_portaudio_version()[1])


def _pycaw() -> str:
    import comtypes
    import pycaw.pycaw  # noqa: F401 - solo se comprueba que carga

    return str(comtypes.__version__)


def _qt() -> str:
    from PySide6 import __version__ as version_qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from vn_audiolibro.ui.acceso import icono_svg

    # Los plugins de imágenes necesitan la aplicación; la de widgets, la misma que usa la interfaz.
    _app = QApplication.instance() or QApplication([])
    if not QImage().loadFromData(icono_svg()):  # el formato lo detecta Qt, como en la ventana
        raise RuntimeError("no se pudo cargar el icono SVG (¿falta el plugin de imágenes?)")
    return str(version_qt)


def _textos() -> str:
    from vn_audiolibro import textos

    idiomas = textos.disponibles()
    if "en" not in idiomas or textos.catalogo("en").gettext("Jugar") != "Play":
        raise RuntimeError(f"faltan los catálogos de idiomas: {idiomas}")
    return ", ".join(idiomas)


def _llavero(plataforma: str = sys.platform) -> str:
    """El llavero del sistema, donde se guarda la clave de Gemini: su backend y sus metadatos.

    `keyring` encuentra los backends por los metadatos del paquete: si el empaquetado los pierde,
    no encontraría ninguno y la clave no se podría guardar.
    """
    from importlib import import_module
    from importlib.metadata import entry_points

    modulo = "keyring.backends.Windows" if plataforma == "win32" else "keyring.backends.SecretService"
    import_module(modulo)
    if not entry_points(group="keyring.backends"):
        raise RuntimeError("faltan los metadatos de keyring")
    return modulo


def comprobaciones(plataforma: str = sys.platform) -> list[Comprobacion]:
    """Lo que se comprueba en este sistema."""
    lista: list[Comprobacion] = [
        ("metadatos", _metadatos),
        ("onnxruntime", _onnxruntime),
        ("opencv", _opencv),
        ("rapidocr", _rapidocr),
        ("opencc", _opencc),
        ("piper y espeak-ng", _piper),
        ("libsndfile", _soundfile),
        ("Qt e icono", _qt),
        ("idiomas de la interfaz", _textos),
        ("llavero del sistema", lambda: _llavero(plataforma)),
    ]
    if plataforma == "win32":
        lista += [("PortAudio", _sounddevice), ("Core Audio", _pycaw)]
    return lista


def autocomprobar(lista: list[Comprobacion] | None = None) -> int:
    """Ejecuta las comprobaciones, informa de cada una y devuelve 0 si todas pasan."""
    fallos = 0
    for nombre, comprobar in comprobaciones() if lista is None else lista:
        try:
            detalle = comprobar()
        except Exception as error:
            fallos += 1
            print(f"FALLO {nombre}: {type(error).__name__}: {error}")
        else:
            print(f"ok    {nombre}: {detalle}")
    print("Todo correcto." if not fallos else f"{fallos} comprobaciones fallidas.")
    return 1 if fallos else 0
