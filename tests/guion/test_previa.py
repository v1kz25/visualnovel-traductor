"""Tests de la traducción de los párrafos del guion, al jugar y por adelantado."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.guion.modelos import OrigenGuion
from vn_audiolibro.guion.previa import AjustesTraduccionGuion, PreparadorGuion
from vn_audiolibro.traduccion.modelos import (
    Glosario,
    LimiteAgotadoError,
    Peticion,
    ResultadoPorPartes,
    Traduccion,
    TraduccionFallidaError,
)

from .sinteticos import guion

PERFIL = "1" * 32


class TraductorFalso:
    """Traduce anteponiendo el destino; con `fallar`, falla."""

    def __init__(self, fallar: bool = False) -> None:
        self.peticiones: list[Peticion] = []
        self._fallar = fallar

    def traducir(self, peticion: Peticion) -> Traduccion:
        self.peticiones.append(peticion)
        if self._fallar:
            raise TraduccionFallidaError("servidor caído")
        return Traduccion(f"{peticion.destino}:{peticion.texto}", "falso")


class TraductorPorPartesFalso(TraductorFalso):
    """Traduce por partes y se puede cancelar."""

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        if cancelado():
            return None
        return ResultadoPorPartes(self.traducir(peticion), por_partes=True)


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[CacheSQLite]:
    cache = CacheSQLite(tmp_path)
    yield cache
    cache.cerrar()


def _preparador(
    cache: CacheSQLite,
    traductor: TraductorFalso | None = None,
    origen: OrigenGuion = OrigenGuion.ORIGINAL,
) -> PreparadorGuion:
    ajustes = AjustesTraduccionGuion(PERFIL, "ja", origen, Glosario.desde_dict({"喫茶店": "café"}))
    return PreparadorGuion(guion(), ajustes, traductor or TraductorFalso(), cache)


def test_clave_y_peticion_desde_el_original(cache: CacheSQLite) -> None:
    preparador = _preparador(cache)
    parrafo = preparador.guion.parrafos[3]

    clave, peticion = preparador.clave(parrafo), preparador.peticion(parrafo)

    assert (clave.perfil, clave.idioma, clave.texto) == (PERFIL, "ja", parrafo.original)
    assert (peticion.texto, peticion.idioma, peticion.destino) == (parrafo.original, "ja", "es")
    assert peticion.glosario.presentes(peticion.texto) == [("喫茶店", "café")]


def test_desde_el_ingles_del_guion(cache: CacheSQLite) -> None:
    preparador = _preparador(cache, origen=OrigenGuion.INGLES)
    parrafo = preparador.guion.parrafos[1]

    assert preparador.clave(parrafo).idioma == "en"
    assert preparador.peticion(parrafo).texto == parrafo.ingles


def test_el_contexto_son_los_parrafos_anteriores_ya_traducidos(cache: CacheSQLite) -> None:
    preparador = _preparador(cache)
    parrafos = preparador.guion.parrafos
    preparador.traducir(parrafos[1])

    contexto = preparador.peticion(parrafos[3]).contexto

    assert [(linea.original, linea.traduccion) for linea in contexto] == [
        (parrafos[1].original, f"es:{parrafos[1].original}")
    ]


def test_traduce_guarda_y_deja_de_estar_pendiente(cache: CacheSQLite) -> None:
    preparador = _preparador(cache, TraductorPorPartesFalso())
    parrafo = preparador.guion.parrafos[0]
    assert preparador.pendiente(parrafo)

    traduccion = preparador.traducir(parrafo)

    assert traduccion is not None
    entrada = cache.consultar(preparador.clave(parrafo))
    assert entrada is not None
    assert entrada.traduccion == traduccion.texto
    assert not preparador.pendiente(parrafo)


def test_cancelada_no_guarda_nada(cache: CacheSQLite) -> None:
    preparador = _preparador(cache, TraductorPorPartesFalso())
    parrafo = preparador.guion.parrafos[0]

    assert preparador.traducir(parrafo, cancelado=lambda: True) is None
    assert preparador.pendiente(parrafo)


def test_parrafo_sin_palabras_no_se_traduce(cache: CacheSQLite) -> None:
    ajustes = AjustesTraduccionGuion(PERFIL, "ja")
    preparador = PreparadorGuion(guion([[[("「……。」", "")]]]), ajustes, TraductorFalso(), cache)
    parrafo = preparador.guion.parrafos[0]

    assert not preparador.hay_que_leer(parrafo)
    assert not preparador.pendiente(parrafo)


def test_traducir_todo_con_progreso_y_se_puede_seguir(cache: CacheSQLite) -> None:
    traductor = TraductorFalso()
    preparador = _preparador(cache, traductor)
    total = len(preparador.guion.parrafos)
    progreso: list[tuple[int, int]] = []

    def al_progreso(hechos: int, de: int) -> None:
        progreso.append((hechos, de))

    assert preparador.pendientes() == total
    assert preparador.traducir_todo(al_progreso, lambda: len(progreso) >= 2) == 2
    assert progreso == [(1, total), (2, total)]
    assert preparador.pendientes() == total - 2

    traducidos: list[None] = []
    assert preparador.traducir_todo(al_traducir=lambda: traducidos.append(None)) == total - 2
    assert len(traducidos) == total - 2
    assert len(traductor.peticiones) == total
    assert preparador.pendientes() == 0
    assert preparador.traducir_todo() == 0


def test_el_fallo_del_traductor_se_propaga(cache: CacheSQLite) -> None:
    preparador = _preparador(cache, TraductorFalso(fallar=True))

    with pytest.raises(TraduccionFallidaError):
        preparador.traducir_todo()


class TraductorPorLotesFalso(TraductorFalso):
    """Traduce por lotes; con `limite`, se agota tras ese número de lotes."""

    def __init__(self, tamano_lote: int = 3, limite: int | None = None) -> None:
        super().__init__()
        self.tamano_lote = tamano_lote
        self.lotes: list[list[str]] = []
        self._limite = limite

    def traducir_lote(
        self, peticiones: list[Peticion], cancelado: Callable[[], bool]
    ) -> list[Traduccion] | None:
        if cancelado():
            return None
        if self._limite is not None and len(self.lotes) >= self._limite:
            raise LimiteAgotadoError("límite diario agotado")
        self.lotes.append([peticion.texto for peticion in peticiones])
        return [Traduccion(f"lote:{peticion.texto}", "gemini") for peticion in peticiones]


def test_traducir_todo_por_lotes(cache: CacheSQLite) -> None:
    traductor = TraductorPorLotesFalso(tamano_lote=3)
    preparador = _preparador(cache, traductor)
    total = len(preparador.guion.parrafos)
    pendientes = preparador.pendientes()
    progreso: list[int] = []
    traducidos: list[None] = []

    assert (
        preparador.traducir_todo(
            lambda h, _t: progreso.append(h), al_traducir=lambda: traducidos.append(None)
        )
        == pendientes
    )
    assert [len(lote) for lote in traductor.lotes] == [3] * (pendientes // 3) + (
        [pendientes % 3] if pendientes % 3 else []
    )
    assert traductor.peticiones == []  # nada línea a línea
    assert len(traducidos) == pendientes
    assert progreso == sorted(progreso)
    assert progreso[-1] == total
    assert preparador.pendientes() == 0
    parrafo = next(p for p in preparador.guion.parrafos if preparador.hay_que_leer(p))
    entrada = cache.consultar(preparador.clave(parrafo))
    assert entrada is not None
    assert (entrada.traduccion, entrada.modelo) == (f"lote:{parrafo.original}", "gemini")


def test_por_lotes_el_contexto_es_el_de_antes_del_lote(cache: CacheSQLite) -> None:
    preparador = _preparador(cache, TraductorPorLotesFalso(tamano_lote=2))
    peticiones: list[Peticion] = []
    original = preparador._traductor.traducir_lote  # type: ignore[attr-defined]

    def apuntar(lote: list[Peticion], cancelado: Callable[[], bool]) -> list[Traduccion] | None:
        peticiones.extend(lote)
        return original(lote, cancelado)  # type: ignore[no-any-return]

    preparador._traductor.traducir_lote = apuntar  # type: ignore[attr-defined]
    preparador.traducir_todo()
    tercera = peticiones[2]  # primera del segundo lote: ve las del primero ya traducidas
    assert [linea.traduccion for linea in tercera.contexto][-2:] == [
        f"lote:{peticion.texto}" for peticion in peticiones[:2]
    ]


def test_por_lotes_se_puede_parar_y_seguir_otro_dia(cache: CacheSQLite) -> None:
    traductor = TraductorPorLotesFalso(tamano_lote=2, limite=1)
    preparador = _preparador(cache, traductor)
    pendientes = preparador.pendientes()

    with pytest.raises(LimiteAgotadoError):
        preparador.traducir_todo()
    assert preparador.pendientes() == pendientes - 2  # el primer lote se ha guardado

    traductor._limite = None
    assert preparador.traducir_todo() == pendientes - 2
    assert preparador.pendientes() == 0


def test_por_lotes_cancelado(cache: CacheSQLite) -> None:
    traductor = TraductorPorLotesFalso(tamano_lote=2)
    preparador = _preparador(cache, traductor)
    pendientes = preparador.pendientes()

    assert preparador.traducir_todo(cancelado=lambda: len(traductor.lotes) >= 1) == 2
    assert preparador.pendientes() == pendientes - 2

    # Cancelado a mitad de un lote: no se guarda nada de él.
    traductor.traducir_lote = lambda _peticiones, _cancelado: None  # type: ignore[method-assign]
    assert preparador.traducir_todo() == 0
    assert preparador.pendientes() == pendientes - 2
