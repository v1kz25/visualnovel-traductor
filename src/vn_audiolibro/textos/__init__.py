"""Textos que ve el usuario, en su idioma: interfaz, mensajes y ayuda de la terminal.

En el código los textos se escriben en español y se marcan con `_()` (o con `ngettext` y
`pgettext`). Los que se definen al importar un módulo se marcan con `N_()`, que no traduce, y se
traducen con `_()` al usarlos: el idioma se elige después de importar.

Cada idioma tiene un catálogo `<código>.po` en esta carpeta; el español es el del código y no
lo necesita. Se usa gettext de la biblioteca estándar y no el sistema de traducción de Qt porque
la terminal también muestra mensajes y no carga Qt. Los `.po` se leen al arrancar, sin
compilarlos a `.mo`: añadir un idioma es añadir un fichero (`python -m vn_audiolibro.textos`).
"""

import ast
import gettext
import io
import struct
from collections.abc import Iterable
from functools import cache
from importlib.resources import files

ORIGEN = "es"
"""Idioma en el que están escritos los textos en el código."""
POR_DEFECTO = "en"
"""Idioma si el del sistema no está disponible."""

_traducciones: gettext.NullTranslations = gettext.NullTranslations()
_activo = ORIGEN


def disponibles() -> list[str]:
    """Códigos de los idiomas de la interfaz: el del código y los que tienen catálogo."""
    catalogos = sorted(
        recurso.name.removesuffix(".po")
        for recurso in files(__name__).iterdir()
        if recurso.name.endswith(".po")
    )
    return [ORIGEN, *catalogos]


@cache
def catalogo(idioma: str) -> gettext.NullTranslations:
    """Las traducciones de un idioma, sin activarlo. Las del español dejan los textos igual."""
    if idioma == ORIGEN:
        return gettext.NullTranslations()
    po = files(__name__).joinpath(f"{idioma}.po").read_text(encoding="utf-8")
    return gettext.GNUTranslations(io.BytesIO(compilar(leer_po(po))))


def activar(idioma: str) -> None:
    """Pone los textos en `idioma` desde ahora (los ya mostrados no cambian)."""
    global _traducciones, _activo
    _traducciones, _activo = catalogo(idioma), idioma


def activo() -> str:
    return _activo


def elegir(preferido: str | None, sistema: Iterable[str]) -> str:
    """El idioma que se usa: el elegido en la app si existe; si no, el primero del sistema que
    esté disponible (`es_ES.UTF-8` vale como `es`); y si ninguno, el inglés."""
    hay = disponibles()
    if preferido in hay:
        return preferido
    for codigo in sistema:
        base = codigo.split(".")[0].replace("-", "_").split("_")[0].lower()
        if base in hay:
            return base
    return POR_DEFECTO


def nombre_idioma(idioma: str) -> str:
    """Nombre del idioma en ese mismo idioma («English»), para elegirlo aunque no se entienda el actual."""
    return catalogo(idioma).pgettext("nombre de este idioma", "Español")


def _(texto: str) -> str:
    return _traducciones.gettext(texto)


def N_(texto: str) -> str:  # noqa: N802 - nombre habitual de gettext
    """Marca un texto para traducirlo más tarde con `_()`; lo devuelve igual."""
    return texto


def ngettext(singular: str, plural: str, n: int) -> str:
    return _traducciones.ngettext(singular, plural, n)


def pgettext(contexto: str, texto: str) -> str:
    return _traducciones.pgettext(contexto, texto)


def decimal(numero: float, cifras: int) -> str:
    """Número con `cifras` decimales y el separador del idioma: «1,25» en español, «1.25» en inglés."""
    return f"{numero:.{cifras}f}".replace(".", pgettext("separador decimal", ","))


# Catálogos


def leer_po(texto: str) -> dict[str, str]:
    """Entradas traducidas de un `.po`, con las claves como las guarda un `.mo`.

    Las claves con contexto van como `contexto\\x04texto` y los plurales como `singular\\x00plural`,
    con las traducciones separadas también por `\\x00`. Se saltan las entradas sin traducir y las
    marcadas como `fuzzy` (salvo la cabecera, que va con la clave vacía).
    """
    catalogo: dict[str, str] = {}
    for entrada in _entradas(texto):
        msgstr = [valor for clave, valor in sorted(entrada.items()) if clave.startswith("msgstr")]
        if entrada.get("fuzzy") and entrada.get("msgid"):
            continue
        if "msgid" not in entrada or not all(msgstr):
            continue
        clave = entrada["msgid"]
        if "msgid_plural" in entrada:
            clave += "\x00" + entrada["msgid_plural"]
        if "msgctxt" in entrada:
            clave = entrada["msgctxt"] + "\x04" + clave
        catalogo[clave] = "\x00".join(msgstr)
    return catalogo


def _entradas(texto: str) -> list[dict[str, str]]:
    """Entradas de un `.po` como diccionarios (`msgid`, `msgstr[0]`…, y `fuzzy` si lo es)."""
    entradas: list[dict[str, str]] = []
    actual: dict[str, str] = {}
    campo = ""
    for linea in (*texto.splitlines(), ""):
        linea = linea.strip()
        if linea.startswith("#") or not linea:
            if actual.get("msgstr") is not None or any(c.startswith("msgstr[") for c in actual):
                entradas.append(actual)
                actual, campo = {}, ""
            if linea.startswith("#,") and "fuzzy" in linea:
                actual["fuzzy"] = "1"
            continue
        if linea.startswith('"'):
            actual[campo] += _cadena(linea)
            continue
        campo, _espacio, valor = linea.partition(" ")
        actual[campo] = _cadena(valor)
    return entradas


def _cadena(literal: str) -> str:
    """Una cadena entre comillas de un `.po` (con los mismos escapes que Python)."""
    valor = ast.literal_eval(literal)
    if not isinstance(valor, str):
        raise ValueError(f"Cadena no válida en el catálogo: {literal}")
    return valor


def compilar(catalogo: dict[str, str]) -> bytes:
    """El catálogo en formato `.mo`, el que lee `gettext.GNUTranslations`."""
    claves = sorted(catalogo)
    ids = [clave.encode() for clave in claves]
    textos = [catalogo[clave].encode() for clave in claves]
    inicio_ids = 7 * 4
    inicio_textos = inicio_ids + 8 * len(claves)
    datos = inicio_textos + 8 * len(claves)
    tablas: list[int] = []
    contenido = b""
    for grupo in (ids, textos):
        for cadena in grupo:
            tablas += [len(cadena), datos + len(contenido)]
            contenido += cadena + b"\x00"
    cabecera = struct.pack("<7I", 0x950412DE, 0, len(claves), inicio_ids, inicio_textos, 0, 0)
    return cabecera + struct.pack(f"<{len(tablas)}I", *tablas) + contenido
