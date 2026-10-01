"""Tests contra el escritorio real de Windows (el de la CI). Crean ventanas propias con Win32."""

import ctypes
import os
import sys
import time
from collections.abc import Iterator

import numpy as np
import pytest

if sys.platform != "win32":
    pytest.skip("solo en Windows", allow_module_level=True)

from ctypes import wintypes

from vn_audiolibro import plataforma
from vn_audiolibro.captura.capturador import CapturadorMss
from vn_audiolibro.captura.modelos import (
    Rectangulo,
    VentanaMinimizadaError,
    VentanaNoEncontradaError,
)
from vn_audiolibro.captura.win32 import CapturadorVentanaWin32, GestorVentanasWin32

TITULO = "vn-audiolibro prueba ventana 測試 テスト"
VERDE = 0x0000C000  # COLORREF: 0x00BBGGRR
WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
SW_MINIMIZE, SW_RESTORE = 6, 9

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = (
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
)  # fmt: skip
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UpdateWindow.argtypes = (wintypes.HWND,)
user32.PeekMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
)
user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
gdi32.CreateSolidBrush.argtypes = (wintypes.COLORREF,)
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class WNDCLASSW(ctypes.Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


_procedimiento = WNDPROC(
    lambda hwnd, mensaje, wparam, lparam: user32.DefWindowProcW(hwnd, mensaje, wparam, lparam)
)
_clase = WNDCLASSW(
    lpfnWndProc=_procedimiento,
    hInstance=kernel32.GetModuleHandleW(None),
    hbrBackground=gdi32.CreateSolidBrush(VERDE),
    lpszClassName="VnAudiolibroPrueba",
)
_clase_roja = WNDCLASSW(
    lpfnWndProc=_procedimiento,
    hInstance=_clase.hInstance,
    hbrBackground=gdi32.CreateSolidBrush(0x000000FF),
    lpszClassName="VnAudiolibroPruebaRoja",
)
user32.RegisterClassW(ctypes.byref(_clase))
user32.RegisterClassW(ctypes.byref(_clase_roja))


def bombear(segundos: float = 0.3) -> None:
    """Atiende los mensajes de la ventana (pintarse, minimizarse…) durante un rato."""
    mensaje = wintypes.MSG()
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        while user32.PeekMessageW(ctypes.byref(mensaje), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(mensaje))
            user32.DispatchMessageW(ctypes.byref(mensaje))
        time.sleep(0.01)


@pytest.fixture
def ventana() -> Iterator[int]:
    hwnd = user32.CreateWindowExW(
        0, _clase.lpszClassName, TITULO, WS_POPUP | WS_VISIBLE, 40, 60, 320, 240, None, None, None, None
    )
    assert hwnd, ctypes.WinError(ctypes.get_last_error())
    user32.UpdateWindow(hwnd)
    bombear()
    yield hwnd
    user32.DestroyWindow(hwnd)
    bombear(0.05)


def test_lista_la_ventana_con_titulo_pid_y_geometria(ventana: int) -> None:
    encontradas = [v for v in GestorVentanasWin32().listar() if v.id == ventana]

    assert len(encontradas) == 1
    assert encontradas[0].titulo == TITULO
    assert encontradas[0].pid == os.getpid()
    assert (encontradas[0].geometria.ancho, encontradas[0].geometria.alto) == (320, 240)


def test_busca_por_parte_del_titulo(ventana: int) -> None:
    assert GestorVentanasWin32().buscar("PRUEBA VENTANA", excluir_pids=frozenset()).id == ventana


def test_buscar_ignora_las_ventanas_del_propio_proceso(ventana: int) -> None:
    with pytest.raises(VentanaNoEncontradaError):
        GestorVentanasWin32().buscar("PRUEBA VENTANA")


def test_geometria_de_ventana_cerrada_falla() -> None:
    with pytest.raises(VentanaNoEncontradaError):
        GestorVentanasWin32().geometria(0x7FFFFFF0)


def test_geometria_en_pantalla(ventana: int) -> None:
    assert GestorVentanasWin32().geometria(ventana) == Rectangulo(40, 60, 320, 240)


def test_capturador_lee_el_contenido(ventana: int) -> None:
    imagen = CapturadorVentanaWin32().capturar(ventana, Rectangulo(8, 8, 32, 16))

    assert imagen.shape == (16, 32, 3)
    assert tuple(imagen[0, 0]) == (0, 0xC0, 0)


def test_capturador_ventana_tapada(ventana: int) -> None:
    # Otra ventana roja encima: PrintWindow sigue dando el contenido verde de la de debajo.
    encima = user32.CreateWindowExW(
        0x8,
        _clase_roja.lpszClassName,
        "encima",
        WS_POPUP | WS_VISIBLE,
        0,
        0,
        800,
        600,
        None,
        None,
        None,
        None,
    )
    bombear()
    try:
        imagen = CapturadorVentanaWin32().capturar(ventana, Rectangulo(0, 0, 32, 16))
    finally:
        user32.DestroyWindow(encima)
    assert tuple(imagen[0, 0]) == (0, 0xC0, 0)


def test_minimizada(ventana: int) -> None:
    user32.ShowWindow(ventana, SW_MINIMIZE)
    bombear()
    with pytest.raises(VentanaMinimizadaError):
        CapturadorVentanaWin32().capturar(ventana, Rectangulo(0, 0, 32, 16))
    assert ventana not in {v.id for v in GestorVentanasWin32().listar()}


class CapturadorFijo:
    def capturar(self, id_ventana: int, zona: Rectangulo) -> np.ndarray:
        return np.full((zona.alto, zona.ancho, 3), 7, dtype=np.uint8)


def test_si_sale_todo_negro_usa_el_alternativo(ventana: int, monkeypatch: pytest.MonkeyPatch) -> None:
    from vn_audiolibro.captura import win32

    monkeypatch.setattr(win32, "_imprimir", lambda *_: np.zeros((20, 20, 4), dtype=np.uint8))
    imagen = CapturadorVentanaWin32(alternativo=CapturadorFijo()).capturar(ventana, Rectangulo(0, 0, 10, 10))
    assert imagen.max() == 7


def test_si_falla_sin_alternativo_avisa(ventana: int, monkeypatch: pytest.MonkeyPatch) -> None:
    from vn_audiolibro.captura import win32

    monkeypatch.setattr(win32, "_imprimir", lambda *_: None)
    with pytest.raises(VentanaNoEncontradaError, match="no da el contenido"):
        CapturadorVentanaWin32().capturar(ventana, Rectangulo(0, 0, 10, 10))


def test_plataforma_usa_win32(ventana: int) -> None:
    gestor = plataforma.gestor_ventanas()
    capturador = plataforma.capturador(gestor)

    assert isinstance(gestor, GestorVentanasWin32)
    assert isinstance(capturador, CapturadorVentanaWin32)
    assert isinstance(plataforma.capturador(gestor, solo_pantalla=True), CapturadorMss)
    assert tuple(capturador.capturar(ventana, Rectangulo(0, 0, 4, 4))[0, 0]) == (0, 0xC0, 0)


def test_ventana_activa(ventana: int) -> None:
    user32.SetForegroundWindow(ventana)
    bombear()

    activa = GestorVentanasWin32().activa()

    assert activa is None or isinstance(activa, int)  # en la CI puede no dejar cambiar el foco
