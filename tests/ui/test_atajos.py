"""Tests de los atajos globales en la interfaz: el diálogo y su uso durante la partida."""

from pathlib import Path

import pytest
from PySide6.QtGui import QKeySequence
from pytestqt.qtbot import QtBot

from vn_audiolibro.atajos.modelos import Accion, Atajo
from vn_audiolibro.configuracion import AjustesApp, cargar_ajustes, guardar_ajustes
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.ui.atajos import DialogoAtajos
from vn_audiolibro.ui.principal import VentanaPrincipal
from vn_audiolibro.ui.puente import PuenteSesion

from .conftest import ESPERA_MS, EscuchaFalsa, Fabrica


@pytest.fixture
def ruta(tmp_path: Path) -> Path:
    return tmp_path / "ajustes.json"


@pytest.fixture
def almacen(tmp_path: Path) -> AlmacenPerfiles:
    almacen = AlmacenPerfiles(tmp_path / "juegos")
    almacen.guardar(Perfil("Alfa", "alfa"))
    return almacen


# El diálogo


def test_dialogo_muestra_los_guardados(qtbot: QtBot, ruta: Path) -> None:
    guardar_ajustes(AjustesApp(atajos={**AjustesApp().atajos, "pausa": "F9"}), ruta)
    dialogo = DialogoAtajos(ruta)
    qtbot.addWidget(dialogo)
    assert dialogo.textos()["pausa"] == "F9"
    assert dialogo.textos()["saltar"] == "Ctrl+Alt+S"
    assert dialogo.activos.isChecked()


def test_dialogo_guarda(qtbot: QtBot, ruta: Path) -> None:
    guardar_ajustes(AjustesApp(idioma="en"), ruta)
    dialogo = DialogoAtajos(ruta)
    qtbot.addWidget(dialogo)
    dialogo.campos[Accion.SALTAR].setKeySequence(QKeySequence("Ctrl+Shift+K"))
    dialogo.activos.setChecked(False)
    assert not dialogo.campos[Accion.SALTAR].isEnabled()

    dialogo.guardar()
    ajustes = cargar_ajustes(ruta)
    assert ajustes.atajos["saltar"] == "Ctrl+Shift+K"
    assert not ajustes.atajos_activos
    assert ajustes.idioma == "en"  # lo demás no se toca


def test_dialogo_no_guarda_atajos_que_no_valen(qtbot: QtBot, ruta: Path) -> None:
    dialogo = DialogoAtajos(ruta)
    qtbot.addWidget(dialogo)
    dialogo.campos[Accion.SALTAR].setKeySequence(QKeySequence("Ctrl+Alt+P"))  # el de pausa

    dialogo.guardar()
    assert "repetido" in dialogo.error.text()
    assert cargar_ajustes(ruta).atajos["saltar"] == "Ctrl+Alt+S"

    dialogo.campos[Accion.SALTAR].setKeySequence(QKeySequence("S"))  # una letra sola
    dialogo.guardar()
    assert "necesitan Ctrl" in dialogo.error.text()

    dialogo.restablecer()
    assert dialogo.textos()["saltar"] == "Ctrl+Alt+S"
    assert not dialogo.error.text()


# Durante la partida


class SubtitulosFalsos:
    def __init__(self) -> None:
        self.alternados = 0
        self.cerrados = False

    def mostrar(self, texto: str) -> None:
        pass

    def alternar(self) -> None:
        self.alternados += 1

    def cerrar(self) -> None:
        self.cerrados = True


def ventana_(
    qtbot: QtBot, almacen: AlmacenPerfiles, fabrica: Fabrica, ruta: Path, subtitulos: SubtitulosFalsos | None
) -> VentanaPrincipal:
    ventana = VentanaPrincipal(
        almacen,
        PuenteSesion(fabrica),
        ruta_ajustes=ruta,
        subtitulos=lambda _: subtitulos,  # type: ignore[arg-type,return-value]
    )
    qtbot.addWidget(ventana)
    ventana.show()
    return ventana


def jugar(qtbot: QtBot, ventana: VentanaPrincipal) -> None:
    ventana.lista_perfiles.setCurrentRow(0)
    with qtbot.waitSignal(ventana.puente.iniciada, timeout=ESPERA_MS):
        ventana.boton_jugar.click()


