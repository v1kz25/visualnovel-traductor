"""Tests de la traducción del guion entero desde la interfaz, con un preparador falso."""

import contextlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace

import pytest
from pytestqt.qtbot import QtBot

from vn_audiolibro.perfiles.modelos import AjustesGuion, Perfil
from vn_audiolibro.traduccion.modelos import Motor, TraduccionFallidaError
from vn_audiolibro.ui.guion import TraducirGuion, duracion

from .conftest import ESPERA_MS

PERFIL = Perfil("Juego", "juego", guion=AjustesGuion("/juegos/juego"))


class PreparadorFalso:
    """Guion de `total` párrafos, de los que ya estaban traducidos los `hechos` primeros."""

    def __init__(self, total: int = 4, hechos: int = 1, puerta: threading.Event | None = None) -> None:
        self.total = total
        self.hechos = hechos
        self.puerta = puerta
        """Si se da, se espera a que se abra antes de cada párrafo pendiente."""

    def pendientes(self) -> int:
        return self.total - self.hechos

    def traducir_todo(
        self,
        al_progreso: Callable[[int, int], None],
        cancelado: Callable[[], bool],
        al_traducir: Callable[[], None],
    ) -> int:
        traducidos = 0
        for indice in range(1, self.total + 1):
            if cancelado():
                break
            if indice > self.hechos:
                if self.puerta is not None:
                    self.puerta.wait(ESPERA_MS / 1000)
                if cancelado():
                    break
                traducidos += 1
                al_traducir()
            al_progreso(indice, self.total)
        self.hechos += traducidos
        return traducidos


class Abrir:
    """Sustituye a `traductor_guion`: apunta los estados y si se ha cerrado el traductor."""

    def __init__(self, preparador: PreparadorFalso | None = None, fallo: Exception | None = None) -> None:
        self.preparador = preparador or PreparadorFalso()
        self.fallo = fallo
        self.abiertos = 0
        self.cerrados = 0

    @contextlib.contextmanager
    def __call__(self, perfil: Perfil, al_estado: Callable[[str], None]) -> Iterator[PreparadorFalso]:
        assert perfil is PERFIL
        al_estado("Arrancando el traductor…")
        if self.fallo is not None:
            raise self.fallo
        self.abiertos += 1
        try:
            yield self.preparador
        finally:
            self.cerrados += 1


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


def dialogo(qtbot: QtBot, abrir: Abrir, reloj: Callable[[], float] | None = None) -> TraducirGuion:
    ventana = TraducirGuion(PERFIL, abrir, reloj or Reloj())  # type: ignore[arg-type]
    qtbot.addWidget(ventana)
    return ventana


@pytest.mark.parametrize(
    ("segundos", "texto"),
    [(10, "menos de 1 min"), (60, "1 min"), (25 * 60, "25 min"), (3 * 3600 + 5 * 60, "3 h 05 min")],
)
def test_duracion(segundos: float, texto: str) -> None:
    assert duracion(segundos) == texto


def test_traduce_lo_que_falta(qtbot: QtBot) -> None:
    abrir = Abrir(PreparadorFalso(total=4, hechos=1))
    ventana = dialogo(qtbot, abrir)
    assert "«Juego»" in ventana.explicacion.text()

    with qtbot.waitSignal(ventana.terminado, timeout=ESPERA_MS) as senal:
        ventana.empezar()
    assert senal.args == [""]
    assert ventana.traducidos_al_terminar == 3
    assert "3 párrafos traducidos" in ventana.mensaje.text()
    assert not ventana.boton_empezar.isEnabled()
    assert (abrir.abiertos, abrir.cerrados) == (1, 1)  # el traductor se para al terminar


