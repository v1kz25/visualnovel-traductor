"""Limpieza del texto reconocido antes de traducirlo y cachearlo."""

import re
from functools import cache

import opencc

CONVERSIONES_OPENCC = {"zh-Hant": "s2tw", "zh-Hans": "t2s"}
"""Conversión de OpenCC por idioma de origen. El japonés no se toca: sus kanji no son chino.

Para el tradicional se usa el estándar de Taiwán, no el genérico `s2t`: este cambia formas
correctas por otras arcaicas (才是 → 纔是, 著 → 着).
"""

RAYA = "——"
PUNTOS_SUSPENSIVOS = "……"

_RAYAS = re.compile(r"[—―─━－\-]+|一{3,}")
"""Rayas de diálogo o pausa. El OCR lee a veces `———` como `一一一`; `一一` es una palabra válida."""
_RAYAS_CHINO = re.compile(r"ー+")
"""En chino no existe la ー japonesa: es una raya que el reconocedor ha leído mal."""
_PUNTOS = re.compile(r"…+|\.{2,}|。{2,}|・{2,}|·{2,}|･{2,}")
_ESPACIOS = re.compile(r"\s+")
_ANCHO_COMPLETO = str.maketrans(",:;?!()", "，：；？！（）")
"""El OCR confunde la puntuación de ancho completo con la ASCII; en chino y japonés es la primera."""


@cache
def _conversor(configuracion: str) -> opencc.OpenCC:
    return opencc.OpenCC(configuracion)


def normalizar(texto: str, idioma: str) -> str:
    """Unifica rayas, puntos suspensivos y puntuación, quita espacios y ajusta la variante del chino.

    Los espacios sobran: el chino y el japonés no los usan y el OCR los inventa entre
    caracteres separados.
    """
    texto = _ESPACIOS.sub("", texto)
    texto = _RAYAS.sub(RAYA, texto)
    if idioma.startswith("zh"):
        texto = _RAYAS_CHINO.sub(RAYA, texto)
    texto = _PUNTOS.sub(PUNTOS_SUSPENSIVOS, texto).translate(_ANCHO_COMPLETO)
    configuracion = CONVERSIONES_OPENCC.get(idioma)
    if configuracion is not None:
        texto = _conversor(configuracion).convert(texto)
    return texto
