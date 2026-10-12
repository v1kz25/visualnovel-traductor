"""Aviso de versiones nuevas: consulta la última release en GitHub, como mucho una vez al día.

Nunca descarga ni instala nada: solo dice que hay una versión nueva y dónde verla. Si el usuario
lo ha desactivado (o aún no ha dicho que sí), no se hace ninguna petición.
"""

import json
import logging
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib.metadata import version

from vn_audiolibro.configuracion import AjustesApp

_registro = logging.getLogger(__name__)

REPO = "v1kz25/visualnovel-traductor"
URL_ULTIMA = f"https://api.github.com/repos/{REPO}/releases/latest"
URL_RELEASES = f"https://github.com/{REPO}/releases/"
"""Las releases se abren en el navegador solo si su enlace empieza así."""
TIEMPO_MAX_S = 5.0
INTERVALO_S = 24 * 60 * 60
"""Como mucho una consulta al día."""
LARGO_MAX_NOTAS = 4000

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Release:
    """Una versión publicada en GitHub."""

    version: str
    """Sin la «v» del tag: «0.3.0»."""
    url: str
    notas: str


Consultar = Callable[[], Release | None]


def numeros(texto: str) -> tuple[int, int, int] | None:
    """La versión «X.Y.Z» (con o sin «v» delante) como números, o None si no tiene ese formato."""
    encontrada = _VERSION.fullmatch(texto.strip())
    if encontrada is None:
        return None
    mayor, menor, parche = (int(parte) for parte in encontrada.groups())
    return mayor, menor, parche


def es_mas_nueva(candidata: str, actual: str) -> bool:
    """Si `candidata` es posterior a `actual`. Una versión que no se entiende nunca lo es."""
    nueva, instalada = numeros(candidata), numeros(actual)
    return nueva is not None and instalada is not None and nueva > instalada


def version_instalada() -> str:
    return version("vn-audiolibro")


def consultar_github(timeout_s: float = TIEMPO_MAX_S) -> Release | None:
    """La última release publicada, o None si no hay conexión, falla o la respuesta no es válida."""
    cabeceras = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"vn-audiolibro/{version_instalada()}",
    }
    peticion = urllib.request.Request(URL_ULTIMA, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout_s) as respuesta:  # noqa: S310
            datos = json.loads(respuesta.read(1024 * 1024))
        return leer_release(datos)
    except Exception:  # sin conexión, error HTTP, JSON roto…: no se avisa de nada
        _registro.info("No se pudo consultar la última versión", exc_info=True)
        return None


def leer_release(datos: object) -> Release | None:
    """La release de la respuesta de GitHub, o None si le falta algo o el enlace no es del repo."""
    if not isinstance(datos, dict):
        return None
    tag, url, notas = datos.get("tag_name"), datos.get("html_url"), datos.get("body") or ""
    if not (isinstance(tag, str) and isinstance(url, str) and isinstance(notas, str)):
        return None
    if numeros(tag) is None or not url.startswith(URL_RELEASES):
        return None
    return Release(tag.strip().removeprefix("v"), url, notas[:LARGO_MAX_NOTAS])


@dataclass(frozen=True)
class Busqueda:
    """Lo que ha salido de buscar una versión nueva."""

    ajustes: AjustesApp
    """Los ajustes con la hora de la búsqueda apuntada, para guardarlos."""
    nueva: Release | None
    """La versión de la que hay que avisar, o None."""


def toca_buscar(ajustes: AjustesApp, ahora: float) -> bool:
    """Si hay que consultar GitHub: activado y sin otra consulta en las últimas 24 horas."""
    if ajustes.avisar_versiones is not True:
        return False
    ultima = ajustes.ultima_busqueda
    # Una hora futura (el reloj se cambió) no debe bloquear la búsqueda para siempre.
    return ultima is None or not 0 <= ahora - ultima < INTERVALO_S


def buscar(
    ajustes: AjustesApp, ahora: float, actual: str, consultar: Consultar = consultar_github
) -> Busqueda:
    """Consulta la última versión si toca y dice si hay que avisar de ella (una vez por versión)."""
    if not toca_buscar(ajustes, ahora):
        return Busqueda(ajustes, None)
    ajustes = replace(ajustes, ultima_busqueda=ahora)
    release = consultar()
    if release is None or not es_mas_nueva(release.version, actual):
        return Busqueda(ajustes, None)
    if ajustes.version_avisada == release.version:
        return Busqueda(ajustes, None)
    return Busqueda(replace(ajustes, version_avisada=release.version), release)
