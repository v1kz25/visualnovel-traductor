"""Tipos de la voz: el audio sintetizado y las interfaces del sintetizador y del reproductor."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import numpy as np
import numpy.typing as npt

Muestras = npt.NDArray[np.int16]
"""Audio PCM mono de 16 bits."""


@dataclass(frozen=True)
class Fragmento:
    """Trozo de audio mono: normalmente una frase."""

    pcm: Muestras
    frecuencia: int
    """Muestras por segundo."""

    @property
    def duracion_s(self) -> float:
        """Duración en segundos."""
        return len(self.pcm) / self.frecuencia


class Sintetizador(Protocol):
    """Convierte texto en español en voz. Cada motor (Piper, otros) lo implementa."""

    def sintetizar(self, texto: str) -> Iterator[Fragmento]:
        """Audio del texto, frase a frase: la primera puede sonar antes de sintetizar el resto."""
        ...


class Salida(Protocol):
    """Audio que está sonando. `escribir` y `terminar` se llaman desde un hilo y `detener` desde otro."""

    def escribir(self, pcm: Muestras) -> None:
        """Añade audio a lo que suena. Si ya se ha detenido, no hace nada."""
        ...

    def terminar(self) -> None:
        """Espera a que acabe de sonar todo lo escrito, o a que se detenga."""
        ...

    def detener(self) -> None:
        """Corta el audio en el acto."""
        ...


class Reproductor(Protocol):
    """Abre salidas de audio en el sistema de sonido."""

    def abrir(self, frecuencia: int) -> Salida:
        """Salida nueva para audio mono de 16 bits a esa frecuencia."""
        ...


class Atenuador(Protocol):
    """Baja el volumen del juego mientras habla la voz."""

    def bajar(self) -> None:
        """Baja el juego. Llamarlo con el juego ya bajado no hace nada."""
        ...

    def restaurar(self) -> None:
        """Devuelve el juego a su volumen original."""
        ...


class ModoLectura(StrEnum):
    """Qué hacer con las líneas que llegan mientras suena otra."""

    COLA = "cola"
    """Leerlas todas en orden, con un máximo en espera."""
    ULTIMA = "ultima"
    """Cortar lo que suena y leer solo la última."""


PAUSA_ENTRE_LINEAS_S = 2.0
"""Silencio entre una línea y la siguiente en modo cola, para que se distingan."""

MAX_EN_ESPERA = 3
"""Líneas que pueden esperar su turno en modo cola; si llegan más, se descartan las más antiguas."""


class VozFallidaError(Exception):
    """No se ha podido sintetizar o reproducir el audio."""
