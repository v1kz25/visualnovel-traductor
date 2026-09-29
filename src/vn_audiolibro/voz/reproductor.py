"""Reproducción con `paplay`: vale para PulseAudio y para PipeWire (con pipewire-pulse).

Cada línea abre su propio proceso y recibe el PCM por la entrada estándar. Cortar el audio es
matar el proceso, y el flujo lleva el nombre de la app para identificarlo en el mezclador.
"""

import contextlib
import shutil
import subprocess
from collections.abc import Callable

from vn_audiolibro.textos import _
from vn_audiolibro.voz.modelos import Muestras, VozFallidaError

NOMBRE_CLIENTE = "vn-audiolibro"

Comando = Callable[[int], list[str]]
"""Orden que reproduce PCM mono de 16 bits leído de la entrada estándar, según la frecuencia."""


def comando_paplay(frecuencia: int) -> list[str]:
    """Orden de `paplay` para PCM mono de 16 bits a esa frecuencia."""
    ejecutable = shutil.which("paplay")
    if ejecutable is None:
        raise VozFallidaError(_("No se encuentra `paplay`: instala pulseaudio-utils"))
    return [
        ejecutable,
        "--raw",
        "--format=s16le",
        f"--rate={frecuencia}",
        "--channels=1",
        f"--client-name={NOMBRE_CLIENTE}",
        "--stream-name=Voz",
    ]


class SalidaProceso:
    """Audio que suena en un proceso hijo."""

    def __init__(self, proceso: subprocess.Popen[bytes]) -> None:
        self._proceso = proceso

    def escribir(self, pcm: Muestras) -> None:
        entrada = self._proceso.stdin
        if entrada is None or entrada.closed:
            return
        try:
            # Bloquea mientras la tubería está llena: marca el ritmo sin acumular audio en memoria.
            entrada.write(pcm.astype("<i2").tobytes())
            entrada.flush()
        except (OSError, ValueError):
            # El proceso se ha detenido desde otro hilo (en Windows, la tubería rota da EINVAL).
            pass

    def terminar(self) -> None:
        entrada = self._proceso.stdin
        if entrada is not None:
            with contextlib.suppress(OSError):
                entrada.close()
        self._proceso.wait()

    def detener(self) -> None:
        if self._proceso.poll() is None:
            self._proceso.kill()
        self._proceso.wait()


class ReproductorProceso:
    """Reproduce cada línea en un proceso nuevo; por defecto, `paplay`."""

    def __init__(self, comando: Comando = comando_paplay) -> None:
        self._comando = comando

    def abrir(self, frecuencia: int) -> SalidaProceso:
        orden = self._comando(frecuencia)
        try:
            proceso = subprocess.Popen(  # noqa: S603 - orden fija, sin shell
                orden, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as error:
            raise VozFallidaError(
                _("No se pudo abrir la salida de audio: {error}").format(error=error)
            ) from error
        return SalidaProceso(proceso)
