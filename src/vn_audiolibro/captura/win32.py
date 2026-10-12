"""Ventanas y captura en Windows, con la API Win32 a través de `ctypes`.

Las coordenadas son las del área cliente (sin marco ni barra de título) en píxeles físicos: el
proceso se declara consciente del DPI por monitor, como hace Qt, para que no las escale Windows.
"""

import sys

if sys.platform != "win32":
    raise ImportError("vn_audiolibro.captura.win32 solo funciona en Windows")

import ctypes
from ctypes import wintypes
from functools import cache
from typing import Any

import numpy as np

from vn_audiolibro.captura.capturador import Capturador
from vn_audiolibro.captura.modelos import (
    Imagen,
    Rectangulo,
    Ventana,
    VentanaMinimizadaError,
    VentanaNoEncontradaError,
    buscar_por_titulo,
)
from vn_audiolibro.procesos import pids_propios
from vn_audiolibro.textos import _

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
"""Pide el contenido compuesto por el DWM: vale también para ventanas de DirectX (Windows 8.1+)."""
DWMWA_CLOAKED = 14
DIB_RGB_COLORS = 0
BI_RGB = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


class _Encabezado(ctypes.Structure):  # BITMAPINFOHEADER
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class _InfoMapa(ctypes.Structure):  # BITMAPINFO
    _fields_ = (("bmiHeader", _Encabezado), ("bmiColors", wintypes.DWORD * 3))


_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")


def _prototipo(funcion: Any, argumentos: tuple[Any, ...], resultado: Any) -> None:
    funcion.argtypes = argumentos
    funcion.restype = resultado


