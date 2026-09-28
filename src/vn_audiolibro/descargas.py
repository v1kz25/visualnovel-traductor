"""Descarga y verificación de los ficheros externos: modelos de OCR y traducción y `llama-server`.

No van en el repo ni en el AppImage: se descargan en el primer arranque desde una URL fija y
solo se aceptan si su SHA-256 coincide con el esperado.
"""

import hashlib
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vn_audiolibro.rutas import directorio_datos

TAM_BLOQUE = 1 << 20


@dataclass(frozen=True)
class Descarga:
    """Fichero descargable con su origen y su huella."""

    fichero: str
    url: str
    sha256: str


Progreso = Callable[[int, int | None], None]
"""Avisa de los bytes descargados y del total (None si el servidor no lo indica)."""

Cancelado = Callable[[], bool]
"""Devuelve True cuando hay que abandonar la descarga."""

Descargador = Callable[[str, Path, Progreso | None, Cancelado | None], None]
"""Función que descarga una URL en una ruta, informando del progreso y atenta a la cancelación."""


class DescargaFallidaError(Exception):
    """El fichero no se pudo descargar o no es el esperado."""


class DescargaCanceladaError(DescargaFallidaError):
    """Se ha cancelado la descarga a medias."""


def directorio_modelos() -> Path:
    """Directorio de datos del usuario donde se guardan los modelos (XDG)."""
    return directorio_datos() / "modelos"


def sha256_fichero(ruta: Path) -> str:
    """SHA-256 en hexadecimal de un fichero, leído por bloques."""
    huella = hashlib.sha256()
    with ruta.open("rb") as fichero:
        while bloque := fichero.read(TAM_BLOQUE):
            huella.update(bloque)
    return huella.hexdigest()


def descargar_https(
    url: str, destino: Path, progreso: Progreso | None = None, cancelado: Cancelado | None = None
) -> None:
    """Descarga una URL HTTPS en `destino`, bloque a bloque."""
    if not url.startswith("https://"):
        raise DescargaFallidaError(f"Solo se descarga por HTTPS: {url}")
    with urllib.request.urlopen(url, timeout=60) as respuesta, destino.open("wb") as fichero:  # noqa: S310
        longitud = respuesta.headers.get("Content-Length")
        total = int(longitud) if longitud and longitud.isdigit() else None
        hecho = 0
        while bloque := respuesta.read(TAM_BLOQUE):
            if cancelado is not None and cancelado():
                raise DescargaCanceladaError(f"Descarga cancelada: {destino.name}")
            fichero.write(bloque)
            hecho += len(bloque)
            if progreso is not None:
                progreso(hecho, total)


def asegurar_descarga(
    descarga: Descarga,
    directorio: Path | None = None,
    descargar: Descargador = descargar_https,
    progreso: Progreso | None = None,
    cancelado: Cancelado | None = None,
) -> Path:
    """Devuelve la ruta del fichero y lo descarga antes si no está o no es el esperado.

    La descarga va a un fichero temporal y solo se mueve a su sitio si el SHA-256 coincide,
    así que un corte a medias nunca deja un fichero roto.
    """
    carpeta = directorio or directorio_modelos()
    ruta = carpeta / descarga.fichero
    if ruta.is_file() and sha256_fichero(ruta) == descarga.sha256:
        return ruta

    carpeta.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".parcial")
    try:
        descargar(descarga.url, temporal, progreso, cancelado)
        obtenido = sha256_fichero(temporal)
        if obtenido != descarga.sha256:
            raise DescargaFallidaError(
                f"SHA-256 inesperado en {descarga.fichero}: {obtenido} (se esperaba {descarga.sha256})"
            )
        temporal.replace(ruta)
    except OSError as error:
        raise DescargaFallidaError(f"No se pudo descargar {descarga.fichero}: {error}") from error
    finally:
        temporal.unlink(missing_ok=True)
    return ruta


def extraer_tar(archivo: Path, destino: Path) -> Path:
    """Extrae un `.tar.gz` en `destino` y devuelve la carpeta.

    Usa el filtro `data` de `tarfile`: rechaza rutas fuera del destino, enlaces que apunten fuera
    y ficheros especiales, y conserva los enlaces simbólicos internos (las bibliotecas de
    llama.cpp los usan) y los permisos de ejecución.
    """
    destino.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archivo, "r:gz") as tar:
            tar.extractall(destino, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise DescargaFallidaError(f"No se pudo extraer {archivo.name}: {error}") from error
    return destino


def extraer_zip(archivo: Path, destino: Path) -> Path:
    """Extrae un `.zip` en `destino` y devuelve la carpeta.

    Rechaza el archivo entero si alguna entrada saldría del destino (ruta absoluta o con `..`),
    en vez de dejar que `zipfile` la recoloque en silencio.
    """
    destino.mkdir(parents=True, exist_ok=True)
    raiz = destino.resolve()
    try:
        with zipfile.ZipFile(archivo) as zip_:
            for nombre in zip_.namelist():
                if not (raiz / nombre).resolve().is_relative_to(raiz):
                    raise DescargaFallidaError(
                        f"No se pudo extraer {archivo.name}: {nombre} sale del destino"
                    )
            zip_.extractall(destino)  # noqa: S202 - rutas comprobadas arriba
    except (zipfile.BadZipFile, OSError) as error:
        raise DescargaFallidaError(f"No se pudo extraer {archivo.name}: {error}") from error
    return destino
