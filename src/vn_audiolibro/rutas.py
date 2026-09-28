"""Directorios de la aplicación en el equipo del usuario.

En Linux siguen la especificación XDG. En Windows, la configuración va en `%APPDATA%` (viaja con
el perfil del usuario) y los datos y el estado en `%LOCALAPPDATA%`: los modelos pesan más de 1 GB
y no deben viajar con él. Si las variables XDG están definidas, mandan en cualquier sistema.
"""

import os
import sys
from pathlib import Path

APP = "vn-audiolibro"


def _base(xdg: str, linux: tuple[str, ...], windows: str, windows_defecto: tuple[str, ...]) -> Path:
    if valor := os.environ.get(xdg):
        return Path(valor)
    if sys.platform == "win32":
        return Path(os.environ.get(windows) or Path.home().joinpath(*windows_defecto))
    return Path.home().joinpath(*linux)


def directorio_datos() -> Path:
    """Datos persistentes: `$XDG_DATA_HOME` o `~/.local/share`; en Windows, `%LOCALAPPDATA%`."""
    return _base("XDG_DATA_HOME", (".local", "share"), "LOCALAPPDATA", ("AppData", "Local")) / APP


def directorio_estado() -> Path:
    """Estado entre ejecuciones: `$XDG_STATE_HOME` o `~/.local/state`.

    En Windows no hay una carpeta aparte para el estado: va en `estado` dentro de la de datos.
    """
    if sys.platform == "win32" and not os.environ.get("XDG_STATE_HOME"):
        return directorio_datos() / "estado"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / APP


def directorio_config() -> Path:
    """Configuración del usuario: `$XDG_CONFIG_HOME` o `~/.config`; en Windows, `%APPDATA%`."""
    return _base("XDG_CONFIG_HOME", (".config",), "APPDATA", ("AppData", "Roaming")) / APP
