"""Tests de los subtítulos encima del juego, con un gestor de ventanas falso (sin X11 ni Win32)."""

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from vn_audiolibro.captura.modelos import Rectangulo, VentanaMinimizadaError, ZonaRelativa
from vn_audiolibro.perfiles.modelos import AjustesSubtitulos, Perfil, PosicionSubtitulos
from vn_audiolibro.ui import subtitulos as modulo
from vn_audiolibro.ui.subtitulos import Subtitulos, abrir_subtitulos, rectangulo_subtitulos

JUEGO = Rectangulo(100, 50, 800, 600)
ZONA = ZonaRelativa(0.1, 0.7, 0.8, 0.25)  # en píxeles del juego: x=80, y=420, 640×150
ENCIMA, DEBAJO, TAPAR = PosicionSubtitulos.ENCIMA, PosicionSubtitulos.DEBAJO, PosicionSubtitulos.TAPAR


@pytest.mark.parametrize(
    ("zona", "posicion", "esperado"),
    [
        (ZONA, ENCIMA, Rectangulo(180, 410, 640, 60)),
        (ZONA, TAPAR, Rectangulo(180, 470, 640, 150)),
        (ZONA, DEBAJO, Rectangulo(180, 410, 640, 60)),  # debajo no cabe: va encima
        (ZonaRelativa(0.1, 0.0, 0.8, 0.2), ENCIMA, Rectangulo(180, 170, 640, 60)),  # encima no cabe
        (ZonaRelativa(0.1, 0.5, 0.8, 0.2), DEBAJO, Rectangulo(180, 470, 640, 60)),
    ],
)
def test_donde_van_los_subtitulos(
    zona: ZonaRelativa, posicion: PosicionSubtitulos, esperado: Rectangulo
) -> None:
    assert rectangulo_subtitulos(JUEGO, zona, posicion, 60) == esperado


def test_si_no_caben_por_ningun_lado_no_se_salen_del_juego() -> None:
    sitio = rectangulo_subtitulos(JUEGO, ZonaRelativa(0, 0, 1, 1), ENCIMA, 60)
    assert sitio.y == JUEGO.y


class VentanasFalsas:
    def __init__(self) -> None:
        self.activa_ahora: int | None = 0x42
        self.posicion = JUEGO
        self.minimizada = False

    def geometria(self, id_ventana: int) -> Rectangulo:
        if self.minimizada:
            raise VentanaMinimizadaError("minimizada")
        return self.posicion

    def activa(self) -> int | None:
        return self.activa_ahora


@pytest.fixture
def ventanas() -> VentanasFalsas:
    return VentanasFalsas()


def abrir(qtbot: QtBot, ventanas: VentanasFalsas, ajustes: AjustesSubtitulos | None = None) -> Subtitulos:
    subtitulos = Subtitulos(
        ajustes or AjustesSubtitulos(activo=True), ZONA, ventanas, 0x42, intervalo_ms=10_000
    )
    qtbot.addWidget(subtitulos)
    return subtitulos


def test_ventana_sin_marco_encima_y_transparente_al_raton(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    banderas = abrir(qtbot, ventanas).windowFlags()

    for bandera in (
        Qt.WindowType.FramelessWindowHint,
        Qt.WindowType.WindowStaysOnTopHint,
        Qt.WindowType.WindowTransparentForInput,
        Qt.WindowType.WindowDoesNotAcceptFocus,
    ):
        assert banderas & bandera


def test_muestra_la_traduccion_sobre_el_juego(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos = abrir(qtbot, ventanas)
    assert subtitulos.isHidden()  # sin texto no se ve nada

    subtitulos.mostrar("¿Volvemos juntos a casa?")

    assert subtitulos.isVisible()
    assert subtitulos.texto.text() == "¿Volvemos juntos a casa?"
    geometria = subtitulos.geometry()
    assert (geometria.x(), geometria.width()) == (180, 640)
    assert geometria.y() + geometria.height() == 470  # justo encima de la zona de texto


def test_sigue_al_juego_si_se_mueve(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos = abrir(qtbot, ventanas)
    subtitulos.mostrar("Hola")

    ventanas.posicion = Rectangulo(300, 50, 800, 600)
    subtitulos.seguir()

    assert subtitulos.geometry().x() == 380


@pytest.mark.parametrize("cambio", ["otra ventana activa", "minimizado"])
def test_se_oculta_si_el_juego_no_esta_a_la_vista(
    qtbot: QtBot, ventanas: VentanasFalsas, cambio: str
) -> None:
    subtitulos = abrir(qtbot, ventanas)
    subtitulos.mostrar("Hola")

    if cambio == "minimizado":
        ventanas.minimizada = True
    else:
        ventanas.activa_ahora = 0x99
    subtitulos.seguir()

    assert subtitulos.isHidden()
    ventanas.minimizada, ventanas.activa_ahora = False, 0x42
    subtitulos.seguir()
    assert subtitulos.isVisible()


def test_tapar_lleva_fondo_opaco(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    tapar = abrir(qtbot, ventanas, AjustesSubtitulos(activo=True, posicion=TAPAR, opacidad=0.2))
    encima = abrir(qtbot, ventanas, AjustesSubtitulos(activo=True, opacidad=0.2))

    assert "rgba(0, 0, 0, 255)" in tapar.texto.styleSheet()
    assert "rgba(0, 0, 0, 51)" in encima.texto.styleSheet()
    assert tapar.texto.font().pointSize() == 22


def test_cerrar(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos = abrir(qtbot, ventanas)
    subtitulos.mostrar("Hola")
    subtitulos.cerrar()
    assert subtitulos.isHidden()


def test_abrir_subtitulos(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, ventanas: VentanasFalsas) -> None:
    class Gestor(VentanasFalsas):
        def buscar(self, texto: str) -> object:
            if texto == "no está":
                raise LookupError(texto)
            return type("Ventana", (), {"id": 0x42})()

    monkeypatch.setattr(modulo, "gestor_ventanas", Gestor)
    activos = AjustesSubtitulos(activo=True)

    assert abrir_subtitulos(Perfil("Juego", "juego")) is None  # desactivados por defecto
    assert abrir_subtitulos(Perfil("Juego", "no está", subtitulos=activos)) is None
    abiertos = abrir_subtitulos(Perfil("Juego", "juego", subtitulos=activos))
    assert isinstance(abiertos, Subtitulos)
    qtbot.addWidget(abiertos)
