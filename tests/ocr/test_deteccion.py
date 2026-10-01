"""Búsqueda del texto con el detector, para el texto escrito sobre la imagen sin caja de texto."""

import unicodedata

import numpy as np
import pytest

from vn_audiolibro.captura.modelos import Imagen, Rectangulo
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR, lineas_detectadas
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR, TextoDetectado

from .sinteticas import cara, error_por_caracter, sobre_imagen

ERROR_MAX = 0.05
DETECTOR = BusquedaTexto.DETECTOR


def trozo(texto: str, x: int, y: int, ancho: int = 100, alto: int = 30) -> TextoDetectado:
    return TextoDetectado(texto, Rectangulo(x, y, ancho, alto))


class DetectorFalso:
    def __init__(self, trozos: list[TextoDetectado]) -> None:
        self.trozos = trozos

    def detectar(self, imagen: Imagen) -> list[TextoDetectado]:
        return self.trozos


class SinReconocedor:
    def reconocer(self, linea: Imagen) -> str:
        raise AssertionError("con el detector no se reconocen líneas sueltas")


IMAGEN = np.zeros((10, 10, 3), dtype=np.uint8)


def test_une_los_trozos_de_cada_fila_de_izquierda_a_derecha() -> None:
    trozos = [
        trozo("くなった。", 260, 142, 150, 28),
        trozo("私は少しだけ嬉し", 20, 140, 230),
        trozo("先輩、今日も", 20, 20),
        trozo("「べつに」", 22, 80),
    ]
    assert lineas_detectadas(trozos, Orientacion.HORIZONTAL) == [
        "先輩、今日も",
        "「べつに」",
        "私は少しだけ嬉しくなった。",
    ]


def test_las_columnas_verticales_van_de_derecha_a_izquierda() -> None:
    trozos = [
        trozo("一緒に", 100, 150, 30, 90),
        trozo("帰ろう", 40, 10, 30, 200),
        trozo("先輩、", 102, 10, 28, 100),
    ]
    assert lineas_detectadas(trozos, Orientacion.VERTICAL) == ["先輩、一緒に", "帰ろう"]


def test_sin_texto_no_hay_lineas() -> None:
    assert lineas_detectadas([], Orientacion.HORIZONTAL) == []


def test_lee_con_el_detector_y_normaliza() -> None:
    detector = DetectorFalso([trozo("あ ……", 0, 40), trozo("「先輩...", 0, 0), trozo("   ", 0, 80)])
    lector = LectorOCR(SinReconocedor(), AjustesLector("ja", busqueda=DETECTOR), detector)

    assert lector.leer(IMAGEN).lineas == ("「先輩……", "あ……")


def test_la_busqueda_con_detector_necesita_el_detector() -> None:
    with pytest.raises(ValueError, match="detector"):
        LectorOCR(SinReconocedor(), AjustesLector("ja", busqueda=DETECTOR))


def test_reconocedor_sin_detector_no_detecta(modelo: object) -> None:
    with pytest.raises(RuntimeError, match="sin detector"):
        ReconocedorRapidOCR(modelo).detectar(IMAGEN)  # type: ignore[arg-type]


# Con los modelos reales
#
# El detector lee bien los caracteres pero pierde o confunde parte de la puntuación (、, ……, 「
# por 『), con cualquier ajuste suyo. Se mide aparte: la búsqueda en el guion la tolera.

TEXTOS = {
    "ja": ["先輩、今日も一緒に帰りませんか？", "「べつに、いいけど……」", "私は少しだけ嬉しくなった。"],
    "zh-Hant": ["他看著窗外的雨，輕聲說道：", "「我們明天還會再見面嗎？」"],
}
PUNTUACION_MAX = 0.2


def sin_puntuacion(texto: str) -> str:
    return "".join(c for c in texto if not unicodedata.category(c).startswith("P"))


def test_texto_sobre_la_imagen_por_color_no_se_lee(reconocedor: ReconocedorRapidOCR) -> None:
    """El caso de la issue: las nubes rompen la búsqueda por color."""
    imagen = sobre_imagen(TEXTOS["ja"], cara("ja", 30))

    leido = LectorOCR(reconocedor, AjustesLector("ja")).leer(imagen)

    assert error_por_caracter(leido.texto, "".join(TEXTOS["ja"])) > 0.5, leido.texto


@pytest.mark.parametrize(("idioma", "tamano"), [("ja", 30), ("zh-Hant", 40)])
def test_texto_sobre_la_imagen_con_el_detector(
    con_detector: ReconocedorRapidOCR, idioma: str, tamano: int
) -> None:
    lineas = TEXTOS[idioma]
    imagen = sobre_imagen(lineas, cara(idioma, tamano), tamano)

    leido = LectorOCR(con_detector, AjustesLector(idioma, busqueda=DETECTOR), con_detector).leer(imagen)

    assert len(leido.lineas) == len(lineas)
    esperado = "".join(lineas)
    assert error_por_caracter(sin_puntuacion(leido.texto), sin_puntuacion(esperado)) < ERROR_MAX, leido.texto
    assert error_por_caracter(leido.texto, esperado) < PUNTUACION_MAX, leido.texto
