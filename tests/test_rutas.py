"""Tests de los directorios de la app en Linux y en Windows."""

import sys
from pathlib import Path

import pytest

from vn_audiolibro.rutas import directorio_config, directorio_datos, directorio_estado

XDG = ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME")


@pytest.fixture
def sin_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for variable in XDG:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_linux_sigue_xdg_por_defecto(sin_xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert directorio_datos() == sin_xdg / ".local" / "share" / "vn-audiolibro"
    assert directorio_estado() == sin_xdg / ".local" / "state" / "vn-audiolibro"
    assert directorio_config() == sin_xdg / ".config" / "vn-audiolibro"


def test_windows_usa_appdata(sin_xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(sin_xdg / "Local"))
    monkeypatch.setenv("APPDATA", str(sin_xdg / "Roaming"))
    assert directorio_datos() == sin_xdg / "Local" / "vn-audiolibro"
    assert directorio_estado() == sin_xdg / "Local" / "vn-audiolibro" / "estado"
    assert directorio_config() == sin_xdg / "Roaming" / "vn-audiolibro"


def test_windows_sin_variables_usa_las_carpetas_del_perfil(
    sin_xdg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    assert directorio_datos() == sin_xdg / "AppData" / "Local" / "vn-audiolibro"
    assert directorio_config() == sin_xdg / "AppData" / "Roaming" / "vn-audiolibro"


@pytest.mark.parametrize("sistema", ["linux", "win32"])
def test_las_variables_xdg_mandan_en_cualquier_sistema(
    sistema: str, sin_xdg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", sistema)
    for variable in XDG:
        monkeypatch.setenv(variable, str(sin_xdg / variable))
    assert directorio_datos() == sin_xdg / "XDG_DATA_HOME" / "vn-audiolibro"
    assert directorio_estado() == sin_xdg / "XDG_STATE_HOME" / "vn-audiolibro"
    assert directorio_config() == sin_xdg / "XDG_CONFIG_HOME" / "vn-audiolibro"
