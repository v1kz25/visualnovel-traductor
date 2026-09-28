"""Test del arranque de la interfaz, sin entrar en el bucle de eventos de Qt."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from vn_audiolibro.preparacion import Aviso
from vn_audiolibro.ui import app
from vn_audiolibro.ui.principal import VentanaPrincipal


def test_abre_la_ventana_principal(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(QApplication, "exec", lambda _: 0)
    monkeypatch.setattr(app, "preparar", lambda: None)  # sin el diálogo de descargas

    assert app.ejecutar(["vn-audiolibro"]) == 0

    ventanas = [w for w in qapp.topLevelWidgets() if isinstance(w, VentanaPrincipal) and w.isVisible()]
    assert ventanas
    assert qapp.applicationName() == "vn-audiolibro"
    assert QApplication.desktopFileName() == "vn-audiolibro"
    assert not QApplication.windowIcon().isNull()
    for ventana in ventanas:
        ventana.close()


def test_icono(qapp: QApplication) -> None:
    assert not app.icono().isNull()


def test_textos_de_qt_en_espanol(qapp: QApplication) -> None:
    traductor = app.instalar_traduccion(qapp)
    assert traductor is not None
    try:
        tipo = QDialogButtonBox.StandardButton
        botones = QDialogButtonBox(tipo.Save | tipo.Cancel)
        textos = {botones.button(boton).text().replace("&", "") for boton in (tipo.Save, tipo.Cancel)}
    finally:
        qapp.removeTranslator(traductor)
    assert textos == {"Guardar", "Cancelar"}


def test_sin_traduccion_disponible(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import QLibraryInfo

    monkeypatch.setattr(QLibraryInfo, "path", lambda _: str(tmp_path))
    assert app.instalar_traduccion(qapp) is None


@pytest.mark.parametrize(
    ("faltan", "avisos", "abre"),
    [
        ([], [], False),
        (["modelo"], [], True),
        ([], [Aviso("sin paplay", grave=True)], True),
        ([], [Aviso("sin libpulse", grave=False)], False),
    ],
)
def test_preparar_solo_si_falta_algo(
    monkeypatch: pytest.MonkeyPatch, faltan: list[object], avisos: list[Aviso], abre: bool
) -> None:
    abiertos: list[tuple[object, object, object]] = []

    class DialogoFalso:
        def __init__(self, faltan: object, avisos: object, acceso: object) -> None:
            abiertos.append((faltan, avisos, acceso))

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(app.preparacion, "pendientes", lambda: faltan)
    monkeypatch.setattr(app.preparacion, "comprobar_sistema", lambda: avisos)
    monkeypatch.setattr(app, "PrimerArranque", DialogoFalso)
    monkeypatch.setattr(app, "ofrecer_acceso_windows", lambda: "acceso")
    app.preparar()
    assert abiertos == ([(faltan, avisos, "acceso")] if abre else [])
