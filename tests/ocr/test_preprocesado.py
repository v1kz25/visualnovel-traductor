"""Tests del preprocesado con máscaras sintéticas: bloques que simulan caracteres."""

import numpy as np

from vn_audiolibro.captura.mascara import TEXTO_CLARO, TEXTO_OSCURO
from vn_audiolibro.captura.modelos import Imagen
from vn_audiolibro.ocr.preprocesado import (
    RAYA,
    AjustesPreprocesado,
    Orientacion,
    filas,
    glifos,
    lineas,
    partir_rayas,
    tramos,
)

AJUSTES = AjustesPreprocesado()
SIN_AMPLIAR = AjustesPreprocesado(ampliar_hasta_px=1)


def test_tramos_une_huecos_pequenos() -> None:
    perfil = np.array([0, 1, 1, 0, 1, 0, 0, 0, 1, 1, 0])

    assert tramos(perfil) == [(1, 3), (4, 5), (8, 10)]
    assert tramos(perfil, hueco_max=1) == [(1, 5), (8, 10)]
    assert tramos(perfil, hueco_max=1, largo_max=3) == [(1, 3), (4, 5), (8, 10)]
    assert tramos(np.zeros(5, dtype=np.int64)) == []


def test_filas_descarta_ruido_y_restos_de_la_fila_anterior() -> None:
    mascara = np.zeros((120, 200), dtype=np.bool_)
    mascara[0:5, 10:100] = True  # parte inferior de la fila anterior, cortada
    mascara[20:50, 10:100] = True
    mascara[60:62, 10:30] = True  # ruido
    mascara[80:110, 10:60] = True

    assert filas(mascara, AJUSTES) == [(20, 50), (80, 110)]


def test_filas_no_separa_el_punto_de_una_interrogacion() -> None:
    mascara = np.zeros((60, 100), dtype=np.bool_)
    mascara[10:24, 10:20] = True  # trazo de ？
    mascara[28:30, 14:16] = True  # su punto, 4 px más abajo
    mascara[40:58, 10:30] = True

    assert filas(mascara, AJUSTES)[0] == (10, 30)


def test_glifos_une_los_trozos_de_un_caracter_pero_no_caracteres_separados() -> None:
    fila = np.zeros((30, 200), dtype=np.bool_)
    fila[:, 0:10] = True
    fila[:, 15:25] = True  # mismo carácter: hueco de 5 px < 0,45 × 30
    fila[:, 60:85] = True  # otro carácter: hueco de 35 px

    assert glifos(fila, AJUSTES) == [(0, 25), (60, 85)]


def fila_con_signos() -> np.ndarray:
    """Fila de 20 px: carácter, raya pegada a 」, 一, carácter y puntos suspensivos."""
    fila = np.zeros((20, 300), dtype=np.bool_)
    fila[2:18, 0:16] = True  # carácter
    fila[9:11, 30:54] = True  # raya
    fila[9:11, 60:84] = True  # raya
    fila[2:18, 88:92] = True  # 」 pegado a la raya
    fila[9:11, 120:134] = True  # 一: más estrecho que un carácter
    fila[2:18, 150:166] = True  # carácter
    for x in range(190, 230, 6):
        fila[15:17, x : x + 2] = True  # puntos suspensivos
    return fila


def test_partir_rayas_separa_las_rayas_aunque_lleven_un_signo_pegado() -> None:
    fila = fila_con_signos()

    marcadas = partir_rayas(fila, glifos(fila, AJUSTES), AJUSTES)

    assert [tramo for tramo, es_raya in marcadas if es_raya] == [(30, 54), (60, 84)]
    assert ((88, 92), False) in marcadas


def test_partir_rayas_no_confunde_el_uno_ni_los_puntos_suspensivos() -> None:
    fila = fila_con_signos()

    marcadas = dict(partir_rayas(fila, glifos(fila, AJUSTES), AJUSTES))

    assert not marcadas[(120, 134)]
    assert not any(es_raya for (inicio, _), es_raya in marcadas.items() if inicio >= 190)


def test_las_rayas_seguidas_salen_como_una_sola_raya_de_texto() -> None:
    imagen = np.zeros((20, 300, 3), dtype=np.uint8)
    imagen[fila_con_signos()] = 255

    (linea,) = lineas(imagen, TEXTO_CLARO)

    assert [s for s in linea if isinstance(s, str)] == [RAYA]
    assert isinstance(linea[0], np.ndarray)
    assert linea[1] == RAYA


def pantalla(fondo: int, texto: int) -> Imagen:
    imagen = np.full((100, 300, 3), fondo, dtype=np.uint8)
    for x in (10, 70, 130):
        imagen[20:50, x : x + 30] = texto
    imagen[60:90, 10:40] = texto
    return imagen


