"""Traducción de los párrafos del guion: la misma petición al jugar y al traducir por adelantado.

El contexto de cada párrafo son los anteriores del guion ya traducidos (en la caché), no lo que
se haya leído en la partida: así la traducción no depende de cuándo se haga.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from vn_audiolibro.cache.modelos import Clave, Entrada
from vn_audiolibro.guion.buscador import clave_busqueda
from vn_audiolibro.guion.modelos import Guion, OrigenGuion, Parrafo
from vn_audiolibro.traduccion.local import LINEAS_CONTEXTO
from vn_audiolibro.traduccion.modelos import (
    Glosario,
    LineaPrevia,
    Peticion,
    Traduccion,
    Traductor,
    TraductorPorPartes,
)

_registro = logging.getLogger(__name__)

IDIOMA_INGLES = "en"


class CacheTraducciones(Protocol):
    """Lo que hace falta de la caché: consultar una línea y guardar su traducción."""

    def consultar(self, clave: Clave) -> Entrada | None: ...

    def guardar_traduccion(self, clave: Clave, traduccion: str, modelo: str) -> None: ...


@dataclass(frozen=True)
class AjustesTraduccionGuion:
    """Lo que sale del perfil para traducir el guion."""

    perfil: str
    idioma: str
    """Idioma del juego (el del texto original del guion)."""
    origen: OrigenGuion = OrigenGuion.ORIGINAL
    glosario: Glosario = field(default_factory=Glosario)
    destino: str = "es"

    def idioma_de(self, parrafo: Parrafo) -> str:
        """Idioma del texto del que se traduce el párrafo."""
        if self.origen is OrigenGuion.INGLES and parrafo.ingles:
            return IDIOMA_INGLES
        return self.idioma


class PreparadorGuion:
    """Claves, peticiones y traducción de los párrafos del guion de un juego."""

    def __init__(
        self, guion: Guion, ajustes: AjustesTraduccionGuion, traductor: Traductor, cache: CacheTraducciones
    ) -> None:
        self.guion = guion
        self.ajustes = ajustes
        self._traductor = traductor
        self._cache = cache

    def texto(self, parrafo: Parrafo) -> str:
        """Texto del que se traduce el párrafo."""
        return parrafo.texto(self.ajustes.origen)

    def hay_que_leer(self, parrafo: Parrafo) -> bool:
        """False si el párrafo no tiene palabras («……。»): no hay nada que traducir ni leer."""
        return bool(clave_busqueda(self.texto(parrafo), self.ajustes.idioma_de(parrafo)))

    def clave(self, parrafo: Parrafo) -> Clave:
        ajustes = self.ajustes
        return Clave(ajustes.perfil, ajustes.idioma_de(parrafo), self.texto(parrafo), ajustes.destino)

    def peticion(self, parrafo: Parrafo) -> Peticion:
        """Petición de traducción con los párrafos anteriores ya traducidos como contexto."""
        ajustes = self.ajustes
        contexto = []
        for anterior in self.guion.parrafos[max(0, parrafo.indice - LINEAS_CONTEXTO) : parrafo.indice]:
            entrada = self._cache.consultar(self.clave(anterior))
            if entrada is not None:
                contexto.append(LineaPrevia(self.texto(anterior), entrada.traduccion))
        idioma = ajustes.idioma_de(parrafo)
        return Peticion(self.texto(parrafo), idioma, tuple(contexto), ajustes.glosario, ajustes.destino)

    def pendiente(self, parrafo: Parrafo) -> bool:
        """Si el párrafo tiene texto y aún no está traducido."""
        return self.hay_que_leer(parrafo) and self._cache.consultar(self.clave(parrafo)) is None

    def traducir(self, parrafo: Parrafo, cancelado: Callable[[], bool] = lambda: False) -> Traduccion | None:
        """Traduce el párrafo y lo guarda en la caché; None si se ha cancelado a medias.

        Lanza `TraduccionFallidaError` si el traductor falla.
        """
        peticion = self.peticion(parrafo)
        if isinstance(self._traductor, TraductorPorPartes):
            resultado = self._traductor.traducir_por_partes(peticion, lambda _: None, cancelado)
            if resultado is None:
                return None
            traduccion = resultado.traduccion
        else:
            traduccion = self._traductor.traducir(peticion)
        self._cache.guardar_traduccion(self.clave(parrafo), traduccion.texto, traduccion.modelo)
        return traduccion

    def traducir_todo(
        self,
        al_progreso: Callable[[int, int], None] = lambda _hechos, _total: None,
        cancelado: Callable[[], bool] = lambda: False,
    ) -> int:
        """Traduce en orden los párrafos que falten y devuelve cuántos ha traducido.

        Lo ya traducido está en la caché, así que se puede cortar y seguir otro día. `al_progreso`
        recibe los párrafos hechos (traducidos ahora o antes) y el total.
        """
        total = len(self.guion.parrafos)
        traducidos = 0
        for hechos, parrafo in enumerate(self.guion.parrafos, 1):
            if cancelado():
                break
            if self.pendiente(parrafo) and self.traducir(parrafo, cancelado) is not None:
                traducidos += 1
            al_progreso(hechos, total)
        return traducidos
