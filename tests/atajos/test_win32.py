"""Tests contra el escritorio real de Windows (el de la CI): se registran atajos y se simulan teclas."""

import ctypes
import queue
import sys
from collections.abc import Iterator

import pytest

if sys.platform != "win32":
    pytest.skip("solo en Windows", allow_module_level=True)

from vn_audiolibro import plataforma
from vn_audiolibro.atajos.modelos import Accion, Atajo
from vn_audiolibro.atajos.win32 import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    EscuchaAtajosWin32,
    codigo_tecla,
    modificadores,
)

PAUSA = Atajo.leer("Ctrl+Alt+Shift+K")
SALTAR = Atajo.leer("Ctrl+Alt+Shift+J")
VK_CONTROL, VK_MENU, VK_SHIFT = 0x11, 0x12, 0x10
KEYEVENTF_KEYUP = 0x2
ESPERA_S = 5

user32 = ctypes.WinDLL("user32")


@pytest.fixture
def escucha() -> Iterator[EscuchaAtajosWin32]:
    escucha = EscuchaAtajosWin32()
    yield escucha
    escucha.detener()


def pulsar(*teclas: int) -> None:
    for tecla in teclas:
        user32.keybd_event(tecla, 0, 0, 0)
    for tecla in reversed(teclas):
        user32.keybd_event(tecla, 0, KEYEVENTF_KEYUP, 0)


def test_codigos() -> None:
    assert (codigo_tecla("A"), codigo_tecla("7"), codigo_tecla("F1"), codigo_tecla("F12")) == (
        0x41,
        0x37,
        0x70,
        0x7B,
    )
    assert modificadores(PAUSA) == MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT


def test_la_plataforma_da_la_de_windows() -> None:
    assert isinstance(plataforma.escucha_atajos(), EscuchaAtajosWin32)


def test_avisa_al_pulsar_el_atajo(escucha: EscuchaAtajosWin32) -> None:
    pulsadas: queue.Queue[Accion] = queue.Queue()
    assert escucha.iniciar({Accion.PAUSA: PAUSA, Accion.SALTAR: SALTAR}, pulsadas.put) == []

    pulsar(VK_CONTROL, VK_MENU, VK_SHIFT, ord("J"))
    assert pulsadas.get(timeout=ESPERA_S) is Accion.SALTAR
    pulsar(VK_CONTROL, VK_MENU, VK_SHIFT, ord("K"))
    assert pulsadas.get(timeout=ESPERA_S) is Accion.PAUSA


def test_un_atajo_que_ya_usa_otra_aplicacion_no_se_registra(escucha: EscuchaAtajosWin32) -> None:
    otra = EscuchaAtajosWin32()
    try:
        assert otra.iniciar({Accion.PAUSA: PAUSA}, lambda _: None) == []
        assert escucha.iniciar({Accion.PAUSA: PAUSA, Accion.SALTAR: SALTAR}, lambda _: None) == [Accion.PAUSA]
    finally:
        otra.detener()


def test_al_detener_se_liberan(escucha: EscuchaAtajosWin32) -> None:
    assert escucha.iniciar({Accion.PAUSA: PAUSA}, lambda _: None) == []
    escucha.detener()
    escucha.detener()

    otra = EscuchaAtajosWin32()
    try:
        assert otra.iniciar({Accion.PAUSA: PAUSA}, lambda _: None) == []
    finally:
        otra.detener()
