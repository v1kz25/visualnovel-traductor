"""Atajos globales en Windows: `RegisterHotKey` en un hilo con su propia cola de mensajes.

Los atajos se registran y se liberan en el mismo hilo que recibe `WM_HOTKEY`, como exige Win32.
Si otra aplicación ya usa un atajo, `RegisterHotKey` falla: se avisa y se sigue con los demás.
"""

import sys

if sys.platform != "win32":
    raise ImportError("vn_audiolibro.atajos.win32 solo funciona en Windows")

import ctypes
import logging
import threading
from collections.abc import Callable, Mapping
from ctypes import wintypes

from vn_audiolibro.atajos.modelos import TECLAS_FUNCION, Accion, Atajo, Modificador

_registro = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
MODIFICADORES = {
    Modificador.CTRL: MOD_CONTROL,
    Modificador.ALT: MOD_ALT,
    Modificador.SHIFT: MOD_SHIFT,
    Modificador.SUPER: MOD_WIN,
}
VK_F1 = 0x70
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
PM_NOREMOVE = 0
ESPERA_S = 5.0

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32")
_user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_user32.GetMessageW.restype = wintypes.BOOL
_user32.PeekMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
)
_user32.PeekMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.PostThreadMessageW.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def codigo_tecla(tecla: str) -> int:
    """Código de tecla virtual (VK) de una letra, un número o una tecla de función."""
    if tecla in TECLAS_FUNCION:
        return VK_F1 + TECLAS_FUNCION.index(tecla)
    return ord(tecla)  # VK de A-Z y 0-9 es su código ASCII


def modificadores(atajo: Atajo) -> int:
    resultado = MOD_NOREPEAT  # mantener pulsado no repite la acción
    for modificador in atajo.modificadores:
        resultado |= MODIFICADORES[modificador]
    return resultado


class EscuchaAtajosWin32:
    """Registra los atajos y atiende `WM_HOTKEY` en un hilo propio."""

    def __init__(self) -> None:
        self._hilo: threading.Thread | None = None
        self._id_hilo = 0

    def iniciar(self, atajos: Mapping[Accion, Atajo], al_pulsar: Callable[[Accion], None]) -> list[Accion]:
        self.detener()
        listo = threading.Event()
        fallidos: list[Accion] = []
        self._hilo = threading.Thread(
            target=self._escuchar,
            args=(dict(atajos), al_pulsar, listo, fallidos),
            name="atajos-win32",
            daemon=True,
        )
        self._hilo.start()
        listo.wait(ESPERA_S)
        return fallidos

    def _escuchar(
        self,
        atajos: dict[Accion, Atajo],
        al_pulsar: Callable[[Accion], None],
        listo: threading.Event,
        fallidos: list[Accion],
    ) -> None:
        mensaje = wintypes.MSG()
        # Crea la cola de mensajes del hilo antes de que `detener` pueda mandarle WM_QUIT.
        _user32.PeekMessageW(ctypes.byref(mensaje), None, 0, 0, PM_NOREMOVE)
        self._id_hilo = _kernel32.GetCurrentThreadId()
        registrados: dict[int, Accion] = {}
        for numero, (accion, atajo) in enumerate(atajos.items(), 1):
            if _user32.RegisterHotKey(None, numero, modificadores(atajo), codigo_tecla(atajo.tecla)):
                registrados[numero] = accion
            else:
                _registro.warning("El atajo %s ya lo usa otra aplicación", atajo)
                fallidos.append(accion)
        listo.set()
        try:
            while _user32.GetMessageW(ctypes.byref(mensaje), None, 0, 0) > 0:
                accion = registrados.get(mensaje.wParam) if mensaje.message == WM_HOTKEY else None
                if accion is None:
                    continue
                try:
                    al_pulsar(accion)
                except Exception:
                    _registro.exception("Fallo al atender el atajo de %s", accion)
        finally:
            for numero in registrados:
                _user32.UnregisterHotKey(None, numero)

    def detener(self) -> None:
        if self._hilo is None:
            return
        _user32.PostThreadMessageW(self._id_hilo, WM_QUIT, 0, 0)
        self._hilo.join()
        self._hilo = None
