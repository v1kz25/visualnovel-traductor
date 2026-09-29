"""Puente entre la sesión de juego, que trabaja en otros hilos, y la interfaz, que vive en el de Qt.

Arrancar la sesión tarda (buscar la ventana, preparar modelos, arrancar el traductor) y los
avisos de cada línea llegan desde el hilo del orquestador. Todo se reenvía como señales de Qt,
que se entregan en el hilo de la interfaz.
"""

import logging
import threading
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego
from vn_audiolibro.pipeline.sesion import Sesion
from vn_audiolibro.textos import _

_registro = logging.getLogger(__name__)


class Control(Protocol):
    """Lo que la interfaz controla de una partida en marcha (el `Orquestador`)."""

    @property
    def pausado(self) -> bool: ...

    def pausar(self) -> None: ...

    def reanudar(self) -> None: ...

    def repetir(self) -> None: ...

    def saltar(self) -> None: ...


class SesionJuego(Protocol):
    """Lo que el puente necesita de una sesión (`Sesion`)."""

    def iniciar(self) -> Control: ...

    def detener(self) -> None: ...


FabricaSesion = Callable[
    [Perfil, Callable[[LineaJuego], None], Callable[[str], None], Callable[[str], None]], SesionJuego
]


def _sesion_real(
    perfil: Perfil,
    al_linea: Callable[[LineaJuego], None],
    al_error: Callable[[str], None],
    al_estado: Callable[[str], None],
) -> SesionJuego:
    return Sesion(perfil, al_linea, al_error, al_estado)


class PuenteSesion(QObject):
    """Arranca, controla y para una partida sin bloquear la interfaz."""

    estado = Signal(str)
    linea = Signal(object)
    error = Signal(str)
    iniciada = Signal()
    terminada = Signal()

    def __init__(self, fabrica: FabricaSesion = _sesion_real, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fabrica = fabrica
        self._sesion: SesionJuego | None = None
        self._control: Control | None = None
        self._arrancando = False
        self._cerrojo = threading.Lock()
        self._hilo: threading.Thread | None = None

    @property
    def jugando(self) -> bool:
        return self._sesion is not None

    @property
    def pausado(self) -> bool:
        return self._control is not None and self._control.pausado

    def iniciar(self, perfil: Perfil) -> None:
        """Arranca la partida en segundo plano. Avisa con `iniciada`, o con `error` y `terminada`."""
        if self._sesion is not None:
            return
        self.esperar()  # por si aún se está parando la anterior
        sesion = self._fabrica(perfil, self.linea.emit, self.error.emit, self.estado.emit)
        with self._cerrojo:
            self._sesion, self._arrancando = sesion, True
        self._lanzar(lambda: self._arrancar(sesion))

    def detener(self) -> None:
        """Para la partida en segundo plano y avisa con `terminada`.

        Si aún está arrancando, no espera: la para el propio arranque al terminar.
        """
        with self._cerrojo:
            sesion, self._sesion, self._control = self._sesion, None, None
            arrancando = self._arrancando
        if sesion is not None and not arrancando:
            self._lanzar(lambda: self._parar(sesion))

    def esperar(self, timeout_s: float | None = None) -> None:
        """Espera a que termine el arranque o la parada en curso (al cerrar la app)."""
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def alternar_pausa(self) -> None:
        if self._control is not None:
            if self._control.pausado:
                self._control.reanudar()
            else:
                self._control.pausar()

    def repetir(self) -> None:
        if self._control is not None:
            self._control.repetir()

    def saltar(self) -> None:
        if self._control is not None:
            self._control.saltar()

    def _lanzar(self, trabajo: Callable[[], None]) -> None:
        self._hilo = threading.Thread(target=trabajo, name="sesion", daemon=True)
        self._hilo.start()

    def _arrancar(self, sesion: SesionJuego) -> None:
        try:
            control = sesion.iniciar()
        except Exception as error:
            _registro.exception("No se pudo empezar a jugar")
            with self._cerrojo:
                self._arrancando = False
                if self._sesion is sesion:
                    self._sesion = None
            self.error.emit(str(error))
            self.terminada.emit()
            return
        with self._cerrojo:
            self._arrancando = False
            cancelada = self._sesion is not sesion
            if not cancelada:
                self._control = control
        if cancelada:
            self._parar(sesion)  # se pidió detener mientras arrancaba
        else:
            self.iniciada.emit()

    def _parar(self, sesion: SesionJuego) -> None:
        try:
            sesion.detener()
        except Exception as error:
            _registro.exception("Error al parar la partida")
            self.error.emit(_("Error al parar: {error}").format(error=error))
        self.terminada.emit()
