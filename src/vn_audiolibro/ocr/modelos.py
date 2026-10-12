"""Modelos de OCR que se descargan: el reconocedor en el primer arranque y el detector al usarlo."""

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

DET_PPOCRV5_MOBILE = Descarga(
    fichero="ch_PP-OCRv5_det_mobile.onnx",
    url=(
        "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/"
        "onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx"
    ),
    sha256="4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
)
"""Detector PP-OCRv5 mobile: busca las líneas de texto en la imagen.

Solo hace falta en los juegos que escriben el texto sobre la imagen, así que se descarga la
primera vez que se usa y no en el primer arranque.
"""
