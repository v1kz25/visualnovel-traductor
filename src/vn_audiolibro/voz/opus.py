"""Audio de la caché en Opus: ocupa unas diez veces menos que el PCM y se decodifica al vuelo."""

import io
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

from vn_audiolibro.textos import _
from vn_audiolibro.voz.modelos import Fragmento, Muestras, VozFallidaError

FRECUENCIA_OPUS = 24000
"""Opus solo admite 8, 12, 16, 24 y 48 kHz; Piper genera a 22,05 kHz y se sube a 24."""


def remuestrear(pcm: Muestras, origen: int, destino: int) -> Muestras:
    """Cambia la frecuencia por interpolación lineal: basta para voz y para saltos pequeños."""
    if origen == destino or len(pcm) == 0:
        return pcm
    cantidad = round(len(pcm) * destino / origen)
    instantes = np.arange(cantidad) * (origen / destino)
    muestras = np.interp(instantes, np.arange(len(pcm)), pcm.astype(np.float32))
    remuestreado: Muestras = np.clip(np.round(muestras), -32768, 32767).astype(np.int16)
    return remuestreado


def codificar(fragmentos: Sequence[Fragmento]) -> bytes:
    """Une los fragmentos en un único fichero Ogg Opus."""
    if not fragmentos:
        raise ValueError("No hay audio que codificar")
    pcm = np.concatenate([remuestrear(f.pcm, f.frecuencia, FRECUENCIA_OPUS) for f in fragmentos])
    salida = io.BytesIO()
    sf.write(salida, pcm, FRECUENCIA_OPUS, format="OGG", subtype="OPUS")
    return salida.getvalue()


def decodificar(ruta: Path) -> Fragmento:
    """Audio de un fichero Opus como un solo fragmento."""
    try:
        datos, frecuencia = sf.read(ruta, dtype="int16", always_2d=True)
    except sf.SoundFileError as error:
        raise VozFallidaError(
            _("Audio ilegible en {fichero}: {error}").format(fichero=ruta.name, error=error)
        ) from error
    pcm: Muestras = np.ascontiguousarray(datos[:, 0])
    return Fragmento(pcm, int(frecuencia))
