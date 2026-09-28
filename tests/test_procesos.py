"""Tests de la tabla de procesos, con un /proc falso y con el sistema real (Linux o Windows)."""

import os
import sys
from pathlib import Path

import pytest

from vn_audiolibro.procesos import Proceso, descendientes, listar_procesos, pids_propios


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los tests con un /proc falso leen como en Linux, también en Windows."""
    monkeypatch.setattr(sys, "platform", "linux")


def escribir_proceso(proc: Path, pid: int, nombre: str, ppid: int) -> None:
    carpeta = proc / str(pid)
    carpeta.mkdir()
    (carpeta / "stat").write_text(f"{pid} ({nombre}) S {ppid} 1 1 0 -1", encoding="utf-8")


@pytest.mark.usefixtures("linux")
def test_lee_proc_con_nombres_raros(tmp_path: Path) -> None:
    escribir_proceso(tmp_path, 100, "Juego (1).exe", 50)
    (tmp_path / "self").mkdir()
    (tmp_path / "300").mkdir()  # proceso que ha terminado mientras se leía

    assert listar_procesos(tmp_path) == {100: Proceso(100, 50, "Juego (1).exe")}


@pytest.mark.usefixtures("linux")
def test_sin_proc_no_hay_procesos(tmp_path: Path) -> None:
    assert listar_procesos(tmp_path / "no-existe") == {}


def test_el_sistema_real_incluye_este_proceso() -> None:
    propio = listar_procesos()[os.getpid()]
    assert propio.padre == os.getppid()
    assert propio.nombre


def test_pids_propios_incluye_este_proceso_y_su_padre() -> None:
    pids = pids_propios()
    assert os.getpid() in pids
    assert os.getppid() in pids or os.getppid() == 1


@pytest.mark.usefixtures("linux")
def test_pids_propios_sin_proc(tmp_path: Path) -> None:
    assert pids_propios(tmp_path) == frozenset({os.getpid()})


@pytest.mark.usefixtures("linux")
def test_pids_propios_no_se_cuelga_con_padres_reutilizados(tmp_path: Path) -> None:
    # En Windows el PID del padre puede ser ya de otro proceso, y formar un ciclo.
    escribir_proceso(tmp_path, os.getpid(), "python", 8)
    escribir_proceso(tmp_path, 8, "explorer", os.getpid())
    assert pids_propios(tmp_path) == frozenset({os.getpid(), 8})


def test_descendientes() -> None:
    procesos = {
        p.pid: p
        for p in [
            Proceso(4, 4, "System"),  # su propio padre: no debe hacer ciclo
            Proceso(100, 4, "juego.exe"),
            Proceso(101, 100, "voces.exe"),
            Proceso(102, 101, "otro.exe"),
            Proceso(200, 4, "firefox.exe"),
        ]
    }
    assert descendientes(100, procesos) == {100, 101, 102}
    assert descendientes(999, procesos) == {999}
