"""Precisión y velocidad del OCR completo con el modelo real sobre imágenes sintéticas.

Criterios de la issue: error por carácter < 5 % y < 200 ms por pantalla en CPU.
"""

import time

import pytest

from vn_audiolibro.captura.mascara import TEXTO_OSCURO
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR, TextoLeido
from vn_audiolibro.ocr.normalizacion import normalizar
from vn_audiolibro.ocr.preprocesado import Orientacion
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR

from .sinteticas import (
    FUENTES_LATINAS,
    Estilo,
    cara,
    error_por_caracter,
    horizontal,
    latina,
    texto_latino,
    vertical,
)

ERROR_MAX = 0.05
TIEMPO_MAX_S = 0.2

TEXTOS = {
    "zh-Hant": ["他看著窗外的雨，輕聲說道：", "「我們明天還會再見面嗎？」", "她沒有回答，只是笑了笑。"],
    "zh-Hans": ["他看着窗外的雨，轻声说道：", "「我们明天还会再见面吗？」", "她没有回答，只是笑了笑。"],
    "ja": ["先輩、今日も一緒に帰りませんか？", "「べつに、いいけど……」", "私は少しだけ嬉しくなった。"],
}
ESTILOS = {
    "espaciado ancho": Estilo(paso=1.8),
    "texto junto": Estilo(paso=1.05),
    "fondo de fuego en degradado": Estilo(fondo=(200, 60, 10), degradado=(90, 90, 110)),
    "letra pequeña": Estilo(tamano=22),
}


@pytest.mark.parametrize("idioma", TEXTOS)
@pytest.mark.parametrize("estilo", ESTILOS)
def test_texto_claro_horizontal(reconocedor: ReconocedorRapidOCR, idioma: str, estilo: str) -> None:
    lineas = TEXTOS[idioma]
    imagen = horizontal(lineas, cara(idioma, ESTILOS[estilo].tamano), ESTILOS[estilo])

    leido = LectorOCR(reconocedor, AjustesLector(idioma)).leer(imagen)

    assert len(leido.lineas) == len(lineas)
    assert error_por_caracter(leido.texto, "".join(lineas)) < ERROR_MAX, leido.texto


@pytest.mark.parametrize("idioma", TEXTOS)
def test_texto_oscuro_sobre_fondo_claro(reconocedor: ReconocedorRapidOCR, idioma: str) -> None:
    lineas = TEXTOS[idioma]
    imagen = horizontal(lineas, cara(idioma), Estilo(fondo=(235, 230, 220), color=(20, 20, 20)))

    leido = LectorOCR(reconocedor, AjustesLector(idioma, color=TEXTO_OSCURO)).leer(imagen)

    assert error_por_caracter(leido.texto, "".join(lineas)) < ERROR_MAX, leido.texto


@pytest.mark.parametrize("idioma", TEXTOS)
def test_texto_vertical(reconocedor: ReconocedorRapidOCR, idioma: str) -> None:
    lineas = TEXTOS[idioma]
    imagen = vertical(lineas, cara(idioma), Estilo(paso=1.3))

    leido = LectorOCR(reconocedor, AjustesLector(idioma, orientacion=Orientacion.VERTICAL)).leer(imagen)

    assert len(leido.lineas) == len(lineas)
    assert error_por_caracter(leido.texto, "".join(lineas)) < ERROR_MAX, leido.texto


def test_una_pantalla_tarda_menos_de_200_ms(reconocedor: ReconocedorRapidOCR) -> None:
    imagen = horizontal(TEXTOS["zh-Hant"], cara("zh-Hant"), Estilo())
    ocr = LectorOCR(reconocedor, AjustesLector("zh-Hant"))
    ocr.leer(imagen)  # la primera ejecución prepara onnxruntime

    tiempos = []
    for _ in range(5):
        inicio = time.perf_counter()
        ocr.leer(imagen)
        tiempos.append(time.perf_counter() - inicio)

    assert sorted(tiempos)[len(tiempos) // 2] < TIEMPO_MAX_S


def test_texto_leido_une_las_lineas_sin_separador() -> None:
    assert TextoLeido(("「你好，", "再見。」")).texto == "「你好，再見。」"
    assert TextoLeido(("I told you", "already."), " ").texto == "I told you already."


PANTALLA_VN = {
    # Nombre del personaje desconocido, rayas y puntos suspensivos espaciados, y 一 tras una raya.
    "zh-Hant": ["？？", "「櫻——————……！！」", "沒錯——她，一切都結束了。"],
    "ja": ["？？", "「桜……！！」", "そうだ——一緒に帰ろう。"],
}


@pytest.mark.parametrize("idioma", PANTALLA_VN)
@pytest.mark.parametrize("tamano", [16, 20])
def test_pantalla_de_vn_con_letra_pequena_y_signos(
    reconocedor: ReconocedorRapidOCR, idioma: str, tamano: int
) -> None:
    lineas = PANTALLA_VN[idioma]
    estilo = Estilo(tamano=tamano, paso=2.0, fondo=(120, 30, 10), degradado=(40, 10, 60))
    imagen = horizontal(lineas, cara(idioma, tamano), estilo)

    leido = LectorOCR(reconocedor, AjustesLector(idioma)).leer(imagen)

    assert leido.lineas[0] == "？？"
    esperado = normalizar("".join(lineas), idioma)  # la racha de rayas queda en ——
    assert error_por_caracter(leido.texto, esperado) < ERROR_MAX, leido.texto


# Inglés: fuentes latinas libres, con el texto y el espaciado de una VN en inglés

INGLES = [
    "I told you already, didn't I?",
    '"Well... it\'s a well-known secret."',
    "She smiled and said nothing.",
]


@pytest.mark.parametrize("fuente", FUENTES_LATINAS)
@pytest.mark.parametrize("tamano", [18, 24, 32])
def test_texto_en_ingles(reconocedor: ReconocedorRapidOCR, fuente: str, tamano: int) -> None:
    imagen = texto_latino(INGLES, latina(fuente, tamano))

    leido = LectorOCR(reconocedor, AjustesLector("en")).leer(imagen)

    assert leido.lineas[0].startswith("I told you already")  # con sus espacios
    assert error_por_caracter(leido.texto, " ".join(INGLES)) < ERROR_MAX, leido.texto