def test_recompone_cada_fila_en_negro_sobre_blanco_y_sin_espaciado() -> None:
    resultado = lineas(pantalla(fondo=30, texto=255), TEXTO_CLARO, ajustes=SIN_AMPLIAR)

    assert len(resultado) == 2
    (primera,) = resultado[0]
    assert isinstance(primera, np.ndarray)
    margen, separacion = round(0.25 * 30), round(0.15 * 30)
    assert primera.shape == (30 + 2 * margen, 3 * 30 + 2 * separacion + 2 * margen, 3)
    assert primera[0, 0].tolist() == [255, 255, 255]
    assert primera[margen, margen].tolist() == [0, 0, 0]


def test_sin_partir_en_glifos_la_fila_conserva_su_espaciado() -> None:
    """Los idiomas con espacios: la fila va entera para no perder los espacios entre palabras."""
    resultado = lineas(pantalla(fondo=30, texto=255), TEXTO_CLARO, ajustes=SIN_AMPLIAR, por_glifos=False)

    assert len(resultado) == 2
    (primera,) = resultado[0]
    assert isinstance(primera, np.ndarray)
    margen = round(0.25 * 30)
    assert primera.shape == (30 + 2 * margen, 150 + 2 * margen, 3)  # de x=10 a x=160, huecos incluidos
    assert primera[margen + 5, margen + 45].tolist() == [255, 255, 255]  # el hueco entre glifos


def test_amplia_la_letra_pequena() -> None:
    (normal,), _ = lineas(pantalla(fondo=30, texto=255), TEXTO_CLARO, ajustes=SIN_AMPLIAR)
    (ampliada,), _ = lineas(pantalla(fondo=30, texto=255), TEXTO_CLARO, ajustes=AJUSTES)

    assert isinstance(normal, np.ndarray)
    assert isinstance(ampliada, np.ndarray)
    assert ampliada.shape[:2] == (normal.shape[0] * 2, normal.shape[1] * 2)


def test_todas_las_filas_tienen_el_alto_de_la_mas_alta() -> None:
    imagen = np.zeros((100, 200, 3), dtype=np.uint8)
    imagen[10:30, 10:20] = 255  # fila baja, como ？？
    imagen[50:80, 10:40] = 255

    (baja,), (alta,) = lineas(imagen, TEXTO_CLARO, ajustes=SIN_AMPLIAR)

    assert isinstance(baja, np.ndarray)
    assert isinstance(alta, np.ndarray)
    assert baja.shape[0] == alta.shape[0]


def test_conserva_el_borde_suavizado_en_gris() -> None:
    imagen = pantalla(fondo=0, texto=255)
    imagen[20:50, 25] = 120  # píxel suavizado: fuera de la máscara laxa, pero junto al texto

    (primera,), _ = lineas(imagen, TEXTO_CLARO, ajustes=SIN_AMPLIAR)

    assert isinstance(primera, np.ndarray)
    margen = round(0.25 * 30)
    assert primera[margen, margen + 15].tolist() == [255 - 120] * 3


def test_texto_oscuro_sobre_fondo_claro() -> None:
    resultado = lineas(pantalla(fondo=230, texto=0), TEXTO_OSCURO)

    assert len(resultado) == 2


def test_sin_texto_no_devuelve_lineas() -> None:
    assert lineas(np.zeros((50, 50, 3), dtype=np.uint8), TEXTO_CLARO) == []


def test_texto_vertical_se_lee_por_columnas_de_derecha_a_izquierda() -> None:
    imagen = np.zeros((200, 100, 3), dtype=np.uint8)
    # Columna derecha: tres glifos; el primero, más ancho que alto, para ver que no se transpone.
    imagen[10:30, 60:90] = 255
    imagen[70:100, 60:90] = 255
    imagen[130:160, 60:90] = 255
    # Columna izquierda: un glifo.
    imagen[10:40, 10:40] = 255

    (derecha,), (izquierda,) = lineas(imagen, TEXTO_CLARO, Orientacion.VERTICAL, SIN_AMPLIAR)

    assert isinstance(derecha, np.ndarray)
    assert isinstance(izquierda, np.ndarray)
    margen = round(0.25 * 30)
    assert derecha.shape[0] == 30 + 2 * margen
    negro = derecha[:, :, 0] == 0
    columnas = np.flatnonzero(negro.any(axis=0))
    assert columnas[0] == margen
    # El primer glifo (30 de ancho y 20 de alto) conserva su forma, centrado en vertical.
    assert negro[:, margen].sum() == 20
    assert izquierda.shape[1] == 30 + 2 * margen
