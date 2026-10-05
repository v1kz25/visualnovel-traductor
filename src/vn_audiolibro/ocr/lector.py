"""Lectura completa de la zona de texto: búsqueda del texto, reconocimiento y normalización."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from vn_audiolibro.captura.mascara import TEXTO_CLARO, ColorTexto
from vn_audiolibro.captura.modelos import Imagen, Rectangulo
from vn_audiolibro.ocr.menu import Fila, alargada, opciones_menu
from vn_audiolibro.ocr.normalizacion import normalizar, separa_palabras
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
    separador: str = ""
    """Lo que va entre línea y línea: nada en chino y japonés, un espacio en inglés."""
    menu: bool = False
    """True si las líneas son las opciones de un menú: cada una va aparte."""

    @property
    def texto(self) -> str:
        """Las líneas unidas: una frase puede seguir en la línea siguiente. Las opciones, una por línea."""
        return ("\n" if self.menu else self.separador).join(self.lineas)


class LectorOCR:
    """Lee el texto de una imagen de la zona de texto.

    Con `BusquedaTexto.DETECTOR` hace falta un `detector`; el reconocedor solo se usa por color.
    Con el detector y texto horizontal, además, se reconocen los menús de opciones.
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
        separador = _separador(ajustes.idioma)
        if self._detector is not None and ajustes.busqueda is BusquedaTexto.DETECTOR:
            return self._leer_detectados(self._detector.detectar(imagen), imagen.shape[1])
        por_glifos = not separa_palabras(ajustes.idioma)
        filas = lineas(imagen, ajustes.color, ajustes.orientacion, ajustes.preprocesado, por_glifos)
        return TextoLeido(self._normalizar(self._leer_linea(fila) for fila in filas), separador)

    def _leer_detectados(self, detectados: list[TextoDetectado], ancho: int) -> TextoLeido:
        ajustes = self._ajustes
        separador = _separador(ajustes.idioma)
        if ajustes.orientacion is Orientacion.HORIZONTAL:
            horizontales = [detectado for detectado in detectados if not alargada(detectado.caja)]
            opciones = opciones_menu(filas_detectadas(horizontales, ajustes.orientacion, separador), ancho)
            if len(normalizadas := self._normalizar(opciones or ())) >= 2:
                return TextoLeido(normalizadas, separador, menu=True)
        return TextoLeido(
            self._normalizar(lineas_detectadas(detectados, ajustes.orientacion, separador)), separador
        )

    def _normalizar(self, textos: Iterable[str]) -> tuple[str, ...]:
        normalizados = (normalizar(texto, self._ajustes.idioma) for texto in textos)
        return tuple(texto for texto in normalizados if texto)

    def _leer_linea(self, linea: Linea) -> str:
        return "".join(
            segmento if isinstance(segmento, str) else self._reconocedor.reconocer(segmento)
            for segmento in linea
        )


def _separador(idioma: str) -> str:
    return " " if separa_palabras(idioma) else ""


def lineas_detectadas(
    detectados: Iterable[TextoDetectado], orientacion: Orientacion, separador: str = ""
) -> list[str]:
    """Une los trozos del detector en líneas, en orden de lectura (ver `filas_detectadas`)."""
    return [fila.texto for fila in filas_detectadas(detectados, orientacion, separador)]


def filas_detectadas(
    detectados: Iterable[TextoDetectado], orientacion: Orientacion, separador: str = ""
) -> list[Fila]:
    """Une los trozos del detector en filas, en orden de lectura, con el recuadro de cada una.

    El detector puede partir una línea en varios trozos (si hay un hueco grande entre
    caracteres). Los trozos que se solapan en altura (en anchura si el texto es vertical) son de
    la misma línea y se leen de izquierda a derecha (de arriba abajo). Las líneas van de arriba
    abajo, o de derecha a izquierda las columnas verticales. Los trozos de una línea se unen con
    `separador` (un espacio en inglés).
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
        Fila(
            separador.join(d.texto for d in sorted(trozos, key=lambda d: d.caja.y if vertical else d.caja.x)),
            _union(d.caja for d in trozos),
        )
        for _, trozos in grupos
    ]


def _union(cajas: Iterable[Rectangulo]) -> Rectangulo:
    """El menor rectángulo que contiene todas las cajas."""
    lista = list(cajas)
    x, y = min(c.x for c in lista), min(c.y for c in lista)
    derecha, abajo = max(c.x + c.ancho for c in lista), max(c.y + c.alto for c in lista)
    return Rectangulo(x, y, derecha - x, abajo - y)


def _solapan(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True si los tramos comparten al menos la mitad del más corto."""
    comun = min(a[1], b[1]) - max(a[0], b[0])
    return comun * 2 >= min(a[1] - a[0], b[1] - b[0])
