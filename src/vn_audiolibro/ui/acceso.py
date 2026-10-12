"""Acceso directo en el menú de aplicaciones, solo para el usuario.

En Linux es un fichero .desktop con el icono: hace falta al ejecutar la app desde el código,
porque el AppImage trae el suyo. En Windows es un .lnk en el menú Inicio que abre el ejecutable
de la versión portable, que no se instala.
"""

import os
import subprocess
import sys
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

from vn_audiolibro.plataforma import sin_ventana
from vn_audiolibro.rutas import APP, directorio_datos
from vn_audiolibro.textos import _

_SCRIPT_LNK = """
$ErrorActionPreference = 'Stop'
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut($env:VN_ACCESO)
$acceso.TargetPath = $env:VN_EJECUTABLE
$acceso.WorkingDirectory = Split-Path -Parent $env:VN_EJECUTABLE
$acceso.IconLocation = "$env:VN_EJECUTABLE,0"
$acceso.Description = $env:VN_DESCRIPCION
$acceso.Save()
"""
"""Crea el .lnk con el objeto COM de Windows. Las rutas llegan por variables de entorno para no
tener que escaparlas dentro del script."""

CrearLnk = Callable[[Path, Path], None]
"""Crea un acceso directo (primera ruta) que abre un ejecutable (segunda)."""


class AccesoNoDisponibleError(Exception):
    """No se puede crear el acceso directo."""


def icono_svg() -> bytes:
    """El icono de la app, el mismo que lleva el AppImage."""
    return files("vn_audiolibro.ui").joinpath("icono.svg").read_bytes()


def contenido_desktop(python: str, icono: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP}\n"
        f"GenericName={_('Audiolibro para novelas visuales')}\n"
        f"Comment={_('Traduce novelas visuales en chino y japonés y las lee en voz alta')}\n"
        f'Exec="{python}" -m vn_audiolibro\n'
        f"Icon={icono}\n"
        "Categories=Game;Utility;\n"
        "Terminal=false\n"
        f"StartupWMClass={APP}\n"
    )


def instalar_acceso(datos: Path | None = None, python: str | None = None) -> Path:
    """Crea (o actualiza) el acceso directo que abre esta instalación. Devuelve la ruta del .desktop.

    `datos` es la carpeta de datos del usuario (`$XDG_DATA_HOME` o `~/.local/share`), no la de la app.
    """
    datos = datos or directorio_datos().parent
    desktop = datos / "applications" / f"{APP}.desktop"
    svg = datos / "icons" / "hicolor" / "scalable" / "apps" / f"{APP}.svg"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    svg.parent.mkdir(parents=True, exist_ok=True)
    svg.write_bytes(icono_svg())
    # Ruta absoluta y no el nombre: GNOME Shell no vuelve a buscar en el tema un icono que no
    # encontró, y a veces lee el .desktop antes de fijarse en el icono recién copiado.
    desktop.write_text(contenido_desktop(python or sys.executable, svg), encoding="utf-8")
    return desktop


def ejecutable_empaquetado() -> Path | None:
    """`vn-audiolibro.exe` de la versión portable de Windows; None si la app se ejecuta desde el código.

    Vale también si se ha abierto con `vn-audiolibro-consola.exe`: el acceso abre la interfaz.
    """
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).with_name(f"{APP}.exe")


def acceso_menu_inicio(programas: Path | None = None) -> Path:
    """El .lnk en el menú Inicio del usuario (`%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs`)."""
    if programas is None:
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        programas = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return programas / f"{APP}.lnk"


def crear_lnk(acceso: Path, ejecutable: Path) -> None:
    """Crea el .lnk con PowerShell, sin abrir ninguna ventana."""
    raiz = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows")
    powershell = raiz / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    entorno = {
        **os.environ,
        "VN_ACCESO": str(acceso),
        "VN_EJECUTABLE": str(ejecutable),
        "VN_DESCRIPCION": _("Audiolibro para novelas visuales"),
    }
    try:
        subprocess.run(  # noqa: S603 - ruta y script fijos; los datos van por el entorno
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", _SCRIPT_LNK],
            env=entorno,
            check=True,
            capture_output=True,
            timeout=60,
            creationflags=sin_ventana(),
        )
    except subprocess.CalledProcessError as error:
        detalle = error.stderr.decode(errors="replace").strip() if error.stderr else error
        raise AccesoNoDisponibleError(
            _("No se pudo crear el acceso directo: {error}").format(error=detalle)
        ) from error
    except (OSError, subprocess.SubprocessError) as error:
        raise AccesoNoDisponibleError(
            _("No se pudo crear el acceso directo: {error}").format(error=error)
        ) from error


def instalar_acceso_windows(
    programas: Path | None = None, ejecutable: Path | None = None, crear: CrearLnk = crear_lnk
) -> Path:
    """Crea (o actualiza) el acceso directo del menú Inicio. Devuelve la ruta del .lnk."""
    ejecutable = ejecutable or ejecutable_empaquetado()
    if ejecutable is None:
        raise AccesoNoDisponibleError(
            _(
                "El acceso directo del menú Inicio solo se puede crear desde la versión empaquetada ({exe})."
            ).format(exe=f"{APP}.exe")
        )
    acceso = acceso_menu_inicio(programas)
    acceso.parent.mkdir(parents=True, exist_ok=True)
    crear(acceso, ejecutable)
    return acceso


def ofrecer_acceso_windows() -> Callable[[], Path] | None:
    """Si procede ofrecer el acceso directo al abrir la app: en la versión empaquetada de Windows,
    mientras no exista."""
    if sys.platform != "win32" or ejecutable_empaquetado() is None or acceso_menu_inicio().exists():
        return None
    return instalar_acceso_windows
