"""Reconocimiento de líneas de texto ya preprocesadas, o búsqueda y reconocimiento a la vez."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from rapidocr import RapidOCR

from vn_audiolibro.captura.modelos import Imagen, Rectangulo


class Reconocedor(Protocol):
    """Convierte la imagen de una línea de texto en texto."""

    def reconocer(self, linea: Imagen) -> str:
        """Texto de la línea, o cadena vacía si no se reconoce nada."""
        ...


@dataclass(frozen=True)
class TextoDetectado:
    """Trozo de texto encontrado en la imagen, con el recuadro que ocupa."""

    texto: str
    caja: Rectangulo


class Detector(Protocol):
    """Busca el texto en una imagen entera y lo reconoce."""

    def detectar(self, imagen: Imagen) -> list[TextoDetectado]:
        """Trozos de texto de la imagen, en cualquier orden."""
        ...


class ReconocedorRapidOCR:
    """Reconocedor PP-OCRv5 de RapidOCR con onnxruntime en CPU.

    Sin `detector` solo se carga el reconocedor: la detección de líneas la hace el preprocesado.
    Con él, también sirve como `Detector` para el texto escrito sobre la imagen. El clasificador
    de orientación no hace falta con texto de juego.
    """

    def __init__(self, modelo: Path, detector: Path | None = None) -> None:
        params: dict[str, Any] = {
            "Global.use_det": detector is not None,
            "Global.use_cls": False,
            "Global.log_level": "warning",
            "Rec.model_path": str(modelo),
        }
        if detector is not None:
            params["Det.model_path"] = str(detector)
        self._motor = RapidOCR(params=params)
        self.con_detector = detector is not None

    def reconocer(self, linea: Imagen) -> str:
        resultado = self._motor(linea, use_det=False, use_cls=False, use_rec=True)
        textos = getattr(resultado, "txts", None) or ()
        return "".join(textos)

    def detectar(self, imagen: Imagen) -> list[TextoDetectado]:
        if not self.con_detector:
            raise RuntimeError("ReconocedorRapidOCR creado sin detector")
        resultado = self._motor(imagen, use_det=True, use_cls=False, use_rec=True)
        textos = getattr(resultado, "txts", None) or ()
        cajas = getattr(resultado, "boxes", None)
        if not textos or cajas is None:
            return []
        return [_detectado(texto, caja) for texto, caja in zip(textos, np.asarray(cajas), strict=True)]


def _detectado(texto: str, puntos: Any) -> TextoDetectado:
    """El cuadrilátero que devuelve el detector, como rectángulo que lo contiene."""
    (x0, y0), (x1, y1) = np.floor(puntos.min(axis=0)), np.ceil(puntos.max(axis=0))
    return TextoDetectado(texto, Rectangulo(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0))))
