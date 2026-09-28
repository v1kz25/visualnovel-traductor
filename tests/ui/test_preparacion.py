"""Tests del diálogo del primer arranque con componentes falsos."""

import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from vn_audiolibro.descargas import Cancelado, DescargaCanceladaError, Progreso
from vn_audiolibro.preparacion import AVISO_COPYRIGHT, Aviso, Componente
from vn_audiolibro.ui.preparacion import DESCARGANDO, ERROR, LISTO, PENDIENTE, PrimerArranque

from .conftest import ESPERA_MS


class Falso:
    """Componente falso: avisa del progreso y puede fallar, esperar a cancelarse o estar ya instalado."""

    def __init__(self, nombre: str, fallos: int = 0, esperar: bool = False, instalado: bool = False) -> None:
        self.nombre = nombre
        self.fallos = fallos
        self.esperar = esperar
        self.ya_instalado = instalado
        self.empezado = threading.Event()
        self.instalaciones = 0

    def componente(self) -> Componente:
        return Componente(self.nombre, "uso", "MIT", 3 * 1024**2, lambda: self.ya_instalado, self.instalar)

    def instalar(self, progreso: Progreso | None, cancelado: Cancelado | None) -> None:
        self.instalaciones += 1
        self.empezado.set()
        assert progreso is not None
        assert cancelado is not None
        progreso(1024**2, 3 * 1024**2)
        while self.esperar:
            if cancelado():
                raise DescargaCanceladaError("cancelada")
            threading.Event().wait(0.01)
        if self.fallos:
            self.fallos -= 1
            raise OSError("sin conexión")
        progreso(3 * 1024**2, 3 * 1024**2)


def abrir(qtbot: QtBot, falsos: list[Falso], avisos: list[Aviso] | None = None) -> PrimerArranque:
    dialogo = PrimerArranque([f.componente() for f in falsos], avisos or [])
    qtbot.addWidget(dialogo)
    return dialogo


def estados(dialogo: PrimerArranque) -> list[str]:
    return [dialogo.tabla.item(fila, 3).text() for fila in range(dialogo.tabla.rowCount())]


def test_muestra_lo_que_se_va_a_descargar_y_los_avisos(qtbot: QtBot) -> None:
    avisos = [Aviso("Falta paplay", grave=True), Aviso("Falta libpulse", grave=False)]
    dialogo = abrir(qtbot, [Falso("OCR"), Falso("Voz")], avisos)

    textos = [etiqueta.text() for etiqueta in dialogo.findChildren(type(dialogo.mensaje))]
    assert "⚠ Falta paplay" in textos
    assert "Aviso: Falta libpulse" in textos
    assert AVISO_COPYRIGHT in textos
    assert any("6,0 MB en total" in texto for texto in textos)
    assert [dialogo.tabla.item(f, 0).text() for f in range(2)] == ["OCR", "Voz"]
    assert estados(dialogo) == [PENDIENTE, PENDIENTE]


def test_descarga_todo_y_se_cierra(qtbot: QtBot) -> None:
    falsos = [Falso("OCR"), Falso("Voz", instalado=True)]
    dialogo = abrir(qtbot, falsos)

    with qtbot.waitSignal(dialogo.terminado, timeout=ESPERA_MS):
        dialogo.boton_descargar.click()

    assert estados(dialogo) == [LISTO, LISTO]
    assert falsos[1].instalaciones == 0  # ya estaba: no se vuelve a descargar
    assert dialogo.result() == QDialog.DialogCode.Accepted


def test_un_error_permite_reintentar(qtbot: QtBot) -> None:
    falsos = [Falso("OCR", fallos=1)]
    dialogo = abrir(qtbot, falsos)

    with qtbot.waitSignal(dialogo.terminado, timeout=ESPERA_MS):
        dialogo.descargar()
    assert estados(dialogo) == [ERROR]
    assert dialogo.mensaje.text() == "No se pudo descargar «OCR»: sin conexión"
    assert dialogo.boton_descargar.text() == "Reintentar"
    assert dialogo.boton_descargar.isEnabled()

    with qtbot.waitSignal(dialogo.terminado, timeout=ESPERA_MS):
        dialogo.boton_descargar.click()
    assert estados(dialogo) == [LISTO]


