"""Herramienta de depuración: lee el texto de imágenes de la zona de texto.

Uso:
    uv run python -m vn_audiolibro.ocr --idioma zh-Hant /tmp/zonas/*.png

Sirve con las zonas que guarda `python -m vn_audiolibro.captura --salida`. La primera vez
descarga el modelo de OCR (y el del detector, si se pide).
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from vn_audiolibro.captura.mascara import TEXTO_CLARO, TEXTO_OSCURO
from vn_audiolibro.descargas import DescargaFallidaError, asegurar_descarga
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR
from vn_audiolibro.ocr.modelos import DET_PPOCRV5_MOBILE, REC_PPOCRV5_MOBILE
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la herramienta."""
    parser = argparse.ArgumentParser(prog="python -m vn_audiolibro.ocr", description=__doc__.splitlines()[0])
    parser.add_argument("imagenes", nargs="+", type=Path, help="imágenes PNG de la zona de texto")
    parser.add_argument("--idioma", default="zh-Hant", help="idioma de origen (zh-Hant, zh-Hans, ja)")
    parser.add_argument("--oscuro", action="store_true", help="el texto es oscuro sobre fondo claro")
    parser.add_argument("--vertical", action="store_true", help="el texto va en columnas verticales")
    parser.add_argument("--detector", action="store_true", help="buscar el texto con el detector")
    args = parser.parse_args(argv)

    try:
        modelo = asegurar_descarga(REC_PPOCRV5_MOBILE)
        detector = asegurar_descarga(DET_PPOCRV5_MOBILE) if args.detector else None
    except DescargaFallidaError as error:
        print(error, file=sys.stderr)
        return 1
    ajustes = AjustesLector(
        idioma=args.idioma,
        color=TEXTO_OSCURO if args.oscuro else TEXTO_CLARO,
        orientacion=Orientacion.VERTICAL if args.vertical else Orientacion.HORIZONTAL,
        busqueda=BusquedaTexto.DETECTOR if args.detector else BusquedaTexto.COLOR,
    )
    reconocedor = ReconocedorRapidOCR(modelo, detector)
    lector = LectorOCR(reconocedor, ajustes, reconocedor if detector else None)
    for ruta in args.imagenes:
        imagen = np.asarray(Image.open(ruta).convert("RGB"))
        inicio = time.perf_counter()
        leido = lector.leer(imagen)
        milisegundos = (time.perf_counter() - inicio) * 1000
        print(f"{ruta.name} ({milisegundos:.0f} ms)")
        for linea in leido.lineas:
            print(f"  {linea}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
