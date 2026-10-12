"""Nombre del personaje que habla, cuando el juego lo escribe al principio de la línea.

Muchas novelas visuales ponen quién habla delante del diálogo: `小雨：……`, `【小雨】……` o
`小雨「……」`. Sin una zona propia para el nombre, se reconoce por ese formato para no leerlo en
voz alta con cada línea. Las reglas son prudentes: ante la duda, la línea se deja entera.
"""

import re

from vn_audiolibro.ocr.normalizacion import separa_palabras

LARGO_MAX_CJK = 8
"""Un nombre en chino o japonés más largo que esto es, casi seguro, una frase."""

_ABREN, _CIERRAN = "【〖\uff3b\\[", "】〗\uff3d\\]"
"""Corchetes alrededor del nombre; \\uff3b y \\uff3d son los de ancho completo."""
_CORCHETES = re.compile(rf"^[{_ABREN}]([^{_ABREN}{_CIERRAN}]{{1,20}})[{_CIERRAN}]\s*(.+)$", re.DOTALL)
_PROHIBIDOS_CJK = r"\s：:，,。！!「」『』【】（）()…—"
_DOS_PUNTOS_CJK = re.compile(rf"^([^{_PROHIBIDOS_CJK}]{{1,{LARGO_MAX_CJK}}})[：:](.+)$", re.DOTALL)
_COMILLAS_CJK = re.compile(rf"^([^{_PROHIBIDOS_CJK}]{{1,{LARGO_MAX_CJK}}})([「『（].*)$", re.DOTALL)
_CIERRES = {"「": "」", "『": "』", "（": "）"}
_DOS_PUNTOS_EN = re.compile(r"^([A-Z][\w'.-]*(?: [A-Z][\w'.-]*){0,2}): (.+)$", re.DOTALL)

_VERBOS_DE_HABLA_ZH = frozenset("說说道曰問问喊叫笑想答")
"""En chino, `他說：` es narración, no un nombre."""
_PARTICULAS_JA = frozenset("はがを")
"""En japonés, `彼女は「……」` es narración con una cita, no un nombre."""


def separar_personaje(texto: str, idioma: str) -> tuple[str | None, str]:
    """Separa el nombre de quien habla del diálogo: `(nombre, diálogo)`, o `(None, texto)` si no hay.

    Con comillas o paréntesis (`小雨「……」`), el diálogo los conserva y tiene que ser entero lo
    que queda tras el nombre: así `彼女は「好き」と言った` no se toma por un nombre.
    """
    if (corchetes := _CORCHETES.match(texto)) is not None:
        return _resultado(corchetes.group(1), corchetes.group(2), texto)
    if separa_palabras(idioma):
        if (dos_puntos := _DOS_PUNTOS_EN.match(texto)) is not None:
            return _resultado(dos_puntos.group(1), dos_puntos.group(2), texto)
        return None, texto
    if (dos_puntos := _DOS_PUNTOS_CJK.match(texto)) is not None and _es_nombre(dos_puntos.group(1), idioma):
        return _resultado(dos_puntos.group(1), dos_puntos.group(2), texto)
    if (comillas := _COMILLAS_CJK.match(texto)) is not None and _es_nombre(comillas.group(1), idioma):
        nombre, dialogo = comillas.groups()
        if dialogo.endswith(_CIERRES[dialogo[0]]):
            return _resultado(nombre, dialogo, texto)
    return None, texto


def _es_nombre(nombre: str, idioma: str) -> bool:
    final = nombre[-1]
    if idioma.startswith("zh"):
        return final not in _VERBOS_DE_HABLA_ZH
    return idioma != "ja" or final not in _PARTICULAS_JA


def _resultado(nombre: str, dialogo: str, texto: str) -> tuple[str | None, str]:
    nombre, dialogo = nombre.strip(), dialogo.strip()
    if not nombre or not dialogo:
        return None, texto
    return nombre, dialogo
