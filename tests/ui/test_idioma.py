"""La interfaz en inglés: ningún texto visible se queda en español, y el idioma se elige en la app."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QTableWidget,
    QTabWidget,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.conftest import parece_espanol
from vn_audiolibro import textos
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.captura.modelos import Rectangulo, Ventana
from vn_audiolibro.configuracion import AjustesApp, cargar_ajustes, guardar_ajustes
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import AjustesVolumen, Perfil
from vn_audiolibro.preparacion import Aviso, Componente
from vn_audiolibro.ui import app
from vn_audiolibro.ui.ajustes import AjustesJuego
from vn_audiolibro.ui.cache import VentanaCache
from vn_audiolibro.ui.editor import EditorJuego
from vn_audiolibro.ui.preparacion import PrimerArranque
from vn_audiolibro.ui.principal import VentanaPrincipal
from vn_audiolibro.ui.puente import PuenteSesion

from .conftest import Fabrica

PERFIL = Perfil("Moon", "moon", volumen=AjustesVolumen(otras=(("Firefox", 0.3),), excluir=("VLC",)))
PERMITIDOS = {"Español"}
"""Textos que no se traducen a propósito: el nombre de cada idioma va en ese idioma."""


def textos_visibles(raiz: QWidget) -> list[str]:
    """Los textos que el usuario puede ver en una ventana y en todo lo que contiene."""
    vistos = [raiz.windowTitle()]
    for widget in (raiz, *raiz.findChildren(QWidget)):
        vistos.append(widget.toolTip())
        if isinstance(widget, QLabel | QAbstractButton):
            vistos.append(widget.text())
        elif isinstance(widget, QLineEdit):
            vistos.append(widget.placeholderText())
        elif isinstance(widget, QComboBox):
            vistos += [widget.itemText(i) for i in range(widget.count())]
        elif isinstance(widget, QTabWidget):
            vistos += [widget.tabText(i) for i in range(widget.count())]
        elif isinstance(widget, QTableWidget):
            cabeceras = (widget.horizontalHeaderItem(i) for i in range(widget.columnCount()))
            vistos += [cabecera.text() for cabecera in cabeceras if cabecera is not None]
        elif isinstance(widget, QListWidget):
            vistos += [widget.item(i).toolTip() for i in range(widget.count())]
    return [texto for texto in vistos if texto and texto not in PERMITIDOS]


@pytest.fixture
def almacen(tmp_path: Path) -> AlmacenPerfiles:
    almacen = AlmacenPerfiles(tmp_path / "juegos")
    almacen.guardar(PERFIL)
    return almacen


def ventanas(almacen: AlmacenPerfiles, tmp_path: Path) -> list[QWidget]:
    """Todas las ventanas de la app, con datos de prueba en inglés."""
    abrir_cache = lambda: CacheSQLite(tmp_path / "cache")  # noqa: E731
    juego = Ventana(0x10, "Moon", 100, Rectangulo(0, 0, 200, 100))
    componente = Componente("OCR", "use", "MIT", 1024, lambda: False, lambda progreso, cancelado: None)
    return [
        VentanaPrincipal(almacen, PuenteSesion(Fabrica()), ruta_ajustes=tmp_path / "ajustes.json"),
        EditorJuego(almacen, PERFIL, lambda: [juego], lambda ventana: None, lambda imagen, ajustes: ""),  # type: ignore[arg-type,return-value]
        EditorJuego(almacen, None, lambda: [juego]),
        AjustesJuego(almacen, PERFIL, abrir_cache, lambda ajustes, destino: None, lambda: []),
        VentanaCache(almacen, abrir_cache, tmp_path / "ajustes.json"),
        PrimerArranque([componente], [Aviso("x", grave=False)], acceso=lambda: tmp_path),
    ]


def test_en_ingles_no_queda_nada_en_espanol(qtbot: QtBot, almacen: AlmacenPerfiles, tmp_path: Path) -> None:
    textos.activar("en")
    espanol = []
    for ventana in ventanas(almacen, tmp_path):
        qtbot.addWidget(ventana)
        espanol += [texto for texto in textos_visibles(ventana) if parece_espanol(texto)]
    assert espanol == []


def test_en_espanol_el_detector_encuentra_los_textos(
    qtbot: QtBot, almacen: AlmacenPerfiles, tmp_path: Path
) -> None:
    """Comprueba el propio test: sin traducir, casi todo parece español."""
    for ventana in ventanas(almacen, tmp_path):
        qtbot.addWidget(ventana)
        assert any(parece_espanol(texto) for texto in textos_visibles(ventana)), ventana


def test_elegir_idioma_en_la_ventana_principal(
    qtbot: QtBot, almacen: AlmacenPerfiles, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ruta = tmp_path / "ajustes.json"
    guardar_ajustes(AjustesApp(limite_cache_mb=500), ruta)
    avisos: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda padre, titulo, texto: avisos.append(texto))
    ventana = VentanaPrincipal(almacen, PuenteSesion(Fabrica()), ruta_ajustes=ruta)
    qtbot.addWidget(ventana)
    assert ventana.idioma.currentData() is None  # el del sistema
    assert [ventana.idioma.itemText(i) for i in range(1, ventana.idioma.count())] == ["Español", "English"]

    ventana.idioma.setCurrentIndex(ventana.idioma.findData("en"))
    ventana.idioma.activated.emit(ventana.idioma.currentIndex())
    assert cargar_ajustes(ruta) == AjustesApp(limite_cache_mb=500, idioma="en")
    assert avisos == ["The language will change the next time you open vn-audiolibro."]
    assert textos.activo() == "es"  # no cambia hasta volver a abrir

    ventana.cambiar_idioma("en")  # el mismo: no avisa otra vez
    ventana.cambiar_idioma(None)  # el del sistema, que en los tests es el español
    assert cargar_ajustes(ruta).idioma is None
    assert avisos[1:] == ["El idioma cambiará la próxima vez que abras vn-audiolibro."]

    otra = VentanaPrincipal(almacen, PuenteSesion(Fabrica()), ruta_ajustes=ruta)
    qtbot.addWidget(otra)
    guardar_ajustes(AjustesApp(idioma="en"), ruta)
    otra = VentanaPrincipal(almacen, PuenteSesion(Fabrica()), ruta_ajustes=ruta)
    qtbot.addWidget(otra)
    assert otra.idioma.currentData() == "en"


def test_textos_de_qt_en_ingles(qapp: object) -> None:
    textos.activar("en")
    traductor = app.instalar_traduccion(qapp)  # type: ignore[arg-type]
    assert traductor is not None
    qapp.removeTranslator(traductor)  # type: ignore[attr-defined]
