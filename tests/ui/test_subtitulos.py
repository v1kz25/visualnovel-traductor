"""Tests de los subtítulos encima del juego, con un gestor de ventanas falso (sin X11 ni Win32)."""

import pytest
from PySide6.QtCore import QPoint, Qt
from pytestqt.qtbot import QtBot

from vn_audiolibro.atajos.modelos import Accion
from vn_audiolibro.captura.modelos import Rectangulo, VentanaMinimizadaError, ZonaRelativa
from vn_audiolibro.perfiles.modelos import AjustesSubtitulos, Perfil, PosicionSubtitulos
from vn_audiolibro.ui import subtitulos as modulo
from vn_audiolibro.ui.subtitulos import (
    VUELTAS_CONTROLES,
    Subtitulos,
    abrir_subtitulos,
    rectangulo_subtitulos,
)
from vn_audiolibro.voz.modelos import EstadoVoz

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

    assert "rgba(0, 0, 0, 255)" in tapar.caja.styleSheet()
    assert "rgba(0, 0, 0, 51)" in encima.caja.styleSheet()
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


def test_ocultar_deja_una_marca_y_volver_a_mostrar(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos = abrir(qtbot, ventanas)
    subtitulos.mostrar("Hola")

    subtitulos.alternar()
    assert subtitulos.isVisible()  # queda la marca, para que no parezca que han desaparecido
    assert subtitulos.caja.isHidden()
    assert subtitulos.marca.isVisible()
    assert subtitulos.geometry().height() < 60
    assert subtitulos.controles.botones[Accion.SUBTITULOS].text() == "Mostrar"
    subtitulos.mostrar("Adiós")  # el texto se sigue actualizando, sin verse
    assert subtitulos.caja.isHidden()

    subtitulos.alternar()
    assert subtitulos.caja.isVisible()
    assert subtitulos.marca.isHidden()
    assert subtitulos.texto.text() == "Adiós"
    assert subtitulos.controles.botones[Accion.SUBTITULOS].text() == "Ocultar"


def test_la_marca_tampoco_se_ve_con_el_juego_en_segundo_plano(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos = abrir(qtbot, ventanas)
    subtitulos.alternar()
    assert subtitulos.isVisible()  # oculto antes de que llegue ningún texto: la marca se ve
    ventanas.activa_ahora = 0x99
    subtitulos.seguir()
    assert subtitulos.isHidden()


# Controles flotantes


class Raton:
    def __init__(self) -> None:
        self.donde = QPoint(0, 0)

    def __call__(self) -> QPoint:
        return self.donde


def con_raton(qtbot: QtBot, ventanas: VentanasFalsas) -> tuple[Subtitulos, Raton]:
    raton = Raton()
    subtitulos = Subtitulos(
        AjustesSubtitulos(activo=True), ZONA, ventanas, 0x42, intervalo_ms=10_000, cursor=raton
    )
    qtbot.addWidget(subtitulos)
    qtbot.addWidget(subtitulos.controles)
    return subtitulos, raton


def test_los_controles_salen_al_pasar_el_raton(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos, raton = con_raton(qtbot, ventanas)
    subtitulos.mostrar("Hola")
    assert subtitulos.controles.isHidden()

    raton.donde = subtitulos.geometry().center()
    subtitulos.seguir()
    controles = subtitulos.controles
    assert controles.isVisible()
    assert controles.geometry().bottom() + 1 == subtitulos.geometry().top()  # justo encima
    assert controles.geometry().right() == subtitulos.geometry().right()  # a la derecha
    assert controles.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert not controles.windowFlags() & Qt.WindowType.WindowTransparentForInput  # sí recibe clics

    # Con el ratón sobre los propios controles, siguen.
    raton.donde = controles.geometry().center()
    for _vuelta in range(VUELTAS_CONTROLES + 1):
        subtitulos.seguir()
    assert controles.isVisible()

    # Al irse el ratón, se van un poco después.
    raton.donde = QPoint(0, 0)
    for _vuelta in range(VUELTAS_CONTROLES - 1):
        subtitulos.seguir()
    assert controles.isVisible()
    subtitulos.seguir()
    assert controles.isHidden()


def test_los_controles_se_van_con_el_juego(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos, raton = con_raton(qtbot, ventanas)
    subtitulos.mostrar("Hola")
    raton.donde = subtitulos.geometry().center()
    subtitulos.seguir()

    ventanas.activa_ahora = 0x99
    subtitulos.seguir()
    assert subtitulos.controles.isHidden()


def test_sobre_la_marca_tambien_salen_los_controles(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos, raton = con_raton(qtbot, ventanas)
    subtitulos.mostrar("Hola")
    subtitulos.alternar()

    raton.donde = subtitulos.geometry().center()
    subtitulos.seguir()
    assert subtitulos.controles.isVisible()


def test_los_botones_hacen_su_accion(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos, _raton = con_raton(qtbot, ventanas)
    pulsadas: list[Accion] = []
    subtitulos.conectar(pulsadas.append)

    for boton in subtitulos.controles.botones.values():
        boton.click()
    assert pulsadas == [Accion.PAUSA, Accion.REPETIR, Accion.SALTAR, Accion.SUBTITULOS]


def test_cerrar_cierra_los_controles(qtbot: QtBot, ventanas: VentanasFalsas) -> None:
    subtitulos, raton = con_raton(qtbot, ventanas)
    subtitulos.mostrar("Hola")
    raton.donde = subtitulos.geometry().center()
    subtitulos.seguir()

    subtitulos.cerrar()
    assert subtitulos.controles.isHidden()


# Cómo va la lectura


def test_dice_cuantas_quedan_en_cola_y_cuando_se_puede_avanzar(
    qtbot: QtBot, ventanas: VentanasFalsas
) -> None:
    subtitulos = abrir(qtbot, ventanas)
    subtitulos.mostrar("Hola")
    alto_solo = subtitulos.geometry().height()
    assert subtitulos.lectura.isHidden()

    subtitulos.estado_voz(EstadoVoz(leyendo=True, en_espera=2))
    assert subtitulos.lectura.text() == "2 líneas más en cola"
    assert subtitulos.lectura.isVisible()
    assert subtitulos.geometry().height() > alto_solo  # cabe debajo del texto
    assert subtitulos.geometry().bottom() + 1 == 470  # sigue justo encima de la zona de texto

    subtitulos.estado_voz(EstadoVoz(leyendo=True, en_espera=1))
    assert subtitulos.lectura.text() == "1 línea más en cola"

    subtitulos.estado_voz(EstadoVoz(leyendo=True, en_espera=0))
    assert subtitulos.lectura.isHidden()  # leyendo la última: nada que decir
    assert subtitulos.geometry().height() == alto_solo

    subtitulos.estado_voz(EstadoVoz(leyendo=False, en_espera=0))
    assert subtitulos.lectura.text() == "✓ Leída · puedes avanzar"
    assert subtitulos.lectura.isVisible()
