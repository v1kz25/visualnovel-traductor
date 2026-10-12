"""Tests de la normalización del texto reconocido."""

import pytest

from vn_audiolibro.ocr.normalizacion import normalizar, separa_palabras


@pytest.mark.parametrize(
    ("leido", "esperado"),
    [
        ("我 們 走 吧", "我們走吧"),
        ("等等———你", "等等——你"),
        ("等等一一一你", "等等——你"),
        ("一一說明", "一一說明"),  # «uno por uno»: dos 一 son una palabra, no una raya
        ("嗯...", "嗯……"),
        ("嗯。。。", "嗯……"),
        ("嗯…", "嗯……"),
        ("えっ・・・", "えっ……"),
        ("說道:「好,走吧!」", "說道：「好，走吧！」"),
    ],
)
def test_unifica_espacios_rayas_y_puntos(leido: str, esperado: str) -> None:
    assert normalizar(leido, "zh-Hant" if "え" not in leido else "ja") == esperado


def test_pasa_a_tradicional_si_el_juego_es_zh_hant() -> None:
    assert normalizar("躯体", "zh-Hant") == "軀體"


def test_el_tradicional_no_cambia_formas_correctas_por_arcaicas() -> None:
    assert normalizar("與她相遇，才是唯一。說著", "zh-Hant") == "與她相遇，才是唯一。說著"


def test_en_chino_la_raya_larga_japonesa_es_una_raya() -> None:
    assert normalizar("「櫻ーー……」", "zh-Hant") == "「櫻——……」"
    assert normalizar("コーヒー", "ja") == "コーヒー"


def test_pasa_a_simplificado_si_el_juego_es_zh_hans() -> None:
    assert normalizar("軀體", "zh-Hans") == "躯体"


def test_no_convierte_el_japones() -> None:
    assert normalizar("学校へ行く", "ja") == "学校へ行く"


@pytest.mark.parametrize(
    ("leido", "esperado"),
    [
        ("  I  told you\talready ", "I told you already"),
        ("a well-known secret", "a well-known secret"),  # los guiones no son rayas
        ("She smiled - and left.", "She smiled - and left."),
        ("Well... really?!", "Well... really?!"),  # la puntuación ASCII se queda
        ("Wait，what？", "Wait,what?"),  # la de ancho completo vuelve a ASCII
    ],
)
def test_en_ingles_conserva_espacios_guiones_y_puntuacion(leido: str, esperado: str) -> None:
    assert normalizar(leido, "en") == esperado


def test_solo_el_ingles_separa_las_palabras() -> None:
    assert separa_palabras("en")
    assert not any(separa_palabras(idioma) for idioma in ("zh-Hant", "zh-Hans", "ja"))
