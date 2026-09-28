"""Preprocesado de la zona de texto para el reconocedor.

Las VN suelen dibujar el texto muy espaciado y sobre fondos con adornos, y el detector de
RapidOCR lo parte mal. Aquí se hace a mano, que es más rápido y preciso con texto limpio:

1. Se aísla el texto por color (máscara laxa del perfil) y se toma su intensidad en gris, que
   conserva el borde suavizado de las letras.
2. Se buscan las filas por proyección horizontal (columnas si el texto es vertical).
3. Dentro de cada fila se buscan los glifos por proyección vertical, uniendo los trozos de un
   mismo carácter (川, 小, 二…) que están a menos de una fracción del alto de la fila.
4. Las rayas (——) se sacan como texto: el reconocedor las pierde cuando van muy espaciadas.
5. El resto se recompone sin el espaciado original, en negro sobre blanco y ampliado si la
   letra es pequeña.
"""

from dataclasses import dataclass
from enum import Enum
from math import ceil

import numpy as np
import numpy.typing as npt
from PIL import Image

from vn_audiolibro.captura.mascara import ColorTexto
from vn_audiolibro.captura.modelos import Gris, Imagen, Mascara

Tramo = tuple[int, int]
"""Intervalo [inicio, fin) de filas o columnas."""

RAYA = "——"

Segmento = Imagen | str
"""Parte de una línea: una imagen para el reconocedor o texto ya conocido (las rayas)."""

Linea = tuple[Segmento, ...]


class Orientacion(Enum):
    """Dirección de escritura del texto del juego."""

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    """Columnas de arriba abajo, de derecha a izquierda (japonés tradicional)."""


@dataclass(frozen=True)
class AjustesPreprocesado:
    """Parámetros del preprocesado, relativos al alto de la fila salvo que se diga otra cosa."""

    union_glifos: float = 0.45
    """Trozos separados por menos de esto se consideran el mismo carácter."""
    separacion: float = 0.15
    """Hueco entre glifos en la fila recompuesta."""
    margen: float = 0.25
    """Margen blanco alrededor de la fila recompuesta."""
    largo_vertical: float = 1.15
    """En texto vertical, largo máximo de un glifo respecto al ancho de la columna."""
    union_filas: float = 0.25
    """Trozos separados en vertical por menos de esto (respecto a la fila más alta) son una fila."""
    min_alto_px: int = 6
    """Filas más bajas se descartan como ruido."""
    min_alto_relativo: float = 0.5
    """Filas más bajas que esta fracción de la fila más alta se descartan.

    Quita restos como la parte inferior de la fila anterior que entra en el recorte de NVL.
    """
    ampliar_hasta_px: int = 32
    """Las filas más bajas se amplían por un factor entero hasta llegar a este alto."""
    raya_grosor_max: float = 0.25
    """Una raya no es más gruesa que esto."""
    raya_largo_min: float = 1.2
    """Una raya mide al menos esto respecto al ancho típico de un carácter de la fila.

    Separa la raya (——) del carácter 一, que es algo más estrecho que los demás.
    """


def tramos(perfil: npt.NDArray[np.int64], hueco_max: int = 0, largo_max: int | None = None) -> list[Tramo]:
    """Intervalos donde el perfil de proyección es positivo.

    Los intervalos separados por `hueco_max` posiciones vacías o menos se unen en uno, salvo que
    el resultado supere `largo_max`.
    """
    lleno = np.concatenate(([False], perfil > 0, [False]))
    cambios = np.flatnonzero(np.diff(lleno.astype(np.int8)))
    resultado: list[Tramo] = []
    for inicio, fin in zip(cambios[::2].tolist(), cambios[1::2].tolist(), strict=True):
        cabe = largo_max is None or (resultado and fin - resultado[-1][0] <= largo_max)
        if resultado and inicio - resultado[-1][1] <= hueco_max and cabe:
            resultado[-1] = (resultado[-1][0], fin)
        else:
            resultado.append((inicio, fin))
    return resultado


