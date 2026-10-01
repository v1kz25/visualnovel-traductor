"""Tests del orquestador con lector, traductor y voz falsos y la caché real en una carpeta temporal."""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from vn_audiolibro.cache.modelos import Clave
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.captura.modelos import Imagen, ZonaEstable
from vn_audiolibro.ocr.lector import TextoLeido
from vn_audiolibro.pipeline.orquestador import AjustesOrquestador, LineaJuego, Orquestador
from vn_audiolibro.traduccion.modelos import (
    Glosario,
    Peticion,
    ResultadoPorPartes,
    Traduccion,
    TraduccionFallidaError,
)
from vn_audiolibro.voz.locutor import TextoPorPartes
from vn_audiolibro.voz.modelos import ModoLectura

ESPERA_S = 5.0
PERFIL = "0" * 32


class LectorFalso:
    """Lee el texto que se asoció a cada imagen al crear la zona."""

    def __init__(self) -> None:
        self.textos: dict[int, str] = {}
        self.leidas: list[str] = []

    def zona(self, texto: str) -> ZonaEstable:
        imagen = np.zeros((4, 4, 3), dtype=np.uint8)
        self.textos[id(imagen)] = texto
        return ZonaEstable(imagen=imagen, y_inicio=0, completa=True, instante=0.0)

    def leer(self, imagen: Imagen) -> TextoLeido:
        texto = self.textos[id(imagen)]
        self.leidas.append(texto)
        if texto == "ilegible":
            raise RuntimeError("fallo del OCR")
        return TextoLeido((texto,) if texto else ())


class TraductorFalso:
    """Traduce anteponiendo `es:`. Con `puerta`, espera a que se abra; `fallo` no se puede traducir."""

    def __init__(self, puerta: threading.Event | None = None) -> None:
        self.peticiones: list[Peticion] = []
        self.traduciendo = threading.Event()
        self._puerta = puerta

    def traducir(self, peticion: Peticion) -> Traduccion:
        self.peticiones.append(peticion)
        self.traduciendo.set()
        if self._puerta is not None:
            assert self._puerta.wait(ESPERA_S)
        if peticion.texto == "fallo":
            raise TraduccionFallidaError("servidor caído")
        return Traduccion(f"es:{peticion.texto}", "falso")


class VozFalsa:
    def __init__(self) -> None:
        self.dichas: list[str] = []
        self.calladas = 0
        self.saltadas = 0

    def decir(self, clave: Clave, texto: str) -> None:
        self.dichas.append(texto)

    def callar(self) -> None:
        self.calladas += 1

    def saltar(self) -> None:
        self.saltadas += 1


class Montaje:
    """Orquestador con sus piezas falsas, para inspeccionarlas."""

    def __init__(
        self,
        cache: CacheSQLite,
        puerta: threading.Event | None = None,
        modo: ModoLectura = ModoLectura.COLA,
        destino: str = "es",
    ) -> None:
        self.lector = LectorFalso()
        self.traductor: TraductorFalso | TraductorPorPartesFalso = TraductorFalso(puerta)
        self.voz: VozFalsa = VozFalsa()
        self.cache = cache
        self.lineas: list[LineaJuego] = []
        self.errores: list[str] = []
        glosario = Glosario.desde_dict({"櫻": "Sakura"})
        self.orquestador = Orquestador(
            AjustesOrquestador(PERFIL, "zh-Hant", glosario, modo, destino=destino),
            self.lector,
            self.traductor,
            cache,
            self.voz,
            self.lineas.append,
            self.errores.append,
        )

    def llega(self, *textos: str) -> None:
        """Llegan zonas con esos textos y se espera a que se procesen."""
        for texto in textos:
            self.orquestador.recibir_zona(self.lector.zona(texto))
            assert self.orquestador.esperar(ESPERA_S)


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[CacheSQLite]:
    cache = CacheSQLite(tmp_path)
    yield cache
    cache.cerrar()


