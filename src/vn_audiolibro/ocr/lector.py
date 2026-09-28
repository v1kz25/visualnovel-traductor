"""Lectura completa de la zona de texto: preprocesado, reconocimiento y normalización."""

from dataclasses import dataclass, field

from vn_audiolibro.captura.mascara import TEXTO_CLARO, ColorTexto
from vn_audiolibro.captura.modelos import Imagen
from vn_audiolibro.ocr.normalizacion import normalizar
from vn_audiolibro.ocr.preprocesado import AjustesPreprocesado, Linea, Orientacion, lineas
from vn_audiolibro.ocr.reconocedor import Reconocedor


@dataclass(frozen=True)
class AjustesLector:
    """Lo que el lector necesita saber del juego (sale del perfil)."""

    idioma: str
    """Idioma de origen: `zh-Hant`, `zh-Hans`, `ja`…"""
    color: ColorTexto = TEXTO_CLARO
    orientacion: Orientacion = Orientacion.HORIZONTAL
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
    """Lee el texto de una imagen de la zona de texto."""

    def __init__(self, reconocedor: Reconocedor, ajustes: AjustesLector) -> None:
        self._reconocedor = reconocedor
        self._ajustes = ajustes

    def leer(self, imagen: Imagen) -> TextoLeido:
        """Texto de la imagen, descartando las líneas en las que no se reconoce nada."""
        ajustes = self._ajustes
        textos = (
            normalizar(self._leer_linea(linea), ajustes.idioma)
            for linea in lineas(imagen, ajustes.color, ajustes.orientacion, ajustes.preprocesado)
        )
        return TextoLeido(tuple(texto for texto in textos if texto))

    def _leer_linea(self, linea: Linea) -> str:
        return "".join(
            segmento if isinstance(segmento, str) else self._reconocedor.reconocer(segmento)
            for segmento in linea
        )
