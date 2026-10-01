"""Imágenes sintéticas de texto de VN generadas con Noto Sans CJK (fuente libre, OFL)."""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import NoReturn

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from vn_audiolibro.captura.modelos import Imagen

CARPETAS_FUENTES = (Path("/usr/share/fonts/opentype/noto"), Path("/usr/share/fonts/noto-cjk"))
FAMILIAS = {"zh-Hant": "Noto Sans CJK TC", "zh-Hans": "Noto Sans CJK SC", "ja": "Noto Sans CJK JP"}

CARPETA_TRUETYPE = Path("/usr/share/fonts/truetype")
FUENTES_LATINAS = {
    "DejaVu Sans": "dejavu/DejaVuSans.ttf",  # fonts-dejavu-core
    "Liberation Serif": "liberation/LiberationSerif-Regular.ttf",  # fonts-liberation
    "Liberation Sans": "liberation/LiberationSans-Regular.ttf",
}
"""Fuentes latinas libres para el texto en inglés, relativas a `CARPETA_TRUETYPE`."""


def falta(motivo: str) -> NoReturn:
    """Salta el test por falta de un recurso, salvo en la CI, donde tiene que estar."""
    if os.environ.get("CI"):
        pytest.fail(motivo)
    pytest.skip(motivo)


def cara(idioma: str, tamano: int = 32) -> ImageFont.FreeTypeFont:
    """Fuente del idioma; salta el test si no está instalada."""
    resultado = fuente(idioma, tamano)
    if resultado is None:
        falta(f"falta la fuente {FAMILIAS[idioma]} (paquete fonts-noto-cjk)")
    return resultado


@cache
def fuente(idioma: str, tamano: int) -> ImageFont.FreeTypeFont | None:
    """Cara de Noto Sans CJK adecuada al idioma, o None si no está instalada."""
    for carpeta in CARPETAS_FUENTES:
        for fichero in sorted(carpeta.glob("NotoSansCJK-*.ttc")):
            for indice in range(10):
                try:
                    cara = ImageFont.truetype(str(fichero), tamano, index=indice)
                except OSError:
                    break
                if cara.getname()[0] == FAMILIAS[idioma]:
                    return cara
    return None


@dataclass(frozen=True)
class Estilo:
    """Aspecto del texto en la imagen."""

    tamano: int = 32
    paso: float = 1.8
    """Distancia entre caracteres, en tamaños de fuente (1.0 = texto junto)."""
    interlineado: float = 1.8
    fondo: tuple[int, int, int] = (40, 20, 80)
    degradado: tuple[int, int, int] | None = None
    """Color del borde derecho del fondo, para simular fondos no uniformes."""
    color: tuple[int, int, int] = (255, 255, 255)


def _fondo(ancho: int, alto: int, estilo: Estilo) -> Image.Image:
    inicio = np.array(estilo.fondo, dtype=np.float64)
    fin = np.array(estilo.degradado or estilo.fondo, dtype=np.float64)
    t = np.linspace(0, 1, ancho)[np.newaxis, :, np.newaxis]
    filas = inicio + (fin - inicio) * t
    return Image.fromarray(np.repeat(filas, alto, axis=0).astype(np.uint8))


def latina(nombre: str, tamano: int) -> ImageFont.FreeTypeFont:
    """Fuente latina libre; salta el test si no está instalada."""
    ruta = CARPETA_TRUETYPE / FUENTES_LATINAS[nombre]
    if not ruta.is_file():
        falta(f"falta la fuente {nombre} ({ruta})")
    return ImageFont.truetype(str(ruta), tamano)


def texto_latino(lineas: list[str], cara: ImageFont.FreeTypeFont, estilo: Estilo | None = None) -> Imagen:
    """Líneas de texto latino escritas de seguido, con el espaciado propio de la fuente."""
    estilo = estilo or Estilo()
    tamano = round(cara.size)
    salto = round(tamano * estilo.interlineado)
    ancho = 30 + max(round(cara.getlength(linea)) for linea in lineas)
    imagen = _fondo(ancho, 20 + salto * len(lineas), estilo)
    dibujo = ImageDraw.Draw(imagen)
    for n, linea in enumerate(lineas):
        dibujo.text((15, 10 + n * salto), linea, font=cara, fill=estilo.color)
    return np.asarray(imagen).copy()


def horizontal(lineas: list[str], cara: ImageFont.FreeTypeFont, estilo: Estilo) -> Imagen:
    """Líneas de texto horizontal, un carácter cada `paso` tamaños de fuente."""
    paso = round(estilo.tamano * estilo.paso)
    salto = round(estilo.tamano * estilo.interlineado)
    ancho = 20 + paso * max(len(linea) for linea in lineas)
    imagen = _fondo(ancho, 20 + salto * len(lineas), estilo)
    dibujo = ImageDraw.Draw(imagen)
    for n, linea in enumerate(lineas):
        for i, caracter in enumerate(linea):
            dibujo.text((10 + i * paso, 10 + n * salto), caracter, font=cara, fill=estilo.color)
    return np.asarray(imagen).copy()


def vertical(columnas: list[str], cara: ImageFont.FreeTypeFont, estilo: Estilo) -> Imagen:
    """Columnas de texto vertical, de arriba abajo y de derecha a izquierda."""
    paso = round(estilo.tamano * estilo.paso)
    salto = round(estilo.tamano * estilo.interlineado)
    alto = 20 + paso * max(len(columna) for columna in columnas)
    ancho = 20 + salto * len(columnas)
    imagen = _fondo(ancho, alto, estilo)
    dibujo = ImageDraw.Draw(imagen)
    for n, columna in enumerate(columnas):
        x = ancho - 10 - estilo.tamano - n * salto
        for i, caracter in enumerate(columna):
            dibujo.text((x, 10 + i * paso), caracter, font=cara, fill=estilo.color)
    return np.asarray(imagen).copy()


def sobre_imagen(lineas: list[str], cara: ImageFont.FreeTypeFont, tamano: int = 30) -> Imagen:
    """Texto blanco con borde negro escrito sobre una imagen con zonas claras grandes (nubes).

    Es como escriben el texto los juegos sin caja de texto: la máscara por color atrapa también
    las nubes y descarta las filas de texto por pequeñas.
    """
    salto = round(tamano * 2.3)
    ancho = 40 + tamano * max(len(linea) for linea in lineas)
    imagen = Image.new("RGB", (ancho, 40 + salto * len(lineas)), (60, 90, 150))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.ellipse((-80, 40, ancho // 2 - 60, imagen.height + 150), fill=(245, 245, 250))
    dibujo.ellipse((ancho // 2 + 60, -60, ancho + 60, salto * 2), fill=(235, 235, 240))
    for n, linea in enumerate(lineas):
        posicion = (20, 20 + n * salto)
        dibujo.text(posicion, linea, font=cara, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    return np.asarray(imagen).copy()


def distancia(a: str, b: str) -> int:
    """Distancia de Levenshtein entre dos textos."""
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def error_por_caracter(leido: str, esperado: str) -> float:
    """Proporción de caracteres mal leídos (CER)."""
    return distancia(leido, esperado) / len(esperado)
