"""Tests del reproductor de PortAudio con un flujo falso en lugar de `sounddevice`."""

import sys
import threading

import numpy as np
import pytest

from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.portaudio import ReproductorPortAudio, SalidaPortAudio

from .falsos import ESPERA_S

FRECUENCIA = 100
"""Con trozos de 0,05 s, 5 muestras por escritura."""


class FlujoFalso:
    def __init__(self, fallar_al_empezar: bool = False, bloquear: bool = False) -> None:
        self.fallar_al_empezar = fallar_al_empezar
        self.escrito: list[bytes] = []
        self.llamadas: list[str] = []
        self.escribiendo = threading.Event()
        self.soltar = threading.Event()
        if not bloquear:
            self.soltar.set()

    def start(self) -> None:
        self.llamadas.append("start")
        if self.fallar_al_empezar:
            raise OSError("sin dispositivo de salida")

    def write(self, datos: bytes) -> bool:
        self.escribiendo.set()
        assert self.soltar.wait(ESPERA_S)
        self.escrito.append(datos)
        return False

    def stop(self) -> None:
        self.llamadas.append("stop")

    def abort(self) -> None:
        self.llamadas.append("abort")

    def close(self) -> None:
        self.llamadas.append("close")


def abrir(flujo: FlujoFalso) -> SalidaPortAudio:
    frecuencias: list[int] = []

    def abrir_flujo(frecuencia: int) -> FlujoFalso:
        frecuencias.append(frecuencia)
        return flujo

    salida = ReproductorPortAudio(abrir_flujo).abrir(FRECUENCIA)
    assert frecuencias == [FRECUENCIA]
    return salida


def test_escribe_el_pcm_en_trozos_y_espera_a_que_suene() -> None:
    flujo = FlujoFalso()
    salida = abrir(flujo)

    salida.escribir(np.arange(7, dtype=np.int16))
    salida.escribir(np.array([-1], dtype=np.int16))
    salida.terminar()

    assert [len(trozo) // 2 for trozo in flujo.escrito] == [5, 2, 1]
    assert b"".join(flujo.escrito) == np.array([*range(7), -1], dtype="<i2").tobytes()
    assert flujo.llamadas == ["start", "stop", "close"]


def test_detener_corta_a_mitad_de_la_escritura() -> None:
    flujo = FlujoFalso(bloquear=True)
    salida = abrir(flujo)
    escritor = threading.Thread(target=salida.escribir, args=(np.zeros(1000, dtype=np.int16),))
    escritor.start()
    assert flujo.escribiendo.wait(ESPERA_S)

    detenedor = threading.Thread(target=salida.detener)
    detenedor.start()
    flujo.soltar.set()  # acaba el trozo en curso; los siguientes ya no se escriben
    detenedor.join(ESPERA_S)
    escritor.join(ESPERA_S)

    assert not escritor.is_alive()
    assert len(flujo.escrito) == 1
    assert flujo.llamadas == ["start", "abort", "close"]

    salida.escribir(np.zeros(10, dtype=np.int16))  # tras detener, no hace nada
    salida.terminar()
    salida.detener()
    assert len(flujo.escrito) == 1
    assert flujo.llamadas == ["start", "abort", "close"]


def test_terminar_y_luego_detener_no_vuelve_a_cerrar() -> None:
    flujo = FlujoFalso()
    salida = abrir(flujo)
    salida.terminar()
    salida.detener()
    salida.escribir(np.zeros(10, dtype=np.int16))
    assert flujo.llamadas == ["start", "stop", "close"]
    assert flujo.escrito == []


def test_si_no_se_puede_abrir_cierra_el_flujo_y_avisa() -> None:
    flujo = FlujoFalso(fallar_al_empezar=True)
    with pytest.raises(VozFallidaError, match="salida de audio: sin dispositivo"):
        abrir(flujo)
    assert flujo.llamadas == ["start", "close"]


def test_si_falta_portaudio_avisa() -> None:
    def sin_portaudio(_: int) -> FlujoFalso:
        raise OSError("PortAudio library not found")

    with pytest.raises(VozFallidaError, match="PortAudio"):
        ReproductorPortAudio(sin_portaudio).abrir(FRECUENCIA)


@pytest.mark.skipif(sys.platform != "win32", reason="sounddevice solo se instala en Windows")
def test_sounddevice_esta_disponible_en_windows() -> None:
    import sounddevice

    assert sounddevice.get_portaudio_version()
