"""Tests del editor de juegos con ventanas, captura y OCR falsos."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox
from pytestqt.qtbot import QtBot

from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, Imagen, Rectangulo, Ventana, ZonaRelativa
from vn_audiolibro.ocr.lector import AjustesLector, TextoLeido
from vn_audiolibro.ocr.preprocesado import Orientacion
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import AjustesVoz, Color, Perfil
from vn_audiolibro.ui import editor as modulo
from vn_audiolibro.ui.editor import EditorJuego, LectorBajoDemanda, capturar_ventana, listar_ventanas
from vn_audiolibro.voz.piper import Hablante

from .conftest import ESPERA_MS

JUEGO = Ventana(0x10, "Mi juego ver. 1.0", 100, Rectangulo(0, 0, 200, 100))
OTRA = Ventana(0x20, "Navegador", 200, Rectangulo(0, 0, 800, 600))


class Falsos:
    """Captura y OCR falsos que apuntan con qué se les llama."""

    def __init__(self) -> None:
        self.leidos: list[tuple[tuple[int, ...], AjustesLector]] = []

    def capturar(self, ventana: Ventana) -> Imagen:
        return np.full((100, 200, 3), 50, dtype=np.uint8)

    def leer(self, imagen: Imagen, ajustes: AjustesLector) -> str:
        self.leidos.append((imagen.shape, ajustes))
        return "你好"


@pytest.fixture
def almacen(tmp_path: Path) -> AlmacenPerfiles:
    return AlmacenPerfiles(tmp_path)


@pytest.fixture
def falsos() -> Falsos:
    return Falsos()


def abrir(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos, perfil: Perfil | None = None
) -> EditorJuego:
    editor = EditorJuego(almacen, perfil, lambda: [JUEGO, OTRA], falsos.capturar, falsos.leer)
    qtbot.addWidget(editor)
    return editor


def boton_guardar(editor: EditorJuego) -> object:
    return editor.botones.button(QDialogButtonBox.StandardButton.Save)


def test_anadir_un_juego(qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos) -> None:
    editor = abrir(qtbot, almacen, falsos)
    assert editor.windowTitle() == "Añadir juego"
    assert not boton_guardar(editor).isEnabled()  # type: ignore[attr-defined]
    assert not editor.boton_probar.isEnabled()

    editor.ventanas.setCurrentIndex(0)
    editor.ventanas.activated.emit(0)
    assert editor.titulo.text() == "Mi juego ver. 1.0"
    assert editor.nombre.text() == "Mi juego ver. 1.0"
    editor.nombre.setText("Mi juego")
    editor.titulo.setText("mi juego")
    editor.idioma.setCurrentIndex(editor.idioma.findData("ja"))
    assert editor.destino.currentText() == "Español"
    editor.destino.setCurrentIndex(editor.destino.findData("en"))
    editor.color.setCurrentIndex(editor.color.findData(Color.OSCURO.value))
    editor.orientacion.setCurrentIndex(editor.orientacion.findData(Orientacion.VERTICAL.value))

    editor.boton_capturar.click()
    assert editor.selector.hay_imagen
    editor.selector.poner_zona(ZonaRelativa(0.1, 0.5, 0.5, 0.5))
    with qtbot.waitSignal(editor.texto_leido, timeout=ESPERA_MS):
        editor.boton_probar.click()
    assert editor.resultado.text() == "Texto leído: 你好"
    forma, ajustes = falsos.leidos[0]
    assert forma == (50, 100, 3)  # solo la zona
    assert (ajustes.idioma, ajustes.orientacion) == ("ja", Orientacion.VERTICAL)

    editor.botones.button(QDialogButtonBox.StandardButton.Save).click()

    assert editor.result() == QDialog.DialogCode.Accepted
    (guardado,) = almacen.listar()
    assert guardado == editor.guardado
    assert (guardado.nombre, guardado.ventana, guardado.idioma) == ("Mi juego", "mi juego", "ja")
    assert guardado.destino == "en"
    assert (guardado.color, guardado.orientacion) == (Color.OSCURO, Orientacion.VERTICAL)
    assert guardado.zona == ZonaRelativa(0.1, 0.5, 0.5, 0.5)


def test_sin_zona_se_usa_toda_la_ventana_y_el_boton_la_pone(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos
) -> None:
    editor = abrir(qtbot, almacen, falsos)
    editor.nombre.setText("Juego")
    editor.titulo.setText("juego")
    editor.guardar()
    assert almacen.listar()[0].zona == TODA_LA_VENTANA

    editor.boton_capturar.click()
    editor.boton_toda.click()
    assert editor.selector.zona == TODA_LA_VENTANA


def test_editar_conserva_el_resto_de_ajustes(qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos) -> None:
    zona = ZonaRelativa(0.1, 0.1, 0.8, 0.3)
    perfil = Perfil(
        "Mi juego", "mi juego", destino="en", zona=zona, color=Color.OSCURO, voz=AjustesVoz(Hablante.HOMBRE)
    )
    almacen.guardar(perfil)
    editor = abrir(qtbot, almacen, falsos, perfil)

    assert editor.windowTitle() == "Editar juego"
    assert editor.nombre.text() == "Mi juego"
    assert editor.ventana_elegida() == JUEGO  # la abierta que coincide con el título
    assert editor.selector.zona == perfil.zona
    assert editor.color.currentText() == "Oscuro sobre fondo claro"
    assert editor.destino.currentText() == "Inglés"
    editor.nombre.setText("Mi juego (renombrado)")
    editor.guardar()

    (guardado,) = almacen.listar()
    assert guardado.id == perfil.id
    assert guardado.nombre == "Mi juego (renombrado)"
    assert guardado.voz.hablante == Hablante.HOMBRE
    assert (guardado.color, guardado.destino) == (Color.OSCURO, "en")


def test_nombre_repetido_o_no_valido_no_cierra(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos
) -> None:
    almacen.guardar(Perfil("Juego", "juego"))
    editor = abrir(qtbot, almacen, falsos)
    editor.nombre.setText("juego")
    editor.titulo.setText("otro")
    editor.guardar()
    assert "Ya hay un juego" in editor.error.text()
    assert editor.guardado is None

    editor.nombre.setText("x" * 100)
    editor.guardar()
    assert "80 caracteres" in editor.error.text()


def test_errores_al_listar_capturar_o_leer(qtbot: QtBot, almacen: AlmacenPerfiles) -> None:
    def falla(*_: object) -> None:
        raise RuntimeError("sin X11")

    editor = EditorJuego(almacen, None, falla, falla, falla)  # type: ignore[arg-type]
    qtbot.addWidget(editor)
    assert "No se pudieron listar las ventanas: sin X11" in editor.error.text()

    editor = EditorJuego(almacen, None, lambda: [JUEGO], falla, falla)  # type: ignore[arg-type]
    qtbot.addWidget(editor)
    editor.boton_capturar.click()
    assert "No se pudo capturar la ventana: sin X11" in editor.error.text()
    editor.probar_ocr()  # sin captura: no hace nada

    editor._capturar = lambda _: np.zeros((10, 10, 3), dtype=np.uint8)
    editor.boton_capturar.click()
    with qtbot.waitSignal(editor.texto_leido, timeout=ESPERA_MS):
        editor.boton_probar.click()
    assert "No se pudo leer: sin X11" in editor.resultado.text()


def test_ocr_sin_texto(qtbot: QtBot, almacen: AlmacenPerfiles) -> None:
    editor = EditorJuego(almacen, None, lambda: [JUEGO], Falsos().capturar, lambda *_: "")
    qtbot.addWidget(editor)
    editor.boton_capturar.click()
    with qtbot.waitSignal(editor.texto_leido, timeout=ESPERA_MS):
        editor.probar_ocr()
    assert "no se ha reconocido texto" in editor.resultado.text()


def test_actualizar_conserva_la_ventana_elegida(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos
) -> None:
    editor = abrir(qtbot, almacen, falsos)
    editor.ventanas.setCurrentIndex(1)
    editor.boton_actualizar.click()
    assert editor.ventana_elegida() == OTRA


# Piezas reales, con X11 y el OCR sustituidos


def test_lector_bajo_demanda_carga_el_modelo_una_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    cargas: list[Path] = []
    monkeypatch.setattr(modulo, "asegurar_descarga", lambda _: Path("rec.onnx"))
    monkeypatch.setattr(modulo, "ReconocedorRapidOCR", lambda modelo: cargas.append(modelo) or "reconocedor")
    monkeypatch.setattr(
        modulo, "LectorOCR", lambda r, a: SimpleNamespace(leer=lambda _: TextoLeido((f"{r}:{a.idioma}",)))
    )
    lector = LectorBajoDemanda()
    imagen = np.zeros((4, 4, 3), dtype=np.uint8)

    assert lector(imagen, AjustesLector("ja")) == "reconocedor:ja"
    assert lector(imagen, AjustesLector("zh-Hant")) == "reconocedor:zh-Hant"
    assert cargas == [Path("rec.onnx")]


def test_listar_ventanas_quita_las_propias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modulo, "gestor_ventanas", lambda: SimpleNamespace(listar=lambda: [JUEGO, OTRA]))
    monkeypatch.setattr(modulo, "pids_propios", lambda: frozenset({200}))
    assert listar_ventanas() == [JUEGO]


def test_capturar_ventana_entera(monkeypatch: pytest.MonkeyPatch) -> None:
    pedidas: list[tuple[int, Rectangulo]] = []

    class CapturadorFalso:
        def __init__(self, ventanas: object) -> None:
            assert ventanas is gestor

        def capturar(self, id_ventana: int, zona: Rectangulo) -> Imagen:
            pedidas.append((id_ventana, zona))
            return np.zeros((zona.alto, zona.ancho, 3), dtype=np.uint8)

    gestor = SimpleNamespace(geometria=lambda _: Rectangulo(10, 20, 300, 150))
    monkeypatch.setattr(modulo, "gestor_ventanas", lambda: gestor)
    monkeypatch.setattr(modulo, "capturador", CapturadorFalso)

    assert capturar_ventana(JUEGO).shape == (150, 300, 3)
    assert pedidas == [(0x10, Rectangulo(0, 0, 300, 150))]
