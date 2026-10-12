"""Tests del lector de guiones con órdenes `OutputLine`."""

from pathlib import Path

import pytest

from vn_audiolibro.guion.modelos import GuionNoEncontradoError, OrigenGuion
from vn_audiolibro.guion.outputline import carpeta_scripts, leer_guion

from .sinteticos import PAGINAS, juego, orden_linea, script


def test_lee_parrafos_y_paginas(tmp_path: Path) -> None:
    guion = leer_guion(juego(tmp_path))

    assert len(guion.fragmentos) == 8
    assert [p.pagina for p in guion.parrafos] == [0, 0, 0, 1, 1, 2, 2]
    assert guion.parrafos[0].original == "朝の光が窓から差し込んで、部屋の中を静かに照らしていた。"
    assert guion.tiene_ingles


def test_une_los_fragmentos_de_un_parrafo(tmp_path: Path) -> None:
    dialogo = leer_guion(juego(tmp_path)).parrafos[1]

    assert dialogo.original == "「おはよう、今日は早いんだね。朝ごはんはもう食べたの？」"
    assert dialogo.ingles == '"Good morning, you are early today. Did you already eat breakfast?"'
    assert dialogo.texto(OrigenGuion.INGLES) == dialogo.ingles
    assert dialogo.texto(OrigenGuion.ORIGINAL) == dialogo.original


def test_quita_escapes_y_comillas(tmp_path: Path) -> None:
    guion = leer_guion(juego(tmp_path))

    assert guion.parrafos[3].ingles == '"Then let\'s go to the cafe by the station."'


def test_cada_fichero_empieza_pagina_y_se_leen_en_orden(tmp_path: Path) -> None:
    ficheros = {"_cap_002.txt": script(PAGINAS[1:]), "_cap_001.txt": script(PAGINAS[:1])}

    guion = leer_guion(juego(tmp_path, ficheros))

    assert guion.parrafos[0].original.startswith("朝の光")
    assert guion.parrafos[3].pagina == 1


def test_ignora_comentarios_lineas_vacias_y_ordenes_sin_texto(tmp_path: Path) -> None:
    texto = (
        "//"
        + orden_linea("消された行です。", "Removed line.")
        + '\tOutputLineAll(NULL, "", Line_WaitForInput);\n'
        + orden_linea("　", "")
        + orden_linea("残る行です。", "Kept line.", "Line_Normal")
    )

    guion = leer_guion(juego(tmp_path, {"a.txt": texto}))

    assert [p.original for p in guion.parrafos] == ["残る行です。"]


def test_sin_ingles(tmp_path: Path) -> None:
    guion = leer_guion(juego(tmp_path, {"a.txt": orden_linea("英語のない行です。", "")}))

    assert not guion.tiene_ingles
    assert guion.parrafos[0].texto(OrigenGuion.INGLES) == "英語のない行です。"


def test_encuentra_la_carpeta_de_los_scripts(tmp_path: Path) -> None:
    carpeta = juego(tmp_path)
    scripts = carpeta / "Juego_Data" / "StreamingAssets" / "Scripts"

    assert carpeta_scripts(carpeta) == scripts
    assert carpeta_scripts(scripts) == scripts
    assert carpeta_scripts(carpeta / "Juego_Data") == scripts
    assert leer_guion(scripts).parrafos


def test_carpeta_sin_guion(tmp_path: Path) -> None:
    (tmp_path / "otro.txt").write_text("nada que ver", encoding="utf-8")

    assert carpeta_scripts(tmp_path) is None
    with pytest.raises(GuionNoEncontradoError, match="No se ha encontrado el guion"):
        leer_guion(tmp_path)
    with pytest.raises(GuionNoEncontradoError):
        leer_guion(tmp_path / "no-existe")


def test_guion_sin_texto(tmp_path: Path) -> None:
    with pytest.raises(GuionNoEncontradoError, match="no tiene texto"):
        leer_guion(juego(tmp_path, {"a.txt": orden_linea("", "")}))


def test_fichero_ilegible(tmp_path: Path) -> None:
    carpeta = juego(tmp_path, {"a.txt": orden_linea("読める行です。", "")})
    (carpeta / "Juego_Data" / "StreamingAssets" / "Scripts" / "b.txt").write_bytes(b"OutputLine(\xff\xfe")

    with pytest.raises(GuionNoEncontradoError, match=r"b\.txt"):
        leer_guion(carpeta)
