"""Tests de la preparación del equipo: componentes y comprobación del sistema."""

import sys
from pathlib import Path

import pytest

from vn_audiolibro import preparacion
from vn_audiolibro.preparacion import componentes, comprobar_sistema, pendientes
from vn_audiolibro.traduccion.llama import ruta_llama_server


@pytest.fixture(autouse=True)
def datos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path / "vn-audiolibro"


def test_todos_pendientes_en_un_equipo_nuevo() -> None:
    todos = componentes()
    assert [c.licencia for c in todos] == ["Apache-2.0", "MIT", "Piper GPL-3.0; voz CC BY 3.0", "Apache-2.0"]
    assert sum(c.tamano for c in todos) > 1_200_000_000
    assert [c.nombre for c in pendientes()] == [c.nombre for c in todos]


def test_los_instalados_no_estan_pendientes(datos: Path) -> None:
    modelos = datos / "modelos"
    modelos.mkdir(parents=True)
    for fichero in [
        "ch_PP-OCRv5_rec_mobile.onnx",
        "es_ES-sharvard-medium.onnx",
        "es_ES-sharvard-medium.onnx.json",
    ]:
        (modelos / fichero).write_bytes(b"")
    servidor = ruta_llama_server()  # la del sistema en el que se ejecuta el test
    assert servidor.is_relative_to(datos)
    servidor.parent.mkdir(parents=True)
    servidor.write_bytes(b"")

    assert [c.nombre for c in pendientes()] == ["Modelo de traducción (Hy-MT2 1.8B, Tencent)"]


def test_instalar_cada_componente_llama_a_su_descarga(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[tuple[str, object, object]] = []

    def apuntar(nombre: str):  # type: ignore[no-untyped-def]
        return lambda *args, progreso, cancelado: llamadas.append((nombre, progreso, cancelado))

    for funcion in [
        "asegurar_descarga",
        "asegurar_llama_server",
        "asegurar_voz",
        "asegurar_modelo_traduccion",
    ]:
        monkeypatch.setattr(preparacion, funcion, apuntar(funcion))
    progreso, cancelado = print, bool
    for componente in componentes():
        componente.instalar(progreso, cancelado)

    assert [nombre for nombre, *_ in llamadas] == [
        "asegurar_descarga",
        "asegurar_llama_server",
        "asegurar_voz",
        "asegurar_modelo_traduccion",
    ]
    assert all(p is progreso and c is cancelado for _, p, c in llamadas)


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.mark.usefixtures("linux")
def test_sistema_completo_sin_avisos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preparacion.shutil, "which", lambda _: "/usr/bin/paplay")
    entorno = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}
    assert comprobar_sistema(entorno, lambda: True) == []


@pytest.mark.parametrize(
    ("entorno", "texto"),
    [
        ({"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}, "no es X11"),
        ({"XDG_SESSION_TYPE": "x11"}, "no es X11"),
    ],
)
@pytest.mark.usefixtures("linux")
def test_sin_x11_es_grave(monkeypatch: pytest.MonkeyPatch, entorno: dict[str, str], texto: str) -> None:
    monkeypatch.setattr(preparacion.shutil, "which", lambda _: "/usr/bin/paplay")
    (aviso,) = comprobar_sistema(entorno, lambda: True)
    assert texto in aviso.texto
    assert aviso.grave


@pytest.mark.usefixtures("linux")
def test_sin_paplay_ni_libpulse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preparacion.shutil, "which", lambda _: None)
    paplay, libpulse = comprobar_sistema({"DISPLAY": ":0"}, lambda: False)
    assert "paplay" in paplay.texto
    assert paplay.grave
    assert "libpulse" in libpulse.texto
    assert not libpulse.grave


def test_en_windows_no_se_pide_x11_ni_paplay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(preparacion.shutil, "which", lambda _: None)
    assert comprobar_sistema({}, lambda: False) == []


@pytest.mark.parametrize(("plataforma", "tamano"), [("linux", 17_014_425), ("win32", 18_567_820)])
def test_el_servidor_de_traduccion_es_el_del_sistema(
    monkeypatch: pytest.MonkeyPatch, plataforma: str, tamano: int
) -> None:
    monkeypatch.setattr(sys, "platform", plataforma)
    assert componentes()[1].tamano == tamano


def test_comprobar_con_el_entorno_real() -> None:
    assert isinstance(comprobar_sistema(), list)