def filas(mascara: Mascara, ajustes: AjustesPreprocesado) -> list[Tramo]:
    """Filas de texto de una máscara horizontal, sin ruido ni filas cortadas.

    Los trozos separados por un hueco pequeño respecto al alto del texto son la misma fila:
    así el punto de ？ o ！ no se queda aparte y se descarta como ruido.
    """
    perfil = mascara.sum(axis=1)
    candidatas = tramos(perfil, hueco_max=1)
    if not candidatas:
        return []
    mas_alta = max(fin - inicio for inicio, fin in candidatas)
    candidatas = tramos(perfil, hueco_max=int(ajustes.union_filas * mas_alta))
    mas_alta = max(fin - inicio for inicio, fin in candidatas)
    minimo = max(ajustes.min_alto_px, ajustes.min_alto_relativo * mas_alta)
    return [(inicio, fin) for inicio, fin in candidatas if fin - inicio >= minimo]


def glifos(fila: Mascara, ajustes: AjustesPreprocesado, largo_max: int | None = None) -> list[Tramo]:
    """Grupos de columnas de una fila, cada uno con uno o varios caracteres seguidos.

    Con `largo_max` cada grupo no pasa de esa longitud, para separar caracteres uno a uno.
    """
    hueco = int(ajustes.union_glifos * fila.shape[0])
    return tramos(fila.sum(axis=0), hueco_max=hueco, largo_max=largo_max)


def partir_rayas(
    fila: Mascara, grupos: list[Tramo], ajustes: AjustesPreprocesado
) -> list[tuple[Tramo, bool]]:
    """Separa las rayas de los grupos de glifos y marca cuáles son rayas.

    Una raya es un trazo fino y más largo que un carácter. Se mira trazo a trazo, no por grupos:
    un signo pegado a la raya (——」) no debe esconderla, y los puntos suspensivos espaciados
    (... ...), igual de finos, están hechos de trazos cortos. El carácter 一 es algo más estrecho
    que un carácter y no llega al largo mínimo.

    Solo detecta las rayas de fuentes que las dibujan más anchas que un carácter (como la del
    juego de la validación). En otras, raya y 一 miden casi lo mismo y se deja la raya al
    reconocedor.

    El ancho de un carácter se estima por su alto (los caracteres CJK son cuadrados): el ancho
    de los grupos no sirve, porque un grupo puede tener varios caracteres o signos estrechos.
    """
    alto = fila.shape[0]
    completos = [grosor for a, b in grupos if (grosor := _grosor(fila[:, a:b])) > alto / 2]
    ancho_caracter = float(np.median(completos)) if completos else float(alto)
    resultado: list[tuple[Tramo, bool]] = []
    for inicio, fin in grupos:
        actual: Tramo | None = None
        for a, b in tramos(fila[:, inicio:fin].sum(axis=0), hueco_max=1):
            trazo = (inicio + a, inicio + b)
            es_raya = (
                _grosor(fila[:, trazo[0] : trazo[1]]) <= ajustes.raya_grosor_max * alto
                and b - a >= ajustes.raya_largo_min * ancho_caracter
            )
            if not es_raya:
                actual = (actual[0], trazo[1]) if actual else trazo
                continue
            if actual:
                resultado.append((actual, False))
                actual = None
            resultado.append((trazo, True))
        if actual:
            resultado.append((actual, False))
    return resultado


def _grosor(pieza: Mascara) -> int:
    return int(np.count_nonzero(pieza.any(axis=1)))


def dilatar(mascara: Mascara) -> Mascara:
    """Amplía la máscara un píxel en cada dirección, para no cortar el borde suavizado."""
    resultado = mascara.copy()
    resultado[1:] |= mascara[:-1]
    resultado[:-1] |= mascara[1:]
    vertical = resultado.copy()
    resultado[:, 1:] |= vertical[:, :-1]
    resultado[:, :-1] |= vertical[:, 1:]
    return resultado


