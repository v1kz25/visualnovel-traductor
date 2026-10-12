"""Búsqueda en el guion de lo que se ve en pantalla, a partir del texto del OCR aunque tenga errores.

Cada fragmento se indexa por sus trigramas de caracteres (solo letras y números, sin puntuación
ni espacios, que es donde más se equivoca el OCR). Un fragmento está en pantalla si buena parte
de sus trigramas aparecen en el texto leído: con un 15 % de caracteres mal leídos sobrevive
alrededor del 60 %.

En las VN de tipo NVL la pantalla acumula los fragmentos de una página hasta que se borra, así
que se elige la página que mejor encaja y, dentro de ella, el último fragmento visible.
"""

import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

from vn_audiolibro.guion.modelos import Guion, Parrafo
from vn_audiolibro.ocr.normalizacion import normalizar

N = 3
"""Tamaño de los gramas."""
UMBRAL = 0.4
"""Parte mínima de los trigramas de un fragmento que tiene que aparecer en el texto leído."""
MIN_GRAMAS = 2
"""Fragmentos con menos trigramas son demasiado cortos para identificarlos solos."""
MIN_GRAMAS_LEJOS = 8
"""Trigramas distintos que tienen que coincidir para saltar a una página lejana (al cargar partida)."""
MARGEN_LARGO = 1.3
"""El tramo en el que se buscan los trigramas de un fragmento mide esto por su número de trigramas."""
MAX_COMUNES = 500
"""Trigramas que aparecen en más fragmentos no sirven para buscar candidatos (sí para puntuar)."""
CERCA_PAGINAS = 3
"""Páginas a partir de la última encontrada que se prefieren a las demás y se miran enteras."""
BONO_CERCA = 1.0
"""Ventaja de una página cercana: equivale a un fragmento más que encaja del todo."""
MAX_PARRAFOS_SEGUIDOS = 3
"""Párrafos que se leen de una vez si el jugador ha avanzado varios sin que se capturasen."""


def clave_busqueda(texto: str, idioma: str) -> str:
    """Texto reducido a letras y números en minúscula, con la normalización del OCR."""
    texto = unicodedata.normalize("NFKC", normalizar(texto, idioma)).casefold()
    return "".join(c for c in texto if unicodedata.category(c)[0] in "LN")


def gramas(texto: str) -> frozenset[str]:
    """Trigramas del texto ya reducido."""
    return frozenset(posiciones(texto))


def posiciones(texto: str) -> dict[str, list[int]]:
    """Trigramas del texto ya reducido, con las posiciones en las que aparece cada uno."""
    resultado: defaultdict[str, list[int]] = defaultdict(list)
    for i in range(len(texto) - N + 1):
        resultado[texto[i : i + N]].append(i)
    return resultado


@dataclass(frozen=True)
class _Candidato:
    indice: int
    pagina: int
    puntuacion: float
    comunes: frozenset[str]
    """Trigramas del fragmento que están juntos en el texto leído."""
    posicion: int
    """Dónde termina el fragmento en el texto leído."""


def ventana(propios: frozenset[str], leidos: dict[str, list[int]], largo: int) -> tuple[frozenset[str], int]:
    """Mayor grupo de trigramas del fragmento que aparecen juntos en el texto leído, y dónde acaba.

    Los trigramas cuentan si caen dentro de un tramo del largo del fragmento (con margen para lo
    que el OCR añade o pierde). Así no encaja un fragmento cuyas palabras sueltas (して, わかります…)
    están repartidas por toda la página.
    """
    puntos = sorted((p, grama) for grama in propios for p in leidos.get(grama, ()))
    mejor: frozenset[str] = frozenset()
    fin = 0
    inicio = 0
    dentro: Counter[str] = Counter()
    for posicion, grama in puntos:
        dentro[grama] += 1
        while posicion - puntos[inicio][0] > largo:
            viejo = puntos[inicio][1]
            dentro[viejo] -= 1
            if not dentro[viejo]:
                del dentro[viejo]
            inicio += 1
        if len(dentro) > len(mejor):
            mejor, fin = frozenset(dentro), posicion
    return mejor, fin


