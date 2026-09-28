"""Modelo de OCR que se descarga en el primer arranque."""

from vn_audiolibro.descargas import Descarga

REC_PPOCRV5_MOBILE = Descarga(
    fichero="ch_PP-OCRv5_rec_mobile.onnx",
    url=(
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/"
        "onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx"
    ),
    sha256="5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5",
)
"""Reconocedor PP-OCRv5 mobile: chino tradicional, simplificado y japonés en un solo modelo.

Lleva el diccionario de caracteres dentro del ONNX, así que no hace falta otro fichero.
"""
