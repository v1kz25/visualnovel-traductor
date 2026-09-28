"""Tests del acceso directo en el menú de aplicaciones."""

import subprocess
import sys
from pathlib import Path

import pytest

from vn_audiolibro.ui import acceso
from vn_audiolibro.ui.acceso import (
    AccesoNoDisponibleError,
    acceso_menu_inicio,
    crear_lnk,
    instalar_acceso,
    instalar_acceso_windows,
    ofrecer_acceso_windows,
)


def test_instalar_acceso(tmp_path: Path) -> None:
    desktop = instalar_acceso(tmp_path, "/ruta/python")

    assert desktop == tmp_path / "applications" / "vn-audiolibro.desktop"
    contenido = desktop.read_text(encoding="utf-8")
    assert 'Exec="/ruta/python" -m vn_audiolibro\n' in contenido
    svg = tmp_path / "icons" / "hicolor" / "scalable" / "apps" / "vn-audiolibro.svg"
    assert f"Icon={svg}\n" in contenido
    assert "StartupWMClass=vn-audiolibro\n" in contenido
    assert svg.read_text(encoding="utf-8").lstrip().startswith("<svg")


def test_instalar_acceso_respeta_xdg_data_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    desktop = instalar_acceso()

    assert desktop == tmp_path / "applications" / "vn-audiolibro.desktop"
    assert (tmp_path / "icons" / "hicolor" / "scalable" / "apps" / "vn-audiolibro.svg").exists()


def test_instalar_acceso_actualiza_el_existente(tmp_path: Path) -> None:
    instalar_acceso(tmp_path, "/python/viejo")
    desktop = instalar_acceso(tmp_path, "/python/nuevo")

    contenido = desktop.read_text(encoding="utf-8")
    assert "/python/nuevo" in contenido
    assert "/python/viejo" not in contenido


# Windows: acceso directo en el menú Inicio


def test_acceso_windows_desde_la_version_empaquetada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "vn-audiolibro-consola.exe"))
    creados: list[tuple[Path, Path]] = []

    acceso = instalar_acceso_windows(tmp_path / "Programs", crear=lambda a, e: creados.append((a, e)))

    assert acceso == tmp_path / "Programs" / "vn-audiolibro.lnk"
    # Aunque se cree desde la consola, el acceso abre la interfaz.
    assert creados == [(acceso, tmp_path / "app" / "vn-audiolibro.exe")]
    assert acceso.parent.is_dir()


def test_sin_empaquetar_no_se_crea_el_acceso_de_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    with pytest.raises(AccesoNoDisponibleError, match="versión empaquetada"):
        instalar_acceso_windows(tmp_path, crear=lambda *_: pytest.fail("no debería crearlo"))


def test_el_menu_inicio_esta_en_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    esperado = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "vn-audiolibro.lnk"
    assert acceso_menu_inicio() == esperado


def test_crear_lnk_pasa_las_rutas_por_el_entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[tuple[list[str], dict[str, str]]] = []

    def run(orden: list[str], env: dict[str, str], **_: object) -> None:
        llamadas.append((orden, env))

    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    monkeypatch.setattr(acceso.subprocess, "run", run)
    raro = tmp_path / "Programs con 'comillas' y $variables" / "vn-audiolibro.lnk"

    crear_lnk(raro, tmp_path / "vn-audiolibro.exe")

    ((orden, entorno),) = llamadas
    assert orden[0] == str(tmp_path / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    assert str(raro) not in " ".join(orden)  # la ruta no se mete en el script
    assert entorno["VN_ACCESO"] == str(raro)
    assert entorno["VN_EJECUTABLE"] == str(tmp_path / "vn-audiolibro.exe")


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "powershell", stderr=b"Acceso denegado"),
        FileNotFoundError("no hay powershell"),
    ],
)
def test_crear_lnk_avisa_si_falla(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception) -> None:
    def run(*_: object, **__: object) -> None:
        raise error

    monkeypatch.setattr(acceso.subprocess, "run", run)
    with pytest.raises(AccesoNoDisponibleError, match=r"Acceso denegado|no hay powershell"):
        crear_lnk(tmp_path / "a.lnk", tmp_path / "a.exe")


@pytest.mark.parametrize(
    ("plataforma", "empaquetada", "existe", "ofrece"),
    [
        ("win32", True, False, True),
        ("win32", True, True, False),
        ("win32", False, False, False),
        ("linux", True, False, False),
    ],
)
def test_cuando_se_ofrece_el_acceso_de_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plataforma: str,
    empaquetada: bool,
    existe: bool,
    ofrece: bool,
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    if existe:
        acceso_menu_inicio().parent.mkdir(parents=True)
        acceso_menu_inicio().touch()
    monkeypatch.setattr(sys, "frozen", empaquetada, raising=False)
    monkeypatch.setattr(sys, "platform", plataforma)
    assert (ofrecer_acceso_windows() is instalar_acceso_windows) is ofrece


@pytest.mark.skipif(sys.platform != "win32", reason="el .lnk solo se crea en Windows")
def test_crea_un_lnk_real_en_windows(tmp_path: Path) -> None:
    lnk = tmp_path / "vn-audiolibro.lnk"
    crear_lnk(lnk, Path(sys.executable))
    assert lnk.read_bytes()[:4] == b"L\x00\x00\x00"  # cabecera de los .lnk
