"""Tests del detector con imágenes sintéticas: bloques blancos que simulan caracteres."""

import numpy as np
import pytest

from vn_audiolibro.captura.detector import AjustesDetector, DetectorTexto
from vn_audiolibro.captura.mascara import TEXTO_OSCURO
from vn_audiolibro.captura.modelos import Imagen

ALTO, ANCHO = 200, 400
ALTO_FILA, PASO_FILA = 20, 40
ANCHO_CAR, PASO_CAR = 16, 30


def fondo(color: tuple[int, int, int] = (200, 80, 20)) -> Imagen:
    """Fondo naranja saturado, como un fondo de fuego."""
    return np.full((ALTO, ANCHO, 3), color, dtype=np.uint8)


def escribir(imagen: Imagen, fila: int, caracteres: int, color: int = 255) -> Imagen:
    """Dibuja `caracteres` bloques de texto en la fila indicada."""
    resultado = imagen.copy()
    y = 10 + fila * PASO_FILA
    for i in range(caracteres):
        x = 10 + i * PASO_CAR
        resultado[y : y + ALTO_FILA, x : x + ANCHO_CAR] = color
    return resultado


def pantalla(*caracteres_por_fila: int) -> Imagen:
    imagen = fondo()
    for fila, caracteres in enumerate(caracteres_por_fila):
        imagen = escribir(imagen, fila, caracteres)
    return imagen


def alimentar(
    detector: DetectorTexto, fotogramas: list[Imagen], inicio: float = 0.0, paso: float = 0.1
) -> list:
    eventos = []
    for i, fotograma in enumerate(fotogramas):
        evento = detector.procesar(fotograma, inicio + i * paso)
        if evento is not None:
            eventos.append(evento)
    return eventos


def test_efecto_maquina_de_escribir_produce_un_solo_evento() -> None:
    detector = DetectorTexto()
    escribiendo = [pantalla(n) for n in range(1, 11)]  # un carácter más en cada captura
    quieto = [pantalla(10)] * 5

    eventos = alimentar(detector, [fondo(), *escribiendo, *quieto])

    assert len(eventos) == 1
    assert eventos[0].completa
    assert eventos[0].y_inicio == 0


def test_no_emite_antes_de_estabilizarse() -> None:
    detector = DetectorTexto(AjustesDetector(estabilidad_s=1.0))

    eventos = alimentar(detector, [fondo(), pantalla(5), pantalla(5), pantalla(5)])

    assert eventos == []


def test_no_repite_el_mismo_texto() -> None:
    detector = DetectorTexto()

    eventos = alimentar(detector, [fondo(), *[pantalla(8)] * 20])

    assert len(eventos) == 1


def test_nvl_emite_solo_las_filas_nuevas() -> None:
    detector = DetectorTexto()
    primera = [fondo(), *[pantalla(8)] * 5]
    segunda = [*[pantalla(8, 6)] * 5]

    eventos = alimentar(detector, [*primera, *segunda])

    assert len(eventos) == 2
    nueva = eventos[1]
    assert not nueva.completa
    assert nueva.y_inicio == 10 + PASO_FILA - AjustesDetector().margen_filas
    assert nueva.imagen.shape[0] == ALTO - nueva.y_inicio


def test_pantalla_nueva_tras_limpiar_es_completa() -> None:
    detector = DetectorTexto()
    fotogramas = [fondo(), *[pantalla(8, 8)] * 5, *[pantalla(3)] * 5]

    eventos = alimentar(detector, fotogramas)

    assert [e.completa for e in eventos] == [True, True]


def test_zona_vacia_no_emite_y_el_texto_siguiente_es_completo() -> None:
    detector = DetectorTexto()
    fotogramas = [fondo(), *[pantalla(8)] * 5, *[fondo()] * 5, *[pantalla(4)] * 5]

    eventos = alimentar(detector, fotogramas)

    assert len(eventos) == 2
    assert eventos[1].completa


@pytest.mark.parametrize("brillo", [60, 120, 200])
def test_ignora_fondos_animados(brillo: int) -> None:
    detector = DetectorTexto()
    fotogramas = [fondo()]
    for i in range(20):
        imagen = pantalla(8)
        imagen[150:190, :, 0] = (brillo + i * 3) % 256  # parpadeo del fondo, sin texto nuevo
        fotogramas.append(imagen)

    eventos = alimentar(detector, fotogramas)

    assert len(eventos) == 1


def test_cambio_de_tamano_reinicia() -> None:
    detector = DetectorTexto()
    alimentar(detector, [fondo(), *[pantalla(8)] * 5])

    assert detector.procesar(np.zeros((50, 50, 3), dtype=np.uint8), 10.0) is None


def test_texto_oscuro_con_otra_mascara() -> None:
    detector = DetectorTexto(color=TEXTO_OSCURO)
    claro = fondo((235, 235, 225))
    fotogramas = [claro, *[escribir(claro, 0, 6, color=10)] * 5]

    eventos = alimentar(detector, fotogramas)

    assert len(eventos) == 1


def indicador(imagen: Imagen, fila: int, caracteres: int) -> Imagen:
    """Dibuja un pequeño indicador de "siguiente" tras el último carácter de la fila."""
    resultado = imagen.copy()
    y = 10 + fila * PASO_FILA + 5
    x = 10 + caracteres * PASO_CAR
    resultado[y : y + 10, x : x + 10] = 255
    return resultado


def test_nvl_con_indicador_que_desaparece_sigue_siendo_filas_nuevas() -> None:
    detector = DetectorTexto()
    primera = indicador(pantalla(8), 0, 8)
    segunda = indicador(pantalla(8, 6), 1, 6)  # el indicador pasa a la nueva fila

    eventos = alimentar(detector, [fondo(), *[primera] * 5, *[segunda] * 5])

    assert len(eventos) == 2
    assert not eventos[1].completa
    assert eventos[1].y_inicio == 10 + PASO_FILA - AjustesDetector().margen_filas


def test_solo_desaparece_el_indicador_no_emite() -> None:
    detector = DetectorTexto()
    fotogramas = [fondo(), *[indicador(pantalla(8), 0, 8)] * 5, *[pantalla(8)] * 5]

    eventos = alimentar(detector, fotogramas)

    assert len(eventos) == 1


def test_nvl_con_lineas_anteriores_atenuadas_sigue_siendo_filas_nuevas() -> None:
    """Al añadir un párrafo, muchas VN pasan los anteriores de blanco a gris claro."""
    detector = DetectorTexto()
    primera = indicador(pantalla(8), 0, 8)
    segunda = escribir(escribir(fondo(), 0, 8, color=176), 1, 6)

    eventos = alimentar(detector, [fondo(), *[primera] * 5, *[segunda] * 5])

    assert len(eventos) == 2
    assert not eventos[1].completa
    assert eventos[1].y_inicio == 10 + PASO_FILA - AjustesDetector().margen_filas
