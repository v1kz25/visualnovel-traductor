"""Tests de la autocomprobación del ejecutable empaquetado."""

import pytest
from pytestqt.qtbot import QtBot

from vn_audiolibro import cli
from vn_audiolibro.autocomprobacion import autocomprobar, comprobaciones


def fallar() -> str:
    raise FileNotFoundError("falta config.yaml")


def test_informa_de_cada_comprobacion_y_falla_si_alguna_falla(capsys: pytest.CaptureFixture[str]) -> None:
    assert autocomprobar([("bien", lambda: "1.0"), ("mal", fallar)]) == 1
    salida = capsys.readouterr().out.splitlines()
    assert salida == [
        "ok    bien: 1.0",
        "FALLO mal: FileNotFoundError: falta config.yaml",
        "1 comprobaciones fallidas.",
    ]


def test_todo_correcto(capsys: pytest.CaptureFixture[str]) -> None:
    assert autocomprobar([("bien", lambda: "1.0")]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Todo correcto."


def test_en_windows_comprueba_tambien_su_audio() -> None:
    nombres = [nombre for nombre, _ in comprobaciones("win32")]
    assert nombres[-2:] == ["PortAudio", "Core Audio"]
    assert "PortAudio" not in [nombre for nombre, _ in comprobaciones("linux")]


@pytest.mark.usefixtures("qapp")
def test_en_este_entorno_no_falta_nada(qtbot: QtBot, capsys: pytest.CaptureFixture[str]) -> None:
    # Las mismas comprobaciones que se hacen al ejecutable empaquetado, pero en el entorno de desarrollo.
    assert cli.main(["--autocomprobacion"]) == 0, capsys.readouterr().out
