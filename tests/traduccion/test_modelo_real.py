"""Prueba con el modelo real: Hy-MT2 servido por `llama-server`.

No corre en la CI (el modelo ocupa 1,1 GB). Se ejecuta si el modelo y `llama-server` están en
el directorio de datos o en las rutas de `VN_MODELO_TRADUCCION` y `VN_LLAMA_SERVER`.
"""

import os
import re
import statistics
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from vn_audiolibro.descargas import directorio_modelos
from vn_audiolibro.rutas import directorio_datos
from vn_audiolibro.traduccion.llama import HY_MT2_1_8B_Q4, VERSION_LLAMA, ServidorLlama
from vn_audiolibro.traduccion.local import TraductorLocal
from vn_audiolibro.traduccion.modelos import LineaPrevia, Peticion

TIEMPO_MAX_S = 3.0
CJK = re.compile(r"[぀-ヿ一-鿿]")
ESPANOL = re.compile(r"[¿¡ñáéíóú«»]", re.IGNORECASE)

# Frases escritas para la prueba, al estilo de una VN (no son de ningún juego).
LINEAS = {
    "zh-Hant": ["無邊無垠的永劫之火。", "「你這個混蛋！我要殺了你！」", "沒錯——她，死了。", "「櫻……！！」"],
    "ja": [
        "「……ねえ、まだ起きてる？」",
        "窓の外では、雨が静かに降り続いていた。",
        "「うん」",
        "「先輩、待ってるよ」",
    ],
    "en": [
        '"...Hey, are you still awake?"',
        "Outside the window, the rain kept falling quietly.",
        '"Yeah."',
        "You bastard! I'll never forgive you!",
    ],
}


def _ruta(variable: str, por_defecto: Path) -> Path:
    return Path(os.environ[variable]) if variable in os.environ else por_defecto


@pytest.fixture(scope="module")
def traductor() -> Iterator[TraductorLocal]:
    ejecutable = _ruta(
        "VN_LLAMA_SERVER",
        directorio_datos() / "llama.cpp" / VERSION_LLAMA / f"llama-{VERSION_LLAMA}" / "llama-server",
    )
    modelo = _ruta("VN_MODELO_TRADUCCION", directorio_modelos() / HY_MT2_1_8B_Q4.fichero)
    if not (ejecutable.is_file() and modelo.is_file()):
        pytest.skip("modelo de traducción o llama-server no instalados")
    with ServidorLlama(ejecutable, modelo) as servidor:
        assert servidor.cliente is not None
        yield TraductorLocal(servidor.cliente)


@pytest.mark.parametrize("destino", ["es", "en"])
@pytest.mark.parametrize("idioma", LINEAS)
def test_traduce_en_menos_de_3_s(traductor: TraductorLocal, idioma: str, destino: str) -> None:
    if idioma == destino:
        pytest.skip("un juego en inglés solo se traduce al español")
    previas: list[LineaPrevia] = []
    tiempos = []
    for linea in LINEAS[idioma]:
        inicio = time.perf_counter()
        traduccion = traductor.traducir(Peticion(linea, idioma, tuple(previas), destino=destino))
        tiempos.append(time.perf_counter() - inicio)
        assert traduccion.texto
        assert not CJK.search(traduccion.texto), traduccion.texto
        assert "\n" not in traduccion.texto
        if destino == "en":
            assert not ESPANOL.search(traduccion.texto), traduccion.texto
        if idioma == "en":
            assert traduccion.texto.casefold() != linea.casefold(), traduccion.texto
        previas.append(LineaPrevia(linea, traduccion.texto))

    assert statistics.median(tiempos) < TIEMPO_MAX_S
