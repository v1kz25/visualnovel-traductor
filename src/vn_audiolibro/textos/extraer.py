"""Busca en el código los textos marcados para traducir y crea o pone al día los catálogos `.po`."""

import ast
from dataclasses import dataclass
from pathlib import Path

from vn_audiolibro.textos import _entradas

RAIZ = Path(__file__).resolve().parents[1]
"""Carpeta del paquete `vn_audiolibro`."""
CARPETA = Path(__file__).resolve().parent
"""Carpeta de los catálogos."""

_FUNCIONES = {"_": 1, "N_": 1, "ngettext": 2, "pgettext": 2}
"""Funciones que marcan textos y cuántos de sus argumentos son textos del catálogo."""


class TextoNoLiteralError(ValueError):
    """Un texto marcado se construye al ejecutar (p. ej. una f-string): no se puede traducir.

    `_()` sí admite una variable: es la forma de traducir un texto marcado antes con `N_()`.
    """


@dataclass(frozen=True)
class Texto:
    """Un texto del código que hay que traducir."""

    msgid: str
    plural: str | None = None
    contexto: str | None = None

    @property
    def clave(self) -> str:
        """La misma clave que usa `leer_po`."""
        clave = self.msgid if self.plural is None else f"{self.msgid}\x00{self.plural}"
        return clave if self.contexto is None else f"{self.contexto}\x04{clave}"


def textos_de(codigo: str, nombre: str = "<código>") -> list[Texto]:
    """Textos marcados en un fichero de código, en orden de aparición."""
    textos: list[tuple[int, int, Texto]] = []
    for nodo in ast.walk(ast.parse(codigo, nombre)):
        if not isinstance(nodo, ast.Call) or (funcion := _funcion(nodo)) is None:
            continue
        argumentos = nodo.args[: _FUNCIONES[funcion]]
        valores = [a.value for a in argumentos if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if len(valores) < _FUNCIONES[funcion]:
            construido = any(isinstance(a, ast.JoinedStr | ast.BinOp) for a in argumentos)
            if not construido and (funcion == "_" or isinstance(nodo.func, ast.Attribute)):
                continue  # un texto marcado con N_() en otro sitio, o el propio módulo de textos
            raise TextoNoLiteralError(f"{nombre}:{nodo.lineno}: {funcion}() necesita un texto fijo")
        if funcion == "ngettext":
            texto = Texto(valores[0], plural=valores[1])
        elif funcion == "pgettext":
            texto = Texto(valores[1], contexto=valores[0])
        else:
            texto = Texto(valores[0])
        textos.append((nodo.lineno, nodo.col_offset, texto))
    return [texto for _linea, _columna, texto in sorted(textos, key=lambda t: t[:2])]


def _funcion(nodo: ast.Call) -> str | None:
    """Qué función de traducción es la llamada, o None si no es ninguna.

    Vale también como método (`catalogo(idioma).pgettext(…)`), para textos de un idioma que no
    es el activo.
    """
    if isinstance(nodo.func, ast.Name) and nodo.func.id in _FUNCIONES:
        return nodo.func.id
    if isinstance(nodo.func, ast.Attribute) and nodo.func.attr in {"gettext", "ngettext", "pgettext"}:
        return "_" if nodo.func.attr == "gettext" else nodo.func.attr
    return None


def textos_del_paquete(raiz: Path = RAIZ) -> list[Texto]:
    """Todos los textos marcados del paquete, sin repetir, en orden de fichero y de aparición."""
    vistos: dict[str, Texto] = {}
    for fichero in sorted(raiz.rglob("*.py")):
        for texto in textos_de(fichero.read_text(encoding="utf-8"), str(fichero.relative_to(raiz))):
            vistos.setdefault(texto.clave, texto)
    return list(vistos.values())


def _po(valor: str) -> str:
    escapado = valor.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escapado}"'


CABECERA = (
    "Content-Type: text/plain; charset=UTF-8\n"
    "Language: {idioma}\n"
    "Plural-Forms: nplurals=2; plural=(n != 1);\n"
)


def actualizar(idioma: str, textos: list[Texto], anterior: str = "") -> str:
    """El catálogo de `idioma` con los `textos` del código, conservando las traducciones de `anterior`.

    Los textos nuevos quedan sin traducir y los que ya no están en el código se quitan.
    """
    traducidos: dict[str, list[str]] = {}
    cabecera = CABECERA.format(idioma=idioma)
    for entrada in _entradas(anterior):
        texto = Texto(entrada["msgid"], entrada.get("msgid_plural"), entrada.get("msgctxt"))
        msgstr = [v for c, v in sorted(entrada.items()) if c.startswith("msgstr")]
        if texto.msgid:
            traducidos[texto.clave] = msgstr
        else:
            cabecera = msgstr[0]
    lineas = ['msgid ""', 'msgstr ""', *(_po(linea) for linea in cabecera.splitlines(keepends=True))]
    for texto in textos:
        lineas.append("")
        if texto.contexto is not None:
            lineas.append(f"msgctxt {_po(texto.contexto)}")
        lineas.append(f"msgid {_po(texto.msgid)}")
        previos = traducidos.get(texto.clave, [])
        if texto.plural is None:
            lineas.append(f"msgstr {_po(previos[0] if previos else '')}")
            continue
        lineas.append(f"msgid_plural {_po(texto.plural)}")
        for indice in range(2):
            lineas.append(f"msgstr[{indice}] {_po(previos[indice] if len(previos) > indice else '')}")
    return "\n".join(lineas) + "\n"
