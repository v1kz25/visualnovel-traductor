"""Guiones de texto con órdenes `OutputLine`, como los de algunos juegos hechos con Unity.

Están en `<Juego>_Data/StreamingAssets/Scripts/*.txt` (UTF-8 con BOM) y cada línea de texto es:

    OutputLine(NULL, "<original>",
               NULL, "<inglés>", Line_WaitForInput);

- `OutputLineAll(NULL, "\\n", …)` es un salto de línea en pantalla: separa párrafos.
- `ClearMessage()` borra la pantalla: separa páginas (y párrafos).

Solo se lee: el juego no se modifica.
"""

import logging
import re
from pathlib import Path

from vn_audiolibro.guion.modelos import Guion, GuionNoEncontradoError, agrupar
from vn_audiolibro.textos import _

_registro = logging.getLogger(__name__)

_CADENA = r'"((?:[^"\\]|\\.)*)"'
_NOMBRE = r'(?:NULL|"(?:[^"\\]|\\.)*")'
"""El nombre del personaje: NULL o una cadena (que no se usa)."""
_ORDEN = re.compile(
    rf"OutputLine\(\s*{_NOMBRE}\s*,\s*{_CADENA}\s*,\s*{_NOMBRE}\s*,\s*{_CADENA}\s*,\s*\w+\s*\)"
    rf"|OutputLineAll\(\s*{_NOMBRE}\s*,\s*{_CADENA}\s*,\s*\w+\s*\)"
    r"|ClearMessage\(\s*\)"
)
_COMENTARIO = re.compile(r"^\s*//.*$", re.MULTILINE)
_ESCAPES = {"n": "\n", '"': '"', "\\": "\\", "t": "\t"}
_ESPACIOS_INICIALES = " \u3000"
"""El guion sangra la narración con un espacio de ancho completo."""


def carpeta_scripts(carpeta: Path) -> Path | None:
    """Carpeta con los `.txt` del guion, buscándola desde la del juego (o la propia carpeta)."""
    candidatas = [carpeta, carpeta / "StreamingAssets" / "Scripts"]
    candidatas += sorted(carpeta.glob("*_Data/StreamingAssets/Scripts"))
    for candidata in candidatas:
        if candidata.is_dir() and any(_con_ordenes(fichero) for fichero in candidata.glob("*.txt")):
            return candidata
    return None


def leer_guion(carpeta: Path) -> Guion:
    """Guion del juego de la carpeta. Lanza `GuionNoEncontradoError` si no hay uno legible."""
    scripts = carpeta_scripts(carpeta)
    if scripts is None:
        raise GuionNoEncontradoError(
            _("No se ha encontrado el guion del juego en {carpeta}").format(carpeta=carpeta)
        )
    fragmentos: list[tuple[str, str, bool, bool]] = []
    for fichero in sorted(scripts.glob("*.txt")):
        fragmentos += _fragmentos(_leer(fichero))
    guion = agrupar(fragmentos)
    if not guion.parrafos:
        raise GuionNoEncontradoError(_("El guion de {carpeta} no tiene texto").format(carpeta=scripts))
    return guion


def _leer(fichero: Path) -> str:
    try:
        return fichero.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise GuionNoEncontradoError(
            _("No se pudo leer {fichero}: {error}").format(fichero=fichero.name, error=error)
        ) from error


def _con_ordenes(fichero: Path) -> bool:
    try:
        return "OutputLine(" in fichero.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False


def _fragmentos(texto: str) -> list[tuple[str, str, bool, bool]]:
    """Fragmentos de un fichero: (original, inglés, fin de párrafo, fin de página).

    Un salto de línea o un borrado de pantalla cierra el fragmento anterior; cada fichero empieza
    en una página nueva.
    """
    resultado: list[tuple[str, str, bool, bool]] = []
    for orden in _ORDEN.finditer(_COMENTARIO.sub("", texto)):
        original, ingles, todo = orden.group(1), orden.group(2), orden.group(3)
        if original is not None:
            limpio = _sin_escapes(original).strip(_ESPACIOS_INICIALES)
            if limpio:
                resultado.append((limpio, _sin_escapes(ingles or ""), False, False))
        elif resultado and (todo is None or "\\n" in todo):
            fin_pagina = todo is None
            anterior = resultado[-1]
            resultado[-1] = (anterior[0], anterior[1], True, anterior[3] or fin_pagina)
    if resultado:
        resultado[-1] = (*resultado[-1][:2], True, True)
    return resultado


def _sin_escapes(cadena: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), cadena)
