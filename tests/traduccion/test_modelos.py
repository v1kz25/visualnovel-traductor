"""Tests del glosario."""

from vn_audiolibro.traduccion.modelos import GLOSARIO_JAPONES, Glosario, glosario_por_defecto

JUEGO = Glosario.desde_dict({"櫻": "Sakura", "羅格之火": "Fuego de Rogue"})


def test_solo_devuelve_los_terminos_presentes() -> None:
    assert JUEGO.presentes("沒錯——櫻，死了。") == [("櫻", "Sakura")]
    assert JUEGO.presentes("無邊無垠的永劫之火。") == []


def test_unir_da_prioridad_al_segundo_glosario() -> None:
    propio = Glosario.desde_dict({"先輩": "Senpai Kaito", "櫻": "Sakura"})

    unido = GLOSARIO_JAPONES.unir(propio)

    assert ("先輩", "Senpai Kaito") in unido.terminos
    assert ("先輩", "senpai") not in unido.terminos
    assert ("さん", "-san") in unido.terminos


def test_glosario_por_defecto_segun_el_idioma() -> None:
    assert glosario_por_defecto("ja") is GLOSARIO_JAPONES
    assert glosario_por_defecto("zh-Hant").terminos == ()
