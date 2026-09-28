"""Tests de la ventana principal con perfiles en una carpeta temporal y una sesión falsa."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from pytestqt.qtbot import QtBot

from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego
from vn_audiolibro.ui.principal import MAX_LINEAS, VentanaPrincipal
from vn_audiolibro.ui.puente import PuenteSesion

from .conftest import ESPERA_MS, Fabrica


class CacheFalsa:
    def __init__(self) -> None:
        self.invalidados: list[str] = []
        self.cerrada = False

    def invalidar(self, perfil: str) -> int:
        self.invalidados.append(perfil)
        return 3

    def cerrar(self) -> None:
        self.cerrada = True


@pytest.fixture
def almacen(tmp_path: Path) -> AlmacenPerfiles:
    almacen = AlmacenPerfiles(tmp_path)
    almacen.guardar(Perfil("Zeta", "zeta"))
    almacen.guardar(Perfil("Alfa", "alfa"))
    return almacen


@pytest.fixture
def fabrica() -> Fabrica:
    return Fabrica()


@pytest.fixture
def cache() -> CacheFalsa:
    return CacheFalsa()


@pytest.fixture
def ventana(qtbot: QtBot, almacen: AlmacenPerfiles, fabrica: Fabrica, cache: CacheFalsa) -> VentanaPrincipal:
    ventana = VentanaPrincipal(almacen, PuenteSesion(fabrica), lambda: cache)  # type: ignore[arg-type,return-value]
    qtbot.addWidget(ventana)
    return ventana


def jugar(qtbot: QtBot, ventana: VentanaPrincipal) -> None:
    with qtbot.waitSignal(ventana.puente.iniciada, timeout=ESPERA_MS):
        ventana.boton_jugar.click()


def textos(ventana: VentanaPrincipal) -> list[str]:
    """Líneas del historial en texto plano: original y traducción alternadas."""
    return ventana.historial.toPlainText().splitlines()


def test_lista_los_perfiles_por_nombre(ventana: VentanaPrincipal) -> None:
    nombres = [ventana.lista_perfiles.item(i).text() for i in range(ventana.lista_perfiles.count())]
    assert nombres == ["Alfa", "Zeta"]
    assert ventana.perfil_elegido() is not None
    assert ventana.boton_jugar.isEnabled()
    assert not ventana.boton_detener.isEnabled()


def test_sin_perfiles(qtbot: QtBot, tmp_path: Path) -> None:
    ventana = VentanaPrincipal(AlmacenPerfiles(tmp_path / "vacia"), PuenteSesion(Fabrica()))
    qtbot.addWidget(ventana)
    assert ventana.perfil_elegido() is None
    assert not ventana.boton_jugar.isEnabled()
    ventana.jugar()  # sin perfil no hace nada
    ventana.borrar()
    assert not ventana.puente.jugando


def test_jugar_muestra_el_estado_y_las_lineas(
    qtbot: QtBot, ventana: VentanaPrincipal, fabrica: Fabrica
) -> None:
    jugar(qtbot, ventana)

    assert fabrica.sesiones[0].perfil.nombre == "Alfa"
    assert textos(ventana) == ["一", "uno"]
    assert "Leyendo «Alfa»" in ventana.estado.text()
    assert not ventana.boton_jugar.isEnabled()
    assert not ventana.lista_perfiles.isEnabled()
    assert ventana.boton_detener.isEnabled()


def test_marcas_de_las_lineas_e_historial_limitado(qtbot: QtBot, ventana: VentanaPrincipal) -> None:
    jugar(qtbot, ventana)
    ventana.puente.linea.emit(LineaJuego("二", "<dos>", desde_cache=True, leida=False))
    assert textos(ventana)[-2:] == ["二", "<dos> (no leída)"]  # el texto no se interpreta como HTML

    for i in range(MAX_LINEAS + 5):
        ventana.puente.linea.emit(LineaJuego(f"原{i}", f"t{i}", desde_cache=False, leida=True))
    assert len(textos(ventana)) == 2 * MAX_LINEAS
    assert textos(ventana)[-1] == f"t{MAX_LINEAS + 4}"


def test_controles(qtbot: QtBot, ventana: VentanaPrincipal, fabrica: Fabrica) -> None:
    jugar(qtbot, ventana)
    ventana.boton_pausa.click()
    assert ventana.boton_pausa.text() == "Seguir (P)"
    ventana.boton_pausa.click()
    assert ventana.boton_pausa.text() == "Pausa (P)"
    ventana.boton_repetir.click()
    ventana.boton_saltar.click()
    assert fabrica.sesiones[0].control.acciones == ["pausar", "reanudar", "repetir", "saltar"]


def test_detener(qtbot: QtBot, ventana: VentanaPrincipal, fabrica: Fabrica) -> None:
    jugar(qtbot, ventana)
    with qtbot.waitSignal(ventana.puente.terminada, timeout=ESPERA_MS):
        ventana.boton_detener.click()

    assert fabrica.sesiones[0].detenida.is_set()
    assert "Partida terminada" in ventana.estado.text()
    assert ventana.boton_jugar.isEnabled()


def test_error_al_jugar(qtbot: QtBot, almacen: AlmacenPerfiles) -> None:
    ventana = VentanaPrincipal(almacen, PuenteSesion(Fabrica(fallo="No hay ninguna ventana con «alfa»")))
    qtbot.addWidget(ventana)
    with qtbot.waitSignal(ventana.puente.terminada, timeout=ESPERA_MS):
        ventana.jugar()
    assert ventana.estado.text() == "⚠ No hay ninguna ventana con «alfa»"
    assert ventana.boton_jugar.isEnabled()


@pytest.mark.parametrize("respuesta", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_borrar_pide_confirmacion_y_vacia_la_cache(
    ventana: VentanaPrincipal,
    almacen: AlmacenPerfiles,
    cache: CacheFalsa,
    monkeypatch: pytest.MonkeyPatch,
    respuesta: QMessageBox.StandardButton,
) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *_: respuesta)
    alfa = ventana.perfil_elegido()
    assert alfa is not None

    ventana.boton_borrar.click()

    if respuesta == QMessageBox.StandardButton.Yes:
        assert [p.nombre for p in almacen.listar()] == ["Zeta"]
        assert cache.invalidados == [alfa.id]
        assert cache.cerrada
        assert ventana.lista_perfiles.count() == 1
    else:
        assert len(almacen.listar()) == 2
        assert cache.invalidados == []


def test_mantener_encima(ventana: VentanaPrincipal) -> None:
    ventana.siempre_encima.setChecked(True)
    assert ventana.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    ventana.siempre_encima.setChecked(False)
    assert not ventana.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_cerrar_para_la_partida(qtbot: QtBot, ventana: VentanaPrincipal, fabrica: Fabrica) -> None:
    jugar(qtbot, ventana)
    ventana.close()
    assert fabrica.sesiones[0].detenida.is_set()


class EditorFalso:
    """Editor que «guarda» un juego nuevo en el almacén al abrirse, o se cancela."""

    def __init__(self, almacen: AlmacenPerfiles, perfil: Perfil | None, aceptar: bool) -> None:
        self.perfil_recibido = perfil
        self.guardado: Perfil | None = None
        self._almacen = almacen
        self._aceptar = aceptar

    def exec(self) -> int:
        if not self._aceptar:
            return QDialog.DialogCode.Rejected.value
        self.guardado = Perfil(f"Nuevo {len(self._almacen.listar())}", "nuevo")
        self._almacen.guardar(self.guardado)
        return QDialog.DialogCode.Accepted.value


@pytest.mark.parametrize("aceptar", [True, False])
def test_anadir_y_editar_abren_el_editor(
    qtbot: QtBot, almacen: AlmacenPerfiles, fabrica: Fabrica, aceptar: bool
) -> None:
    abiertos: list[EditorFalso] = []

    def abrir_editor(padre: object, almacen: AlmacenPerfiles, perfil: Perfil | None) -> EditorFalso:
        abiertos.append(EditorFalso(almacen, perfil, aceptar))
        return abiertos[-1]

    ventana = VentanaPrincipal(almacen, PuenteSesion(fabrica), abrir_editor=abrir_editor)  # type: ignore[arg-type]
    qtbot.addWidget(ventana)

    ventana.boton_editar.click()
    assert abiertos[0].perfil_recibido is not None
    assert abiertos[0].perfil_recibido.nombre == "Alfa"
    ventana.boton_anadir.click()
    assert abiertos[1].perfil_recibido is None

    elegido = ventana.perfil_elegido()
    assert elegido is not None
    if aceptar:
        assert ventana.lista_perfiles.count() == 4
        assert elegido.nombre == "Nuevo 3"  # queda elegido el último que se ha guardado
    else:
        assert ventana.lista_perfiles.count() == 2


def test_no_se_edita_mientras_se_juega(qtbot: QtBot, ventana: VentanaPrincipal) -> None:
    jugar(qtbot, ventana)
    assert not ventana.boton_anadir.isEnabled()
    assert not ventana.boton_editar.isEnabled()
    ventana.editar(None)  # ni siquiera llamándolo directamente


@pytest.mark.parametrize("aceptar", [True, False])
def test_ajustes_abre_el_dialogo_del_juego_elegido(
    qtbot: QtBot, almacen: AlmacenPerfiles, fabrica: Fabrica, aceptar: bool
) -> None:
    abiertos: list[Perfil] = []

    def abrir_ajustes(padre: object, almacen: AlmacenPerfiles, perfil: Perfil) -> SimpleNamespace:
        abiertos.append(perfil)
        codigo = QDialog.DialogCode.Accepted if aceptar else QDialog.DialogCode.Rejected
        return SimpleNamespace(exec=lambda: codigo.value, guardado=perfil if aceptar else None)

    ventana = VentanaPrincipal(almacen, PuenteSesion(fabrica), abrir_ajustes=abrir_ajustes)  # type: ignore[arg-type]
    qtbot.addWidget(ventana)
    ventana.lista_perfiles.setCurrentRow(1)
    ventana.boton_ajustes.click()

    assert [p.nombre for p in abiertos] == ["Zeta"]
    elegido = ventana.perfil_elegido()
    assert elegido is not None
    assert elegido.nombre == "Zeta"


def test_ver_la_cache(qtbot: QtBot, almacen: AlmacenPerfiles, fabrica: Fabrica) -> None:
    abiertas: list[AlmacenPerfiles] = []

    def abrir(padre: object, almacen: AlmacenPerfiles) -> SimpleNamespace:
        abiertas.append(almacen)
        return SimpleNamespace(exec=lambda: 0)

    ventana = VentanaPrincipal(almacen, PuenteSesion(fabrica), abrir_ventana_cache=abrir)  # type: ignore[arg-type]
    qtbot.addWidget(ventana)
    ventana.boton_cache.click()
    assert abiertas == [almacen]

    jugar(qtbot, ventana)
    assert not ventana.boton_cache.isEnabled()
    ventana.ver_cache()  # mientras se juega, no se abre
    assert len(abiertas) == 1
