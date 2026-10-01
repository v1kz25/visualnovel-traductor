"""Claves de API de los traductores en línea, guardadas en el llavero del sistema.

Nunca van en ficheros de configuración, en la caché ni en los registros: en Linux se guardan en
el llavero de la sesión (GNOME, KDE…, por Secret Service) y en Windows en el Administrador de
credenciales. Si no hay llavero, no se guardan.
"""

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from vn_audiolibro.textos import _

SERVICIO = "vn-audiolibro"
GEMINI = "gemini"
"""Nombre de la clave de Gemini en el llavero."""


class LlaveroNoDisponibleError(Exception):
    """No hay llavero del sistema donde guardar o leer la clave."""


def _llavero_no_disponible(error: Exception) -> LlaveroNoDisponibleError:
    return LlaveroNoDisponibleError(
        _("No se puede usar el llavero del sistema para guardar la clave: {error}").format(error=error)
    )


def leer(nombre: str = GEMINI) -> str | None:
    """La clave guardada, o None si no hay ninguna o no se puede leer el llavero."""
    try:
        return keyring.get_password(SERVICIO, nombre) or None
    except KeyringError:
        return None


def guardar(clave: str, nombre: str = GEMINI) -> None:
    """Guarda la clave en el llavero, sin espacios alrededor."""
    try:
        keyring.set_password(SERVICIO, nombre, clave.strip())
    except KeyringError as error:
        raise _llavero_no_disponible(error) from error


def borrar(nombre: str = GEMINI) -> None:
    """Borra la clave del llavero; si no había ninguna, no hace nada."""
    try:
        keyring.delete_password(SERVICIO, nombre)
    except PasswordDeleteError:
        pass
    except KeyringError as error:
        raise _llavero_no_disponible(error) from error
