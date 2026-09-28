"""Sintetizador y reproductor falsos para probar el locutor sin audio real."""

import threading
import time
from collections.abc import Iterator

import numpy as np

from vn_audiolibro.voz.modelos import Fragmento, Muestras

FRECUENCIA = 22050
ESPERA_S = 5.0
"""Tiempo máximo que un test espera a otro hilo antes de darse por fallido."""


def fragmento(valor: int, muestras: int = 2205) -> Fragmento:
    """Fragmento reconocible: todas sus muestras valen `valor`."""
    return Fragmento(np.full(muestras, valor, dtype=np.int16), FRECUENCIA)


class SintetizadorFalso:
    """Devuelve un fragmento por frase (separadas por `|`), cuyo valor es la longitud de la frase.

    Con `pausa`, espera a que se abra antes de sintetizar la segunda frase. Si el texto es
    `error`, falla.
    """

    def __init__(self, pausa: threading.Event | None = None) -> None:
        self.textos: list[str] = []
        self.frases: list[str] = []
        self._pausa = pausa

    def sintetizar(self, texto: str) -> Iterator[Fragmento]:
        self.textos.append(texto)
        if texto == "error":
            raise RuntimeError("fallo del sintetizador")
        for i, frase in enumerate(texto.split("|")):
            if i == 1 and self._pausa is not None:
                assert self._pausa.wait(ESPERA_S)
            self.frases.append(frase)
            yield fragmento(len(frase))


class SalidaFalsa:
    """Guarda lo escrito. Con `bloquear`, `terminar` no vuelve hasta que se suelta o se detiene."""

    def __init__(self, frecuencia: int, bloquear: bool) -> None:
        self.frecuencia = frecuencia
        self.escrito: list[Muestras] = []
        self.terminada = False
        self.detenida = threading.Event()
        self.sonando = threading.Event()
        self._soltar = threading.Event()
        if not bloquear:
            self._soltar.set()

    def escribir(self, pcm: Muestras) -> None:
        if not self.detenida.is_set():
            self.escrito.append(pcm)

    def terminar(self) -> None:
        self.sonando.set()
        while not (self._soltar.wait(0.01) or self.detenida.is_set()):
            pass
        self.terminada = not self.detenida.is_set()

    def detener(self) -> None:
        self.detenida.set()

    def soltar(self) -> None:
        self._soltar.set()

    @property
    def valores(self) -> list[int]:
        """Valor de cada fragmento escrito."""
        return [int(pcm[0]) for pcm in self.escrito]


class ReproductorFalso:
    """Crea salidas falsas. Con `puerta`, `abrir` espera a que se abra antes de devolver."""

    def __init__(self, bloquear: bool = False, puerta: threading.Event | None = None) -> None:
        self.salidas: list[SalidaFalsa] = []
        self.abriendo = threading.Event()
        self._bloquear = bloquear
        self._puerta = puerta

    def abrir(self, frecuencia: int) -> SalidaFalsa:
        self.abriendo.set()
        if self._puerta is not None:
            assert self._puerta.wait(ESPERA_S)
        salida = SalidaFalsa(frecuencia, self._bloquear)
        self.salidas.append(salida)
        return salida

    def esperar_sonando(self, indice: int) -> SalidaFalsa:
        """Espera a que la salida `indice` haya recibido todo su audio y esté sonando."""
        limite = time.monotonic() + ESPERA_S
        while time.monotonic() < limite:
            if len(self.salidas) > indice and self.salidas[indice].sonando.wait(0.01):
                return self.salidas[indice]
            time.sleep(0.01)
        raise AssertionError(f"La salida {indice} no ha llegado a sonar")


class AtenuadorFalso:
    """Apunta cada llamada; con `fallar`, lanza una excepción en cada una."""

    def __init__(self, fallar: bool = False) -> None:
        self.llamadas: list[str] = []
        self._fallar = fallar

    def bajar(self) -> None:
        self.llamadas.append("bajar")
        if self._fallar:
            raise RuntimeError("sin servidor de sonido")

    def restaurar(self) -> None:
        self.llamadas.append("restaurar")
        if self._fallar:
            raise RuntimeError("sin servidor de sonido")
