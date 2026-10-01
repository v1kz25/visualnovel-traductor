"""Tests de las claves en el llavero (con el llavero en memoria de `conftest.py`)."""

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError

from tests.conftest import LlaveroEnMemoria
from vn_audiolibro import claves


def test_guardar_leer_y_borrar(llavero: LlaveroEnMemoria) -> None:
    assert claves.leer() is None

    claves.guardar("  mi-clave \n")

    assert claves.leer() == "mi-clave"
    assert llavero.claves == {("vn-audiolibro", "gemini"): "mi-clave"}
    claves.borrar()
    assert claves.leer() is None
    claves.borrar()  # sin clave, no pasa nada


class SinLlavero(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def get_password(self, service: str, username: str) -> str | None:
        raise KeyringError("no hay Secret Service")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise KeyringError("no hay Secret Service")

    def delete_password(self, service: str, username: str) -> None:
        raise KeyringError("no hay Secret Service")


def test_sin_llavero_no_se_guarda_en_ningun_otro_sitio() -> None:
    keyring.set_keyring(SinLlavero())

    assert claves.leer() is None
    with pytest.raises(claves.LlaveroNoDisponibleError, match="llavero"):
        claves.guardar("mi-clave")
    with pytest.raises(claves.LlaveroNoDisponibleError):
        claves.borrar()
