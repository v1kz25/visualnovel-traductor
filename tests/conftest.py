"""Configuración común: los tests ven la app en español, sea cual sea el idioma del equipo."""

import re
from collections.abc import Iterator

import pytest

from vn_audiolibro import plataforma, textos


@pytest.fixture(autouse=True)
def en_espanol(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Sistema en español y sin ajustes guardados: la CLI elige el idioma al arrancar.

    Al terminar, deja activo el español aunque el test haya cambiado de idioma.
    """
    monkeypatch.setattr(plataforma, "idiomas_sistema", lambda entorno=None: ["es_ES.UTF-8"])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))
    yield
    textos.activar(textos.ORIGEN)


@pytest.fixture
def en_ingles() -> Iterator[None]:
    """La app en inglés durante el test."""
    textos.activar("en")
    yield
    textos.activar(textos.ORIGEN)


_ESPANOL = re.compile(
    r"[áéíóúñ¿¡«»]|\b(el|la|los|las|del|de|que|un|una|para|con|por|sin|juego|juegos|ventana)\b",
    re.IGNORECASE,
)


def parece_espanol(texto: str) -> bool:
    """Si un texto que debería estar en otro idioma parece haberse quedado en español."""
    return bool(_ESPANOL.search(texto))
