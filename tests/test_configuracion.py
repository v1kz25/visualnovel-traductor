"""Tests de los ajustes generales de la app."""

from pathlib import Path

import pytest

from vn_audiolibro.configuracion import (
    LIMITE_CACHE_MB,
    AjustesApp,
    cargar_ajustes,
    fichero_ajustes,
    formato_tamano,
    guardar_ajustes,
)


def test_por_defecto_sin_fichero(tmp_path: Path) -> None:
    ajustes = cargar_ajustes(tmp_path / "ajustes.json")
    assert ajustes.limite_cache_mb == LIMITE_CACHE_MB
    assert ajustes.limite_cache_bytes == LIMITE_CACHE_MB * 1024 * 1024


@pytest.mark.parametrize("limite", [500, None])
def test_guardar_y_cargar(tmp_path: Path, limite: int | None) -> None:
    ruta = tmp_path / "config" / "ajustes.json"
    guardar_ajustes(AjustesApp(limite_cache_mb=limite), ruta)
    assert cargar_ajustes(ruta) == AjustesApp(limite_cache_mb=limite)
    assert not list(ruta.parent.glob("*.parcial"))


def test_sin_limite_no_hay_bytes() -> None:
    assert AjustesApp(limite_cache_mb=None).limite_cache_bytes is None


def test_limite_demasiado_pequeno() -> None:
    with pytest.raises(ValueError, match="al menos 100 MB"):
        AjustesApp(limite_cache_mb=10)


@pytest.mark.parametrize(
    "contenido", ["no es json", "[]", '{"limite_cache_mb": "mucho"}', '{"limite_cache_mb": 5}']
)
def test_fichero_ilegible_da_los_de_por_defecto(
    tmp_path: Path, contenido: str, caplog: pytest.LogCaptureFixture
) -> None:
    ruta = tmp_path / "ajustes.json"
    ruta.write_text(contenido)
    assert cargar_ajustes(ruta) == AjustesApp()
    assert "Ajustes ilegibles" in caplog.text


def test_fichero_en_la_configuracion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert fichero_ajustes() == tmp_path / "vn-audiolibro" / "ajustes.json"


@pytest.mark.parametrize(
    ("bytes_", "texto"),
    [(0, "0 KB"), (230_400, "225 KB"), (1_258_291, "1,2 MB"), (2 * 1024**3, "2,0 GB")],
)
def test_formato_tamano(bytes_: int, texto: str) -> None:
    assert formato_tamano(bytes_) == texto