@pytest.fixture
def montaje(cache: CacheSQLite) -> Iterator[Montaje]:
    montaje = Montaje(cache)
    yield montaje
    montaje.orquestador.cerrar()


def test_traduce_guarda_y_lee(montaje: Montaje) -> None:
    montaje.llega("她走了。")

    assert montaje.voz.dichas == ["es:她走了。"]
    assert montaje.lineas == [LineaJuego("她走了。", "es:她走了。", desde_cache=False, leida=True)]
    entrada = montaje.cache.consultar(Clave(PERFIL, "zh-Hant", "她走了。"))
    assert entrada is not None
    assert (entrada.traduccion, entrada.modelo) == ("es:她走了。", "falso")


def test_la_segunda_vez_sale_de_la_cache(montaje: Montaje) -> None:
    montaje.llega("一", "二", "一")

    assert [p.texto for p in montaje.traductor.peticiones] == ["一", "二"]
    assert montaje.lineas[-1] == LineaJuego("一", "es:一", desde_cache=True, leida=True)
    assert montaje.voz.dichas == ["es:一", "es:二", "es:一"]


def test_ignora_la_misma_linea_redibujada_y_las_vacias(montaje: Montaje) -> None:
    montaje.llega("一", "一", "", "二")
    assert montaje.voz.dichas == ["es:一", "es:二"]


def test_pasa_el_contexto_y_el_glosario(montaje: Montaje) -> None:
    montaje.llega("一", "二", "三", "四", "櫻")

    ultima = montaje.traductor.peticiones[-1]
    assert [linea.original for linea in ultima.contexto] == ["二", "三", "四"]  # solo las 3 últimas
    assert ultima.contexto[-1].traduccion == "es:四"
    assert ultima.glosario.presentes("櫻") == [("櫻", "Sakura")]
    assert ultima.idioma == "zh-Hant"


def test_traduce_al_destino_y_lo_guarda_aparte_en_la_cache(cache: CacheSQLite) -> None:
    en_espanol = Montaje(cache)
    en_espanol.llega("她走了。")
    en_espanol.orquestador.cerrar()
    en_ingles = Montaje(cache, destino="en")
    try:
        en_ingles.llega("她走了。")
    finally:
        en_ingles.orquestador.cerrar()

    # La traducción al español no vale para el juego en inglés: se vuelve a traducir.
    assert [p.destino for p in en_ingles.traductor.peticiones] == ["en"]
    assert not en_ingles.lineas[0].desde_cache
    assert cache.consultar(Clave(PERFIL, "zh-Hant", "她走了。", "en")) is not None
    assert cache.consultar(Clave(PERFIL, "zh-Hant", "她走了。")) is not None


def test_en_modo_ultima_si_llega_otra_mientras_traduce_no_se_lee_y_se_descartan_las_intermedias(
    cache: CacheSQLite,
) -> None:
    puerta = threading.Event()
    montaje = Montaje(cache, puerta, ModoLectura.ULTIMA)
    orquestador = montaje.orquestador

    orquestador.recibir_zona(montaje.lector.zona("一"))
    assert montaje.traductor.traduciendo.wait(ESPERA_S)
    orquestador.recibir_zona(montaje.lector.zona("二"))
    orquestador.recibir_zona(montaje.lector.zona("三"))
    puerta.set()
    assert orquestador.esperar(ESPERA_S)
    orquestador.cerrar()

    assert montaje.lector.leidas == ["一", "三"]  # «二» se descarta sin leerla
    assert montaje.lineas[0] == LineaJuego("一", "es:一", desde_cache=False, leida=False)
    assert montaje.voz.dichas == ["es:三"]
    assert cache.consultar(Clave(PERFIL, "zh-Hant", "一")) is not None  # guardada para la próxima vez


