"""Tests de la ventana de la caché con una caché real en una carpeta temporal."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from vn_audiolibro.cache.modelos import Clave
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.configuracion import AjustesApp, cargar_ajustes, guardar_ajustes
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.ui.cache import JUEGO_BORRADO, VentanaCache

JUEGO = Perfil("Juego", "juego")
BORRADO = "0" * 32


@pytest.fixture
def directorio(tmp_path: Path) -> Path:
    cache = CacheSQLite(tmp_path / "cache")
    for perfil, textos in ((JUEGO.id, ["一", "二"]), (BORRADO, ["三"])):
        for texto in textos:
            clave = Clave(perfil, "zh-Hant", texto)
            cache.guardar_traduccion(clave, "x", "hy-mt2")
            cache.guardar_audio(clave, b"a" * 2000)
    cache.cerrar()
    return tmp_path


@pytest.fixture
def ventana(qtbot: QtBot, directorio: Path) -> VentanaCache:
    almacen = AlmacenPerfiles(directorio / "perfiles")
    almacen.guardar(JUEGO)
    ventana = VentanaCache(almacen, lambda: CacheSQLite(directorio / "cache"), directorio / "ajustes.json")
    qtbot.addWidget(ventana)
    return ventana


def filas(ventana: VentanaCache) -> list[list[str]]:
    return [[ventana.tabla.item(f, c).text() for c in range(3)] for f in range(ventana.tabla.rowCount())]


def responder(monkeypatch: pytest.MonkeyPatch, respuesta: QMessageBox.StandardButton) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *_: respuesta)


def test_muestra_cada_juego_y_el_total(ventana: VentanaCache) -> None:
    assert filas(ventana) == [["Juego", "2", "4 KB"], [JUEGO_BORRADO, "1", "2 KB"]]
    assert ventana.total.text() == "Total: 6 KB"
    assert ventana.limitar.isChecked()
    assert ventana.limite.value() == 2048
    assert not ventana.boton_vaciar.isEnabled()  # nada elegido
    assert ventana.boton_vaciar_todo.isEnabled()


@pytest.mark.parametrize("respuesta", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_vaciar_el_elegido(
    ventana: VentanaCache, monkeypatch: pytest.MonkeyPatch, respuesta: QMessageBox.StandardButton
) -> None:
    responder(monkeypatch, respuesta)
    ventana.tabla.selectRow(0)
    assert ventana.perfil_elegido() == (JUEGO.id, "Juego")
    ventana.boton_vaciar.click()
    esperado = [[JUEGO_BORRADO, "1", "2 KB"]] if respuesta == QMessageBox.StandardButton.Yes else None
    assert filas(ventana) == (esperado or [["Juego", "2", "4 KB"], [JUEGO_BORRADO, "1", "2 KB"]])


def test_vaciar_todo(ventana: VentanaCache, monkeypatch: pytest.MonkeyPatch) -> None:
    responder(monkeypatch, QMessageBox.StandardButton.Yes)
    ventana.boton_vaciar_todo.click()
    assert filas(ventana) == []
    assert ventana.total.text() == "La caché está vacía."
    assert not ventana.boton_vaciar_todo.isEnabled()
    ventana.vaciar_elegido()  # sin nada elegido: no hace nada


def test_cerrar_sin_cambiar_el_limite_no_guarda(ventana: VentanaCache, directorio: Path) -> None:
    ventana.reject()  # botón «Cerrar» o la X de la ventana
    assert not (directorio / "ajustes.json").exists()


def test_bajar_el_limite_lo_guarda_y_recorta(ventana: VentanaCache, directorio: Path) -> None:
    ventana.limite.setValue(100)
    ventana.reject()  # botón «Cerrar» o la X de la ventana
    assert cargar_ajustes(directorio / "ajustes.json") == AjustesApp(limite_cache_mb=100)
    # 100 MB no recorta 6 KB: la caché sigue igual
    cache = CacheSQLite(directorio / "cache")
    assert len(cache.resumen()) == 2
    cache.cerrar()


def test_quitar_el_limite(ventana: VentanaCache, directorio: Path) -> None:
    ventana.limitar.setChecked(False)
    assert not ventana.limite.isEnabled()
    ventana.reject()  # botón «Cerrar» o la X de la ventana
    assert cargar_ajustes(directorio / "ajustes.json").limite_cache_mb is None


def test_abre_sin_limite_si_asi_se_guardo(qtbot: QtBot, directorio: Path) -> None:
    guardar_ajustes(AjustesApp(limite_cache_mb=None), directorio / "ajustes.json")
    ventana = VentanaCache(
        AlmacenPerfiles(directorio / "perfiles"),
        lambda: CacheSQLite(directorio / "cache"),
        directorio / "ajustes.json",
    )
    qtbot.addWidget(ventana)
    assert not ventana.limitar.isChecked()
    assert not ventana.limite.isEnabled()