_HWND, _HDC, _INT, _UINT, _BOOL = wintypes.HWND, wintypes.HDC, ctypes.c_int, wintypes.UINT, wintypes.BOOL
_prototipo(_user32.EnumWindows, (_EnumProc, wintypes.LPARAM), _BOOL)
_prototipo(_user32.IsWindow, (_HWND,), _BOOL)
_prototipo(_user32.IsWindowVisible, (_HWND,), _BOOL)
_prototipo(_user32.IsIconic, (_HWND,), _BOOL)
_prototipo(_user32.GetWindowTextLengthW, (_HWND,), _INT)
_prototipo(_user32.GetWindowTextW, (_HWND, wintypes.LPWSTR, _INT), _INT)
_prototipo(_user32.GetWindowThreadProcessId, (_HWND, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD)
_prototipo(_user32.GetClientRect, (_HWND, ctypes.POINTER(wintypes.RECT)), _BOOL)
_prototipo(_user32.GetForegroundWindow, (), _HWND)
_prototipo(_user32.ClientToScreen, (_HWND, ctypes.POINTER(wintypes.POINT)), _BOOL)
_prototipo(_user32.PrintWindow, (_HWND, _HDC, _UINT), _BOOL)
_prototipo(_user32.GetDC, (_HWND,), _HDC)
_prototipo(_user32.ReleaseDC, (_HWND, _HDC), _INT)
_prototipo(_user32.SetProcessDpiAwarenessContext, (wintypes.HANDLE,), _BOOL)
_prototipo(_gdi32.CreateCompatibleDC, (_HDC,), _HDC)
_prototipo(_gdi32.CreateCompatibleBitmap, (_HDC, _INT, _INT), wintypes.HBITMAP)
_prototipo(_gdi32.SelectObject, (_HDC, wintypes.HGDIOBJ), wintypes.HGDIOBJ)
_prototipo(
    _gdi32.GetDIBits,
    (_HDC, wintypes.HBITMAP, _UINT, _UINT, wintypes.LPVOID, ctypes.POINTER(_InfoMapa), _UINT),
    _INT,
)
_prototipo(_gdi32.DeleteObject, (wintypes.HGDIOBJ,), _BOOL)
_prototipo(_gdi32.DeleteDC, (_HDC,), _BOOL)
_prototipo(
    _dwmapi.DwmGetWindowAttribute, (_HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD), ctypes.c_long
)


@cache
def _consciente_del_dpi() -> None:
    """Pide coordenadas físicas. Si Qt ya lo ha hecho, Windows lo rechaza y no pasa nada."""
    _user32.SetProcessDpiAwarenessContext(wintypes.HANDLE(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))


def _tamano_cliente(id_ventana: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    if not _user32.IsWindow(id_ventana) or not _user32.GetClientRect(id_ventana, ctypes.byref(rect)):
        raise VentanaNoEncontradaError(
            _("La ventana {id_ventana:#x} ya no existe").format(id_ventana=id_ventana)
        )
    if _user32.IsIconic(id_ventana) or rect.right <= 0 or rect.bottom <= 0:
        raise VentanaMinimizadaError(
            _("La ventana {id_ventana:#x} está minimizada").format(id_ventana=id_ventana)
        )
    return rect.right, rect.bottom


class GestorVentanasWin32:
    """Consulta las ventanas de nivel superior visibles del escritorio."""

    def __init__(self) -> None:
        _consciente_del_dpi()

    def listar(self) -> list[Ventana]:
        """Ventanas visibles con título, de la de delante a la de atrás. Sin las minimizadas."""
        ids: list[int] = []

        def apuntar(hwnd: int | None, _: int) -> bool:
            if hwnd:
                ids.append(hwnd)
            return True

        _user32.EnumWindows(_EnumProc(apuntar), 0)
        ventanas = []
        for id_ventana in ids:
            if not _user32.IsWindowVisible(id_ventana) or _oculta_por_dwm(id_ventana):
                continue
            titulo = _titulo(id_ventana)
            if not titulo:
                continue
            try:
                geometria = self.geometria(id_ventana)
            except (VentanaNoEncontradaError, VentanaMinimizadaError):
                continue
            ventanas.append(Ventana(id_ventana, titulo, _pid(id_ventana), geometria))
        return ventanas

    def buscar(self, texto: str, excluir_pids: frozenset[int] | None = None) -> Ventana:
        """Primera ventana cuyo título contiene `texto`; sin contar las de esta app ni su terminal."""
        excluidos = pids_propios() if excluir_pids is None else excluir_pids
        return buscar_por_titulo(self.listar(), texto, excluidos)

    def geometria(self, id_ventana: int) -> Rectangulo:
        """Posición en pantalla y tamaño del área cliente."""
        ancho, alto = _tamano_cliente(id_ventana)
        origen = wintypes.POINT(0, 0)
        if not _user32.ClientToScreen(id_ventana, ctypes.byref(origen)):
            raise VentanaNoEncontradaError(
                _("La ventana {id_ventana:#x} ya no existe").format(id_ventana=id_ventana)
            )
        return Rectangulo(x=origen.x, y=origen.y, ancho=ancho, alto=alto)

    def activa(self) -> int | None:
        """Ventana que está en primer plano, o None si no hay ninguna."""
        return _activa()


def _activa() -> int | None:
    return _user32.GetForegroundWindow() or None


def _titulo(id_ventana: int) -> str:
    largo = _user32.GetWindowTextLengthW(id_ventana)
    if largo <= 0:
        return ""
    texto = ctypes.create_unicode_buffer(largo + 1)
    _user32.GetWindowTextW(id_ventana, texto, largo + 1)
    return texto.value


def _pid(id_ventana: int) -> int | None:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(id_ventana, ctypes.byref(pid))
    return int(pid.value) or None


def _oculta_por_dwm(id_ventana: int) -> bool:
    """Ventanas «encubiertas»: se dicen visibles pero no se ven (apps de la tienda, otros escritorios)."""
    encubierta = wintypes.DWORD()
    resultado = _dwmapi.DwmGetWindowAttribute(
        id_ventana, DWMWA_CLOAKED, ctypes.byref(encubierta), ctypes.sizeof(encubierta)
    )
    return resultado == 0 and encubierta.value != 0


class CapturadorVentanaWin32:
    """Captura el contenido de la propia ventana con `PrintWindow`, aunque tenga otras encima.

    Si Windows no puede dar el contenido (falla, o sale todo negro, como con algunos juegos de
    DirectX a pantalla completa), usa el capturador alternativo, que captura lo que se ve.
    """

    def __init__(self, alternativo: Capturador | None = None) -> None:
        _consciente_del_dpi()
        self._alternativo = alternativo

    def capturar(self, id_ventana: int, zona: Rectangulo) -> Imagen:
        """Captura la zona (en píxeles relativos al área cliente) en RGB."""
        ancho_cliente, alto_cliente = _tamano_cliente(id_ventana)
        # Basta con pintar hasta la esquina inferior derecha de la zona.
        ancho = min(zona.x + zona.ancho, ancho_cliente)
        alto = min(zona.y + zona.alto, alto_cliente)
        bgra = _imprimir(id_ventana, ancho, alto)
        recorte = None if bgra is None else bgra[zona.y :, zona.x :, :3]
        if recorte is None or recorte.size == 0 or not recorte.any():
            if self._alternativo is None:
                raise VentanaNoEncontradaError(
                    _("Windows no da el contenido de la ventana {id_ventana:#x}").format(
                        id_ventana=id_ventana
                    )
                )
            return self._alternativo.capturar(id_ventana, zona)
        rgb: Imagen = np.ascontiguousarray(recorte[:, :, ::-1])
        return rgb


def _imprimir(id_ventana: int, ancho: int, alto: int) -> Imagen | None:
    """Las `alto` primeras filas y `ancho` primeras columnas del área cliente en BGRA, o None."""
    if ancho <= 0 or alto <= 0:
        return None
    pantalla = _user32.GetDC(None)
    memoria = _gdi32.CreateCompatibleDC(pantalla)
    mapa = _gdi32.CreateCompatibleBitmap(pantalla, ancho, alto)
    anterior = _gdi32.SelectObject(memoria, mapa)
    try:
        if not _user32.PrintWindow(id_ventana, memoria, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return None
        _gdi32.SelectObject(memoria, anterior)
        info = _InfoMapa()
        encabezado = info.bmiHeader
        encabezado.biSize = ctypes.sizeof(_Encabezado)
        encabezado.biWidth, encabezado.biHeight = ancho, -alto  # alto negativo: de arriba abajo
        encabezado.biPlanes, encabezado.biBitCount, encabezado.biCompression = 1, 32, BI_RGB
        datos = np.empty((alto, ancho, 4), dtype=np.uint8)
        filas = _gdi32.GetDIBits(
            memoria, mapa, 0, alto, datos.ctypes.data_as(wintypes.LPVOID), ctypes.byref(info), DIB_RGB_COLORS
        )
        return datos if filas == alto else None
    finally:
        _gdi32.SelectObject(memoria, anterior)
        _gdi32.DeleteObject(mapa)
        _gdi32.DeleteDC(memoria)
        _user32.ReleaseDC(None, pantalla)
