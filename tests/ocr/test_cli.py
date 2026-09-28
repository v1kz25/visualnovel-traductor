"""Tests de la herramienta de depuración del OCR."""

from pathlib import Path

import pytest
from PIL import Image

from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.ocr import __main__ as cli

from .sinteticas import Estilo, cara, horizontal


@pytest.mark.usefixtures("modelo")
def test_lee_las_imagenes_indicadas(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "zona-001.png"
    Image.fromarray(horizontal(["我們走吧。"], cara("zh-Hant"), Estilo())).save(ruta)

    assert cli.main(["--idioma", "zh-Hant", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "zona-001.png" in salida
    assert "我們走吧。" in salida


def test_falla_si_no_hay_modelo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def sin_modelo(*_: object) -> Path:
        raise DescargaFallidaError("sin conexión")

    monkeypatch.setattr(cli, "asegurar_descarga", sin_modelo)

    assert cli.main([str(tmp_path / "x.png")]) == 1
    assert "sin conexión" in capsys.readouterr().err
