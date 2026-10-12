"""Tests contra un servidor X real (Xvfb en la CI): se cogen atajos y se simulan teclas con XTEST."""

import os
import queue
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="necesita un servidor X")
pytest.importorskip("Xlib", reason="solo en Linux")

from Xlib import XK, X, display  # noqa: E402
from Xlib.ext import xtest  # noqa: E402

from vn_audiolibro.atajos.modelos import Accion, Atajo  # noqa: E402
from vn_audiolibro.atajos.x11 import EscuchaAtajosX11, mascara  # noqa: E402

# Combinaciones raras, para no chocar con las del escritorio si se ejecuta en uno real. Nunca
# Ctrl+Alt+F1…F12: en Linux cambian de consola antes de llegar a ningún atajo.
PAUSA = Atajo.leer("Ctrl+Alt+Shift+K")
SALTAR = Atajo.leer("Ctrl+Alt+Shift+J")
ESPERA_S = 5


@pytest.fixture
def escucha() -> Iterator[EscuchaAtajosX11]:
    escucha = EscuchaAtajosX11()
    yield escucha
    escucha.detener()


@pytest.fixture
def teclado() -> Iterator[display.Display]:
    conexion = display.Display()
    if not conexion.has_extension("XTEST"):
        conexion.close()
        pytest.skip("el servidor X no tiene XTEST")
    yield conexion
    conexion.close()


def pulsar(conexion: display.Display, *teclas: str) -> None:
    """Pulsa las teclas en orden y las suelta al revés, como una persona."""
    codigos = [conexion.keysym_to_keycode(XK.string_to_keysym(tecla)) for tecla in teclas]
    for codigo in codigos:
        xtest.fake_input(conexion, X.KeyPress, codigo)
    for codigo in reversed(codigos):
        xtest.fake_input(conexion, X.KeyRelease, codigo)
    conexion.sync()


def test_mascara() -> None:
    assert mascara(Atajo.leer("Ctrl+Alt+P")) == X.ControlMask | X.Mod1Mask
    assert mascara(Atajo.leer("Meta+Shift+F1")) == X.Mod4Mask | X.ShiftMask


def test_avisa_al_pulsar_el_atajo(escucha: EscuchaAtajosX11, teclado: display.Display) -> None:
    pulsadas: queue.Queue[Accion] = queue.Queue()
    assert escucha.iniciar({Accion.PAUSA: PAUSA, Accion.SALTAR: SALTAR}, pulsadas.put) == []

    pulsar(teclado, "Control_L", "Alt_L", "Shift_L", "J")
    assert pulsadas.get(timeout=ESPERA_S) is Accion.SALTAR
    pulsar(teclado, "Control_L", "Alt_L", "Shift_L", "K")
    assert pulsadas.get(timeout=ESPERA_S) is Accion.PAUSA


def test_un_atajo_que_ya_usa_otra_aplicacion_no_se_coge(escucha: EscuchaAtajosX11) -> None:
    otra = EscuchaAtajosX11()
    try:
        assert otra.iniciar({Accion.PAUSA: PAUSA}, lambda _: None) == []
        assert escucha.iniciar({Accion.PAUSA: PAUSA, Accion.SALTAR: SALTAR}, lambda _: None) == [Accion.PAUSA]
    finally:
        otra.detener()


def test_al_detener_se_liberan(escucha: EscuchaAtajosX11) -> None:
    assert escucha.iniciar({Accion.PAUSA: PAUSA}, lambda _: None) == []
    escucha.detener()
    escucha.detener()  # dos veces no falla

    otra = EscuchaAtajosX11()
    try:
        assert otra.iniciar({Accion.PAUSA: PAUSA}, lambda _: None) == []
    finally:
        otra.detener()
