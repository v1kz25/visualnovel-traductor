"""Tests del selector de la zona de texto."""

from dataclasses import astuple

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from pytestqt.qtbot import QtBot

from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, ZonaRelativa
from vn_audiolibro.ui.zona import SelectorZona, a_qimage


def captura(ancho: int = 200, alto: int = 100) -> np.ndarray:
    imagen = np.zeros((alto, ancho, 3), dtype=np.uint8)
    imagen[:, :, 0] = 200  # rojo
    return imagen


@pytest.fixture
def selector(qtbot: QtBot) -> SelectorZona:
    selector = SelectorZona()
    qtbot.addWidget(selector)
    selector.resize(400, 200)  # misma proporción que la captura: la ocupa entera
    selector.mostrar(captura())
    return selector


def test_a_qimage() -> None:
    imagen = a_qimage(captura(3, 2))
    assert (imagen.width(), imagen.height()) == (3, 2)
    assert imagen.pixelColor(1, 1).red() == 200


def test_dibujar_la_zona_con_el_raton(qtbot: QtBot, selector: SelectorZona) -> None:
    with qtbot.waitSignal(selector.zona_cambiada) as senal:
        qtbot.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(240, 120))
        qtbot.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(40, 20))  # de abajo arriba

    assert selector.zona == pytest.approx(ZonaRelativa(0.1, 0.1, 0.5, 0.5))
    assert senal.args == [selector.zona]


def test_la_captura_se_centra_sin_deformar(selector: SelectorZona) -> None:
    selector.resize(400, 400)  # captura 2:1 en un cuadrado: franjas arriba y abajo
    area = selector.area_imagen()
    assert (area.x(), area.y(), area.width(), area.height()) == (0, 100, 400, 200)
    zona = selector.zona_entre(QPointF(-50, 0), QPointF(500, 450))  # fuera: se recorta al borde
    assert zona == TODA_LA_VENTANA


def test_un_clic_sin_arrastrar_no_cambia_la_zona(qtbot: QtBot, selector: SelectorZona) -> None:
    selector.poner_zona(ZonaRelativa(0.1, 0.1, 0.5, 0.5))
    qtbot.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(51, 50))
    assert selector.zona == ZonaRelativa(0.1, 0.1, 0.5, 0.5)


def test_el_arrastre_se_ve_mientras_se_mueve(selector: SelectorZona) -> None:
    selector.mousePressEvent(_evento(QPointF(10, 10)))
    selector.mouseMoveEvent(_evento(QPointF(90, 50)))
    assert selector._arrastre is not None
    assert selector._arrastre.width() == 80
    assert not selector.grab().isNull()  # dibuja la sombra con el arrastre a medias


def test_otros_botones_o_sin_captura_no_hacen_nada(qtbot: QtBot) -> None:
    selector = SelectorZona()
    qtbot.addWidget(selector)
    selector.resize(400, 200)
    qtbot.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(150, 80))
    assert selector.zona is None
    assert not selector.grab().isNull()  # sin captura dibuja el aviso

    selector.mostrar(captura())
    qtbot.mousePress(selector, Qt.MouseButton.RightButton, pos=QPoint(10, 10))
    qtbot.mouseRelease(selector, Qt.MouseButton.RightButton, pos=QPoint(150, 80))
    assert selector.zona is None


def test_dibuja_la_zona_guardada(selector: SelectorZona) -> None:
    selector.poner_zona(ZonaRelativa(0.2, 0.2, 0.3, 0.3))
    imagen = selector.grab().toImage()
    assert imagen.pixelColor(2, 2).red() < 200  # fuera de la zona, oscurecido
    assert imagen.pixelColor(140, 70).red() == 200  # dentro, tal cual
    assert selector.sizeHint().width() > 0


def test_dibujar_la_zona_del_nombre(qtbot: QtBot, selector: SelectorZona) -> None:
    selector.poner_zona(ZonaRelativa(0.1, 0.5, 0.8, 0.4))
    selector.dibujar_nombre(True)
    with qtbot.waitSignal(selector.zona_nombre_cambiada) as senal:
        qtbot.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(40, 80))
        qtbot.mouseMove(selector, QPoint(100, 90))
        assert not selector.grab().isNull()  # dibuja el arrastre del nombre sin tapar la zona
        qtbot.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(120, 96))

    nombre = selector.zona_nombre
    assert nombre is not None
    assert astuple(nombre) == pytest.approx((0.1, 0.4, 0.2, 0.08))
    assert senal.args == [nombre]
    assert selector.zona == ZonaRelativa(0.1, 0.5, 0.8, 0.4)  # la de texto no cambia
    assert not selector.dibujando_nombre  # el siguiente recuadro vuelve a ser la zona de texto
    imagen = selector.grab().toImage()
    assert imagen.pixelColor(40, 88).blue() > 150  # el recuadro del nombre, en otro color

    selector.poner_zona_nombre(None)
    assert selector.zona_nombre is None


def _evento(punto: QPointF):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        punto,
        punto,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