def test_pausa_calla_e_ignora_zonas(montaje: Montaje) -> None:
    orquestador = montaje.orquestador
    orquestador.pausar()
    assert orquestador.pausado
    assert montaje.voz.calladas == 1

    montaje.llega("一")
    assert montaje.lineas == []

    orquestador.reanudar()
    assert not orquestador.pausado
    montaje.llega("二")
    assert montaje.voz.dichas == ["es:二"]


def test_pausar_mientras_traduce_no_la_lee(cache: CacheSQLite) -> None:
    puerta = threading.Event()
    montaje = Montaje(cache, puerta)
    montaje.orquestador.recibir_zona(montaje.lector.zona("一"))
    assert montaje.traductor.traduciendo.wait(ESPERA_S)
    montaje.orquestador.pausar()
    puerta.set()
    assert montaje.orquestador.esperar(ESPERA_S)
    montaje.orquestador.cerrar()

    assert montaje.voz.dichas == []
    assert not montaje.lineas[0].leida


def test_silenciada_sigue_traduciendo_sin_leer(montaje: Montaje) -> None:
    orquestador = montaje.orquestador
    orquestador.silenciar()
    assert orquestador.silenciado
    assert montaje.voz.calladas == 1  # corta lo que suena

    montaje.llega("一")
    orquestador.repetir()  # silenciada, tampoco repite
    assert montaje.voz.dichas == []
    assert montaje.lineas == [LineaJuego("一", "es:一", desde_cache=False, leida=False, silenciada=True)]
    assert montaje.cache.consultar(Clave(PERFIL, "zh-Hant", "一")) is not None

    orquestador.quitar_silencio()
    assert not orquestador.silenciado
    montaje.llega("二")
    assert montaje.voz.dichas == ["es:二"]
    assert not montaje.lineas[-1].silenciada


def test_repetir_y_saltar(montaje: Montaje) -> None:
    montaje.orquestador.repetir()  # sin líneas todavía: nada
    montaje.llega("一", "二")
    montaje.orquestador.repetir()
    montaje.orquestador.saltar()

    assert montaje.voz.dichas == ["es:一", "es:二", "es:二"]
    assert montaje.voz.saltadas == 1


def test_un_fallo_de_traduccion_avisa_y_sigue(montaje: Montaje) -> None:
    montaje.llega("fallo", "一")

    assert montaje.errores == ["No se pudo traducir la línea: servidor caído"]
    assert montaje.voz.dichas == ["es:一"]


def test_un_fallo_inesperado_avisa_y_sigue(montaje: Montaje) -> None:
    montaje.llega("ilegible", "一")

    assert montaje.errores == ["Error al procesar la línea: fallo del OCR"]
    assert montaje.voz.dichas == ["es:一"]


def test_tras_cerrar_ignora_las_zonas(montaje: Montaje) -> None:
    montaje.orquestador.cerrar()
    montaje.orquestador.recibir_zona(montaje.lector.zona("一"))
    assert montaje.lector.leidas == []


# Traducción por partes (streaming)


class TraductorPorPartesFalso:
    """Traduce cada trozo del original separado por `|` como una parte.

    Con `puerta`, espera a que se abra antes de la segunda parte. Si el original empieza por
    `mal`, lo entregado no vale y devuelve la traducción entera aparte.
    """

    def __init__(self, puerta: threading.Event | None = None) -> None:
        self.peticiones: list[Peticion] = []
        self.primera_entregada = threading.Event()
        self._puerta = puerta

    def traducir(self, peticion: Peticion) -> Traduccion:
        raise AssertionError("debería traducir por partes")

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        self.peticiones.append(peticion)
        partes = [f"es:{trozo}" for trozo in peticion.texto.split("|")]
        for i, parte in enumerate(partes):
            if i == 1 and self._puerta is not None:
                assert self._puerta.wait(ESPERA_S)
            if cancelado():
                return None
            al_parte(parte)
            self.primera_entregada.set()
        if peticion.texto.startswith("mal"):
            return ResultadoPorPartes(Traduccion("es:bien", "falso"), por_partes=False)
        return ResultadoPorPartes(Traduccion(" ".join(partes), "falso"), por_partes=True)


