"""Lectura completa de la zona de texto: búsqueda del texto, reconocimiento y normalización."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from vn_audiolibro.captura.mascara import TEXTO_CLARO, ColorTexto
from vn_audiolibro.captura.modelos import Imagen
from vn_audiolibro.ocr.normalizacion import normalizar
from vn_audiolibro.ocr.preprocesado import AjustesPreprocesado, BusquedaTexto, Linea, Orientacion, lineas
from vn_audiolibro.ocr.reconocedor import Detector, Reconocedor, TextoDetectado


@dataclass(frozen=True)
class AjustesLector:
    """Lo que el lector necesita saber del juego (sale del perfil)."""

    idioma: str
    """Idioma de origen: `zh-Hant`, `zh-Hans`, `ja`…"""
    color: ColorTexto = TEXTO_CLARO
    orientacion: Orientacion = Orientacion.HORIZONTAL
    busqueda: BusquedaTexto = BusquedaTexto.COLOR
    preprocesado: AjustesPreprocesado = field(default_factory=AjustesPreprocesado)


@dataclass(frozen=True)
class TextoLeido:
    """Texto reconocido en la zona, línea a línea y en orden de lectura."""

    lineas: tuple[str, ...]

    @property
    def texto(self) -> str:
        """Las líneas unidas sin separador: en chino y japonés una frase sigue en la línea siguiente."""
        return "".join(self.lineas)


class LectorOCR:
    """Lee el texto de una imagen de la zona de texto.

    Con `BusquedaTexto.DETECTOR` hace falta un `detector`; el reconocedor solo se usa por color.
    """

    def __init__(
        self, reconocedor: Reconocedor, ajustes: AjustesLector, detector: Detector | None = None
    ) -> None:
        if ajustes.busqueda is BusquedaTexto.DETECTOR and detector is None:
            raise ValueError("La búsqueda con detector necesita un detector")
        self._reconocedor = reconocedor
        self._ajustes = ajustes
        self._detector = detector

    def leer(self, imagen: Imagen) -> TextoLeido:
        """Texto de la imagen, descartando las líneas en las que no se reconoce nada."""
        ajustes = self._ajustes
        textos = (normalizar(texto, ajustes.idioma) for texto in self._lineas(imagen))
        return TextoLeido(tuple(texto for texto in textos if texto))

    def _lineas(self, imagen: Imagen) -> Iterable[str]:
        ajustes = self._ajustes
        if self._detector is not None and ajustes.busqueda is BusquedaTexto.DETECTOR:
            return lineas_detectadas(self._detector.detectar(imagen), ajustes.orientacion)
        return (
            self._leer_linea(linea)
            for linea in lineas(imagen, ajustes.color, ajustes.orientacion, ajustes.preprocesado)
        )

    def _leer_linea(self, linea: Linea) -> str:
        return "".join(
            segmento if isinstance(segmento, str) else self._reconocedor.reconocer(segmento)
            for segmento in linea
        )


def lineas_detectadas(detectados: Iterable[TextoDetectado], orientacion: Orientacion) -> list[str]:
    """Une los trozos del detector en líneas, en orden de lectura.

    El detector puede partir una línea en varios trozos (si hay un hueco grande entre
    caracteres). Los trozos que se solapan en altura (en anchura si el texto es vertical) son de
    la misma línea y se leen de izquierda a derecha (de arriba abajo). Las líneas van de arriba
    abajo, o de derecha a izquierda las columnas verticales.
    """
    vertical = orientacion is Orientacion.VERTICAL

    def tramo(detectado: TextoDetectado) -> tuple[int, int]:
        caja = detectado.caja
        return (caja.x, caja.x + caja.ancho) if vertical else (caja.y, caja.y + caja.alto)

    grupos: list[tuple[tuple[int, int], list[TextoDetectado]]] = []
    for detectado in sorted(detectados, key=lambda d: sum(tramo(d)), reverse=vertical):
        inicio, fin = tramo(detectado)
        if grupos and _solapan(grupos[-1][0], (inicio, fin)):
            (a, b), trozos = grupos[-1]
            grupos[-1] = ((min(a, inicio), max(b, fin)), [*trozos, detectado])
        else:
            grupos.append(((inicio, fin), [detectado]))
    return [
        "".join(d.texto for d in sorted(trozos, key=lambda d: d.caja.y if vertical else d.caja.x))
        for _, trozos in grupos
    ]


def _solapan(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True si los tramos comparten al menos la mitad del más corto."""
    comun = min(a[1], b[1]) - max(a[0], b[0])
    return comun * 2 >= min(a[1] - a[0], b[1] - b[0])
