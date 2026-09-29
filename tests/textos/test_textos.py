"""Tests de los textos traducibles: lectura de catálogos, elección del idioma y traducción."""

import gettext
import io

import pytest

from vn_audiolibro import textos
from vn_audiolibro.textos import _, compilar, leer_po, ngettext, pgettext

PO = r"""
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

# Un comentario
msgid "Hola"
msgstr "Hello"

msgid "Texto "
"en dos líneas"
msgstr "Text "
"on two lines"

msgid "Con \"comillas\"\n"
msgstr "With \"quotes\"\n"

msgid "{n} línea"
msgid_plural "{n} líneas"
msgstr[0] "{n} line"
msgstr[1] "{n} lines"

msgctxt "separador decimal"
msgid ","
msgstr "."

msgid "Sin traducir"
msgstr ""

#, fuzzy
msgid "Dudosa"
msgstr "Doubtful"
"""


def traducciones(po: str) -> gettext.GNUTranslations:
    return gettext.GNUTranslations(io.BytesIO(compilar(leer_po(po))))


def test_leer_po() -> None:
    catalogo = leer_po(PO)
    assert catalogo["Hola"] == "Hello"
    assert catalogo["Texto en dos líneas"] == "Text on two lines"
    assert catalogo['Con "comillas"\n'] == 'With "quotes"\n'
    assert catalogo["{n} línea\x00{n} líneas"] == "{n} line\x00{n} lines"
    assert catalogo["separador decimal\x04,"] == "."
    assert "Plural-Forms" in catalogo[""]


def test_sin_traducir_y_dudosas_se_quedan_en_espanol() -> None:
    t = traducciones(PO)
    assert t.gettext("Sin traducir") == "Sin traducir"
    assert t.gettext("Dudosa") == "Dudosa"


def test_catalogo_compilado_con_plurales_y_contexto() -> None:
    t = traducciones(PO)
    assert t.gettext("Hola") == "Hello"
    assert t.ngettext("{n} línea", "{n} líneas", 1) == "{n} line"
    assert t.ngettext("{n} línea", "{n} líneas", 2) == "{n} lines"
    assert t.pgettext("separador decimal", ",") == "."
    assert t.gettext("No está") == "No está"


def test_cadena_no_valida() -> None:
    with pytest.raises(ValueError, match="no válida"):
        leer_po('msgid b"Hola"\nmsgstr "Hello"\n')


def test_disponibles() -> None:
    assert textos.disponibles()[0] == "es"
    assert "en" in textos.disponibles()


@pytest.mark.parametrize(
    ("preferido", "sistema", "esperado"),
    [
        ("en", ["es_ES.UTF-8"], "en"),
        ("es", ["en_US.UTF-8"], "es"),
        (None, ["es_ES.UTF-8"], "es"),
        (None, ["en_GB"], "en"),
        (None, ["fr_FR.UTF-8", "es-MX"], "es"),
        (None, ["de_DE"], "en"),
        (None, [], "en"),
        ("xx", ["es_ES"], "es"),
    ],
)
def test_elegir(preferido: str | None, sistema: list[str], esperado: str) -> None:
    assert textos.elegir(preferido, sistema) == esperado


def test_activar_cambia_los_textos() -> None:
    assert _("Jugar") == "Jugar"
    textos.activar("en")
    assert textos.activo() == "en"
    assert _("Jugar") == "Play"
    assert (
        ngettext("Vaciada la caché: {n} línea", "Vaciada la caché: {n} líneas", 3)
        == "Cleared the cache: {n} lines"
    )
    assert pgettext("separador decimal", ",") == "."
    assert textos.N_("Jugar") == "Jugar"  # marca sin traducir
    textos.activar("es")
    assert _("Jugar") == "Jugar"


def test_nombre_de_cada_idioma_en_su_idioma() -> None:
    textos.activar("en")
    assert textos.nombre_idioma("es") == "Español"
    assert textos.nombre_idioma("en") == "English"


@pytest.mark.usefixtures("en_ingles")
def test_decimal_en_ingles() -> None:
    assert textos.decimal(1.25, 2) == "1.25"


def test_decimal_en_espanol() -> None:
    assert textos.decimal(1.25, 2) == "1,25"
