"""Prueba con la voz real de Piper.

En local se salta si la voz no se puede descargar; en la CI es obligatoria (se guarda en caché).
"""

import json
import shutil
import time
from pathlib import Path

import pytest

from tests.ocr.sinteticas import falta
from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.piper import (
    JOHN_MEDIUM,
    KRISTIN_MEDIUM,
    SHARVARD_MEDIUM,
    Hablante,
    SintetizadorPiper,
    VozElegida,
    VozPiper,
    asegurar_voz,
    elegir_voz,
)

PRIMERA_FRASE_MAX_S = 0.5


@pytest.fixture(scope="module")
def modelo() -> Path:
    try:
        return asegurar_voz()
    except DescargaFallidaError as error:
        falta(f"voz de Piper no disponible: {error}")


@pytest.fixture(scope="module")
def sintetizador(modelo: Path) -> SintetizadorPiper:
    return SintetizadorPiper(modelo)


def test_una_frase_por_fragmento(sintetizador: SintetizadorPiper) -> None:
    fragmentos = list(sintetizador.sintetizar("Hoy hace mucho frío. ¿Volvemos juntos a casa?"))

    assert len(fragmentos) == 2
    assert all(f.frecuencia == 22050 for f in fragmentos)
    assert all(0.5 < f.duracion_s < 5 for f in fragmentos)


def test_primera_frase_en_menos_de_medio_segundo(sintetizador: SintetizadorPiper) -> None:
    list(sintetizador.sintetizar("Calentamiento."))
    texto = "Ella no respondió. Se limitó a mirar las llamas que devoraban la ciudad, sin decir nada."

    inicio = time.perf_counter()
    next(iter(sintetizador.sintetizar(texto)))

    assert time.perf_counter() - inicio < PRIMERA_FRASE_MAX_S


def test_mujer_y_hombre_suenan_distinto(modelo: Path, sintetizador: SintetizadorPiper) -> None:
    hombre = SintetizadorPiper(modelo, Hablante.HOMBRE)
    texto = "Buenos días."

    (de_mujer,) = sintetizador.sintetizar(texto)
    (de_hombre,) = hombre.sintetizar(texto)

    assert len(de_mujer.pcm) != len(de_hombre.pcm) or bool((de_mujer.pcm != de_hombre.pcm).any())


def test_con_hablante_reutiliza_el_modelo_con_otra_voz(modelo: Path, sintetizador: SintetizadorPiper) -> None:
    rapido = SintetizadorPiper(modelo, velocidad=1.5)
    hombre = rapido.con_hablante(Hablante.HOMBRE)
    texto = "Buenos días."

    (de_hombre,) = hombre.sintetizar(texto)
    (de_hombre_aparte,) = SintetizadorPiper(modelo, Hablante.HOMBRE, velocidad=1.5).sintetizar(texto)
    (de_mujer,) = rapido.sintetizar(texto)  # el original no cambia

    assert hombre._voz is rapido._voz  # sin cargar el modelo otra vez
    assert de_hombre.duracion_s == pytest.approx(de_hombre_aparte.duracion_s, rel=0.15)  # misma velocidad
    assert len(de_mujer.pcm) != len(de_hombre.pcm) or bool((de_mujer.pcm != de_hombre.pcm).any())


def test_hablante_que_la_voz_no_tiene(tmp_path: Path, modelo: Path) -> None:
    # Configuración sin hablantes, como la de las voces de un solo hablante.
    unico = tmp_path / "unico.onnx"
    try:
        unico.symlink_to(modelo)
    except OSError:  # Windows sin permiso para enlaces simbólicos
        shutil.copyfile(modelo, unico)
    config = json.loads(modelo.with_name(modelo.name + ".json").read_text(encoding="utf-8"))
    config["num_speakers"], config["speaker_id_map"] = 1, {}
    (tmp_path / "unico.onnx.json").write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(VozFallidaError, match="hablante hombre"):
        SintetizadorPiper(unico, Hablante.HOMBRE)


def test_la_velocidad_acorta_el_audio(modelo: Path, sintetizador: SintetizadorPiper) -> None:
    texto = "Hoy hace mucho frío en la ciudad."
    (normal,) = sintetizador.sintetizar(texto)
    (rapido,) = SintetizadorPiper(modelo, velocidad=1.5).sintetizar(texto)
    # No llega a 1,5 veces más corto: los silencios del principio y del final no se aceleran, y
    # Piper varía un poco la duración de cada fonema en cada síntesis.
    assert rapido.duracion_s < normal.duracion_s / 1.2


def test_velocidad_no_valida(modelo: Path) -> None:
    with pytest.raises(VozFallidaError, match="Velocidad"):
        SintetizadorPiper(modelo, velocidad=0)


@pytest.mark.parametrize("voz", [KRISTIN_MEDIUM, JOHN_MEDIUM], ids=["kristin", "john"])
def test_voces_inglesas(voz: VozPiper) -> None:
    try:
        modelo = asegurar_voz(voz)
    except DescargaFallidaError as error:
        falta(f"voz inglesa de Piper no disponible: {error}")
    fragmentos = list(SintetizadorPiper(modelo, None).sintetizar("Shall we go home together? It's raining."))
    assert len(fragmentos) == 2
    assert all(f.frecuencia == 22050 and f.duracion_s > 0.3 for f in fragmentos)


def test_elegir_voz() -> None:
    assert elegir_voz("es", Hablante.HOMBRE) == VozElegida(SHARVARD_MEDIUM, Hablante.HOMBRE)
    assert elegir_voz("es") == VozElegida(SHARVARD_MEDIUM, Hablante.MUJER)
    assert elegir_voz("en", Hablante.MUJER) == VozElegida(KRISTIN_MEDIUM, None)
    assert elegir_voz("en", Hablante.HOMBRE) == VozElegida(JOHN_MEDIUM, None)
