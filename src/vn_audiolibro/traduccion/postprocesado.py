"""Limpieza y validación de la salida del modelo."""

import re
from collections.abc import Sequence

COMILLAS_APERTURA = '「『“"«'
COMILLAS_CIERRE = '」』”"»'

_ESPACIOS = re.compile(r"\s+")

COMILLAS_DIALOGO = {"es": ("«", "»"), "en": ("\u201c", "\u201d")}
"""Comillas con las que se escribe un diálogo en cada idioma de destino."""

LARGO_FIJO = 60
"""Margen de caracteres para salidas de líneas cortas (「うん」 -> «Sí»)."""
LARGO_POR_CARACTER = 8
"""Caracteres de la traducción por carácter de chino o japonés, como máximo razonable."""
LARGO_CITA = 12
"""Longitud mínima de una traducción anterior para buscarla repetida en la salida."""


def es_dialogo(original: str) -> bool:
    """Si la línea es un diálogo entre comillas japonesas (「…」 o 『…』)."""
    texto = original.strip()
    return len(texto) >= 2 and texto[0] in "「『" and texto[-1] in "」』"


def limpiar(salida: str, original: str, destino: str = "es") -> str:
    """Quita espacios sobrantes y unifica las comillas del diálogo según el idioma de destino.

    El modelo devuelve las comillas del original unas veces como 「」, otras como “” y a veces
    mezcladas; en español se usan las angulares («…») y en inglés las inglesas (“…”).
    """
    texto = _ESPACIOS.sub(" ", salida).strip()
    if es_dialogo(original):
        apertura, cierre = COMILLAS_DIALOGO[destino]
        return f"{apertura}{_sin_comillas(texto)}{cierre}"
    return texto


def es_valida(salida: str, original: str, traducciones_previas: Sequence[str] = ()) -> bool:
    """Si la salida es la traducción de la línea y no algo más.

    Con contexto, Hy-MT2 a veces repite las líneas anteriores (sobre todo si la línea es corta):
    la salida tiene varias líneas cuando el original no, contiene una traducción anterior o es
    desproporcionadamente larga.
    """
    return bool(salida.strip()) and es_valida_parcial(salida, original, traducciones_previas)


def es_valida_parcial(salida: str, original: str, traducciones_previas: Sequence[str] = ()) -> bool:
    """Como `es_valida`, pero para una salida que aún se está generando.

    Las tres comprobaciones solo pueden pasar de válida a no válida al llegar más texto, así que
    sirven para descartar una salida en streaming en cuanto se tuerce.
    """
    texto = salida.strip()
    if "\n" in texto and "\n" not in original.strip():
        return False
    if len(texto) > LARGO_FIJO + LARGO_POR_CARACTER * len(original):
        return False
    citas = (_sin_comillas(previa)[:LARGO_CITA] for previa in traducciones_previas)
    return not any(len(cita) == LARGO_CITA and cita in texto for cita in citas)


def _sin_comillas(texto: str) -> str:
    return texto.strip().lstrip(COMILLAS_APERTURA).rstrip(COMILLAS_CIERRE).strip()
