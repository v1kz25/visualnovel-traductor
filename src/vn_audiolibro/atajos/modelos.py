"""Atajos de teclado globales: qué hacen, cómo se escriben y la interfaz de cada sistema.

Un atajo global funciona aunque el juego tenga el foco, pero el juego deja de recibir esa
combinación de teclas: por eso se usan combinaciones con Ctrl y Alt que los juegos no suelen
usar, y se pueden cambiar o desactivar.
"""

import string
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from vn_audiolibro.textos import N_, _


class Accion(StrEnum):
    """Lo que se puede hacer con un atajo mientras se juega."""

    PAUSA = "pausa"
    REPETIR = "repetir"
    SALTAR = "saltar"
    SUBTITULOS = "subtitulos"


NOMBRES_ACCIONES = {
    Accion.PAUSA: N_("Pausar o seguir"),
    Accion.REPETIR: N_("Repetir la línea"),
    Accion.SALTAR: N_("Saltar la línea"),
    Accion.SUBTITULOS: N_("Mostrar u ocultar los subtítulos"),
}
"""Se traducen al mostrarlos, con `_()`."""


class Modificador(StrEnum):
    """Teclas modificadoras, con el nombre que les da Qt al escribir un atajo."""

    CTRL = "Ctrl"
    ALT = "Alt"
    SHIFT = "Shift"
    SUPER = "Meta"


TECLAS_FUNCION = tuple(f"F{n}" for n in range(1, 13))
TECLAS = (*string.ascii_uppercase, *string.digits, *TECLAS_FUNCION)
"""Teclas admitidas: las que tienen el mismo nombre en X11 y en Windows con cualquier teclado."""


class AtajoNoValidoError(ValueError):
    """El texto no es un atajo que se pueda usar."""


@dataclass(frozen=True)
class Atajo:
    """Una combinación de teclas: modificadores y una tecla."""

    modificadores: frozenset[Modificador]
    tecla: str

    def __str__(self) -> str:
        """Como lo escribe Qt: «Ctrl+Alt+P»."""
        return "+".join([*(m.value for m in Modificador if m in self.modificadores), self.tecla])

    @classmethod
    def leer(cls, texto: str) -> "Atajo":
        """Lee «Ctrl+Alt+P». Lanza `AtajoNoValidoError` si no es un atajo que se pueda usar.

        Una letra o un número necesitan Ctrl, Alt o Super: si no, al escribir en otra aplicación
        se dispararía el atajo. Las teclas de función pueden ir solas, pero no con Ctrl+Alt.
        """
        partes = [parte.strip() for parte in texto.split("+")]
        tecla = partes[-1].upper() if partes else ""
        if tecla not in TECLAS:
            raise AtajoNoValidoError(
                _("Atajo no válido: «{atajo}». Usa una letra, un número o de F1 a F12.").format(atajo=texto)
            )
        try:
            modificadores = frozenset(Modificador(parte) for parte in partes[:-1])
        except ValueError:
            raise AtajoNoValidoError(
                _("Atajo no válido: «{atajo}». Los modificadores son Ctrl, Alt, Shift y Meta.").format(
                    atajo=texto
                )
            ) from None
        if tecla in TECLAS_FUNCION and {Modificador.CTRL, Modificador.ALT} <= modificadores:
            raise AtajoNoValidoError(
                _("Atajo no válido: «{atajo}». Ctrl+Alt con F1 a F12 cambia de consola en Linux.").format(
                    atajo=texto
                )
            )
        if tecla not in TECLAS_FUNCION and not modificadores - {Modificador.SHIFT}:
            raise AtajoNoValidoError(
                _("Atajo no válido: «{atajo}». Una letra o un número necesitan Ctrl, Alt o Meta.").format(
                    atajo=texto
                )
            )
        return cls(modificadores, tecla)


POR_DEFECTO = {
    Accion.PAUSA: "Ctrl+Alt+P",
    Accion.REPETIR: "Ctrl+Alt+R",
    Accion.SALTAR: "Ctrl+Alt+S",
    Accion.SUBTITULOS: "Ctrl+Alt+H",
}


def leer_atajos(textos: Mapping[str, str]) -> dict[Accion, Atajo]:
    """Los atajos de cada acción; lanza `AtajoNoValidoError` si alguno no vale o se repite."""
    atajos = {Accion(accion): Atajo.leer(texto) for accion, texto in textos.items()}
    vistos: dict[Atajo, Accion] = {}
    for accion, atajo in atajos.items():
        if atajo in vistos:
            raise AtajoNoValidoError(
                _("El atajo «{atajo}» está repetido: «{una}» y «{otra}».").format(
                    atajo=atajo, una=_(NOMBRES_ACCIONES[vistos[atajo]]), otra=_(NOMBRES_ACCIONES[accion])
                )
            )
        vistos[atajo] = accion
    return atajos


class EscuchaAtajos(Protocol):
    """Atajos globales del sistema (X11 en Linux, Win32 en Windows)."""

    def iniciar(self, atajos: Mapping[Accion, Atajo], al_pulsar: Callable[[Accion], None]) -> list[Accion]:
        """Empieza a escuchar los atajos y devuelve las acciones cuyo atajo no se ha podido usar
        (porque ya lo usa otra aplicación). `al_pulsar` se llama desde otro hilo."""
        ...

    def detener(self) -> None:
        """Deja de escuchar y libera los atajos. Se puede llamar aunque no se haya iniciado."""
        ...
