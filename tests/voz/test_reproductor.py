"""Tests del reproductor por proceso, con órdenes del sistema en lugar de `paplay`."""

import sys
import threading
from pathlib import Path

import numpy as np
import pytest

from vn_audiolibro.voz import reproductor
from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.reproductor import ReproductorProceso, comando_paplay

from .falsos import ESPERA_S


def test_escribe_el_pcm_en_la_entrada_del_proceso(tmp_path: Path) -> None:
    destino = tmp_path / "audio.raw"
    copiar = f"import shutil, sys; shutil.copyfileobj(sys.stdin.buffer, open({str(destino)!r}, 'wb'))"
    salida = ReproductorProceso(lambda _: [sys.executable, "-c", copiar]).abrir(22050)

    salida.escribir(np.array([1, -2], dtype=np.int16))
    salida.escribir(np.array([300], dtype=np.int16))
    salida.terminar()

    assert destino.read_bytes() == np.array([1, -2, 300], dtype="<i2").tobytes()


def test_detener_corta_aunque_la_escritura_este_bloqueada() -> None:
    # El proceso no lee: la tubería se llena y `escribir` se queda bloqueado hasta que se detiene.
    salida = ReproductorProceso(lambda _: [sys.executable, "-c", "import time; time.sleep(30)"]).abrir(22050)
    escritor = threading.Thread(target=salida.escribir, args=(np.zeros(1 << 20, dtype=np.int16),))
    escritor.start()

    salida.detener()
    escritor.join(ESPERA_S)

    assert not escritor.is_alive()
    salida.escribir(np.zeros(10, dtype=np.int16))  # tras detener, no hace nada
    salida.terminar()
    salida.detener()


def test_comando_paplay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reproductor.shutil, "which", lambda _: "/usr/bin/paplay")
    orden = comando_paplay(22050)
    assert orden[0] == "/usr/bin/paplay"
    assert "--rate=22050" in orden
    assert "--client-name=vn-audiolibro" in orden


def test_sin_paplay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reproductor.shutil, "which", lambda _: None)
    with pytest.raises(VozFallidaError, match="paplay"):
        comando_paplay(22050)


def test_orden_que_no_existe(tmp_path: Path) -> None:
    with pytest.raises(VozFallidaError, match="salida de audio"):
        ReproductorProceso(lambda _: [str(tmp_path / "no-existe")]).abrir(22050)
