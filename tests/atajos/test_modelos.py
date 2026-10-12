"""Tests de los atajos de teclado: cómo se leen, se escriben y se validan."""

import pytest

from vn_audiolibro.atajos.modelos import (
    POR_DEFECTO,
    Accion,
    Atajo,
    AtajoNoValidoError,
    Modificador,
    leer_atajos,
)


@pytest.mark.parametrize(
    ("texto", "modificadores", "tecla"),
    [
        ("Ctrl+Alt+P", {Modificador.CTRL, Modificador.ALT}, "P"),
        ("Alt+Ctrl+p", {Modificador.CTRL, Modificador.ALT}, "P"),
        ("Meta+Shift+7", {Modificador.SUPER, Modificador.SHIFT}, "7"),
        ("F9", set(), "F9"),
        ("Shift+F12", {Modificador.SHIFT}, "F12"),
        ("Ctrl+F5", {Modificador.CTRL}, "F5"),
    ],
)
def test_leer(texto: str, modificadores: set[Modificador], tecla: str) -> None:
    assert Atajo.leer(texto) == Atajo(frozenset(modificadores), tecla)


def test_se_escribe_como_qt() -> None:
    assert str(Atajo.leer("Shift+Alt+Ctrl+Meta+K")) == "Ctrl+Alt+Shift+Meta+K"


@pytest.mark.parametrize(
    ("texto", "motivo"),
    [
        ("", "Usa una letra"),
        ("Ctrl+Alt+Space", "Usa una letra"),
        ("Ctrl+Alt+F13", "Usa una letra"),
        ("Hyper+P", "modificadores"),
        ("P", "necesitan Ctrl, Alt o Meta"),
        ("Shift+P", "necesitan Ctrl, Alt o Meta"),
        ("Ctrl+Alt+F2", "cambia de consola"),
        ("Ctrl+Alt+Shift+F12", "cambia de consola"),
    ],
)
def test_atajos_no_validos(texto: str, motivo: str) -> None:
    with pytest.raises(AtajoNoValidoError, match=motivo):
        Atajo.leer(texto)


def test_los_de_por_defecto_valen() -> None:
    atajos = leer_atajos(POR_DEFECTO)
    assert set(atajos) == set(Accion)
    assert atajos[Accion.PAUSA] == Atajo.leer("Ctrl+Alt+P")


def test_un_atajo_repetido_no_vale() -> None:
    with pytest.raises(AtajoNoValidoError, match="repetido: «Pausar o seguir» y «Saltar la línea»"):
        leer_atajos({"pausa": "Ctrl+Alt+P", "saltar": "Alt+Ctrl+P"})


def test_una_accion_desconocida_no_vale() -> None:
    with pytest.raises(ValueError, match="volar"):
        leer_atajos({"volar": "Ctrl+Alt+V"})
