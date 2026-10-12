"""Tests de los ajustes de un juego: voz, lectura, volumen y glosario."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QMessageBox, QSpinBox
from pytestqt.qtbot import QtBot

from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import (
    AjustesLectura,
    AjustesVolumen,
    AjustesVoz,
    Perfil,
    PerfilInvalidoError,
)
from vn_audiolibro.traduccion.modelos import Glosario
from vn_audiolibro.ui import ajustes as modulo
from vn_audiolibro.ui.ajustes import NO_TOCAR, SILENCIAR, AjustesJuego, listar_aplicaciones, probar_voz
from vn_audiolibro.voz.modelos import Fragmento, ModoLectura
from vn_audiolibro.voz.piper import Hablante
from vn_audiolibro.voz.volumen import Flujo

from .conftest import ESPERA_MS

PERFIL = Perfil(
    "Juego",
    "juego",
    glosario=Glosario.desde_dict({"櫻": "Sakura"}),
    personajes=(("櫻", None),),
    volumen=AjustesVolumen(nivel_juego=0.5, otras=(("Firefox", 0.0), ("Spotify", 0.4)), excluir=("Discord",)),
)


class CacheFalsa:
    def __init__(self) -> None:
        self.llamadas: list[str] = []

    def invalidar(self, perfil: str) -> int:
        self.llamadas.append(f"invalidar {perfil}")
        return 0

    def borrar_audio(self, perfil: str) -> int:
        self.llamadas.append(f"borrar_audio {perfil}")
        return 0

    def cerrar(self) -> None:
        self.llamadas.append("cerrar")


@pytest.fixture
def almacen(tmp_path: Path) -> AlmacenPerfiles:
    almacen = AlmacenPerfiles(tmp_path)
    almacen.guardar(PERFIL)
    return almacen


@pytest.fixture
def cache() -> CacheFalsa:
    return CacheFalsa()


@pytest.fixture
def probadas() -> list[tuple[AjustesVoz, str]]:
    return []


@pytest.fixture
def dialogo(
    qtbot: QtBot, almacen: AlmacenPerfiles, cache: CacheFalsa, probadas: list[tuple[AjustesVoz, str]]
) -> AjustesJuego:
    def probar(voz: AjustesVoz, destino: str) -> None:
        probadas.append((voz, destino))

    dialogo = AjustesJuego(almacen, PERFIL, lambda: cache, probar, lambda: ["Firefox", "VLC"])  # type: ignore[arg-type,return-value]
    qtbot.addWidget(dialogo)
    return dialogo


def fila(dialogo: AjustesJuego, i: int) -> tuple[QComboBox, QSpinBox]:
    acciones, nivel = dialogo.tabla_apps.cellWidget(i, 1), dialogo.tabla_apps.cellWidget(i, 2)
    assert isinstance(acciones, QComboBox)
    assert isinstance(nivel, QSpinBox)
    return acciones, nivel


def test_se_rellena_con_el_juego(dialogo: AjustesJuego) -> None:
    assert dialogo.windowTitle() == "Ajustes de «Juego»"
    assert dialogo.hablante.currentText() == "Mujer"
    assert dialogo.texto_velocidad.text() == "1,00×"
    assert dialogo.pausa.value() == 2.0
    assert dialogo.bajar.isChecked()
    assert dialogo.texto_nivel.text() == "50 %"
    assert dialogo.aplicaciones() == [
        ("Firefox", SILENCIAR, 0.0),
        ("Spotify", "bajar", 0.4),
        ("Discord", NO_TOCAR, 0.3),
    ]
    assert not fila(dialogo, 0)[1].isEnabled()  # silenciada: sin nivel
    assert dialogo.tabla_glosario.rowCount() == 1


def test_guardar_sin_cambios_no_toca_la_cache(
    dialogo: AjustesJuego, almacen: AlmacenPerfiles, cache: CacheFalsa
) -> None:
    dialogo.guardar()
    assert dialogo.result() == QDialog.DialogCode.Accepted
    assert almacen.cargar(PERFIL.id) == PERFIL
    assert cache.llamadas == []


def test_cambiar_la_voz_borra_el_audio_guardado(
    dialogo: AjustesJuego, almacen: AlmacenPerfiles, cache: CacheFalsa
) -> None:
    dialogo.hablante.setCurrentIndex(dialogo.hablante.findData(Hablante.HOMBRE.value))
    dialogo.velocidad.setValue(125)
    assert dialogo.texto_velocidad.text() == "1,25×"
    dialogo.guardar()

    assert almacen.cargar(PERFIL.id).voz == AjustesVoz(Hablante.HOMBRE, 1.25)
    assert cache.llamadas == [f"borrar_audio {PERFIL.id}", "cerrar"]


@pytest.mark.parametrize("respuesta", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_cambiar_el_glosario_pregunta_si_retraducir(
    dialogo: AjustesJuego,
    almacen: AlmacenPerfiles,
    cache: CacheFalsa,
    monkeypatch: pytest.MonkeyPatch,
    respuesta: QMessageBox.StandardButton,
) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *_: respuesta)
    dialogo.anadir_termino("先輩", "senpai")
    dialogo.anadir_termino("", "")  # fila a medias: no cuenta
    dialogo.guardar()

    glosario = almacen.cargar(PERFIL.id).glosario
    assert glosario == Glosario.desde_dict({"櫻": "Sakura", "先輩": "senpai"})
    if respuesta == QMessageBox.StandardButton.Yes:
        assert cache.llamadas == [f"invalidar {PERFIL.id}", "cerrar"]
    else:
        assert cache.llamadas == []


def test_lectura(dialogo: AjustesJuego, almacen: AlmacenPerfiles) -> None:
    dialogo.modo.setCurrentIndex(dialogo.modo.findData(ModoLectura.ULTIMA.value))
    assert not dialogo.pausa.isEnabled()
    dialogo.modo.setCurrentIndex(dialogo.modo.findData(ModoLectura.COLA.value))
    dialogo.pausa.setValue(1.5)
    dialogo.guardar()
    assert almacen.cargar(PERFIL.id).lectura == AjustesLectura(ModoLectura.COLA, 1.5)


def test_volumen(dialogo: AjustesJuego, almacen: AlmacenPerfiles) -> None:
    dialogo.nivel.setValue(80)
    dialogo.anadir_aplicacion("VLC")
    dialogo.anadir_aplicacion("  firefox ")  # ya está (sin distinguir mayúsculas)
    dialogo.anadir_aplicacion("")
    acciones, nivel = fila(dialogo, 1)  # Spotify: de bajar a silenciar
    acciones.setCurrentIndex(acciones.findData(SILENCIAR))
    assert not nivel.isEnabled()
    dialogo.tabla_apps.setCurrentCell(2, 0)  # quita Discord
    dialogo._quitar_fila(dialogo.tabla_apps)
    dialogo.bajar.setChecked(False)
    assert not dialogo.nivel.isEnabled()
    dialogo.guardar()

    volumen = almacen.cargar(PERFIL.id).volumen
    assert volumen == AjustesVolumen(
        activo=False, nivel_juego=0.8, otras=(("Firefox", 0.0), ("Spotify", 0.0), ("VLC", 0.3)), excluir=()
    )


def test_ver_las_aplicaciones_que_suenan(dialogo: AjustesJuego) -> None:
    dialogo.nueva_app.setEditText("Fi")
    dialogo.buscar_aplicaciones()
    assert [dialogo.nueva_app.itemText(i) for i in range(dialogo.nueva_app.count())] == ["Firefox", "VLC"]
    assert dialogo.nueva_app.currentText() == "Fi"
    dialogo.nueva_app.hidePopup()


def test_glosario_quitar_termino(
    dialogo: AjustesJuego, almacen: AlmacenPerfiles, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.No)
    dialogo.tabla_glosario.setCurrentCell(0, 0)
    dialogo._quitar_fila(dialogo.tabla_glosario)
    dialogo._quitar_fila(dialogo.tabla_glosario)  # sin filas: nada
    dialogo.guardar()
    assert almacen.cargar(PERFIL.id).glosario == Glosario()


def voz_de(dialogo: AjustesJuego, i: int) -> QComboBox:
    voz = dialogo.tabla_personajes.cellWidget(i, 2)
    assert isinstance(voz, QComboBox)
    return voz


def test_voces_de_los_personajes(dialogo: AjustesJuego, almacen: AlmacenPerfiles, cache: CacheFalsa) -> None:
    tabla = dialogo.tabla_personajes
    assert tabla.rowCount() == 1
    assert [tabla.item(0, c).text() for c in (0, 1)] == ["櫻", "Sakura"]  # con su nombre traducido
    assert voz_de(dialogo, 0).currentText() == "La del juego"

    voz_de(dialogo, 0).setCurrentIndex(voz_de(dialogo, 0).findData(Hablante.HOMBRE.value))
    dialogo.anadir_personaje("", None)
    tabla.item(1, 0).setText("小雨")
    dialogo.anadir_personaje("", None)  # fila a medias: no cuenta
    dialogo.guardar()

    assert almacen.cargar(PERFIL.id).personajes == (("櫻", Hablante.HOMBRE), ("小雨", None))
    assert cache.llamadas == []  # el audio guardado sabe con qué voz se sintetizó


def test_personaje_repetido_no_se_guarda(dialogo: AjustesJuego, almacen: AlmacenPerfiles) -> None:
    dialogo.anadir_personaje("櫻", Hablante.MUJER)
    dialogo.guardar()

    assert "sin repetirlo" in dialogo.error.text()
    assert almacen.cargar(PERFIL.id) == PERFIL
    dialogo.tabla_personajes.setCurrentCell(1, 0)
    dialogo._quitar_fila(dialogo.tabla_personajes)
    dialogo.guardar()
    assert dialogo.result() == QDialog.DialogCode.Accepted


def test_escuchar_la_voz(qtbot: QtBot, dialogo: AjustesJuego, probadas: list[tuple[AjustesVoz, str]]) -> None:
    dialogo.velocidad.setValue(150)
    with qtbot.waitSignal(dialogo.prueba_terminada, timeout=ESPERA_MS):
        dialogo.boton_probar.click()
    assert probadas == [(AjustesVoz(Hablante.MUJER, 1.5), "es")]
    assert dialogo.boton_probar.isEnabled()
    assert dialogo.error.text() == ""


def test_juego_en_ingles_prueba_la_voz_inglesa_y_pide_el_glosario_en_ingles(
    qtbot: QtBot, almacen: AlmacenPerfiles
) -> None:
    probadas: list[str] = []
    perfil = replace(PERFIL, destino="en")
    dialogo = AjustesJuego(almacen, perfil, probar=lambda _, d: probadas.append(d), aplicaciones=lambda: [])
    qtbot.addWidget(dialogo)
    with qtbot.waitSignal(dialogo.prueba_terminada, timeout=ESPERA_MS):
        dialogo.probar()
    assert probadas == ["en"]
    assert any("(Inglés)" in etiqueta.text() for etiqueta in dialogo.findChildren(QLabel))


def test_escuchar_la_voz_con_error(qtbot: QtBot, almacen: AlmacenPerfiles) -> None:
    def falla(_: AjustesVoz, __: str) -> None:
        raise RuntimeError("sin paplay")

    dialogo = AjustesJuego(almacen, PERFIL, probar=falla, aplicaciones=lambda: [])
    qtbot.addWidget(dialogo)
    with qtbot.waitSignal(dialogo.prueba_terminada, timeout=ESPERA_MS):
        dialogo.probar()
    assert dialogo.error.text() == "No se pudo probar la voz: sin paplay"


def test_error_al_guardar(
    dialogo: AjustesJuego, monkeypatch: pytest.MonkeyPatch, almacen: AlmacenPerfiles
) -> None:
    def falla(_: Perfil) -> Path:
        raise PerfilInvalidoError("disco lleno")

    monkeypatch.setattr(almacen, "guardar", falla)
    dialogo.guardar()
    assert dialogo.error.text() == "disco lleno"
    assert dialogo.guardado is None


# Funciones reales, con Piper, paplay y PulseAudio sustituidos


@pytest.mark.parametrize(
    ("destino", "hablante", "modelo", "hablante_piper", "frase"),
    [
        ("es", Hablante.HOMBRE, "es_ES-sharvard-medium.onnx", Hablante.HOMBRE, "Hola."),
        ("en", Hablante.HOMBRE, "en_US-john-medium.onnx", None, "Hello."),
        ("en", Hablante.MUJER, "en_US-kristin-medium.onnx", None, "Hello."),
    ],
)
def test_probar_voz(
    monkeypatch: pytest.MonkeyPatch,
    destino: str,
    hablante: Hablante,
    modelo: str,
    hablante_piper: Hablante | None,
    frase: str,
) -> None:
    escrito: list[int] = []
    leidas: list[str] = []
    fragmentos = [Fragmento(np.ones(10, dtype=np.int16), 22050), Fragmento(np.ones(5, dtype=np.int16), 22050)]
    salida = SimpleNamespace(
        escribir=lambda pcm: escrito.append(len(pcm)), terminar=lambda: escrito.append(-1)
    )
    creados: list[tuple[object, ...]] = []

    def sintetizador(*args: object) -> SimpleNamespace:
        creados.append(args)

        def sintetizar(texto: str) -> object:
            leidas.append(texto)
            return iter(fragmentos)

        return SimpleNamespace(sintetizar=sintetizar)

    monkeypatch.setattr(modulo, "asegurar_voz", lambda voz: Path(voz.modelo.fichero))
    monkeypatch.setattr(modulo, "SintetizadorPiper", sintetizador)
    monkeypatch.setattr(modulo, "reproductor", lambda: SimpleNamespace(abrir=lambda _: salida))

    probar_voz(AjustesVoz(hablante, 1.2), destino)

    assert creados == [(Path(modelo), hablante_piper, 1.2)]
    assert leidas[0].startswith(frase)
    assert escrito == [10, 5, -1]


def test_listar_aplicaciones(monkeypatch: pytest.MonkeyPatch) -> None:
    cerrados: list[bool] = []
    flujos = [
        Flujo(1, "firefox", "firefox", 1, (1.0,)),
        Flujo(2, "VLC", "vlc", 2, (1.0,)),
        Flujo(3, "vn-audiolibro", "paplay", 3, (1.0,)),
        Flujo(4, "", "", 4, (1.0,)),
        Flujo(5, "VLC", "vlc", 2, (1.0,)),
    ]
    cliente = SimpleNamespace(flujos=lambda: flujos, cerrar=lambda: cerrados.append(True))
    monkeypatch.setattr(modulo, "cliente_audio", lambda: cliente)
    assert listar_aplicaciones() == ["firefox", "VLC"]
    assert cerrados == [True]


def test_listar_aplicaciones_sin_servidor(monkeypatch: pytest.MonkeyPatch) -> None:
    def falla() -> None:
        raise RuntimeError("sin PulseAudio")

    monkeypatch.setattr(modulo, "cliente_audio", falla)
    assert listar_aplicaciones() == []


def test_subtitulos(dialogo: AjustesJuego, almacen: AlmacenPerfiles) -> None:
    from vn_audiolibro.perfiles.modelos import AjustesSubtitulos, PosicionSubtitulos

    assert not dialogo.subtitulos.isChecked()  # desactivados por defecto
    assert not dialogo.posicion.isEnabled()

    dialogo.subtitulos.setChecked(True)
    dialogo.tamano.setValue(30)
    dialogo.opacidad.setValue(40)
    assert dialogo.texto_opacidad.text() == "40 %"
    dialogo.posicion.setCurrentIndex(dialogo.posicion.findData(PosicionSubtitulos.TAPAR.value))
    assert not dialogo.opacidad.isEnabled()  # al tapar, el fondo es opaco
    dialogo.guardar()

    guardado = almacen.cargar(PERFIL.id).subtitulos
    assert guardado == AjustesSubtitulos(True, PosicionSubtitulos.TAPAR, 30, 0.4)
