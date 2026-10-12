"""Tipos del guion: fragmentos, párrafos y páginas tal como los muestra el juego."""

from dataclasses import dataclass
from enum import StrEnum


class GuionNoEncontradoError(ValueError):
    """En la carpeta no hay un guion que se sepa leer, o no se puede leer."""


class OrigenGuion(StrEnum):
    """De qué texto del guion se traduce."""

    ORIGINAL = "original"
    """El del idioma del juego (japonés, chino…)."""
    INGLES = "ingles"
    """La traducción oficial al inglés que traen algunos guiones."""


@dataclass(frozen=True)
class Fragmento:
    """Lo que aparece en pantalla con un clic: una parte de un párrafo."""

    original: str
    ingles: str
    """Traducción oficial al inglés del fragmento, o cadena vacía si el guion no la trae."""
    parrafo: int
    """Índice del párrafo al que pertenece."""
    pagina: int
    """Índice de la página: los fragmentos de una página se ven a la vez hasta que se borra."""


@dataclass(frozen=True)
class Parrafo:
    """Unidad que se traduce y se lee: una frase de diálogo o de narración entera."""

    indice: int
    original: str
    ingles: str
    pagina: int

    def texto(self, origen: OrigenGuion) -> str:
        """Texto del que se traduce según el origen elegido."""
        if origen is OrigenGuion.INGLES and self.ingles:
            return self.ingles
        return self.original


@dataclass(frozen=True)
class Guion:
    """Guion completo del juego, en orden de lectura."""

    fragmentos: tuple[Fragmento, ...]
    parrafos: tuple[Parrafo, ...]

    @property
    def tiene_ingles(self) -> bool:
        """Si el guion trae la traducción oficial al inglés."""
        return any(parrafo.ingles for parrafo in self.parrafos)


def agrupar(fragmentos: list[tuple[str, str, bool, bool]]) -> Guion:
    """Guion a partir de los fragmentos en orden, cada uno con (original, inglés, fin de párrafo,
    fin de página). Los fragmentos de un párrafo se unen sin separador en el original y tal cual
    en inglés (el guion ya trae el espacio entre frases)."""
    resultado: list[Fragmento] = []
    parrafos: list[Parrafo] = []
    actual: list[tuple[str, str]] = []
    pagina = 0
    for original, ingles, fin_parrafo, fin_pagina in fragmentos:
        resultado.append(Fragmento(original, ingles, len(parrafos), pagina))
        actual.append((original, ingles))
        if fin_parrafo or fin_pagina:
            parrafos.append(_parrafo(len(parrafos), actual, pagina))
            actual = []
        if fin_pagina:
            pagina += 1
    if actual:
        parrafos.append(_parrafo(len(parrafos), actual, pagina))
    return Guion(tuple(resultado), tuple(parrafos))


def _parrafo(indice: int, partes: list[tuple[str, str]], pagina: int) -> Parrafo:
    original = "".join(texto for texto, _ in partes).strip()
    ingles = " ".join("".join(texto for _, texto in partes).split())
    return Parrafo(indice, original, ingles, pagina)
