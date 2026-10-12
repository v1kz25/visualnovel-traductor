"""Ajustes generales de la app, comunes a todos los juegos (`~/.config/vn-audiolibro/ajustes.json`)."""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vn_audiolibro.rutas import directorio_config
from vn_audiolibro.textos import _, decimal

_registro = logging.getLogger(__name__)

LIMITE_CACHE_MB = 2048
"""Tamaño máximo de la caché por defecto: da para varias novelas enteras con su audio."""
LIMITE_MIN_MB = 100


@dataclass(frozen=True)
class AjustesApp:
    """Ajustes que no dependen del juego."""

    limite_cache_mb: int | None = LIMITE_CACHE_MB
    """Tamaño máximo de la caché en MB, o None para no limitarla."""
    idioma: str | None = None
    """Idioma de la interfaz elegido en la app, o None para usar el del sistema."""
    avisar_versiones: bool | None = None
    """Si se busca al arrancar si hay una versión nueva; None si aún no se ha preguntado."""
    ultima_busqueda: float | None = None
    """Cuándo se buscó por última vez una versión nueva (segundos desde 1970)."""
    version_avisada: str | None = None
    """Última versión nueva de la que se ha avisado, para no repetir el aviso."""

    def __post_init__(self) -> None:
        if self.limite_cache_mb is not None and self.limite_cache_mb < LIMITE_MIN_MB:
            raise ValueError(
                _("El límite de la caché tiene que ser de al menos {minimo} MB").format(minimo=LIMITE_MIN_MB)
            )

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
        ultima = _opcional(datos, "ultima_busqueda", (int, float))
        return AjustesApp(
            limite_cache_mb=limite,
            idioma=_opcional(datos, "idioma", str),
            avisar_versiones=_opcional(datos, "avisar_versiones", bool),
            ultima_busqueda=None if ultima is None else float(ultima),
            version_avisada=_opcional(datos, "version_avisada", str),
        )
    except FileNotFoundError:
        return AjustesApp()
    except (OSError, ValueError, TypeError, AttributeError):
        _registro.warning("Ajustes ilegibles en %s: se usan los de por defecto", ruta, exc_info=True)
        return AjustesApp()


def _opcional(datos: dict[str, Any], campo: str, tipos: type | tuple[type, ...]) -> Any:
    """El valor de `campo`, o None si no está; TypeError si no es de los tipos esperados."""
    valor = datos.get(campo)
    es_bool_por_numero = isinstance(valor, bool) and tipos is not bool  # `bool` es un `int`
    if valor is not None and (not isinstance(valor, tipos) or es_bool_por_numero):
        raise TypeError(f"{campo} no válido: {valor!r}")
    return valor


def guardar_ajustes(ajustes: AjustesApp, ruta: Path | None = None) -> None:
    ruta = ruta or fichero_ajustes()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".parcial")
    datos = asdict(ajustes)
    temporal.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
    temporal.replace(ruta)


def formato_tamano(bytes_: int) -> str:
    """Tamaño legible con el separador decimal del idioma: «225 KB», «1,2 MB», «2,0 GB»."""
    for unidad, factor in (("GB", 1024**3), ("MB", 1024**2)):
        if bytes_ >= factor:
            return f"{decimal(bytes_ / factor, 1)} {unidad}"
    return f"{round(bytes_ / 1024)} KB"