def test_reintentar_mientras_el_hilo_anterior_acaba(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """El hilo sigue vivo un instante tras avisar del error; el reintento no debe ignorarse (#57)."""
    falsos = [Falso("OCR", fallos=1)]
    dialogo = abrir(qtbot, falsos)
    salir = threading.Event()
    original = dialogo._descargar_todo

    def descargar_y_tardar_en_salir() -> None:
        original()
        salir.wait(ESPERA_MS / 1000)

    monkeypatch.setattr(dialogo, "_descargar_todo", descargar_y_tardar_en_salir)
    with qtbot.waitSignal(dialogo.terminado, timeout=ESPERA_MS):
        dialogo.descargar()
    assert not dialogo.descargando

    salir.set()
    with qtbot.waitSignal(dialogo.terminado, timeout=ESPERA_MS):
        dialogo.boton_descargar.click()
    assert estados(dialogo) == [LISTO]
    assert falsos[0].instalaciones == 2


def test_cancelar_a_mitad(qtbot: QtBot) -> None:
    falso = Falso("Traductor", esperar=True)
    dialogo = abrir(qtbot, [falso])

    dialogo.descargar()
    assert falso.empezado.wait(ESPERA_MS / 1000)
    qtbot.waitUntil(lambda: estados(dialogo) == [DESCARGANDO], timeout=ESPERA_MS)
    assert dialogo.boton_cerrar.text() == "Cancelar"
    dialogo.descargar()  # ya descargando: no hace nada
    with qtbot.waitSignal(dialogo.terminado, timeout=ESPERA_MS):
        dialogo.boton_cerrar.click()

    assert estados(dialogo) == [PENDIENTE]
    assert dialogo.mensaje.text() == "Descarga cancelada."
    assert dialogo.boton_cerrar.text() == "Ahora no"


def test_cerrar_la_ventana_durante_la_descarga_la_cancela(qtbot: QtBot) -> None:
    falso = Falso("Traductor", esperar=True)
    dialogo = abrir(qtbot, [falso])
    dialogo.descargar()
    assert falso.empezado.wait(ESPERA_MS / 1000)
    dialogo.reject()
    assert not dialogo.descargando
    assert dialogo.result() == QDialog.DialogCode.Rejected


def test_ahora_no_cierra_sin_descargar(qtbot: QtBot) -> None:
    falso = Falso("OCR")
    dialogo = abrir(qtbot, [falso])
    dialogo.boton_cerrar.click()
    assert dialogo.result() == QDialog.DialogCode.Rejected
    assert falso.instalaciones == 0


def test_sin_pendientes(qtbot: QtBot) -> None:
    dialogo = abrir(qtbot, [], [Aviso("La sesión no es X11", grave=True)])
    assert not dialogo.boton_descargar.isEnabled()


@pytest.mark.parametrize(("hecho", "total", "maximo"), [(1024**2, 3 * 1024**2, 3072), (500, 0, 0)])
def test_barra_de_progreso(qtbot: QtBot, hecho: int, total: int, maximo: int) -> None:
    dialogo = abrir(qtbot, [Falso("OCR")])
    dialogo.progreso.emit(hecho, total)
    assert dialogo.barra.maximum() == maximo


@pytest.mark.parametrize(("marcada", "creados"), [(True, 1), (False, 0)])
def test_acceso_del_menu_inicio_al_cerrar(qtbot: QtBot, marcada: bool, creados: int) -> None:
    llamadas: list[str] = []

    def crear() -> Path:
        llamadas.append("crear")
        return Path("acceso.lnk")

    dialogo = PrimerArranque([Falso("OCR").componente()], [], acceso=crear)
    qtbot.addWidget(dialogo)
    assert not dialogo.casilla_acceso.isHidden()
    assert dialogo.casilla_acceso.isChecked()
    dialogo.casilla_acceso.setChecked(marcada)

    dialogo.boton_cerrar.click()  # «Ahora no» también lo crea
    dialogo.done(QDialog.DialogCode.Rejected)  # cerrar otra vez no lo repite

    assert len(llamadas) == creados


def test_si_el_acceso_falla_el_dialogo_se_cierra_igual(qtbot: QtBot) -> None:
    def fallar() -> Path:
        raise OSError("sin permiso")

    dialogo = PrimerArranque([], [], acceso=fallar)
    qtbot.addWidget(dialogo)
    dialogo.boton_cerrar.click()
    assert dialogo.result() == QDialog.DialogCode.Rejected


def test_sin_acceso_no_hay_casilla(qtbot: QtBot) -> None:
    dialogo = abrir(qtbot, [Falso("OCR")])
    assert dialogo.casilla_acceso.isHidden()
