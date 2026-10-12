"""Reproducción con PortAudio (`sounddevice`), la que se usa en Windows.

Cada línea abre su propio flujo de salida en modo bloqueante: escribir espera a que haya sitio en
el búfer, lo que marca el ritmo igual que la tubería de `paplay`. El audio se escribe en trozos
cortos para que `detener`, desde otro hilo, lo corte sin esperar a que acabe lo ya escrito.
"""

import threading
from collections.abc import Callable
from typing import Protocol

from vn_audiolibro.textos import _
from vn_audiolibro.voz.modelos import Muestras, VozFallidaError

TROZO_S = 0.05
"""Audio que se escribe de una vez: lo que puede seguir sonando como mucho tras `detener`."""


class Flujo(Protocol):
    """Lo que se usa de `sounddevice.RawOutputStream`."""

    def start(self) -> None: ...

    def write(self, datos: bytes) -> object: ...

    def stop(self) -> None:
        """Espera a que suene lo que queda en el búfer y para."""
        ...

    def abort(self) -> None:
        """Para en el acto, descartando lo que queda en el búfer."""
        ...

    def close(self) -> None: ...


AbrirFlujo = Callable[[int], Flujo]
"""Flujo de salida para PCM mono de 16 bits a esa frecuencia."""


def flujo_sounddevice(frecuencia: int) -> Flujo:
    """Flujo de salida en el dispositivo por defecto del sistema."""
    import sounddevice

    flujo: Flujo = sounddevice.RawOutputStream(samplerate=frecuencia, channels=1, dtype="int16")
    return flujo


class SalidaPortAudio:
    """Audio que suena en un flujo de PortAudio."""

    def __init__(self, flujo: Flujo, frecuencia: int) -> None:
        self._flujo = flujo
        self._muestras_por_trozo = max(1, int(frecuencia * TROZO_S))
        # PortAudio no admite usar el mismo flujo desde dos hilos a la vez.
        self._cerrojo = threading.Lock()
        self._detenida = threading.Event()
        self._cerrada = False

    def escribir(self, pcm: Muestras) -> None:
        datos = pcm.astype("<i2")
        for inicio in range(0, len(datos), self._muestras_por_trozo):
            if self._detenida.is_set():
                return
            with self._cerrojo:
                if self._cerrada:
                    return
                self._flujo.write(datos[inicio : inicio + self._muestras_por_trozo].tobytes())

    def terminar(self) -> None:
        self._cerrar(self._flujo.stop)

    def detener(self) -> None:
        self._detenida.set()
        self._cerrar(self._flujo.abort)

    def _cerrar(self, parar: Callable[[], None]) -> None:
        with self._cerrojo:
            if self._cerrada:
                return
            self._cerrada = True
            try:
                parar()
            finally:
                self._flujo.close()


class ReproductorPortAudio:
    """Reproduce cada línea en un flujo nuevo del dispositivo de salida por defecto."""

    def __init__(self, abrir_flujo: AbrirFlujo = flujo_sounddevice) -> None:
        self._abrir_flujo = abrir_flujo

    def abrir(self, frecuencia: int) -> SalidaPortAudio:
        flujo: Flujo | None = None
        try:
            flujo = self._abrir_flujo(frecuencia)
            flujo.start()
        except Exception as error:
            # sounddevice lanza PortAudioError, o OSError si falta la biblioteca de PortAudio.
            if flujo is not None:
                flujo.close()
            raise VozFallidaError(
                _("No se pudo abrir la salida de audio: {error}").format(error=error)
            ) from error
        return SalidaPortAudio(flujo, frecuencia)
