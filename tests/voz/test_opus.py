"""Tests de la conversión del audio a Opus y de vuelta."""

from pathlib import Path

import numpy as np
import pytest

from vn_audiolibro.voz import opus
from vn_audiolibro.voz.modelos import Fragmento, VozFallidaError


def tono(segundos: float, frecuencia: int = 22050, hz: float = 440) -> Fragmento:
    t = np.arange(round(segundos * frecuencia)) / frecuencia
    return Fragmento((np.sin(2 * np.pi * hz * t) * 10000).astype(np.int16), frecuencia)


def test_remuestrear_conserva_la_duracion() -> None:
    fragmento = tono(1.0)
    subido = opus.remuestrear(fragmento.pcm, 22050, 24000)
    assert len(subido) == 24000
    assert subido.dtype == np.int16


def test_remuestrear_a_la_misma_frecuencia_no_cambia_nada() -> None:
    fragmento = tono(0.1)
    assert opus.remuestrear(fragmento.pcm, 22050, 22050) is fragmento.pcm


def test_remuestrear_audio_vacio() -> None:
    vacio = np.zeros(0, dtype=np.int16)
    assert len(opus.remuestrear(vacio, 22050, 24000)) == 0


def test_ida_y_vuelta_une_los_fragmentos(tmp_path: Path) -> None:
    ruta = tmp_path / "linea.opus"
    ruta.write_bytes(opus.codificar([tono(0.5), tono(0.25, hz=880)]))

    leido = opus.decodificar(ruta)

    assert leido.frecuencia == opus.FRECUENCIA_OPUS
    assert leido.duracion_s == pytest.approx(0.75, abs=0.02)
    energia = float(np.sqrt(np.mean(leido.pcm.astype(np.float64) ** 2)))
    assert energia == pytest.approx(10000 / np.sqrt(2), rel=0.1)


def test_opus_ocupa_mucho_menos_que_el_pcm() -> None:
    fragmento = tono(2.0)
    assert len(opus.codificar([fragmento])) < fragmento.pcm.nbytes / 5


def test_sin_fragmentos_no_hay_nada_que_codificar() -> None:
    with pytest.raises(ValueError, match="No hay audio"):
        opus.codificar([])


def test_fichero_ilegible(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.opus"
    ruta.write_bytes(b"no es audio")
    with pytest.raises(VozFallidaError, match=r"roto\.opus"):
        opus.decodificar(ruta)
