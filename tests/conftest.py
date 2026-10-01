"""Configuración común: los tests ven la app en español, sea cual sea el idioma del equipo."""

import re
from collections.abc import Iterator

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from vn_audiolibro import plataforma, textos


class LlaveroEnMemoria(KeyringBackend):
    """Llavero de pega: ningún test lee ni escribe en el llavero real del equipo."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.claves: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.claves.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.claves[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.claves.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def llavero() -> Iterator[LlaveroEnMemoria]:
    """Llavero en memoria, vacío en cada test."""
    anterior = keyring.get_keyring()
    propio = LlaveroEnMemoria()
    keyring.set_keyring(propio)
    yield propio
    keyring.set_keyring(anterior)


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