class VozPorPartesFalsa(VozFalsa):
    """Lee las partes en un hilo, como el locutor, y apunta si la traducción estaba en la caché."""

    def __init__(self, cache: CacheSQLite) -> None:
        super().__init__()
        self.partes: list[str] = []
        self.en_cache_al_terminar: list[bool] = []
        self._cache = cache
        self._hilos: list[threading.Thread] = []

    def decir_por_partes(self, clave: Clave, texto: TextoPorPartes) -> None:
        def leer() -> None:
            self.partes.extend(texto.partes(lambda: True))
            self.en_cache_al_terminar.append(self._cache.consultar(clave) is not None)

        hilo = threading.Thread(target=leer)
        hilo.start()
        self._hilos.append(hilo)

    def esperar(self) -> None:
        for hilo in self._hilos:
            hilo.join(ESPERA_S)


def por_partes(
    cache: CacheSQLite, puerta: threading.Event | None = None, modo: ModoLectura = ModoLectura.COLA
) -> Montaje:
    montaje = Montaje(cache, modo=modo)
    montaje.orquestador.cerrar()
    montaje.traductor = TraductorPorPartesFalso(puerta)
    montaje.voz = VozPorPartesFalsa(cache)
    montaje.orquestador = Orquestador(
        AjustesOrquestador(PERFIL, "zh-Hant", modo=modo),
        montaje.lector,
        montaje.traductor,
        cache,
        montaje.voz,
        montaje.lineas.append,
        montaje.errores.append,
    )
    return montaje


def test_por_partes_la_voz_empieza_con_la_primera_parte(cache: CacheSQLite) -> None:
    montaje = por_partes(cache)
    montaje.llega("一|二")
    montaje.orquestador.cerrar()
    voz = montaje.voz
    assert isinstance(voz, VozPorPartesFalsa)
    voz.esperar()

    assert voz.partes == ["es:一", "es:二"]
    assert voz.en_cache_al_terminar == [True]  # la voz puede guardar el audio al acabar
    assert voz.dichas == []  # no se vuelve a leer entera
    (linea,) = montaje.lineas
    assert (linea.traduccion, linea.leida) == ("es:一 es:二", True)
    assert linea.tiempos is not None
    assert linea.tiempos.hasta_voz_s is not None


def test_por_partes_silenciada_no_empieza_a_leer(cache: CacheSQLite) -> None:
    montaje = por_partes(cache)
    montaje.orquestador.silenciar()
    montaje.llega("一|二")
    montaje.orquestador.cerrar()

    voz = montaje.voz
    assert isinstance(voz, VozPorPartesFalsa)
    assert (voz.partes, voz.dichas) == ([], [])
    (linea,) = montaje.lineas
    assert (linea.traduccion, linea.leida, linea.silenciada) == ("es:一 es:二", False, True)
    assert cache.consultar(Clave(PERFIL, "zh-Hant", "一|二")) is not None


def test_por_partes_en_modo_ultima_si_llega_otra_linea_se_cancela_y_se_calla(cache: CacheSQLite) -> None:
    puerta = threading.Event()
    montaje = por_partes(cache, puerta, ModoLectura.ULTIMA)
    traductor = montaje.traductor
    assert isinstance(traductor, TraductorPorPartesFalso)

    montaje.orquestador.recibir_zona(montaje.lector.zona("一|二"))
    assert traductor.primera_entregada.wait(ESPERA_S)
    montaje.orquestador.recibir_zona(montaje.lector.zona("三"))
    puerta.set()
    assert montaje.orquestador.esperar(ESPERA_S)
    montaje.orquestador.cerrar()

    assert montaje.voz.calladas == 1
    assert cache.consultar(Clave(PERFIL, "zh-Hant", "一|二")) is None  # traducción a medias: no se guarda
    assert [linea.original for linea in montaje.lineas] == ["三"]