def test_progreso_y_tiempo_que_falta(qtbot: QtBot) -> None:
    puerta = threading.Event()
    reloj = Reloj()
    ventana = dialogo(qtbot, Abrir(PreparadorFalso(total=5, hechos=1, puerta=puerta)), reloj)
    with qtbot.waitSignal(ventana.inicio, timeout=ESPERA_MS):
        ventana.empezar()
    assert ventana.traduciendo
    assert ventana.boton_cerrar.text() == "Parar"
    assert ventana.restante_s() is None  # aún sin ritmo

    # Un párrafo en 2 minutos: de los 4 que faltaban quedan 3, unos 6 minutos.
    reloj.ahora += 120
    with qtbot.waitSignal(ventana.traducido, timeout=ESPERA_MS):
        puerta.set()
        puerta.clear()
    qtbot.waitUntil(lambda: ventana.barra.value() == 2, timeout=ESPERA_MS)
    assert ventana.restante_s() == 360
    assert ventana.barra.format() == "2 de 5 párrafos (40 %)"
    assert "Falta, más o menos: 6 min" in ventana.tiempo.text()

    with qtbot.waitSignal(ventana.terminado, timeout=ESPERA_MS):
        ventana.boton_cerrar.click()  # «Parar»
        puerta.set()


def test_parar_y_seguir_otro_dia(qtbot: QtBot) -> None:
    puerta = threading.Event()
    preparador = PreparadorFalso(total=3, hechos=0, puerta=puerta)
    abrir = Abrir(preparador)
    ventana = dialogo(qtbot, abrir)
    with qtbot.waitSignal(ventana.inicio, timeout=ESPERA_MS):
        ventana.empezar()

    with qtbot.waitSignal(ventana.terminado, timeout=ESPERA_MS) as senal:
        ventana.boton_cerrar.click()
        assert not ventana.boton_cerrar.isEnabled()
        assert ventana.mensaje.text() == "Parando…"
        puerta.set()
    assert senal.args == ["cancelado"]
    assert ventana.boton_empezar.text() == "Seguir"
    assert ventana.boton_cerrar.isEnabled()
    assert ventana.boton_cerrar.text() == "Cerrar"
    assert "por donde lo ha dejado" in ventana.mensaje.text()
    assert preparador.hechos < 3

    with qtbot.waitSignal(ventana.terminado, timeout=ESPERA_MS) as senal:
        ventana.boton_empezar.click()
    assert senal.args == [""]
    assert preparador.hechos == 3
    assert (abrir.abiertos, abrir.cerrados) == (2, 2)


def test_un_fallo_se_muestra_y_se_puede_reintentar(qtbot: QtBot) -> None:
    abrir = Abrir(fallo=TraduccionFallidaError("El traductor no responde"))
    ventana = dialogo(qtbot, abrir)
    with qtbot.waitSignal(ventana.terminado, timeout=ESPERA_MS):
        ventana.empezar()
    assert ventana.mensaje.text() == "El traductor no responde"
    assert ventana.boton_empezar.text() == "Reintentar"
    assert ventana.boton_empezar.isEnabled()


def test_cerrar_la_ventana_para_la_traduccion(qtbot: QtBot) -> None:
    puerta = threading.Event()
    abrir = Abrir(PreparadorFalso(total=3, hechos=0, puerta=puerta))
    ventana = dialogo(qtbot, abrir)
    with qtbot.waitSignal(ventana.inicio, timeout=ESPERA_MS):
        ventana.empezar()
    puerta.set()
    ventana.reject()
    assert not ventana.traduciendo
    assert abrir.cerrados == 1


def test_un_fallo_inesperado_tambien_se_muestra(qtbot: QtBot) -> None:
    ventana = dialogo(qtbot, Abrir(fallo=RuntimeError()))
    with qtbot.waitSignal(ventana.terminado, timeout=ESPERA_MS):
        ventana.empezar()
    assert ventana.mensaje.text() == "RuntimeError"


@pytest.mark.parametrize(
    ("motor", "texto"), [(Motor.LOCAL, "varias horas"), (Motor.GEMINI, "40 líneas por petición")]
)
def test_la_explicacion_depende_del_traductor(qtbot: QtBot, motor: Motor, texto: str) -> None:
    ventana = TraducirGuion(replace(PERFIL, traductor=motor), Abrir())  # type: ignore[arg-type]
    qtbot.addWidget(ventana)
    assert texto in ventana.explicacion.text()
