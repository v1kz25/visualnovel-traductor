"""Menús de opciones: el juego pide elegir entre varias frases cortas, cada una en su botón.

Se reconocen por la posición de las filas que encuentra el detector: dos o más filas cortas, de
altura parecida, centradas una encima de otra y bastante más separadas que las líneas de un
diálogo. Además, o no empiezan todas en el mismo sitio (el texto de un diálogo va alineado a la
izquierda) o están en el centro de la zona. Lo demás que haya en la zona (rótulos del fondo, el
cuadro de diálogo de detrás) no es una opción y se descarta.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from vn_audiolibro.captura.modelos import Rectangulo

HUECO_MIN = 1.0
"""Hueco mínimo entre una opción y la siguiente, en altos de fila. Entre líneas de diálogo es menor."""
CENTRADO = 0.5
"""Diferencia máxima entre los centros de las opciones, en altos de fila."""
ALTO_MIN = 0.7
"""La fila más baja de dos opciones mide al menos esto respecto a la más alta."""
ANCHO_MAX = 0.6
"""Una opción ocupa como mucho esta fracción del ancho de la zona."""
ALINEADAS = 0.3
"""Filas cuyos comienzos difieren menos que esto (en altos de fila) van alineadas a la izquierda."""
EN_MEDIO = 0.05
"""Distancia máxima del centro de las opciones al de la zona, en fracción del ancho."""
ALARGADA = 1.5
"""Una caja más alta que esto respecto a su ancho es texto vertical del fondo (un cartel) en un
juego con texto horizontal: no puede ser una opción."""


@dataclass(frozen=True)
class Fila:
    """Una fila de texto encontrada por el detector y el recuadro que ocupa."""

    texto: str
    caja: Rectangulo


def opciones_menu(filas: Sequence[Fila], ancho_zona: int) -> list[str] | None:
    """El texto de cada opción, de arriba abajo, si las filas son un menú; si no, None."""
    candidatas = sorted((fila for fila in filas if _puede_ser_opcion(fila, ancho_zona)), key=_arriba)
    menus = [
        cadena
        for inicio in range(len(candidatas))
        if len(cadena := _cadena(candidatas[inicio:])) >= 2 and _es_menu(cadena, ancho_zona)
    ]
    if not menus:
        return None
    return [fila.texto for fila in max(menus, key=len)]


def alargada(caja: Rectangulo) -> bool:
    """True si la caja es de texto vertical (más alta que ancha)."""
    return caja.alto > ALARGADA * caja.ancho


def _arriba(fila: Fila) -> int:
    return fila.caja.y


def _centro(fila: Fila) -> float:
    return fila.caja.x + fila.caja.ancho / 2


def _puede_ser_opcion(fila: Fila, ancho_zona: int) -> bool:
    return fila.caja.ancho <= ANCHO_MAX * ancho_zona and any(caracter.isalnum() for caracter in fila.texto)


def _cadena(filas: Sequence[Fila]) -> list[Fila]:
    """La primera fila y, hacia abajo, cada una que podría ser la opción siguiente."""
    cadena = [filas[0]]
    for fila in filas[1:]:
        if _sigue(cadena[-1], fila, filas[0]):
            cadena.append(fila)
    return cadena


def _sigue(anterior: Fila, fila: Fila, primera: Fila) -> bool:
    """True si `fila` puede ser la opción que va debajo de `anterior` en el menú que abre `primera`."""
    bajo, alto = sorted((anterior.caja.alto, fila.caja.alto))
    hueco = fila.caja.y - (anterior.caja.y + anterior.caja.alto)
    return (
        bajo >= ALTO_MIN * alto
        and abs(_centro(fila) - _centro(primera)) <= CENTRADO * alto
        and hueco >= HUECO_MIN * alto
    )


def _es_menu(cadena: Sequence[Fila], ancho_zona: int) -> bool:
    """Descarta los párrafos de un texto alineado a la izquierda que no estén en el centro de la zona."""
    alto = max(fila.caja.alto for fila in cadena)
    comienzos = [fila.caja.x for fila in cadena]
    alineadas = max(comienzos) - min(comienzos) < ALINEADAS * alto
    centro = sum(_centro(fila) for fila in cadena) / len(cadena)
    return not alineadas or abs(centro - ancho_zona / 2) <= EN_MEDIO * ancho_zona
