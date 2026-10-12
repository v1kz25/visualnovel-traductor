"""Tests del aviso de versión nueva en la interfaz, sin conexión."""

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from vn_audiolibro.actualizaciones import INTERVALO_S, Release
from vn_audiolibro.configuracion import AjustesApp, cargar_ajustes, guardar_ajustes
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.ui.principal import VentanaPrincipal
from vn_audiolibro.ui.versiones import NOTAS, AvisoVersion, BuscadorVersiones, preguntar_si_avisar

from .conftest import ESPERA_MS

URL = "https://github.com/v1kz25/visualnovel-traductor/releases/tag/v0.3.0"
NUEVA = Release("0.3.0", URL, "## Añadido\n- Cosas nuevas")
AHORA = 1_800_000_000.0


@pytest.fixture
def ruta(tmp_path: Path) -> Path:
    return tmp_path / "ajustes.json"


class Consulta:
    def __init__(self, release: Release | None = NUEVA) -> None:
        self.release = release
        self.veces = 0

    def __call__(self) -> Release | None:
        self.veces += 1
        return self.release


@pytest.mark.parametrize(
    ("respuesta", "activado"),
    [(QMessageBox.StandardButton.Yes, True), (QMessageBox.StandardButton.No, False)],
)
def test_la_primera_vez_pregunta(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    ruta: Path,
    respuesta: QMessageBox.StandardButton,
    activado: bool,
) -> None:
    guardar_ajustes(AjustesApp(idioma="en"), ruta)
    monkeypatch.setattr(QMessageBox, "question", lambda *_: respuesta)
    preguntar_si_avisar(None, ruta)  # type: ignore[arg-type]
    assert cargar_ajustes(ruta) == AjustesApp(idioma="en", avisar_versiones=activado)


@pytest.mark.parametrize("activado", [True, False])
def test_si_ya_contesto_no_pregunta(monkeypatch: pytest.MonkeyPatch, ruta: Path, activado: bool) -> None:
    guardar_ajustes(AjustesApp(avisar_versiones=activado), ruta)

    def preguntar(*_: object) -> QMessageBox.StandardButton:
        raise AssertionError("no debería preguntar")

    monkeypatch.setattr(QMessageBox, "question", preguntar)
    preguntar_si_avisar(None, ruta)  # type: ignore[arg-type]


def test_busca_y_avisa(qtbot: QtBot, ruta: Path) -> None:
    guardar_ajustes(AjustesApp(avisar_versiones=True), ruta)
    consulta = Consulta()
    buscador = BuscadorVersiones("0.2.0", consulta, ruta, reloj=lambda: AHORA)
    with qtbot.waitSignal(buscador.encontrada, timeout=ESPERA_MS) as senal:
        assert buscador.iniciar()
    assert senal.args == [NUEVA]
    ajustes = cargar_ajustes(ruta)
    assert (ajustes.ultima_busqueda, ajustes.version_avisada) == (AHORA, "0.3.0")

    # Hoy ya no vuelve a consultar.
    assert not buscador.iniciar()
    assert consulta.veces == 1


def test_sin_version_nueva_apunta_la_busqueda_y_no_avisa(qtbot: QtBot, ruta: Path) -> None:
    guardar_ajustes(AjustesApp(avisar_versiones=True, ultima_busqueda=AHORA - INTERVALO_S), ruta)
    buscador = BuscadorVersiones("0.3.0", Consulta(), ruta, reloj=lambda: AHORA)
    avisos: list[object] = []
    buscador.encontrada.connect(avisos.append)
    with qtbot.waitSignal(buscador.terminada, timeout=ESPERA_MS):
        assert buscador.iniciar()
    assert avisos == []
    assert cargar_ajustes(ruta).ultima_busqueda == AHORA


@pytest.mark.parametrize("activado", [None, False])
def test_desactivado_no_hace_ninguna_peticion(ruta: Path, activado: bool | None) -> None:
    guardar_ajustes(AjustesApp(avisar_versiones=activado), ruta)
    consulta = Consulta()
    assert not BuscadorVersiones("0.2.0", consulta, ruta).iniciar()
    assert consulta.veces == 0


def test_conserva_lo_que_cambio_mientras_buscaba(qtbot: QtBot, ruta: Path) -> None:
    guardar_ajustes(AjustesApp(avisar_versiones=True), ruta)

    def consultar() -> Release | None:
        # Mientras tanto, el usuario cambia el idioma de la app.
        guardar_ajustes(AjustesApp(avisar_versiones=True, idioma="en"), ruta)
        return NUEVA

    buscador = BuscadorVersiones("0.2.0", consultar, ruta, reloj=lambda: AHORA)
    with qtbot.waitSignal(buscador.terminada, timeout=ESPERA_MS):
        buscador.iniciar()
    assert cargar_ajustes(ruta).idioma == "en"


def test_franja_del_aviso(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    abiertas: list[QUrl] = []
    aviso = AvisoVersion(abrir_url=abiertas.append)
    qtbot.addWidget(aviso)
    assert aviso.isHidden()

    aviso.mostrar(NUEVA)
    assert not aviso.isHidden()
    assert "0.3.0" in aviso.texto.text()

    aviso.texto.linkActivated.emit(URL)
    assert abiertas == [QUrl(URL)]

    cajas: list[QMessageBox] = []
    monkeypatch.setattr(QMessageBox, "open", lambda caja: cajas.append(caja))
    aviso.texto.linkActivated.emit(NOTAS)
    (caja,) = cajas
    assert "Cosas nuevas" in caja.text()
    assert "0.3.0" in caja.windowTitle()

    aviso.cerrar.click()
    assert aviso.isHidden()


def test_ventana_principal(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ruta: Path) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("vn_audiolibro.ui.principal.version_instalada", lambda: "0.2.0")
    ventana = VentanaPrincipal(
        AlmacenPerfiles(tmp_path / "juegos"), ruta_ajustes=ruta, consultar_version=Consulta()
    )
    qtbot.addWidget(ventana)
    assert not ventana.avisar_versiones.isChecked()

    ventana.buscar_version_nueva()
    assert ventana.avisar_versiones.isChecked()
    qtbot.waitUntil(lambda: not ventana.aviso_version.isHidden(), timeout=ESPERA_MS)

    ventana.avisar_versiones.setChecked(False)
    assert cargar_ajustes(ruta).avisar_versiones is False
