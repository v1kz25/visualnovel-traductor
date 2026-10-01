"""Tests contra un servidor X real (el escritorio o Xvfb en la CI). Crean ventanas sin mostrarlas."""

import os
from collections.abc import Iterator

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="necesita un servidor X")
pytest.importorskip("Xlib", reason="solo en Linux")

from Xlib import X, Xatom, display  # noqa: E402

from vn_audiolibro.captura import __main__ as cli  # noqa: E402
from vn_audiolibro.captura.capturador import CapturadorMss  # noqa: E402
from vn_audiolibro.captura.modelos import Rectangulo, VentanaNoEncontradaError  # noqa: E402
from vn_audiolibro.captura.x11 import CapturadorVentanaX11, GestorVentanasX11  # noqa: E402

TITULO = "vn-audiolibro prueba ventana 測試 テスト"


@pytest.fixture
def conexion() -> Iterator[display.Display]:
    pantalla = display.Display()
    yield pantalla
    pantalla.close()


@pytest.fixture
def ventana(conexion: display.Display) -> Iterator[int]:
    raiz = conexion.screen().root
    ventana = raiz.create_window(0, 0, 320, 240, 0, X.CopyFromParent)
    ventana.change_property(
        conexion.intern_atom("_NET_WM_NAME"), conexion.intern_atom("UTF8_STRING"), 8, TITULO.encode()
    )
    ventana.change_property(conexion.intern_atom("_NET_WM_PID"), Xatom.CARDINAL, 32, [os.getpid()])
    conexion.sync()
    yield ventana.id
    ventana.destroy()
    conexion.sync()


@pytest.fixture
def gestor(conexion: display.Display, ventana: int, monkeypatch: pytest.MonkeyPatch) -> GestorVentanasX11:
    gestor = GestorVentanasX11(conexion)
    original = gestor._propiedad

    def propiedad(objetivo, nombre, tipo=X.AnyPropertyType):  # type: ignore[no-untyped-def]
        if nombre == "_NET_CLIENT_LIST":
            return [ventana, 0x7FFFFFF]  # la segunda no existe: se debe ignorar
        return original(objetivo, nombre, tipo)

    monkeypatch.setattr(gestor, "_propiedad", propiedad)
    return gestor


def test_lista_la_ventana_con_titulo_pid_y_geometria(gestor: GestorVentanasX11, ventana: int) -> None:
    encontradas = [v for v in gestor.listar() if v.id == ventana]

    assert len(encontradas) == 1
    assert encontradas[0].titulo == TITULO
    assert encontradas[0].pid == os.getpid()
    assert (encontradas[0].geometria.ancho, encontradas[0].geometria.alto) == (320, 240)


def test_busca_por_parte_del_titulo(gestor: GestorVentanasX11, ventana: int) -> None:
    assert gestor.buscar("PRUEBA VENTANA", excluir_pids=frozenset()).id == ventana


def test_buscar_ignora_las_ventanas_del_propio_proceso(gestor: GestorVentanasX11) -> None:
    # La ventana de prueba lleva el PID de este proceso, como la terminal que lanza la app.
    with pytest.raises(VentanaNoEncontradaError):
        gestor.buscar("PRUEBA VENTANA")


def test_buscar_inexistente_falla(gestor: GestorVentanasX11) -> None:
    with pytest.raises(VentanaNoEncontradaError):
        gestor.buscar("no existe ninguna ventana así")


def test_geometria_de_ventana_cerrada_falla(conexion: display.Display) -> None:
    with pytest.raises(VentanaNoEncontradaError):
        GestorVentanasX11(conexion).geometria(0x7FFFFFF)


VERDE = 0x00C000


@pytest.fixture
def ventana_visible(conexion: display.Display) -> Iterator[int]:
    """Ventana verde, mapeada y sin decoraciones del gestor de ventanas."""
    raiz = conexion.screen().root
    ventana = raiz.create_window(
        0, 0, 64, 48, 0, X.CopyFromParent, background_pixel=VERDE, override_redirect=True
    )
    ventana.map()
    conexion.sync()
    yield ventana.id
    ventana.destroy()
    conexion.sync()


def test_capturador_mss_devuelve_rgb_del_tamano_pedido(gestor: GestorVentanasX11, ventana: int) -> None:
    capturador = CapturadorMss(gestor)
    imagen = capturador.capturar(ventana, Rectangulo(0, 0, 64, 32))
    capturador.cerrar()

    assert imagen.shape == (32, 64, 3)
    assert imagen.dtype == np.uint8


def test_capturador_ventana_lee_el_contenido(conexion: display.Display, ventana_visible: int) -> None:
    capturador = CapturadorVentanaX11(pantalla=conexion)
    imagen = None
    for _ in range(20):  # el servidor tarda un instante en pintar la ventana recién mapeada
        imagen = capturador.capturar(ventana_visible, Rectangulo(8, 8, 32, 16))
        if imagen[..., 1].mean() > 150:
            break
    assert imagen is not None
    assert imagen.shape == (16, 32, 3)
    assert tuple(imagen[0, 0]) == (0, 0xC0, 0)


class CapturadorFijo:
    def capturar(self, id_ventana: int, zona: Rectangulo) -> np.ndarray:
        return np.full((zona.alto, zona.ancho, 3), 7, dtype=np.uint8)


def test_capturador_ventana_usa_el_alternativo_si_no_puede(conexion: display.Display, ventana: int) -> None:
    # Una ventana sin mapear no tiene pixmap: XComposite falla y se usa el alternativo.
    capturador = CapturadorVentanaX11(alternativo=CapturadorFijo(), pantalla=conexion)

    assert capturador.capturar(ventana, Rectangulo(0, 0, 10, 10)).max() == 7


def test_cli_lista_ventanas(gestor: GestorVentanasX11, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli, "gestor_ventanas", lambda: gestor)

    assert cli.main(["--listar"]) == 0
    assert TITULO in capsys.readouterr().out


def test_cli_ventana_inexistente(gestor: GestorVentanasX11, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "gestor_ventanas", lambda: gestor)

    assert cli.main(["--ventana", "no existe ninguna ventana así"]) == 1


def test_ventana_activa_segun_el_gestor_de_ventanas(
    conexion: display.Display, ventana: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    gestor = GestorVentanasX11(conexion)
    activa: list[int] | None = None

    def propiedad(objetivo, nombre, tipo=X.AnyPropertyType):  # type: ignore[no-untyped-def]
        return activa if nombre == "_NET_ACTIVE_WINDOW" else None

    monkeypatch.setattr(gestor, "_propiedad", propiedad)
    assert gestor.activa() is None  # sin gestor de ventanas (Xvfb), no se sabe
    activa = [0]
    assert gestor.activa() is None
    activa = [ventana]
    assert gestor.activa() == ventana
