# Especificación de PyInstaller para Windows. La usa construir_windows.sh; no se ejecuta a mano.
#
# Genera una carpeta con dos ejecutables que comparten las bibliotecas:
#   vn-audiolibro.exe           la interfaz gráfica, sin ventana de consola
#   vn-audiolibro-consola.exe   las órdenes de la terminal (jugar, juegos…) y la autocomprobación
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

AQUI = Path(SPECPATH)  # noqa: F821 - lo define PyInstaller
ICONO = os.environ["VN_ICONO"]

datos = [
    *collect_data_files("vn_audiolibro"),  # el icono y los catálogos de idiomas
    # Solo la configuración: los modelos de OCR se descargan en el primer arranque.
    *collect_data_files("rapidocr", excludes=["**/*.onnx"]),
    # Solo los datos de espeak-ng, con los que Piper convierte el texto en fonemas.
    *collect_data_files("piper", includes=["espeak-ng-data/**"]),
    *collect_data_files("opencc"),
    *copy_metadata("vn-audiolibro"),  # para --version
    *copy_metadata("keyring"),  # keyring busca sus backends en sus metadatos
]

analisis = Analysis(  # noqa: F821
    [str(AQUI / "entrada.py")],
    datas=datos,
    # Las implementaciones de cada sistema se importan al pedirlas (plataforma.py).
    hiddenimports=[*collect_submodules("vn_audiolibro"), "piper.espeakbridge", "keyring.backends.Windows"],
    excludes=["tkinter", "pytest", "vn_audiolibro.captura.x11", "Xlib", "pulsectl"],
    noarchive=False,
)
pyz = PYZ(analisis.pure)  # noqa: F821


def ejecutable(nombre, consola):
    return EXE(  # noqa: F821
        pyz,
        analisis.scripts,
        [],
        exclude_binaries=True,
        name=nombre,
        console=consola,
        icon=ICONO,
        upx=False,
    )


COLLECT(  # noqa: F821
    ejecutable("vn-audiolibro", consola=False),
    ejecutable("vn-audiolibro-consola", consola=True),
    analisis.binaries,
    analisis.datas,
    name="vn-audiolibro",
    upx=False,
)
