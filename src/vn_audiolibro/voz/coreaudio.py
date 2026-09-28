"""Volumen de cada aplicación en Windows, con las sesiones de audio de Core Audio (`pycaw`).

Windows agrupa el audio de cada proceso en una sesión con su propio volumen: es lo que se ve en el
mezclador de volumen. Cada sesión se presenta al atenuador como un `Flujo`, con el PID de su
proceso y el nombre del ejecutable, igual que los flujos de PulseAudio en Linux.

Las sesiones son del dispositivo de salida por defecto. Todas las llamadas a COM se hacen desde
un mismo hilo, que es el que inicializa COM, y ningún objeto COM sale de él ni se guarda entre
llamadas: si se liberase desde otro hilo (el recolector de basura puede hacerlo en cualquiera),
Windows cerraría la app con un «access violation».
"""

import gc
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from vn_audiolibro.procesos import Proceso, listar_procesos
from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.reproductor import NOMBRE_CLIENTE
from vn_audiolibro.voz.volumen import Flujo, Volumen

_registro = logging.getLogger(__name__)


class Sesion(Protocol):
    """Sesión de audio de una aplicación."""

    @property
    def identificador(self) -> str:
        """Distingue la sesión de las demás mientras exista."""
        ...

    @property
    def pid(self) -> int:
        """0 en la de los sonidos del sistema."""
        ...

    @property
    def nombre(self) -> str:
        """El que la aplicación da a la sesión; casi siempre vacío."""
        ...

    def volumen(self) -> float:
        """Amplitud de 0 a 1."""
        ...

    def poner_volumen(self, volumen: float) -> None:
        """Si la sesión ya no existe, no hace nada."""
        ...


def a_escala_pulse(amplitud: float) -> float:
    """Windows da el volumen de la sesión como amplitud; PulseAudio, en escala cúbica.

    El atenuador trabaja en la de PulseAudio para que un mismo nivel baje lo mismo en los dos
    sistemas: 0,7 son unos -9 dB.
    """
    return float(max(0.0, amplitud) ** (1 / 3))


def a_amplitud(volumen: Volumen) -> float:
    """Volumen en escala de PulseAudio, a amplitud de Windows (una sola para todos los canales)."""
    return min(1.0, max(volumen, default=0.0) ** 3)


class ClienteCoreAudio:
    """Cliente de las sesiones de audio de Windows, con la interfaz de `ClienteAudio`."""

    def __init__(
        self,
        listar_sesiones: Callable[[], list[Sesion]] | None = None,
        procesos: Callable[[], dict[int, Proceso]] = listar_procesos,
        iniciar_hilo: Callable[[], None] | None = None,
    ) -> None:
        self._listar_sesiones = listar_sesiones or _sesiones_pycaw
        self._procesos = procesos
        self._hilo_com = ThreadPoolExecutor(1, "coreaudio", iniciar_hilo or _iniciar_com)
        self._indices: dict[str, int] = {}
        """Número de cada sesión por su identificador, estable mientras exista."""
        try:
            self.flujos()
        except Exception as error:
            self._hilo_com.shutdown()
            raise VozFallidaError(f"No se pudo acceder al audio de Windows: {error}") from None

    def flujos(self) -> list[Flujo]:
        return self._en_hilo(self._flujos)

    def poner_volumen(self, indice: int, volumen: Volumen) -> None:
        self._en_hilo(lambda: self._poner_volumen(indice, volumen))

    def cerrar(self) -> None:
        self._hilo_com.shutdown()

    def _en_hilo[T](self, funcion: Callable[[], T]) -> T:
        return self._hilo_com.submit(_aislar, funcion).result()

    def _flujos(self) -> list[Flujo]:
        nombres = {pid: proceso.nombre for pid, proceso in self._procesos().items()}
        flujos = []
        for sesion in self._listar_sesiones():
            indice = self._indices.setdefault(sesion.identificador, len(self._indices))
            ejecutable = nombres.get(sesion.pid, "") if sesion.pid else ""
            # La voz de la app suena en su propio proceso: se marca como suya para no bajarla.
            aplicacion = NOMBRE_CLIENTE if sesion.pid == os.getpid() else sesion.nombre or ejecutable
            flujos.append(
                Flujo(
                    indice=indice,
                    aplicacion=aplicacion,
                    binario=ejecutable,
                    pid=sesion.pid or None,
                    volumen=(a_escala_pulse(sesion.volumen()),),
                )
            )
        return flujos

    def _poner_volumen(self, indice: int, volumen: Volumen) -> None:
        for sesion in self._listar_sesiones():
            if self._indices.get(sesion.identificador) == indice:
                sesion.poner_volumen(a_amplitud(volumen))
                return
        _registro.debug("La sesión %d ya no existe", indice)


def _aislar[T](funcion: Callable[[], T]) -> T:
    """Ejecuta en el hilo COM sin dejar salir objetos COM en una excepción.

    El traceback de un error guarda las variables de cada llamada, entre ellas objetos COM: se
    convierte en un `VozFallidaError` con solo el mensaje y se libera todo aquí mismo.
    """
    try:
        return funcion()
    except Exception as error:
        mensaje = f"{type(error).__name__}: {error}"
    gc.collect()
    raise VozFallidaError(mensaje)


def _iniciar_com() -> None:
    import comtypes

    comtypes.CoInitialize()


class _SesionPycaw:
    """Sesión de `pycaw` con la interfaz de `Sesion`."""

    def __init__(self, sesion: Any) -> None:
        self._sesion = sesion
        self._identificador = str(sesion.InstanceIdentifier)

    @property
    def identificador(self) -> str:
        return self._identificador

    @property
    def pid(self) -> int:
        return int(self._sesion.ProcessId)

    @property
    def nombre(self) -> str:
        nombre = str(self._sesion.DisplayName or "")
        # Las de Windows traen una referencia a un recurso («@%SystemRoot%\…»), no un nombre.
        return "" if nombre.startswith("@") else nombre

    def volumen(self) -> float:
        return float(self._sesion.SimpleAudioVolume.GetMasterVolume())

    def poner_volumen(self, volumen: float) -> None:
        import comtypes

        try:
            self._sesion.SimpleAudioVolume.SetMasterVolume(volumen, None)
        except (comtypes.COMError, OSError):
            _registro.debug("La sesión %s ya no existe", self._identificador)


def _sesiones_pycaw() -> list[Sesion]:
    from pycaw.pycaw import AudioUtilities

    return [_SesionPycaw(sesion) for sesion in AudioUtilities.GetAllSessions()]
