"""Tipos de la traducción: la interfaz de los traductores, el contexto y el glosario."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Motor(StrEnum):
    """Traductor que usa un juego."""

    LOCAL = "local"
    """Hy-MT2 en el equipo: gratis y sin conexión. El de por defecto."""
    GEMINI = "gemini"
    """Gemini de Google, en la nube: opcional, con la clave del usuario. Si falla, se traduce en local."""


@dataclass(frozen=True)
class LineaPrevia:
    """Línea anterior del juego, ya traducida: da contexto a la siguiente."""

    original: str
    traduccion: str


@dataclass(frozen=True)
class Traduccion:
    """Resultado de traducir una línea."""

    texto: str
    modelo: str
    """Traductor que la generó; se guarda en la caché."""


@dataclass(frozen=True)
class Glosario:
    """Traducciones fijas de términos: nombres propios, honoríficos, lugares…"""

    terminos: tuple[tuple[str, str], ...] = ()

    @classmethod
    def desde_dict(cls, terminos: dict[str, str]) -> "Glosario":
        """Glosario a partir de un diccionario término -> traducción."""
        return cls(tuple(terminos.items()))

    def presentes(self, texto: str) -> list[tuple[str, str]]:
        """Términos que aparecen en el texto: solo esos van al prompt, para no distraer al modelo."""
        return [(termino, traduccion) for termino, traduccion in self.terminos if termino in texto]

    def unir(self, otro: "Glosario") -> "Glosario":
        """Este glosario con los términos de `otro`; si un término está en los dos, gana `otro`."""
        propios = {termino for termino, _ in otro.terminos}
        return Glosario(tuple(t for t in self.terminos if t[0] not in propios) + otro.terminos)


GLOSARIO_JAPONES = Glosario.desde_dict(
    {
        "先輩": "senpai",
        "後輩": "kouhai",
        "先生": "sensei",
        "お兄ちゃん": "onii-chan",
        "お姉ちゃん": "onee-chan",
        "さん": "-san",
        "ちゃん": "-chan",
        "くん": "-kun",
        "さま": "-sama",
    }
)
"""Honoríficos japoneses, que se mantienen como en las traducciones de aficionados.

Sin ellos el modelo traduce 先輩 por "Maestro" y, con 田中さん, llega a inventarse el apellido.
"""

GLOSARIOS_POR_DEFECTO = {"ja": GLOSARIO_JAPONES}


def glosario_por_defecto(idioma: str) -> Glosario:
    """Glosario base del idioma de origen, que el glosario de cada juego amplía."""
    return GLOSARIOS_POR_DEFECTO.get(idioma, Glosario())


@dataclass(frozen=True)
class Peticion:
    """Línea que hay que traducir, con su contexto y su glosario."""

    texto: str
    idioma: str
    contexto: Sequence[LineaPrevia] = ()
    glosario: Glosario = field(default_factory=Glosario)
    destino: str = "es"
    """Idioma al que se traduce (`es` o `en`)."""


class Traductor(Protocol):
    """Traduce líneas de juego al idioma de destino. Cada motor (local, APIs) lo implementa."""

    def traducir(self, peticion: Peticion) -> Traduccion:
        """Traducción de la línea. Lanza `TraduccionFallidaError` si no se puede traducir."""
        ...


@dataclass(frozen=True)
class ResultadoPorPartes:
    """Resultado de traducir en streaming."""

    traduccion: Traduccion
    por_partes: bool
    """True si lo entregado por partes es la traducción. False si la salida en streaming no valía
    y se ha repetido la petición: lo entregado se descarta y hay que leer la traducción entera."""


@runtime_checkable
class TraductorPorPartes(Protocol):
    """Traductor que entrega la traducción a medida que se genera."""

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        """Traduce llamando a `al_parte` con cada frase lista. None si `cancelado` pasa a ser True."""
        ...


class TraduccionFallidaError(Exception):
    """El traductor no ha podido traducir la línea (servidor caído, error de red…)."""
