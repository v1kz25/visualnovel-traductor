"""Tests de la elección de implementación según el sistema operativo."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from vn_audiolibro import plataforma
from vn_audiolibro.captura.capturador import CapturadorMss
from vn_audiolibro.captura.modelos import Rectangulo
from vn_audiolibro.voz.portaudio import ReproductorPortAudio
from vn_audiolibro.voz.volumen import Juego

IDIOMAS_SISTEMA = plataforma.idiomas_sistema
"""La de verdad: en los tests, `plataforma.idiomas_sistema` se sustituye por el español."""
VENTANAS = SimpleNamespace(geometria=lambda _: Rectangulo(0, 0, 10, 10))


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.mark.usefixtures("windows")
def test_captura_de_pantalla_vale_en_cualquier_sistema() -> None:
    capturador = plataforma.capturador(VENTANAS, solo_pantalla=True)  # type: ignore[arg-type]
    assert isinstance(capturador, CapturadorMss)
    capturador.cerrar()


@pytest.mark.skipif(sys.platform != "linux", reason="solo en Linux")
def test_en_linux_usa_x11_y_pulseaudio(monkeypatch: pytest.MonkeyPatch) -> None:
    from vn_audiolibro.captura import x11
    from vn_audiolibro.voz import reproductor, volumen

    monkeypatch.setattr(x11, "GestorVentanasX11", lambda: "gestor x11")
    monkeypatch.setattr(x11, "CapturadorVentanaX11", lambda alternativo: ("x11", type(alternativo)))
    monkeypatch.setattr(reproductor, "ReproductorProceso", lambda: "paplay")
    monkeypatch.setattr(volumen, "ClientePulse", lambda: "pulse")
    monkeypatch.setattr(volumen, "juego_de_pid", lambda pid: Juego(frozenset({pid}), frozenset()))

    assert plataforma.gestor_ventanas() == "gestor x11"
    assert plataforma.capturador(VENTANAS) == ("x11", CapturadorMss)  # type: ignore[arg-type]
    assert plataforma.reproductor() == "paplay"
    assert plataforma.cliente_audio() == "pulse"
    assert plataforma.juego_de_pid(7).pids == frozenset({7})


def test_en_windows_usa_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    # El módulo real solo se importa en Windows: aquí se sustituye por uno falso.
    falso = SimpleNamespace(
        GestorVentanasWin32=lambda: "gestor win32",
        CapturadorVentanaWin32=lambda alternativo: ("win32", type(alternativo)),
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "vn_audiolibro.captura.win32", falso)

    assert plataforma.gestor_ventanas() == "gestor win32"
    assert plataforma.capturador(VENTANAS) == ("win32", CapturadorMss)  # type: ignore[arg-type]
    assert isinstance(plataforma.reproductor(), ReproductorPortAudio)

    from vn_audiolibro.voz import coreaudio

    monkeypatch.setattr(coreaudio, "ClienteCoreAudio", lambda: "core audio")
    assert plataforma.cliente_audio() == "core audio"


@pytest.mark.skipif(sys.platform == "win32", reason="en Windows sí existe")
def test_el_modulo_de_windows_no_se_importa_en_linux() -> None:
    with pytest.raises(ImportError, match="solo funciona en Windows"):
        import vn_audiolibro.captura.win32  # noqa: F401


def test_procesos_sin_consola_en_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert plataforma.sin_ventana() == 0
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert plataforma.sin_ventana() == 0x08000000


def test_en_otros_sistemas_no_hay_ventanas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(plataforma.PlataformaNoCompatibleError, match="darwin"):
        plataforma.gestor_ventanas()
    with pytest.raises(plataforma.PlataformaNoCompatibleError, match="darwin"):
        plataforma.capturador(VENTANAS)  # type: ignore[arg-type]
    with pytest.raises(plataforma.PlataformaNoCompatibleError, match="darwin"):
        plataforma.reproductor()
    with pytest.raises(plataforma.PlataformaNoCompatibleError, match="darwin"):
        plataforma.cliente_audio()


@pytest.mark.parametrize(
    ("entorno", "esperado"),
    [
        ({"LANGUAGE": "en_GB:en", "LANG": "es_ES.UTF-8"}, ["en_GB", "en", "es_ES.UTF-8"]),
        ({"LC_ALL": "C", "LC_MESSAGES": "fr_FR.UTF-8", "LANG": "POSIX"}, ["fr_FR.UTF-8"]),
        ({}, []),
    ],
)
def test_idiomas_del_sistema_en_linux(entorno: dict[str, str], esperado: list[str]) -> None:
    assert IDIOMAS_SISTEMA(entorno) == esperado


def test_idiomas_del_sistema_en_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sale del idioma de la interfaz de Windows; si no se puede leer, no hay ninguno."""
    import ctypes

    kernel32 = SimpleNamespace(GetUserDefaultUILanguage=lambda: 0x0C0A)  # español de España
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)
    assert IDIOMAS_SISTEMA() == ["es_ES"]
    monkeypatch.delattr(ctypes, "windll")
    assert IDIOMAS_SISTEMA() == []


def test_carpeta_de_proceso() -> None:
    carpeta = plataforma.carpeta_de_proceso(os.getpid())

    assert carpeta is not None
    assert carpeta.is_dir()
    if plataforma.es_linux():
        assert carpeta == Path.cwd()


def test_carpeta_de_proceso_que_no_existe() -> None:
    assert plataforma.carpeta_de_proceso(2**30) is None
