"""Reconocimiento de líneas de texto ya preprocesadas."""

from pathlib import Path
from typing import Protocol

from rapidocr import RapidOCR

from vn_audiolibro.captura.modelos import Imagen


class Reconocedor(Protocol):
    """Convierte la imagen de una línea de texto en texto."""

    def reconocer(self, linea: Imagen) -> str:
        """Texto de la línea, o cadena vacía si no se reconoce nada."""
        ...


class ReconocedorRapidOCR:
    """Reconocedor PP-OCRv5 de RapidOCR con onnxruntime en CPU.

    Solo se carga el reconocedor: la detección de líneas la hace el preprocesado y el
    clasificador de orientación no hace falta con texto de juego.
    """

    def __init__(self, modelo: Path) -> None:
        self._motor = RapidOCR(
            params={
                "Global.use_det": False,
                "Global.use_cls": False,
                "Global.log_level": "warning",
                "Rec.model_path": str(modelo),
            }
        )

    def reconocer(self, linea: Imagen) -> str:
        resultado = self._motor(linea, use_det=False, use_cls=False, use_rec=True)
        textos = getattr(resultado, "txts", None) or ()
        return "".join(textos)
