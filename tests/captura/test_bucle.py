"""Tests del bucle de captura con capturador y ventanas falsos."""

import time

import numpy as np
import pytest

from vn_audiolibro.captura.bucle import BucleCaptura
from vn_audiolibro.captura.modelos import (
    TODA_LA_VENTANA,
    Imagen,
    Rectangulo,
    Ventana,
    VentanaMinimizadaError,
    VentanaNoEncontradaError,
    ZonaEstable,
    ZonaRelativa,
    buscar_por_titulo,
)

VENTANA = Rectangulo(x=100, y=50, ancho=800, alto=600)


class VentanasFalsas:
    def __init__(self) -> None:
        self.geometria_actual = VENTANA

    def geometria(self, id_ventana: int) -> Rectangulo:
        return self.geometria_actual


class CapturadorFalso:
    """Devuelve primero un fondo y después un bloque de texto blanco."""

    def __init__(self) -> None:
        self.zonas: list[Rectangulo] = []

    def capturar(self, id_ventana: int, zona: Rectangulo) -> Imagen:
        self.zonas.append(zona)
        imagen = np.zeros((zona.alto, zona.ancho, 3), dtype=np.uint8)
        if len(self.zonas) > 1:
            imagen[10:30, 10:200] = 255
        return imagen


def test_zona_relativa_escala_con_la_ventana() -> None:
    zona = ZonaRelativa(0.25, 0.5, 0.5, 0.25)

    assert zona.en_pixeles(800, 600) == Rectangulo(200, 300, 400, 150)
    assert zona.en_pixeles(1600, 1200) == Rectangulo(400, 600, 800, 300)


def test_zona_relativa_desde_pixeles_se_recorta_a_la_ventana() -> None:
    zona = ZonaRelativa.desde_pixeles(Rectangulo(600, 450, 400, 300), 800, 600)

    assert zona.en_pixeles(800, 600) == Rectangulo(600, 450, 200, 150)


@pytest.mark.parametrize(
    "valores", [(-0.1, 0, 0.5, 0.5), (0.6, 0, 0.5, 0.5), (0, 0, 0, 0.5), (0, 1, 0.5, 0.5)]
)
def test_zona_relativa_invalida(valores: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError, match="fuera"):
        ZonaRelativa(*valores)


def test_rectangulo_vacio_falla() -> None:
    with pytest.raises(ValueError, match="vacío"):
        Rectangulo(0, 0, 0, 10)


def test_paso_detecta_texto_y_llama_al_callback() -> None:
    eventos: list[ZonaEstable] = []
    capturador = CapturadorFalso()
    bucle = BucleCaptura(1, ZonaRelativa(0, 0, 0.5, 1 / 3), eventos.append, VentanasFalsas(), capturador)

    for i in range(6):
        bucle.paso(i * 0.1)

    assert len(eventos) == 1
    assert eventos[0].imagen.shape == (200, 400, 3)


def test_la_zona_sigue_a_la_ventana_si_se_redimensiona() -> None:
    ventanas = VentanasFalsas()
    capturador = CapturadorFalso()
    bucle = BucleCaptura(1, ZonaRelativa(0.5, 0.5, 0.5, 0.5), lambda _: None, ventanas, capturador)

    bucle.paso(0.0)
    ventanas.geometria_actual = Rectangulo(x=300, y=300, ancho=1600, alto=1200)
    bucle.paso(0.1)

    assert capturador.zonas == [Rectangulo(400, 300, 400, 300), Rectangulo(800, 600, 800, 600)]


def test_hilo_arranca_y_se_detiene() -> None:
    eventos: list[ZonaEstable] = []
    bucle = BucleCaptura(
        1, TODA_LA_VENTANA, eventos.append, VentanasFalsas(), CapturadorFalso(), intervalo_s=0.01
    )

    bucle.iniciar()
    bucle.iniciar()  # idempotente
    limite = time.monotonic() + 3
    while not eventos and time.monotonic() < limite:
        time.sleep(0.02)
    bucle.detener()

    assert len(eventos) == 1


def test_con_la_ventana_minimizada_sigue_esperando() -> None:
    class Minimizable(CapturadorFalso):
        minimizada = True

        def capturar(self, id_ventana: int, zona: Rectangulo) -> Imagen:
            if self.minimizada:
                self.minimizada = False
                raise VentanaMinimizadaError("minimizada")
            return super().capturar(id_ventana, zona)

    eventos: list[ZonaEstable] = []
    capturador = Minimizable()
    bucle = BucleCaptura(1, TODA_LA_VENTANA, eventos.append, VentanasFalsas(), capturador, intervalo_s=0.01)

    bucle.iniciar()
    limite = time.monotonic() + 3
    while not eventos and time.monotonic() < limite:
        time.sleep(0.02)
    bucle.detener()

    assert len(eventos) == 1  # el hilo no se ha parado al estar minimizada


def test_buscar_por_titulo() -> None:
    terminal = Ventana(1, "uv run vn-audiolibro jugar Juego", 10, VENTANA)
    juego = Ventana(2, "JUEGO ~ capítulo 1", 20, VENTANA)

    assert buscar_por_titulo([terminal, juego], "juego", frozenset({10})) == juego
    assert buscar_por_titulo([terminal, juego], "juego", frozenset()) == terminal
    with pytest.raises(VentanaNoEncontradaError, match="«otro»"):
        buscar_por_titulo([terminal, juego], "otro", frozenset())