def test_por_partes_si_no_valia_se_calla_y_se_lee_entera(cache: CacheSQLite) -> None:
    montaje = por_partes(cache)
    montaje.llega("mal|dos")
    montaje.orquestador.cerrar()

    assert montaje.voz.calladas == 1
    assert montaje.voz.dichas == ["es:bien"]
    assert montaje.lineas[0].traduccion == "es:bien"
    assert cache.consultar(Clave(PERFIL, "zh-Hant", "mal|dos")) is not None


def test_tiempos_de_una_linea_desde_la_cache(montaje: Montaje) -> None:
    montaje.llega("一", "二", "一")
    tiempos = montaje.lineas[-1].tiempos
    assert tiempos is not None
    assert tiempos.ocr_s >= 0
    assert tiempos.traduccion_s < 1
    assert tiempos.hasta_voz_s is not None


def test_si_el_juego_amplia_la_linea_solo_se_traduce_y_lee_lo_nuevo(montaje: Montaje) -> None:
    montaje.llega("她走了。", "她走了。他沒有回頭。")

    assert [p.texto for p in montaje.traductor.peticiones] == ["她走了。", "他沒有回頭。"]
    assert montaje.traductor.peticiones[1].contexto[0].original == "她走了。"
    assert montaje.voz.dichas == ["es:她走了。", "es:他沒有回頭。"]
    assert montaje.lineas[1].original == "他沒有回頭。"


# Modo cola


def test_en_cola_todas_las_lineas_se_traducen_y_se_leen_en_orden(cache: CacheSQLite) -> None:
    puerta = threading.Event()
    montaje = Montaje(cache, puerta)
    orquestador = montaje.orquestador

    orquestador.recibir_zona(montaje.lector.zona("一"))
    assert montaje.traductor.traduciendo.wait(ESPERA_S)
    orquestador.recibir_zona(montaje.lector.zona("二"))
    orquestador.recibir_zona(montaje.lector.zona("三"))
    puerta.set()
    assert orquestador.esperar(ESPERA_S)
    orquestador.cerrar()

    assert montaje.voz.dichas == ["es:一", "es:二", "es:三"]
    assert all(linea.leida for linea in montaje.lineas)


def test_en_cola_como_mucho_esperan_tres_zonas(cache: CacheSQLite) -> None:
    puerta = threading.Event()
    montaje = Montaje(cache, puerta)
    orquestador = montaje.orquestador

    orquestador.recibir_zona(montaje.lector.zona("一"))
    assert montaje.traductor.traduciendo.wait(ESPERA_S)
    for texto in ["二", "三", "四", "五"]:
        orquestador.recibir_zona(montaje.lector.zona(texto))
    puerta.set()
    assert orquestador.esperar(ESPERA_S)
    orquestador.cerrar()

    assert montaje.lector.leidas == ["一", "三", "四", "五"]  # «二» era la más antigua


def test_por_partes_en_cola_otra_linea_no_cancela_la_traduccion(cache: CacheSQLite) -> None:
    puerta = threading.Event()
    montaje = por_partes(cache, puerta)
    traductor = montaje.traductor
    assert isinstance(traductor, TraductorPorPartesFalso)

    montaje.orquestador.recibir_zona(montaje.lector.zona("一|二"))
    assert traductor.primera_entregada.wait(ESPERA_S)
    montaje.orquestador.recibir_zona(montaje.lector.zona("三"))
    puerta.set()
    assert montaje.orquestador.esperar(ESPERA_S)
    montaje.orquestador.cerrar()
    voz = montaje.voz
    assert isinstance(voz, VozPorPartesFalsa)
    voz.esperar()

    assert voz.partes == ["es:一", "es:二", "es:三"]
    assert voz.calladas == 0
    assert [linea.original for linea in montaje.lineas] == ["一|二", "三"]