def test_los_atajos_controlan_la_partida(
    qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path, escucha: EscuchaFalsa
) -> None:
    fabrica = Fabrica()
    subtitulos = SubtitulosFalsos()
    ventana = ventana_(qtbot, almacen, fabrica, ruta, subtitulos)
    jugar(qtbot, ventana)
    assert escucha.atajos is not None
    assert escucha.atajos[Accion.PAUSA] == Atajo.leer("Ctrl+Alt+P")
    control = fabrica.sesiones[-1].control

    for accion in (Accion.PAUSA, Accion.REPETIR, Accion.SALTAR, Accion.SUBTITULOS, Accion.PAUSA):
        escucha.pulsar(accion)
    qtbot.waitUntil(lambda: len(control.acciones) == 4 and subtitulos.alternados == 1, timeout=ESPERA_MS)
    assert control.acciones == ["pausar", "repetir", "saltar", "reanudar"]

    with qtbot.waitSignal(ventana.puente.terminada, timeout=ESPERA_MS):
        ventana.detener()
    assert escucha.detenida


def test_atajos_desactivados(
    qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path, escucha: EscuchaFalsa
) -> None:
    guardar_ajustes(AjustesApp(atajos_activos=False), ruta)
    ventana = ventana_(qtbot, almacen, Fabrica(), ruta, None)
    jugar(qtbot, ventana)
    assert escucha.atajos is None


def test_avisa_de_los_atajos_ocupados(
    qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path, escucha: EscuchaFalsa
) -> None:
    escucha.fallidos = [Accion.SALTAR]
    ventana = ventana_(qtbot, almacen, Fabrica(), ruta, None)
    jugar(qtbot, ventana)
    assert "ya los usa otra aplicación" in ventana.estado.text()
    assert "Ctrl+Alt+S" in ventana.estado.text()


def test_sin_atajos_en_el_sistema_se_juega_igual(
    qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path, escucha: EscuchaFalsa
) -> None:
    escucha.fallo = RuntimeError("sin X11")
    ventana = ventana_(qtbot, almacen, Fabrica(), ruta, None)
    jugar(qtbot, ventana)
    assert "No se pueden usar los atajos" in ventana.estado.text()
    assert ventana.puente.jugando


def test_atajos_guardados_que_no_valen(qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path) -> None:
    guardar_ajustes(AjustesApp(atajos={**AjustesApp().atajos, "saltar": "S"}), ruta)
    ventana = ventana_(qtbot, almacen, Fabrica(), ruta, None)
    jugar(qtbot, ventana)
    assert "necesitan Ctrl" in ventana.estado.text()


# Modo «solo subtítulos»


def test_solo_subtitulos_minimiza_la_app_mientras_se_juega(
    qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path
) -> None:
    ventana = ventana_(qtbot, almacen, Fabrica(), ruta, SubtitulosFalsos())
    ventana.solo_subtitulos.setChecked(True)
    assert cargar_ajustes(ruta).solo_subtitulos

    jugar(qtbot, ventana)
    assert ventana.isMinimized()
    with qtbot.waitSignal(ventana.puente.terminada, timeout=ESPERA_MS):
        ventana.detener()
    assert not ventana.isMinimized()


def test_sin_subtitulos_no_se_minimiza(qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path) -> None:
    guardar_ajustes(AjustesApp(solo_subtitulos=True), ruta)
    ventana = ventana_(qtbot, almacen, Fabrica(), ruta, None)
    assert ventana.solo_subtitulos.isChecked()
    jugar(qtbot, ventana)
    assert not ventana.isMinimized()  # sin subtítulos, la app es la única forma de ver la traducción


def test_no_se_configuran_los_atajos_mientras_se_juega(
    qtbot: QtBot, almacen: AlmacenPerfiles, ruta: Path
) -> None:
    ventana = ventana_(qtbot, almacen, Fabrica(), ruta, None)
    assert ventana.boton_atajos.isEnabled()
    jugar(qtbot, ventana)
    assert not ventana.boton_atajos.isEnabled()
