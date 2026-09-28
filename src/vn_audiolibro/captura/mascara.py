"""Separación del texto y el fondo a partir del color."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import numpy as np

from vn_audiolibro.captura.modelos import Gris, Imagen, Mascara


def mascara_texto_claro(imagen: Imagen, umbral: int = 185, saturacion_max: int = 45) -> Mascara:
    """Marca los píxeles casi blancos: brillantes y poco saturados.

    El canal mínimo de RGB separa bien el texto blanco de fondos de color (fuego, cielos,
    degradados), que tienen al menos un canal bajo.
    """
    minimo = imagen.min(axis=2)
    maximo = imagen.max(axis=2)
    resultado: Mascara = (minimo > umbral) & ((maximo.astype(np.int16) - minimo) < saturacion_max)
    return resultado


def mascara_texto_oscuro(imagen: Imagen, umbral: int = 70, saturacion_max: int = 45) -> Mascara:
    """Marca los píxeles casi negros, para juegos con texto oscuro sobre fondo claro."""
    minimo = imagen.min(axis=2)
    maximo = imagen.max(axis=2)
    resultado: Mascara = (maximo < umbral) & ((maximo.astype(np.int16) - minimo) < saturacion_max)
    return resultado


def tinta_clara(imagen: Imagen) -> Gris:
    """Intensidad del texto claro: el canal mínimo de RGB (alto en el texto blanco)."""
    resultado: Gris = imagen.min(axis=2)
    return resultado


def tinta_oscura(imagen: Imagen) -> Gris:
    """Intensidad del texto oscuro: el canal máximo invertido (alto en el texto negro)."""
    resultado: Gris = 255 - imagen.max(axis=2)
    return resultado


@dataclass(frozen=True)
class ColorTexto:
    """Cómo separar el texto del fondo en un juego.

    - `estricta`: solo el texto con su color pleno; sirve para detectar texto nuevo.
    - `laxa`: también el texto atenuado; muchas VN oscurecen las líneas anteriores al añadir una
      nueva, y sin ella parecería que el texto anterior ha desaparecido.
    - `tinta`: intensidad del texto en gris, con el borde suavizado que la máscara pierde; el OCR
      la necesita con letra pequeña.
    """

    estricta: Callable[[Imagen], Mascara]
    laxa: Callable[[Imagen], Mascara]
    tinta: Callable[[Imagen], Gris]


TEXTO_CLARO = ColorTexto(mascara_texto_claro, partial(mascara_texto_claro, umbral=140), tinta_clara)
TEXTO_OSCURO = ColorTexto(mascara_texto_oscuro, partial(mascara_texto_oscuro, umbral=110), tinta_oscura)
