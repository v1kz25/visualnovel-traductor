"""Orquestador: de cada zona de texto estable a su traducción leída en voz alta.

La captura entrega zonas desde su hilo; el orquestador las procesa en el suyo (OCR, caché o
traducción, voz) y avisa de cada línea para mostrarla. Solo guarda la última zona pendiente:
si el jugador avanza deprisa, las intermedias se descartan sin leerlas.

Si el traductor traduce por partes, la voz empieza con la primera frase mientras se traduce el
resto, y una traducción que ya no hace falta (llega otra línea, se pausa) se cancela.
"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from vn_audiolibro.cache.modelos import Clave, Entrada
from vn_audiolibro.captura.modelos import Imagen, ZonaEstable
from vn_audiolibro.ocr.lector import TextoLeido
from vn_audiolibro.traduccion.local import LINEAS_CONTEXTO
from vn_audiolibro.traduccion.modelos import (
    Glosario,
    LineaPrevia,
    Peticion,
    TraduccionFallidaError,
    Traductor,
    TraductorPorPartes,
)
from vn_audiolibro.voz.locutor import TextoPorPartes
from vn_audiolibro.voz.modelos import MAX_EN_ESPERA, ModoLectura

_registro = logging.getLogger(__name__)


class Lector(Protocol):
    """Lee el texto de una zona (normalmente `LectorOCR`)."""

    def leer(self, imagen: Imagen) -> TextoLeido: ...


class CacheTraducciones(Protocol):
    """Lo que el orquestador necesita de la caché."""

    def consultar(self, clave: Clave) -> Entrada | None: ...

    def guardar_traduccion(self, clave: Clave, traduccion: str, modelo: str) -> None: ...


class Voz(Protocol):
    """Lo que el orquestador necesita del locutor."""

    def decir(self, clave: Clave, texto: str) -> None: ...

    def decir_por_partes(self, clave: Clave, texto: TextoPorPartes) -> None: ...

    def saltar(self) -> None: ...

    def callar(self) -> None: ...


@dataclass(frozen=True)
class Tiempos:
    """Cuánto ha tardado cada etapa de una línea, en segundos."""

    ocr_s: float
    traduccion_s: float
    """Hasta tener la traducción completa; casi 0 si salió de la caché."""
    hasta_voz_s: float | None
    """Desde que el texto quedó estable en pantalla hasta que se pidió leerlo (None si no se leyó).
    Antes de eso, el detector espera a que el texto deje de cambiar (efecto máquina de escribir)."""


@dataclass(frozen=True)
class _Resultado:
    texto: str
    desde_cache: bool
    voz: float | None
    """Instante en que la voz empezó a leer la traducción por partes, si llegó a hacerlo."""


@dataclass(frozen=True)
class LineaJuego:
    """Línea del juego ya procesada, para mostrarla."""

    original: str
    traduccion: str
    desde_cache: bool
    leida: bool
    """False si llegó otra línea mientras se traducía: se guarda, pero no se lee."""
    tiempos: Tiempos | None = field(default=None, compare=False)


@dataclass(frozen=True)
class AjustesOrquestador:
    """Lo que el orquestador necesita saber del juego (sale del perfil)."""

    perfil: str
    """Identificador del perfil: agrupa la caché del juego."""
    idioma: str
    glosario: Glosario = field(default_factory=Glosario)
    modo: ModoLectura = ModoLectura.COLA
    max_en_espera: int = MAX_EN_ESPERA
    destino: str = "es"
    """Idioma al que se traduce."""


class Orquestador:
    """Procesa las zonas de texto en su propio hilo, de una en una.

    En modo cola, las zonas que llegan mientras se procesa otra esperan su turno (como mucho
    `max_en_espera`; si llegan más, se descartan las más antiguas) y todas se leen. En modo
    «última», cada zona nueva sustituye a la pendiente y cancela la traducción en curso.
    """

    def __init__(
        self,
        ajustes: AjustesOrquestador,
        lector: Lector,
        traductor: Traductor,
        cache: CacheTraducciones,
        voz: Voz,
        al_linea: Callable[[LineaJuego], None] = lambda _: None,
        al_error: Callable[[str], None] = lambda _: None,
    ) -> None:
        self._ajustes = ajustes
        self._lector = lector
        self._traductor = traductor
        self._cache = cache
        self._voz = voz
        self._al_linea = al_linea
        self._al_error = al_error
        self._condicion = threading.Condition()
        self._pendientes: deque[ZonaEstable] = deque(maxlen=max(1, ajustes.max_en_espera))
        self._ocupado = False
        self._pausado = False
        self._cerrado = False
        self._ultimo_texto = ""
        self._ultima: tuple[Clave, str] | None = None
        self._contexto: deque[LineaPrevia] = deque(maxlen=LINEAS_CONTEXTO)
        self._hilo = threading.Thread(target=self._bucle, name="orquestador", daemon=True)
        self._hilo.start()

    @property
    def pausado(self) -> bool:
        with self._condicion:
            return self._pausado

    def recibir_zona(self, zona: ZonaEstable) -> None:
        """Nueva zona estable (se llama desde el hilo de la captura)."""
        with self._condicion:
            if self._pausado or self._cerrado:
                return
            if self._ajustes.modo is ModoLectura.ULTIMA:
                self._pendientes.clear()
            self._pendientes.append(zona)  # con la cola llena, se cae la más antigua
            self._condicion.notify_all()

    def pausar(self) -> None:
        """Deja de procesar zonas y calla la voz hasta `reanudar`."""
        with self._condicion:
            self._pausado = True
            self._pendientes.clear()
        self._voz.callar()

    def reanudar(self) -> None:
        with self._condicion:
            self._pausado = False

    def repetir(self) -> None:
        """Vuelve a leer la última línea."""
        with self._condicion:
            ultima = self._ultima
        if ultima is not None:
            self._voz.decir(*ultima)

    def saltar(self) -> None:
        """Corta la línea que suena; en modo cola, pasa a la siguiente."""
        self._voz.saltar()

    def esperar(self, timeout_s: float | None = None) -> bool:
        """Espera a que no quede ninguna zona por procesar. Devuelve False si se agota el tiempo."""
        with self._condicion:
            return self._condicion.wait_for(lambda: not self._pendientes and not self._ocupado, timeout_s)

    def cerrar(self) -> None:
        """Para el hilo; lo que esté traduciendo termina, pero no se lee."""
        with self._condicion:
            self._cerrado = True
            self._pendientes.clear()
            self._condicion.notify_all()
        self._hilo.join()

    def _bucle(self) -> None:
        while True:
            with self._condicion:
                self._condicion.wait_for(lambda: bool(self._pendientes) or self._cerrado)
                if self._cerrado:
                    return
                zona = self._pendientes.popleft()
                self._ocupado = True
            try:
                if zona is not None:
                    self._procesar(zona)
            except Exception as error:
                # El hilo tiene que seguir vivo para la zona siguiente.
                _registro.exception("No se pudo procesar la zona de texto")
                self._al_error(f"Error al procesar la línea: {error}")
            finally:
                with self._condicion:
                    self._ocupado = False
                    self._condicion.notify_all()

    def _procesar(self, zona: ZonaEstable) -> None:
        inicio = time.monotonic()
        texto = self._lector.leer(zona.imagen).texto
        ocr_s = time.monotonic() - inicio
        if not texto or texto == self._ultimo_texto:
            return  # sin texto, o la misma línea redibujada
        anterior, self._ultimo_texto = self._ultimo_texto, texto
        if anterior and texto.startswith(anterior):
            # El juego ha añadido texto a la línea anterior, que ya se leyó: solo va lo nuevo.
            texto = texto[len(anterior) :].strip()
        clave = Clave(self._ajustes.perfil, self._ajustes.idioma, texto, self._ajustes.destino)

        entrada = self._cache.consultar(clave)
        resultado = _Resultado(entrada.traduccion, True, None) if entrada else self._traducir(clave, texto)
        if resultado is None:
            return
        traduccion_s = time.monotonic() - inicio - ocr_s

        self._contexto.append(LineaPrevia(texto, resultado.texto))
        with self._condicion:
            # Si ya espera otra línea o se ha pausado, esta llega tarde: se guarda pero no se lee.
            leer = resultado.voz is None and not self._llega_tarde_sin_cerrojo()
            self._ultima = (clave, resultado.texto)
        voz = resultado.voz
        if leer:
            self._voz.decir(clave, resultado.texto)
            voz = time.monotonic()
        tiempos = Tiempos(ocr_s, traduccion_s, None if voz is None else voz - zona.instante)
        self._al_linea(LineaJuego(texto, resultado.texto, resultado.desde_cache, voz is not None, tiempos))

    def _llega_tarde_sin_cerrojo(self) -> bool:
        if self._pausado or self._cerrado:
            return True
        # En modo cola, que llegue otra línea no deja vieja a esta: se leerá después.
        return self._ajustes.modo is ModoLectura.ULTIMA and bool(self._pendientes)

    def _llega_tarde(self) -> bool:
        with self._condicion:
            return self._llega_tarde_sin_cerrojo()

    def _traducir(self, clave: Clave, texto: str) -> _Resultado | None:
        ajustes = self._ajustes
        peticion = Peticion(texto, ajustes.idioma, tuple(self._contexto), ajustes.glosario, ajustes.destino)
        try:
            if isinstance(self._traductor, TraductorPorPartes):
                return self._traducir_por_partes(clave, peticion, self._traductor)
            nueva = self._traductor.traducir(peticion)
        except TraduccionFallidaError as error:
            _registro.warning("No se pudo traducir «%s»: %s", texto, error)
            self._al_error(f"No se pudo traducir la línea: {error}")
            return None
        self._cache.guardar_traduccion(clave, nueva.texto, nueva.modelo)
        return _Resultado(nueva.texto, False, None)

    def _traducir_por_partes(
        self, clave: Clave, peticion: Peticion, traductor: TraductorPorPartes
    ) -> _Resultado | None:
        partes = TextoPorPartes()
        voz: float | None = None

        def al_parte(parte: str) -> None:
            nonlocal voz
            if voz is None:
                self._voz.decir_por_partes(clave, partes)
                voz = time.monotonic()
            partes.anadir(parte)

        try:
            resultado = traductor.traducir_por_partes(peticion, al_parte, self._llega_tarde)
            if resultado is not None:
                # Antes de terminar las partes: la voz guarda el audio si la traducción ya está.
                traduccion = resultado.traduccion
                self._cache.guardar_traduccion(clave, traduccion.texto, traduccion.modelo)
        finally:
            partes.terminar()

        if resultado is None or not resultado.por_partes:
            if voz is not None:
                self._voz.callar()  # cancelada, o lo leído no valía y se leerá la traducción entera
            return None if resultado is None else _Resultado(resultado.traduccion.texto, False, None)
        return _Resultado(resultado.traduccion.texto, False, voz)
