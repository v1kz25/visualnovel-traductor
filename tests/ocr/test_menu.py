"""Menús de opciones: se separa cada opción y se descarta el texto del fondo."""

import numpy as np
import pytest

from vn_audiolibro.captura.modelos import Imagen, Rectangulo
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR
from vn_audiolibro.ocr.menu import Fila, opciones_menu
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR, TextoDetectado

from .sinteticas import cara, menu

ANCHO = 1280
DETECTOR = BusquedaTexto.DETECTOR


def fila(texto: str, x: int, y: int, ancho: int, alto: int = 40) -> Fila:
    return Fila(texto, Rectangulo(x, y, ancho, alto))


def centrada(texto: str, y: int, ancho: int, centro: int = 640) -> Fila:
    return fila(texto, centro - ancho // 2, y, ancho)


class DetectorFalso:
    def __init__(self, trozos: list[TextoDetectado]) -> None:
        self.trozos = trozos

    def detectar(self, imagen: Imagen) -> list[TextoDetectado]:
        return self.trozos


class SinReconocedor:
    def reconocer(self, linea: Imagen) -> str:
        raise AssertionError("con el detector no se reconocen líneas sueltas")


IMAGEN = np.zeros((870, ANCHO, 3), dtype=np.uint8)


def test_dos_opciones_y_texto_del_fondo() -> None:
    """El caso de la issue: dos botones centrados y un cartel en el borde."""
    filas = [
        fila("ボスタースクー", 0, 467, 66, 38),
        centrada("返事を返す", 440, 170),
        centrada("返事をしない", 220, 206),
    ]
    assert opciones_menu(filas, ANCHO) == ["返事をしない", "返事を返す"]


def test_tres_opciones_aunque_no_esten_en_el_centro_de_la_zona() -> None:
    filas = [
        centrada("学校へ行く", 100, 200, 400),
        centrada("家に帰る", 250, 160, 400),
        centrada("寝る", 400, 80, 400),
    ]
    assert opciones_menu(filas, ANCHO) == ["学校へ行く", "家に帰る", "寝る"]


def test_se_queda_con_el_menu_mas_largo_y_descarta_el_dialogo_de_debajo() -> None:
    filas = [
        centrada("はい", 100, 80),
        centrada("いいえ", 200, 120),
        centrada("わからない", 300, 200),
        fila("「どうするの？」と彼女は聞いた。", 100, 700, 640),
    ]
    assert opciones_menu(filas, ANCHO) == ["はい", "いいえ", "わからない"]


def test_las_lineas_de_un_dialogo_no_son_un_menu() -> None:
    """Las líneas de un diálogo van muy juntas, aunque sean cortas y estén centradas."""
    filas = [centrada("先輩、今日も", 600, 240), centrada("一緒に帰る？", 660, 240)]
    assert opciones_menu(filas, ANCHO) is None


def test_los_parrafos_alineados_a_la_izquierda_no_son_un_menu() -> None:
    """Texto NVL: párrafos cortos separados por una línea en blanco, alineados a la izquierda."""
    filas = [fila("「うん」", 100, 100, 160), fila("「そうだね」", 100, 200, 160)]
    assert opciones_menu(filas, ANCHO) is None


def test_opciones_igual_de_largas_en_el_centro_de_la_zona() -> None:
    filas = [centrada("右へ行く", 200, 160), centrada("左へ行く", 400, 160)]
    assert opciones_menu(filas, ANCHO) == ["右へ行く", "左へ行く"]


@pytest.mark.parametrize(
    "filas",
    [
        [
            centrada("とても長い一行の文章がここにある" * 2, 100, 900),
            centrada("短い", 300, 80),
        ],  # demasiado ancha
        [centrada("——", 100, 120), centrada("はい", 300, 80)],  # sin letras
        [centrada("はい", 100, 80), fila("いいえ", 640 - 60, 300, 120, 20)],  # alturas distintas
        [centrada("はい", 100, 80)],  # una sola
        [],
    ],
)
def test_no_es_un_menu(filas: list[Fila]) -> None:
    assert opciones_menu(filas, ANCHO) is None


def detectado(texto: str, x: int, y: int, ancho: int, alto: int = 40) -> TextoDetectado:
    return TextoDetectado(texto, Rectangulo(x, y, ancho, alto))


def test_el_lector_separa_las_opciones_sin_el_cartel_vertical() -> None:
    """Un cartel vertical que se solapa en altura con una opción no se une a su fila."""
    detector = DetectorFalso(
        [
            detectado("返事をしない", 537, 220, 206),
            detectado("ポスター", 20, 380, 40, 200),
            detectado("返事を返す", 555, 440, 170),
        ]
    )
    leido = LectorOCR(SinReconocedor(), AjustesLector("ja", busqueda=DETECTOR), detector).leer(IMAGEN)

    assert leido.menu
    assert leido.lineas == ("返事をしない", "返事を返す")
    assert leido.texto == "返事をしない\n返事を返す"


def test_sin_menu_el_lector_une_las_lineas_como_siempre() -> None:
    detector = DetectorFalso([detectado("先輩、", 100, 600, 120), detectado("帰ろう。", 100, 660, 160)])
    leido = LectorOCR(SinReconocedor(), AjustesLector("ja", busqueda=DETECTOR), detector).leer(IMAGEN)

    assert not leido.menu
    assert leido.texto == "先輩、帰ろう。"


def test_en_vertical_no_se_buscan_menus() -> None:
    detector = DetectorFalso([detectado("はい", 600, 100, 80), detectado("いいえ", 580, 300, 120)])
    ajustes = AjustesLector("ja", orientacion=Orientacion.VERTICAL, busqueda=DETECTOR)
    leido = LectorOCR(SinReconocedor(), ajustes, detector).leer(IMAGEN)

    assert not leido.menu


# Con los modelos reales


@pytest.mark.parametrize(
    "opciones",
    [["返事をしない", "返事を返す"], ["学校へ行く", "家に帰る", "先輩に電話する"]],
)
def test_menu_sintetico_con_el_detector(con_detector: ReconocedorRapidOCR, opciones: list[str]) -> None:
    imagen = menu(opciones, cara("ja", 30), cartel="ポスタースクール", rotulo="掲示板")

    leido = LectorOCR(con_detector, AjustesLector("ja", busqueda=DETECTOR), con_detector).leer(imagen)

    assert leido.menu, leido
    assert list(leido.lineas) == opciones
