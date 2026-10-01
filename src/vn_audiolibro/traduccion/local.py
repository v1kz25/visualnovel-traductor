"""Traductor local: Hy-MT2 servido por `llama-server`, sin conexión ni coste."""

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Protocol

from vn_audiolibro.traduccion import postprocesado, prompt
from vn_audiolibro.traduccion.modelos import (
    Peticion,
    ResultadoPorPartes,
    Traduccion,
    glosario_por_defecto,
)
from vn_audiolibro.traduccion.partes import Segmentador

MODELO_LOCAL = "hy-mt2-1.8b-q4_k_m"

LINEAS_CONTEXTO = 3
"""Líneas anteriores que se pasan como contexto."""

TOKENS_FIJOS = 64
TOKENS_POR_CARACTER = 3
"""Tope de tokens de la salida según el original (~1 token por carácter en la práctica): corta
una salida desbocada sin esperar a los 512 tokens."""


FRASES_CALENTAMIENTO = {"zh-Hant": "你好。", "zh-Hans": "你好。", "ja": "こんにちは。", "en": "Hello."}


def max_tokens(texto: str) -> int:
    """Tope de tokens de la traducción de `texto`."""
    return TOKENS_FIJOS + TOKENS_POR_CARACTER * len(texto)


class Completador(Protocol):
    """Lo que el traductor necesita del servidor: un prompt dentro, texto fuera."""

    def completar(self, prompt: str, max_tokens: int = 512) -> str: ...

    def completar_por_partes(self, prompt: str, max_tokens: int = 512) -> Generator[str]: ...


@dataclass(frozen=True)
class _Encargo:
    """Todo lo necesario para pedir una traducción y validar la salida."""

    texto: str
    destino: str
    con_contexto: str
    sin_contexto: str
    previas: tuple[str, ...]
    tope: int
    hay_contexto: bool

    def valida(self, salida: str, parcial: bool = False) -> bool:
        if not self.hay_contexto:
            return True  # sin contexto no hay nada que el modelo pueda repetir
        comprobar = postprocesado.es_valida_parcial if parcial else postprocesado.es_valida
        return comprobar(salida, self.texto, self.previas)


class TraductorLocal:
    """Traduce con Hy-MT2, con glosario y contexto de las líneas anteriores.

    Si la salida no es válida (el modelo ha repetido el contexto), repite la petición sin
    contexto. Si tampoco vale, devuelve la última salida limpia: mejor algo que nada.
    """

    def __init__(self, cliente: Completador, modelo: str = MODELO_LOCAL) -> None:
        self._cliente = cliente
        self.modelo = modelo

    def calentar(self, idioma: str, destino: str = "es") -> None:
        """Hace una traducción corta para que la primera línea del juego no pague el arranque en frío."""
        self.traducir(Peticion(FRASES_CALENTAMIENTO.get(idioma, "你好。"), idioma, destino=destino))

    def traducir(self, peticion: Peticion) -> Traduccion:
        encargo = self._encargo(peticion)
        salida = self._cliente.completar(encargo.con_contexto, encargo.tope)
        if not encargo.valida(salida):
            salida = self._cliente.completar(encargo.sin_contexto, encargo.tope)
        return self._traduccion(salida, encargo)

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        """Traduce en streaming y entrega cada frase en cuanto está lista.

        Con contexto, la salida se valida a medida que llega. Si se tuerce (repite líneas
        anteriores o se desboca), se corta y se repite sin contexto y sin streaming, como en
        `traducir`: el resultado lo indica para que lo ya entregado se descarte.
        """
        encargo = self._encargo(peticion)
        segmentador = Segmentador()
        salida = ""
        trozos = self._cliente.completar_por_partes(encargo.con_contexto, encargo.tope)
        try:
            for trozo in trozos:
                if cancelado():
                    return None
                salida += trozo
                if not encargo.valida(salida, parcial=True):
                    break
                for parte in segmentador.anadir(trozo):
                    al_parte(parte)
            else:
                if encargo.valida(salida):
                    if resto := segmentador.terminar():
                        al_parte(resto)
                    return ResultadoPorPartes(self._traduccion(salida, encargo), por_partes=True)
        finally:
            trozos.close()  # si se deja a medias, corta la conexión y el servidor deja de generar

        salida = self._cliente.completar(encargo.sin_contexto, encargo.tope)
        return ResultadoPorPartes(self._traduccion(salida, encargo), por_partes=False)

    def _encargo(self, peticion: Peticion) -> _Encargo:
        contexto = list(peticion.contexto)[-LINEAS_CONTEXTO:]
        glosario = glosario_por_defecto(peticion.idioma).unir(peticion.glosario)
        terminos = glosario.presentes(peticion.texto)
        originales = [linea.original for linea in contexto]
        return _Encargo(
            texto=peticion.texto,
            destino=peticion.destino,
            con_contexto=prompt.construir(peticion.texto, originales, terminos, peticion.destino),
            sin_contexto=prompt.construir(peticion.texto, (), terminos, peticion.destino),
            # Si una línea anterior está dentro de esta (el juego la amplió), repetir su
            # traducción es correcto, no un fallo del modelo.
            previas=tuple(linea.traduccion for linea in contexto if linea.original not in peticion.texto),
            tope=max_tokens(peticion.texto),
            hay_contexto=bool(contexto),
        )

    def _traduccion(self, salida: str, encargo: _Encargo) -> Traduccion:
        return Traduccion(postprocesado.limpiar(salida, encargo.texto, encargo.destino), self.modelo)
