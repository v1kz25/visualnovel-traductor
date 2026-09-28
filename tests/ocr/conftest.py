"""Recursos compartidos de los tests de OCR: la fuente CJK y el modelo real.

En local se saltan los tests si faltan; en la CI (`CI=true`) su ausencia es un fallo.
"""

from pathlib import Path

import pytest

from vn_audiolibro.descargas import DescargaFallidaError, asegurar_descarga
from vn_audiolibro.ocr.modelos import REC_PPOCRV5_MOBILE
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR

from .sinteticas import falta


@pytest.fixture(scope="session")
def modelo() -> Path:
    try:
        return asegurar_descarga(REC_PPOCRV5_MOBILE)
    except DescargaFallidaError as error:
        falta(f"modelo de OCR no disponible: {error}")


@pytest.fixture(scope="session")
def reconocedor(modelo: Path) -> ReconocedorRapidOCR:
    return ReconocedorRapidOCR(modelo)
