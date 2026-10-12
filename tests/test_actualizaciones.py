"""Tests del aviso de versiones nuevas, sin conexión: GitHub se sustituye por una función."""

import io
import json
import urllib.request
from typing import Any

import pytest

from vn_audiolibro import actualizaciones
from vn_audiolibro.actualizaciones import (
    INTERVALO_S,
    LARGO_MAX_NOTAS,
    Release,
    buscar,
    consultar_github,
    es_mas_nueva,
    leer_release,
    numeros,
)
from vn_audiolibro.configuracion import AjustesApp

URL = "https://github.com/v1kz25/visualnovel-traductor/releases/tag/v0.3.0"
NUEVA = Release("0.3.0", URL, "## Añadido\n- Cosas")
AHORA = 1_800_000_000.0


def respuesta(**campos: Any) -> dict[str, Any]:
    return {"tag_name": "v0.3.0", "html_url": URL, "body": "## Añadido\n- Cosas", **campos}


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("0.2.0", (0, 2, 0)),
        ("v1.10.3", (1, 10, 3)),
        (" v0.3.0 ", (0, 3, 0)),
        ("0.3", None),
        ("v0.3.0-rc1", None),
    ],
)
def test_numeros(texto: str, esperado: tuple[int, int, int] | None) -> None:
    assert numeros(texto) == esperado


@pytest.mark.parametrize(
    ("candidata", "actual", "esperado"),
    [
        ("0.3.0", "0.2.0", True),
        ("0.10.0", "0.9.0", True),  # por números, no por texto
        ("0.2.0", "0.2.0", False),
        ("0.1.9", "0.2.0", False),
        ("rara", "0.2.0", False),
        ("0.3.0", "0.3.0.dev1", False),
    ],
)
def test_es_mas_nueva(candidata: str, actual: str, esperado: bool) -> None:
    assert es_mas_nueva(candidata, actual) is esperado


def test_leer_release() -> None:
    assert leer_release(respuesta()) == NUEVA
    assert leer_release(respuesta(body=None)) == Release("0.3.0", URL, "")
    assert len(leer_release(respuesta(body="x" * 10_000)).notas) == LARGO_MAX_NOTAS  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "datos",
    [
        [],
        respuesta(tag_name=None),
        respuesta(tag_name="ultima"),
        respuesta(html_url="https://ejemplo.com/v0.3.0"),
        respuesta(html_url="https://github.com/otro/repo/releases/tag/v0.3.0"),
        respuesta(body=3),
    ],
)
def test_release_no_valida(datos: object) -> None:
    assert leer_release(datos) is None


class RespuestaFalsa(io.BytesIO):
    def __enter__(self) -> "RespuestaFalsa":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def test_consultar_github(monkeypatch: pytest.MonkeyPatch) -> None:
    peticiones: list[tuple[urllib.request.Request, float]] = []

    def abrir(peticion: urllib.request.Request, timeout: float) -> RespuestaFalsa:
        peticiones.append((peticion, timeout))
        return RespuestaFalsa(json.dumps(respuesta()).encode())

    monkeypatch.setattr(urllib.request, "urlopen", abrir)
    assert consultar_github() == NUEVA
    ((peticion, timeout),) = peticiones
    assert peticion.full_url == actualizaciones.URL_ULTIMA
    assert peticion.get_header("User-agent", "").startswith("vn-audiolibro/")
    assert timeout <= 5


@pytest.mark.parametrize("fallo", [OSError("sin red"), ValueError("JSON roto")])
def test_sin_conexion_no_hay_release(monkeypatch: pytest.MonkeyPatch, fallo: Exception) -> None:
    def abrir(*_: object, **__: object) -> RespuestaFalsa:
        raise fallo

    monkeypatch.setattr(urllib.request, "urlopen", abrir)
    assert consultar_github() is None


def no_consultar() -> Release | None:
    raise AssertionError("no debería consultar GitHub")


@pytest.mark.parametrize(
    "ajustes",
    [
        AjustesApp(avisar_versiones=None),  # aún no se ha preguntado
        AjustesApp(avisar_versiones=False),
        AjustesApp(avisar_versiones=True, ultima_busqueda=AHORA - INTERVALO_S + 60),  # hoy ya se buscó
    ],
)
def test_no_consulta_si_no_toca(ajustes: AjustesApp) -> None:
    assert buscar(ajustes, AHORA, "0.2.0", no_consultar) == actualizaciones.Busqueda(ajustes, None)


@pytest.mark.parametrize("ultima", [None, AHORA - INTERVALO_S, AHORA + 3600])  # nunca, ayer, en el futuro
def test_avisa_de_una_version_nueva(ultima: float | None) -> None:
    ajustes = AjustesApp(avisar_versiones=True, ultima_busqueda=ultima)
    busqueda = buscar(ajustes, AHORA, "0.2.0", lambda: NUEVA)
    assert busqueda.nueva == NUEVA
    assert (busqueda.ajustes.ultima_busqueda, busqueda.ajustes.version_avisada) == (AHORA, "0.3.0")


def test_avisa_una_sola_vez_por_version() -> None:
    ajustes = AjustesApp(avisar_versiones=True, version_avisada="0.3.0")
    busqueda = buscar(ajustes, AHORA, "0.2.0", lambda: NUEVA)
    assert busqueda.nueva is None
    assert busqueda.ajustes.ultima_busqueda == AHORA
    # Otra versión más nueva sí se avisa.
    otra = Release("0.4.0", URL, "")
    assert buscar(ajustes, AHORA, "0.2.0", lambda: otra).nueva == otra


@pytest.mark.parametrize("release", [None, Release("0.2.0", URL, ""), Release("0.1.0", URL, "")])
def test_sin_version_nueva_no_avisa(release: Release | None) -> None:
    busqueda = buscar(AjustesApp(avisar_versiones=True), AHORA, "0.2.0", lambda: release)
    assert busqueda.nueva is None
    assert busqueda.ajustes == AjustesApp(avisar_versiones=True, ultima_busqueda=AHORA)
