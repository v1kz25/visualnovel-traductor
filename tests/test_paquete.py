import importlib
import sys
from pathlib import Path

import pytest

MODULOS = ["captura", "ocr", "traduccion", "voz", "cache", "perfiles", "pipeline", "ui"]


@pytest.mark.parametrize("modulo", MODULOS)
def test_modulos_importables(modulo: str) -> None:
    assert importlib.import_module(f"vn_audiolibro.{modulo}").__doc__


def test_main_usa_la_linea_de_comandos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from vn_audiolibro import main

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["vn-audiolibro", "juegos"])
    with pytest.raises(SystemExit) as salida:
        main()
    assert salida.value.code == 0
    assert "No hay juegos" in capsys.readouterr().out