class BuscadorGuion:
    """Encuentra el último fragmento del guion que se ve en pantalla."""

    def __init__(self, guion: Guion, idioma: str) -> None:
        self._guion = guion
        self._idioma = idioma
        self._gramas = [gramas(clave_busqueda(f.original, idioma)) for f in guion.fragmentos]
        indice: defaultdict[str, list[int]] = defaultdict(list)
        paginas: dict[int, list[int]] = {}
        for i, propios in enumerate(self._gramas):
            for grama in propios:
                indice[grama].append(i)
            paginas.setdefault(guion.fragmentos[i].pagina, []).append(i)
        self._indice = {grama: tuple(lista) for grama, lista in indice.items() if len(lista) <= MAX_COMUNES}
        self._paginas = {pagina: range(lista[0], lista[-1] + 1) for pagina, lista in paginas.items()}

    def buscar(self, texto: str, cerca: int | None = None) -> int | None:
        """Índice del último fragmento visible en `texto`, o None si no encaja ninguno.

        `cerca` es el último fragmento encontrado: entre páginas que encajan parecido, gana la que
        está justo después, y para saltar a una lejana hace falta más coincidencia.
        """
        leidos = posiciones(clave_busqueda(texto, self._idioma))
        cercanas = self._cercanas(cerca)
        candidatos = self._candidatos(leidos, cercanas)
        pagina = self._mejor_pagina(candidatos, cercanas)
        if pagina is None:
            return None
        return _ultimo_visible([c for c in candidatos if c.pagina == pagina])

    def _cercanas(self, cerca: int | None) -> range:
        if cerca is None:
            return range(0)
        base = self._guion.fragmentos[cerca].pagina
        return range(base, base + CERCA_PAGINAS + 1)

    def _candidatos(self, leidos: dict[str, list[int]], cercanas: range) -> list[_Candidato]:
        indices: set[int] = set()
        for grama in leidos:
            indices.update(self._indice.get(grama, ()))
        for pagina in cercanas:
            indices.update(self._paginas.get(pagina, ()))
        candidatos = []
        for i in sorted(indices):
            propios = self._gramas[i]
            if len(propios) < MIN_GRAMAS:
                continue
            comunes, posicion = ventana(propios, leidos, round(MARGEN_LARGO * len(propios)) + N)
            if len(comunes) >= UMBRAL * len(propios):
                pagina = self._guion.fragmentos[i].pagina
                candidatos.append(_Candidato(i, pagina, len(comunes) / len(propios), comunes, posicion))
        return candidatos

    @staticmethod
    def _mejor_pagina(candidatos: list[_Candidato], cercanas: range) -> int | None:
        sumas: defaultdict[int, float] = defaultdict(float)
        coincidencias: defaultdict[int, set[str]] = defaultdict(set)
        for candidato in candidatos:
            sumas[candidato.pagina] += candidato.puntuacion
            coincidencias[candidato.pagina] |= candidato.comunes
        validas = [p for p in sumas if p in cercanas or len(coincidencias[p]) >= MIN_GRAMAS_LEJOS]
        if not validas:
            return None
        return max(validas, key=lambda p: sumas[p] + (BONO_CERCA if p in cercanas else 0))


def _ultimo_visible(candidatos: list[_Candidato]) -> int:
    """Último fragmento de la página que está en pantalla.

    Los fragmentos visibles aparecen en el texto en el mismo orden que en el guion. Uno posterior
    que encaja porque repite palabras de otro visible («…したのは誰なのか。») cae en la misma
    posición que este, no después, y se descarta.
    """
    ultimo = candidatos[0]
    for candidato in candidatos[1:]:
        if candidato.posicion > ultimo.posicion:
            ultimo = candidato
    return ultimo.indice


class SeguidorGuion:
    """Sigue por dónde va el jugador en el guion y dice qué párrafos hay que leer."""

    def __init__(self, guion: Guion, buscador: BuscadorGuion) -> None:
        self.guion = guion
        self._buscador = buscador
        self._fragmento: int | None = None
        self._parrafo: int | None = None

    @property
    def parrafo_actual(self) -> int | None:
        """Último párrafo leído, o None si aún no se ha encontrado ninguno."""
        return self._parrafo

    def nuevos(self, texto: str) -> list[Parrafo] | None:
        """Párrafos nuevos en pantalla, en orden; lista vacía si no hay ninguno nuevo y None si el
        texto no está en el guion (un menú, un texto dibujado en la imagen…)."""
        encontrado = self._buscador.buscar(texto, self._fragmento)
        if encontrado is None:
            return None
        fragmento = self.guion.fragmentos[encontrado]
        anterior = self._parrafo
        if anterior is not None:
            misma_pagina = self.guion.parrafos[anterior].pagina == fragmento.pagina
            if fragmento.parrafo == anterior or (misma_pagina and fragmento.parrafo < anterior):
                # Nada nuevo, o el OCR de la última línea ha fallado y encaja una anterior.
                return []
        self._fragmento, self._parrafo = encontrado, fragmento.parrafo
        if anterior is None or anterior > fragmento.parrafo:
            return [self.guion.parrafos[fragmento.parrafo]]
        desde = max(anterior + 1, fragmento.parrafo - MAX_PARRAFOS_SEGUIDOS + 1)
        seguidos = self.guion.parrafos[desde : fragmento.parrafo + 1]
        return [parrafo for parrafo in seguidos if parrafo.pagina == fragmento.pagina]

    def siguientes(self, cuantos: int) -> tuple[Parrafo, ...]:
        """Los párrafos que vienen después del actual, para traducirlos por adelantado."""
        if self._parrafo is None:
            return ()
        return self.guion.parrafos[self._parrafo + 1 : self._parrafo + 1 + cuantos]

    def anteriores(self, parrafo: Parrafo, cuantos: int) -> tuple[Parrafo, ...]:
        """Los párrafos justo antes de `parrafo`, para dar contexto a su traducción."""
        return self.guion.parrafos[max(0, parrafo.indice - cuantos) : parrafo.indice]
