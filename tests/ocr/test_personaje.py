"""Tests de la separación del nombre del personaje que habla."""

import pytest

from vn_audiolibro.ocr.personaje import separar_personaje


@pytest.mark.parametrize(
    ("texto", "idioma", "nombre", "dialogo"),
    [
        ("小雨：我們回家吧。", "zh-Hant", "小雨", "我們回家吧。"),
        ("【小雨】我們回家吧。", "zh-Hant", "小雨", "我們回家吧。"),
        ("〖小雨〗我們回家吧。", "zh-Hans", "小雨", "我們回家吧。"),
        ("小雨「我們回家吧。」", "zh-Hant", "小雨", "「我們回家吧。」"),
        ("圭一「おはよう。」", "ja", "圭一", "「おはよう。」"),
        ("レナ『はぅ、かぁいいよう』", "ja", "レナ", "『はぅ、かぁいいよう』"),
        ("圭一（眠い……）", "ja", "圭一", "（眠い……）"),
        ("？？？「誰だ？」", "ja", "？？？", "「誰だ？」"),
        ("【圭一】おはよう。", "ja", "圭一", "おはよう。"),
        ("Keiichi: Good morning.", "en", "Keiichi", "Good morning."),
        ("Mion Sonozaki: Hey!", "en", "Mion Sonozaki", "Hey!"),
        ("[Rena] Hau~", "en", "Rena", "Hau~"),
    ],
)
def test_separa_el_nombre_del_dialogo(texto: str, idioma: str, nombre: str, dialogo: str) -> None:
    assert separar_personaje(texto, idioma) == (nombre, dialogo)


@pytest.mark.parametrize(
    ("texto", "idioma"),
    [
        ("我們回家吧。", "zh-Hant"),  # sin nombre
        ("「我們回家吧。」", "zh-Hant"),  # solo el diálogo
        ("他說：「我們回家吧。」", "zh-Hant"),  # narración: «él dijo»
        ("說道：「好，走吧！」", "zh-Hant"),
        ("那天晚上，小雨說：「好。」", "zh-Hant"),  # con coma: es una frase, no un nombre
        ("彼女は「好き」と言った。", "ja"),  # la cita no es todo lo que queda
        ("彼女は「好き」", "ja"),  # «ella»: con partícula, no es un nombre
        ("とても長い名前の誰かさん「こんにちは」", "ja"),  # demasiado largo para ser un nombre
        ("小雨「我們回家", "zh-Hant"),  # la cita no se cierra
        ("小雨：", "zh-Hant"),  # nombre sin diálogo
        ("Good morning: said nobody.", "en"),  # no empieza por un nombre en mayúscula
        ("He said: hello.", "en"),  # «said» va en minúscula
        ("Keiichi:Good morning.", "en"),  # sin espacio tras los dos puntos
    ],
)
def test_deja_la_linea_entera_si_no_hay_nombre(texto: str, idioma: str) -> None:
    assert separar_personaje(texto, idioma) == (None, texto)
