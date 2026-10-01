"""Tests del editor de juegos con ventanas, captura y OCR falsos."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit
from pytestqt.qtbot import QtBot

from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, Imagen, Rectangulo, Ventana, ZonaRelativa
from vn_audiolibro.guion.modelos import OrigenGuion
from vn_audiolibro.ocr.lector import AjustesLector, TextoLeido
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import AjustesGuion, AjustesVoz, Color, Perfil
from vn_audiolibro.traduccion.gemini import URL_CLAVES
from vn_audiolibro.traduccion.modelos import Motor
from vn_audiolibro.ui import editor as modulo
from vn_audiolibro.ui.editor import EditorJuego, LectorBajoDemanda, capturar_ventana, listar_ventanas
from vn_audiolibro.voz.piper import Hablante

from ..guion.sinteticos import juego
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
    qtbot: QtBot,
    almacen: AlmacenPerfiles,
    falsos: Falsos,
    perfil: Perfil | None = None,
    carpeta_juego: Path | None = None,
    elegida: str = "",
) -> EditorJuego:
    editor = EditorJuego(
        almacen,
        perfil,
        lambda: [JUEGO, OTRA],
        falsos.capturar,
        falsos.leer,
        pedir_carpeta=lambda _padre, _desde: elegida,
        carpeta_juego=lambda _pid: carpeta_juego,
    )
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
    assert editor.busqueda.currentData() == BusquedaTexto.COLOR.value
    editor.busqueda.setCurrentIndex(editor.busqueda.findData(BusquedaTexto.DETECTOR.value))

    editor.boton_capturar.click()
    assert editor.selector.hay_imagen
    editor.selector.poner_zona(ZonaRelativa(0.1, 0.5, 0.5, 0.5))
    with qtbot.waitSignal(editor.texto_leido, timeout=ESPERA_MS):
        editor.boton_probar.click()
    assert editor.resultado.text() == "Texto leído: 你好"
    forma, ajustes = falsos.leidos[0]
    assert forma == (50, 100, 3)  # solo la zona
    assert (ajustes.idioma, ajustes.orientacion) == ("ja", Orientacion.VERTICAL)
    assert ajustes.busqueda is BusquedaTexto.DETECTOR

    editor.botones.button(QDialogButtonBox.StandardButton.Save).click()

    assert editor.result() == QDialog.DialogCode.Accepted
    (guardado,) = almacen.listar()
    assert guardado == editor.guardado
    assert (guardado.nombre, guardado.ventana, guardado.idioma) == ("Mi juego", "mi juego", "ja")
    assert guardado.destino == "en"
    assert (guardado.color, guardado.orientacion) == (Color.OSCURO, Orientacion.VERTICAL)
    assert guardado.busqueda is BusquedaTexto.DETECTOR
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


def test_un_juego_en_ingles_solo_se_traduce_al_espanol_y_en_horizontal(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos
) -> None:
    editor = abrir(qtbot, almacen, falsos)
    editor.destino.setCurrentIndex(editor.destino.findData("en"))
    editor.orientacion.setCurrentIndex(editor.orientacion.findData(Orientacion.VERTICAL.value))

    editor.idioma.setCurrentIndex(editor.idioma.findData("en"))
    assert editor.idioma.currentText() == "Inglés"
    assert (editor.destino.currentData(), editor.orientacion.currentData()) == ("es", "horizontal")
    assert not editor.destino.isEnabled()
    assert not editor.orientacion.isEnabled()

    editor.idioma.setCurrentIndex(editor.idioma.findData("ja"))
    assert editor.destino.isEnabled()
    assert editor.orientacion.isEnabled()


def test_gemini_pide_la_clave_y_la_guarda_en_el_llavero(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos
) -> None:
    from vn_audiolibro import claves

    editor = abrir(qtbot, almacen, falsos)
    editor.nombre.setText("Juego")
    editor.titulo.setText("juego")
    assert editor.clave.isHidden()  # con el traductor local no hay clave que poner

    editor.traductor.setCurrentIndex(editor.traductor.findData(Motor.GEMINI.value))
    assert not editor.clave.isHidden()
    assert editor.clave.echoMode() is QLineEdit.EchoMode.Password
    assert f'<a href="{URL_CLAVES}">' in editor.aviso_gemini.text()  # el enlace para crear la clave
    editor.guardar()
    assert "clave de API" in editor.error.text()  # sin clave no se puede elegir Gemini
    assert almacen.listar() == []

    editor.clave.setText(" clave-123 ")
    editor.guardar()

    assert claves.leer() == "clave-123"
    (guardado,) = almacen.listar()
    assert guardado.traductor is Motor.GEMINI
    assert editor.clave.text() == ""


def test_editar_un_juego_con_gemini_y_clave_guardada(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos
) -> None:
    from vn_audiolibro import claves

    claves.guardar("clave-123")
    perfil = Perfil("Juego", "juego", traductor=Motor.GEMINI)
    almacen.guardar(perfil)
    editor = abrir(qtbot, almacen, falsos, perfil)

    assert editor.traductor.currentData() == Motor.GEMINI.value
    assert "Guardada" in editor.clave.placeholderText()
    editor.guardar()  # no hace falta volver a escribirla
    assert editor.guardado is not None
    assert claves.leer() == "clave-123"


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
    cargas: list[tuple[Path, Path | None]] = []

    def reconocedor(modelo: Path, detector: Path | None) -> SimpleNamespace:
        cargas.append((modelo, detector))
        return SimpleNamespace(con_detector=detector is not None, nombre=f"r{len(cargas)}")

    def lector_ocr(r: SimpleNamespace, a: AjustesLector, d: SimpleNamespace | None) -> SimpleNamespace:
        texto = f"{r.nombre}:{a.idioma}:{d is r}"
        return SimpleNamespace(leer=lambda _: TextoLeido((texto,)))

    monkeypatch.setattr(modulo, "asegurar_descarga", lambda descarga: Path(descarga.fichero))
    monkeypatch.setattr(modulo, "ReconocedorRapidOCR", reconocedor)
    monkeypatch.setattr(modulo, "LectorOCR", lector_ocr)
    lector = LectorBajoDemanda()
    imagen = np.zeros((4, 4, 3), dtype=np.uint8)
    detector = AjustesLector("ja", busqueda=BusquedaTexto.DETECTOR)

    assert lector(imagen, AjustesLector("ja")) == "r1:ja:False"
    assert lector(imagen, AjustesLector("zh-Hant")) == "r1:zh-Hant:False"
    # El detector solo se carga al hacer falta, y después sirve también para buscar por color.
    assert lector(imagen, detector) == "r2:ja:True"
    assert lector(imagen, AjustesLector("ja")) == "r2:ja:False"
    rec, det = Path("ch_PP-OCRv5_rec_mobile.onnx"), Path("ch_PP-OCRv5_det_mobile.onnx")
    assert cargas == [(rec, None), (rec, det)]


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


# Guion


def test_elegir_el_guion_y_guardarlo(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos, tmp_path: Path
) -> None:
    carpeta = juego(tmp_path)
    editor = abrir(qtbot, almacen, falsos, elegida=str(carpeta))
    editor.nombre.setText("Juego")
    editor.titulo.setText("juego")
    assert not editor.origen_guion.isEnabled()

    editor.boton_guion.click()

    assert editor.carpeta_guion.text() == str(carpeta)
    assert "7 párrafos, con la traducción oficial al inglés" in editor.estado_guion.text()
    assert editor.origen_guion.isEnabled()
    editor.origen_guion.setCurrentIndex(editor.origen_guion.findData(OrigenGuion.INGLES.value))
    boton_guardar(editor).click()  # type: ignore[attr-defined]

    assert almacen.buscar("Juego").guion == AjustesGuion(str(carpeta), OrigenGuion.INGLES)


def test_carpeta_sin_guion_o_cancelar(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos, tmp_path: Path
) -> None:
    editor = abrir(qtbot, almacen, falsos)
    editor.boton_guion.click()  # cancelado: no cambia nada
    assert editor.carpeta_guion.text() == ""

    editor.carpeta_guion.setText(str(tmp_path))
    editor.comprobar_guion()
    assert "No se ha encontrado el guion" in editor.estado_guion.text()

    editor.carpeta_guion.setText("")
    editor.comprobar_guion()
    assert "Opcional" in editor.estado_guion.text()
    editor.nombre.setText("Juego")
    editor.titulo.setText("juego")
    boton_guardar(editor).click()  # type: ignore[attr-defined]
    assert almacen.buscar("Juego").guion is None


def test_al_elegir_la_ventana_encuentra_el_guion_del_juego(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos, tmp_path: Path
) -> None:
    carpeta = juego(tmp_path)
    editor = abrir(qtbot, almacen, falsos, carpeta_juego=carpeta)

    editor.ventanas.setCurrentIndex(0)
    editor.ventanas.activated.emit(0)

    assert editor.carpeta_guion.text() == str(carpeta)
    assert "Guion encontrado" in editor.estado_guion.text()


def test_al_elegir_la_ventana_sin_guion_no_pone_nada(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos, tmp_path: Path
) -> None:
    editor = abrir(qtbot, almacen, falsos, carpeta_juego=tmp_path)

    editor.ventanas.setCurrentIndex(0)
    editor.ventanas.activated.emit(0)

    assert editor.carpeta_guion.text() == ""


def test_editar_muestra_el_guion(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos, tmp_path: Path
) -> None:
    carpeta = juego(tmp_path)
    perfil = Perfil("Juego", "juego", guion=AjustesGuion(str(carpeta), OrigenGuion.INGLES))
    editor = abrir(qtbot, almacen, falsos, perfil, carpeta_juego=tmp_path / "otra")

    assert editor.carpeta_guion.text() == str(carpeta)
    assert editor.origen_guion.currentData() == OrigenGuion.INGLES.value
    assert "Guion encontrado" in editor.estado_guion.text()


def test_elegir_carpeta_parte_de_steam(monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, tmp_path: Path) -> None:
    pedidas: list[str] = []
    monkeypatch.setattr(modulo, "STEAM", tmp_path)
    monkeypatch.setattr(
        modulo.QFileDialog, "getExistingDirectory", lambda _padre, _titulo, desde: pedidas.append(desde) or ""
    )

    assert modulo.elegir_carpeta(None, "") == ""  # type: ignore[arg-type]
    assert modulo.elegir_carpeta(None, "/juegos") == ""  # type: ignore[arg-type]
    assert pedidas == [str(tmp_path), "/juegos"]


def test_editar_un_juego_abierto_sin_guion_lo_encuentra(
    qtbot: QtBot, almacen: AlmacenPerfiles, falsos: Falsos, tmp_path: Path
) -> None:
    carpeta = juego(tmp_path)
    editor = abrir(qtbot, almacen, falsos, Perfil("Juego", "mi juego"), carpeta_juego=carpeta)

    assert editor.carpeta_guion.text() == str(carpeta)
    assert "Guion encontrado" in editor.estado_guion.text()
