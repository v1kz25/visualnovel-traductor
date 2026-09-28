"""Tests del troceo de la traducción que llega en streaming."""

import pytest

from vn_audiolibro.traduccion.partes import Segmentador


def trocear(*trozos: str) -> list[str]:
    """Partes que salen al ir añadiendo los trozos, más el resto final."""
    segmentador = Segmentador()
    partes = [parte for trozo in trozos for parte in segmentador.anadir(trozo)]
    resto = segmentador.terminar()
    return [*partes, resto] if resto else partes


def test_corta_en_cada_fin_de_frase_en_cuanto_llega_el_espacio() -> None:
    segmentador = Segmentador()
    assert segmentador.anadir("Hoy hace frío.") == []  # aún no se sabe si la frase acaba
    assert segmentador.anadir(" ¿Volvemos") == ["Hoy hace frío."]
    assert segmentador.anadir(" a casa? Vale") == ["¿Volvemos a casa?"]
    assert segmentador.terminar() == "Vale"
    assert segmentador.terminar() == ""


@pytest.mark.parametrize(
    ("trozos", "partes"),
    [
        (("Espera... no te vayas.",), ["Espera...", "no te vayas."]),
        (("¡¿En serio?! Sí, claro.",), ["¡¿En serio?!", "Sí, claro."]),
        (("«No lo sé.» Ella calló.",), ["«No lo sé.»", "Ella calló."]),
        (("Sí. No. Tal vez.",), ["Sí. No. Tal vez."]),  # frases muy cortas van juntas
        (("Hola, ¿qué tal?",), ["Hola, ¿qué tal?"]),  # coma demasiado pronto
        (
            ("Se limitó a mirar las llamas de la ciudad, sin decir nada.",),
            ["Se limitó a mirar las llamas de la ciudad,", "sin decir nada."],
        ),
        (("Sin", " signos", " de", " puntuación"), ["Sin signos de puntuación"]),
        (("3.5 metros",), ["3.5 metros"]),
    ],
)
def test_partes(trozos: tuple[str, ...], partes: list[str]) -> None:
    assert trocear(*trozos) == partes


def test_el_texto_se_conserva_entero() -> None:
    texto = "Ella no respondió. Se limitó a mirar las llamas, que devoraban la ciudad; nada más. ¿Y tú?"
    trozos = [texto[i : i + 3] for i in range(0, len(texto), 3)]
    assert " ".join(trocear(*trozos)) == texto
