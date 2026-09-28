"""Tests de la limpieza y validación de la salida del modelo."""

import pytest

from vn_audiolibro.traduccion.postprocesado import es_dialogo, es_valida, limpiar


@pytest.mark.parametrize("salida", ["“Sí”", "「Sí」", "「Sí»", "Sí", "  «Sí» "])
def test_unifica_las_comillas_del_dialogo(salida: str) -> None:
    assert limpiar(salida, "「うん」") == "«Sí»"


def test_no_anade_comillas_a_la_narracion() -> None:
    assert limpiar(" Fuego  eterno,\nsin fin. ", "無邊無垠的永劫之火。") == "Fuego eterno, sin fin."


def test_es_dialogo() -> None:
    assert es_dialogo("「うん」")
    assert es_dialogo("『召喚者』")
    assert not es_dialogo("他說「好」。")


PREVIAS = ["«…¿Eh, todavía estás despierto?»", "Fuera de la ventana, la lluvia continuaba cayendo."]


def test_salida_normal_es_valida() -> None:
    assert es_valida("«Sí»", "「うん」", PREVIAS)


def test_salida_con_varias_lineas_no_es_valida() -> None:
    salida = "「…Oye, todavía estás despierto?»\nFuera de la ventana, la lluvia seguía cayendo."

    assert not es_valida(salida, "「うん」", PREVIAS)


def test_salida_que_repite_una_traduccion_anterior_no_es_valida() -> None:
    assert not es_valida("Fuera de la ventana, la lluvia continuaba cayendo. Sí.", "「うん」", PREVIAS)


def test_salida_desproporcionada_no_es_valida() -> None:
    assert not es_valida("palabra " * 20, "「うん」")
    assert es_valida("palabra " * 20, "這火焰在將一切都燃燒殆盡之前決不停息，彷彿在體現著人類的罪孽一般。")


def test_salida_vacia_no_es_valida() -> None:
    assert not es_valida("  ", "「うん」")


@pytest.mark.parametrize("salida", ["«Yeah»", "「Yeah」", "Yeah", " “Yeah” "])
def test_en_ingles_el_dialogo_va_con_comillas_inglesas(salida: str) -> None:
    assert limpiar(salida, "「うん」", "en") == "\u201cYeah\u201d"
