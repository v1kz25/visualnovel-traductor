"""Ajustes generales de la app, comunes a todos los juegos (`~/.config/vn-audiolibro/ajustes.json`)."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from vn_audiolibro.rutas import directorio_config

_registro = logging.getLogger(__name__)

LIMITE_CACHE_MB = 2048
"""Tamaño máximo de la caché por defecto: da para varias novelas enteras con su audio."""
LIMITE_MIN_MB = 100


@dataclass(frozen=True)
class AjustesApp:
    """Ajustes que no dependen del juego."""

    limite_cache_mb: int | None = LIMITE_CACHE_MB
    """Tamaño máximo de la caché en MB, o None para no limitarla."""

    def __post_init__(self) -> None:
        if self.limite_cache_mb is not None and self.limite_cache_mb < LIMITE_MIN_MB:
            raise ValueError(f"El límite de la caché tiene que ser de al menos {LIMITE_MIN_MB} MB")

    @property
    def limite_cache_bytes(self) -> int | None:
        return None if self.limite_cache_mb is None else self.limite_cache_mb * 1024 * 1024


def fichero_ajustes() -> Path:
    return directorio_config() / "ajustes.json"


def cargar_ajustes(ruta: Path | None = None) -> AjustesApp:
    """Ajustes guardados; si no hay o no se pueden leer, los valores por defecto."""
    ruta = ruta or fichero_ajustes()
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        limite = datos.get("limite_cache_mb", LIMITE_CACHE_MB)
        if limite is not None and (isinstance(limite, bool) or not isinstance(limite, int)):
            raise TypeError(f"límite no válido: {limite!r}")
        return AjustesApp(limite_cache_mb=limite)
    except FileNotFoundError:
        return AjustesApp()
    except (OSError, ValueError, TypeError, AttributeError):
        _registro.warning("Ajustes ilegibles en %s: se usan los de por defecto", ruta, exc_info=True)
        return AjustesApp()


def guardar_ajustes(ajustes: AjustesApp, ruta: Path | None = None) -> None:
    ruta = ruta or fichero_ajustes()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".parcial")
    datos = {"limite_cache_mb": ajustes.limite_cache_mb}
    temporal.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
    temporal.replace(ruta)


def formato_tamano(bytes_: int) -> str:
    """Tamaño legible en español: «225 KB», «1,2 MB», «2,0 GB»."""
    for unidad, factor in (("GB", 1024**3), ("MB", 1024**2)):
        if bytes_ >= factor:
            return f"{bytes_ / factor:.1f} {unidad}".replace(".", ",")
    return f"{round(bytes_ / 1024)} KB"
