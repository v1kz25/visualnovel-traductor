"""Atajos globales en X11: `XGrabKey` en la ventana raíz, con su propia conexión al servidor.

Un atajo que ya ha cogido otra aplicación da `BadAccess`: se avisa y se sigue con los demás.
"""

import logging
import select
import threading
from collections.abc import Callable, Mapping

from Xlib import XK, X, display, error

from vn_audiolibro.atajos.modelos import Accion, Atajo, Modificador

_registro = logging.getLogger(__name__)

MASCARAS = {
    Modificador.CTRL: X.ControlMask,
    Modificador.ALT: X.Mod1Mask,
    Modificador.SHIFT: X.ShiftMask,
    Modificador.SUPER: X.Mod4Mask,
}
BLOQUEOS = (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask)
"""Bloq Mayús y Bloq Num cambian el estado de la tecla: el atajo se coge con todas sus variantes."""
MODIFICADORES = X.ControlMask | X.Mod1Mask | X.ShiftMask | X.Mod4Mask
ESPERA_S = 0.2
"""Cada cuánto mira el hilo si tiene que parar."""


def mascara(atajo: Atajo) -> int:
    resultado = 0
    for modificador in atajo.modificadores:
        resultado |= MASCARAS[modificador]
    return resultado


class EscuchaAtajosX11:
    """Escucha los atajos en un hilo con una conexión X propia (python-xlib no es seguro entre hilos)."""

    def __init__(self, abrir: Callable[[], display.Display] = display.Display) -> None:
        self._abrir = abrir
        self._pantalla: display.Display | None = None
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self._registrados: dict[tuple[int, int], Accion] = {}

    def iniciar(self, atajos: Mapping[Accion, Atajo], al_pulsar: Callable[[Accion], None]) -> list[Accion]:
        self.detener()
        pantalla = self._abrir()
        self._pantalla = pantalla
        fallidos = [accion for accion, atajo in atajos.items() if not self._coger(pantalla, accion, atajo)]
        self._parar.clear()
        self._hilo = threading.Thread(
            target=self._escuchar, args=(pantalla, al_pulsar), name="atajos-x11", daemon=True
        )
        self._hilo.start()
        return fallidos

    def _coger(self, pantalla: display.Display, accion: Accion, atajo: Atajo) -> bool:
        codigo = pantalla.keysym_to_keycode(XK.string_to_keysym(atajo.tecla))
        if not codigo:
            _registro.warning("La tecla %s no está en este teclado", atajo.tecla)
            return False
        raiz = pantalla.screen().root
        estado = mascara(atajo)
        fallo = error.CatchError(error.BadAccess)
        for bloqueo in BLOQUEOS:
            raiz.grab_key(codigo, estado | bloqueo, True, X.GrabModeAsync, X.GrabModeAsync, onerror=fallo)
        pantalla.sync()
        if fallo.get_error() is not None:
            _registro.warning("El atajo %s ya lo usa otra aplicación", atajo)
            for bloqueo in BLOQUEOS:
                raiz.ungrab_key(codigo, estado | bloqueo)
            pantalla.sync()
            return False
        self._registrados[(codigo, estado)] = accion
        return True

    def _escuchar(self, pantalla: display.Display, al_pulsar: Callable[[Accion], None]) -> None:
        while not self._parar.is_set():
            select.select([pantalla.fileno()], [], [], ESPERA_S)
            while pantalla.pending_events():
                evento = pantalla.next_event()
                if evento.type != X.KeyPress:
                    continue
                accion = self._registrados.get((evento.detail, evento.state & MODIFICADORES))
                if accion is not None:
                    try:
                        al_pulsar(accion)
                    except Exception:
                        _registro.exception("Fallo al atender el atajo de %s", accion)

    def detener(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join()
            self._hilo = None
        if self._pantalla is not None:
            raiz = self._pantalla.screen().root
            for codigo, estado in self._registrados:
                for bloqueo in BLOQUEOS:
                    raiz.ungrab_key(codigo, estado | bloqueo)
            self._pantalla.close()
            self._pantalla = None
        self._registrados = {}
