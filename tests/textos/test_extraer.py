"""Tests del extractor de textos y de que los catálogos estén completos y al día."""

import runpy
import string
import sys
from pathlib import Path

import pytest

from vn_audiolibro import textos
from vn_audiolibro.textos import extraer, leer_po
from vn_audiolibro.textos.extraer import Texto, TextoNoLiteralError, actualizar, textos_de, textos_del_paquete

CODIGO = """
from vn_audiolibro.textos import N_, _, ngettext, pgettext

CONSTANTE = N_("Marcada")
print(_("Hola"), _(CONSTANTE), ngettext("{n} línea", "{n} líneas", 2))
print(pgettext("contexto", "Texto"), catalogo("en").pgettext("otro", "Método"))
print(catalogo("en").gettext(CONSTANTE))
"""


def catalogo_en() -> str:
    return (extraer.CARPETA / "en.po").read_text(encoding="utf-8")


def test_textos_de_un_fichero_en_orden() -> None:
    assert textos_de(CODIGO) == [
        Texto("Marcada"),
        Texto("Hola"),
        Texto("{n} línea", plural="{n} líneas"),
        Texto("Texto", contexto="contexto"),
        Texto("Método", contexto="otro"),
    ]


@pytest.mark.parametrize(
    "codigo", ['_(f"Hola {nombre}")', '_("Hola " + nombre)', 'ngettext("uno", plural, 2)', "N_(variable)"]
)
def test_textos_que_no_se_pueden_traducir(codigo: str) -> None:
    with pytest.raises(TextoNoLiteralError, match="necesita un texto fijo"):
        textos_de(codigo)


def test_actualizar_conserva_traducciones_y_quita_las_que_sobran() -> None:
    anterior = actualizar("fr", [Texto("Hola"), Texto("Adiós")])
    anterior = anterior.replace('msgid "Hola"\nmsgstr ""', 'msgid "Hola"\nmsgstr "Bonjour"')
    nuevo = actualizar(
        "fr", [Texto("Hola"), Texto("{n} línea", plural="{n} líneas"), Texto(",", contexto="c")], anterior
    )
    assert "Adiós" not in nuevo
    assert 'msgid "Hola"\nmsgstr "Bonjour"' in nuevo
    assert 'msgid_plural "{n} líneas"\nmsgstr[0] ""\nmsgstr[1] ""' in nuevo
    assert 'msgctxt "c"\nmsgid ","' in nuevo
    assert "Language: fr" in nuevo
    assert leer_po(nuevo)["Hola"] == "Bonjour"


def test_crear_catalogo_desde_la_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(extraer, "CARPETA", tmp_path)
    monkeypatch.setattr(sys, "argv", ["textos", "fr"])
    runpy.run_module("vn_audiolibro.textos", run_name="__main__")
    creado = (tmp_path / "fr.po").read_text(encoding="utf-8")
    assert 'msgid "Jugar"\nmsgstr ""' in creado
    assert "fr.po" in capsys.readouterr().out


# Los catálogos de la app


@pytest.mark.parametrize("idioma", [i for i in textos.disponibles() if i != textos.ORIGEN])
def test_catalogo_completo(idioma: str) -> None:
    """Cada texto marcado en el código tiene traducción y el catálogo no guarda textos viejos.

    Si falla, ejecuta `uv run python -m vn_audiolibro.textos <idioma>` y traduce los `msgstr` vacíos.
    """
    po = (extraer.CARPETA / f"{idioma}.po").read_text(encoding="utf-8")
    traducidos = leer_po(po)
    claves = {texto.clave for texto in textos_del_paquete()}
    assert sorted(claves - traducidos.keys()) == []
    assert sorted(traducidos.keys() - claves - {""}) == []


def _campos(texto: str) -> set[str]:
    return {campo for _, campo, _, _ in string.Formatter().parse(texto) if campo is not None}


@pytest.mark.parametrize("idioma", [i for i in textos.disponibles() if i != textos.ORIGEN])
def test_traducciones_con_los_mismos_datos(idioma: str) -> None:
    """Las traducciones usan los mismos `{campos}` que el original, o `format` fallaría."""
    po = (extraer.CARPETA / f"{idioma}.po").read_text(encoding="utf-8")
    distintos = []
    for clave, traduccion in leer_po(po).items():
        if not clave:
            continue
        original = clave.split("\x04")[-1].split("\x00")[0]
        for forma in traduccion.split("\x00"):
            if _campos(forma) != _campos(original):
                distintos.append((original, forma))
    assert distintos == []


def test_el_catalogo_ingles_esta_en_el_paquete() -> None:
    assert "Content-Type: text/plain; charset=UTF-8" in catalogo_en()