def recomponer(piezas: list[Gris], alto: int, ajustes: AjustesPreprocesado) -> Imagen:
    """Une los glifos en una fila en negro sobre blanco, centrados, con margen y ampliada si hace falta.

    `alto` es el mínimo: en vertical un glifo puede ser algo más largo que ancha la columna.
    """
    alto = max(alto, *(pieza.shape[0] for pieza in piezas))
    separacion = max(1, round(ajustes.separacion * alto))
    margen = max(1, round(ajustes.margen * alto))
    trozos: list[Gris] = []
    for pieza in piezas:
        if trozos:
            trozos.append(np.zeros((alto, separacion), dtype=np.uint8))
        arriba = (alto - pieza.shape[0]) // 2
        trozos.append(np.pad(pieza, ((arriba, alto - pieza.shape[0] - arriba), (0, 0))))
    gris = 255 - np.pad(np.hstack(trozos), margen)
    factor = ceil(ajustes.ampliar_hasta_px / alto)
    if factor > 1:
        ampliada = Image.fromarray(gris).resize(
            (gris.shape[1] * factor, gris.shape[0] * factor), Image.Resampling.BICUBIC
        )
        gris = np.asarray(ampliada)
    resultado: Imagen = np.repeat(gris[:, :, np.newaxis], 3, axis=2)
    return resultado


def _segmentos(fila: Mascara, tinta: Gris, alto: int, vertical: bool, ajustes: AjustesPreprocesado) -> Linea:
    """Parte la fila en imágenes para el reconocedor y rayas ya convertidas en texto."""
    # En vertical cada glifo se gira por separado, así que no pueden ir varios juntos: un
    # carácter CJK es casi cuadrado y no ocupa más que el ancho de la columna.
    largo_max = round(ajustes.largo_vertical * fila.shape[0]) if vertical else None
    resultado: list[Segmento] = []
    pendientes: list[Gris] = []
    for (a, b), es_raya in partir_rayas(fila, glifos(fila, ajustes, largo_max), ajustes):
        if not es_raya:
            # En vertical la fila está volteada por el [::-1]; se deshace antes de transponer.
            pendientes.append(tinta[:, a:b][::-1].T if vertical else tinta[:, a:b])
            continue
        if pendientes:
            resultado.append(recomponer(pendientes, alto, ajustes))
            pendientes = []
        if not resultado or not isinstance(resultado[-1], str):
            resultado.append(RAYA)
    if pendientes:
        resultado.append(recomponer(pendientes, alto, ajustes))
    return tuple(resultado)


def lineas(
    imagen: Imagen,
    color: ColorTexto,
    orientacion: Orientacion = Orientacion.HORIZONTAL,
    ajustes: AjustesPreprocesado | None = None,
) -> list[Linea]:
    """Líneas de texto en orden de lectura, partidas en segmentos listos para el reconocedor.

    Todas las filas se recomponen con el alto de la más alta: si no, una fila solo con signos
    bajos (？？) se amplía como si fueran caracteres completos y el reconocedor lee `77`.

    El texto vertical se transpone para buscar las columnas y los glifos igual que en horizontal,
    pero cada glifo se recorta de la columna sin transponer para no deformarlo. Las columnas se
    leen de derecha a izquierda y sus glifos se colocan en fila.
    """
    ajustes = ajustes or AjustesPreprocesado()
    mascara = color.laxa(imagen)
    tinta: Gris = np.where(dilatar(mascara), color.tinta(imagen), 0).astype(np.uint8)
    vertical = orientacion is Orientacion.VERTICAL
    if vertical:
        mascara, tinta = mascara.T[::-1], tinta.T[::-1]
    tramos_filas = filas(mascara, ajustes)
    if not tramos_filas:
        return []
    alto = max(fin - inicio for inicio, fin in tramos_filas)
    return [
        _segmentos(mascara[inicio:fin], tinta[inicio:fin], alto, vertical, ajustes)
        for inicio, fin in tramos_filas
    ]
