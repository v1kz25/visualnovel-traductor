"""Locutor: lee las traducciones en voz alta, de una en una.

Trabaja en su propio hilo. En modo cola lee todas las líneas en orden, con un máximo en espera
para no acumular un retraso enorme; en modo «última», cada línea nueva corta la que suena.
"""

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vn_audiolibro.cache.modelos import Clave, Entrada
from vn_audiolibro.voz import opus
from vn_audiolibro.voz.modelos import (
    MAX_EN_ESPERA,
    PAUSA_ENTRE_LINEAS_S,
    Atenuador,
    Fragmento,
    ModoLectura,
    Reproductor,
    Salida,
    Sintetizador,
    VozFallidaError,
)

_registro = logging.getLogger(__name__)


class CacheAudio(Protocol):
    """Lo que el locutor necesita de la caché: consultar una línea y guardar su audio."""

    def consultar(self, clave: Clave) -> Entrada | None: ...

    def guardar_audio(self, clave: Clave, datos: bytes, voz: str | None = None) -> Path: ...


class TextoPorPartes:
    """Texto que llega por partes desde otro hilo, como una traducción en streaming.

    Quien lo produce llama a `anadir` con cada parte y a `terminar` al acabar (también si se
    cancela). Quien lo lee puede dejar de esperar en cualquier momento.
    """

    ESPERA_S = 0.05

    def __init__(self) -> None:
        self._cola: queue.Queue[str | None] = queue.Queue()

    def anadir(self, parte: str) -> None:
        self._cola.put(parte)

    def terminar(self) -> None:
        self._cola.put(None)

    def partes(self, seguir: Callable[[], bool]) -> Iterator[str]:
        """Las partes a medida que llegan, hasta el final o hasta que `seguir` devuelva False."""
        while seguir():
            try:
                parte = self._cola.get(timeout=self.ESPERA_S)
            except queue.Empty:
                continue
            if parte is None:
                return
            yield parte


@dataclass(frozen=True)
class _Pedido:
    clave: Clave
    texto: str
    id: int
    """Orden de llegada; cortar es invalidar los pedidos hasta un id."""
    partes: TextoPorPartes | None = None
    voz: str | None = None
    """Voz del personaje que la dice, o None para la del juego."""


class Locutor:
    """Lee en voz alta cada traducción que recibe.

    Si la línea tiene audio en la caché, suena ese. Si no, se sintetiza y suena frase a frase
    mientras se sintetiza el resto; al acabar la síntesis, el audio se guarda en la caché.

    En modo `COLA` las líneas se leen en orden, con como mucho `max_en_espera` esperando (si
    llegan más, se descartan las más antiguas) y `pausa_s` de silencio entre una y otra para que
    se distingan. En modo `ULTIMA`, cada línea corta la que suena y sustituye a la pendiente.

    Con un `atenuador`, el juego se baja cuando empieza a sonar una línea y se restaura cuando
    no queda nada por leer (no entre una línea y la siguiente).

    `voces` son otros sintetizadores, por su identificador, para las líneas de los personajes
    que tienen otra voz. El audio guardado de una línea solo vale si es de la voz que toca.
    """

    def __init__(
        self,
        sintetizador: Sintetizador,
        reproductor: Reproductor,
        cache: CacheAudio | None = None,
        atenuador: Atenuador | None = None,
        modo: ModoLectura = ModoLectura.COLA,
        max_en_espera: int = MAX_EN_ESPERA,
        pausa_s: float = PAUSA_ENTRE_LINEAS_S,
        voces: Mapping[str, Sintetizador] | None = None,
    ) -> None:
        self._sintetizador = sintetizador
        self._voces = dict(voces or {})
        self._reproductor = reproductor
        self._cache = cache
        self._atenuador = atenuador
        self._modo = modo
        self._condicion = threading.Condition()
        self._cola: deque[_Pedido] = deque()
        self._max_en_espera = max(1, max_en_espera)
        self._pausa_s = pausa_s
        self._fin_anterior: float | None = None
        """Cuándo terminó de sonar entera la línea anterior (para la pausa entre líneas)."""
        self._ultimo_id = 0
        self._cortado_hasta = 0
        self._actual: _Pedido | None = None
        self._salida: Salida | None = None
        self._cerrado = False
        self._hilo = threading.Thread(target=self._bucle, name="locutor", daemon=True)
        self._hilo.start()

    def decir(self, clave: Clave, texto: str, voz: str | None = None) -> None:
        """Lee la línea cuando le toque (o en el acto, cortando lo que suene, en modo `ULTIMA`).

        Con `voz`, la lee con esa de las `voces`; si no la hay, con la del juego.
        """
        voz = self._voz(voz)
        self._anadir(lambda id_pedido: _Pedido(clave, texto, id_pedido, voz=voz))

    def decir_por_partes(self, clave: Clave, texto: TextoPorPartes, voz: str | None = None) -> None:
        """Como `decir`, pero empieza a leer la primera parte sin esperar a las demás.

        El audio se guarda en la caché al terminar, si para entonces la traducción ya está en
        ella y ha llegado entera.
        """
        voz = self._voz(voz)
        self._anadir(lambda id_pedido: _Pedido(clave, "", id_pedido, texto, voz))

    def _voz(self, voz: str | None) -> str | None:
        return voz if voz in self._voces else None

    def saltar(self) -> None:
        """Corta la línea que suena y pasa a la siguiente de la cola, sin pausa."""
        with self._condicion:
            if self._actual is not None:
                self._cortado_hasta = max(self._cortado_hasta, self._actual.id)
            self._fin_anterior = None
            salida = self._salida
            self._condicion.notify_all()
        if salida is not None:
            salida.detener()

    def callar(self) -> None:
        """Corta lo que suena y vacía la cola."""
        with self._condicion:
            self._cortado_hasta = self._ultimo_id
            self._cola.clear()
            self._fin_anterior = None
            salida = self._salida
            self._condicion.notify_all()
        if salida is not None:
            salida.detener()

    def esperar(self, timeout_s: float | None = None) -> bool:
        """Espera a que no quede nada por leer. Devuelve False si se agota el tiempo."""
        with self._condicion:
            return self._condicion.wait_for(lambda: not self._cola and self._actual is None, timeout_s)

    def cerrar(self) -> None:
        """Corta lo que suena, para el hilo y devuelve el volumen del juego."""
        with self._condicion:
            self._cerrado = True
        self.callar()
        self._hilo.join()
        self._atenuar(bajar=False)

    def _anadir(self, crear: Callable[[int], _Pedido]) -> None:
        salida = None
        with self._condicion:
            self._ultimo_id += 1
            pedido = crear(self._ultimo_id)
            if self._modo is ModoLectura.ULTIMA:
                self._cortado_hasta = pedido.id - 1
                self._cola.clear()
                salida = self._salida
            elif len(self._cola) >= self._max_en_espera:
                descartado = self._cola.popleft()  # la más antigua de las que esperan
                _registro.debug("Cola llena: se descarta «%s»", descartado.texto)
            self._cola.append(pedido)
            self._condicion.notify_all()
        if salida is not None:
            salida.detener()

    def _bucle(self) -> None:
        while True:
            with self._condicion:
                self._condicion.wait_for(lambda: bool(self._cola) or self._cerrado)
                if self._cerrado:
                    return
                pedido = self._actual = self._cola.popleft()
            try:
                self._atender(pedido)
            except Exception:
                # El hilo tiene que seguir vivo para la línea siguiente.
                _registro.exception("No se pudo leer «%s»", pedido.texto)
            finally:
                with self._condicion:
                    libre = not self._cola
                if libre:
                    self._atenuar(bajar=False)
                with self._condicion:
                    self._actual = None
                    self._salida = None
                    self._condicion.notify_all()

    def _atender(self, pedido: _Pedido) -> None:
        guardado = self._audio_guardado(pedido.clave, pedido.voz) if pedido.partes is None else None
        if guardado is not None:
            self._reproducir(pedido, [guardado])
            return

        sintetizador = self._sintetizador if pedido.voz is None else self._voces[pedido.voz]
        sintetizados: list[Fragmento] = []
        textos: Iterable[str] = [pedido.texto]
        if pedido.partes is not None:
            textos = pedido.partes.partes(lambda: self._vigente(pedido))

        def sintetizar() -> Iterator[Fragmento]:
            for texto in textos:
                for fragmento in sintetizador.sintetizar(texto):
                    sintetizados.append(fragmento)
                    yield fragmento
            if pedido.partes is not None and not self._vigente(pedido):
                return  # se dejaron de esperar las partes: el audio está incompleto
            # Síntesis completa, aunque aún quede audio por sonar: ya se puede guardar.
            self._guardar(pedido.clave, sintetizados, pedido.voz)

        self._reproducir(pedido, sintetizar())

    def _reproducir(self, pedido: _Pedido, fragmentos: Iterable[Fragmento]) -> None:
        salida: Salida | None = None
        try:
            for fragmento in fragmentos:
                if salida is None:
                    if not self._esperar_pausa(pedido):
                        return
                    salida = self._abrir(pedido, fragmento.frecuencia)
                    if salida is not None:
                        self._atenuar(bajar=True)
                if salida is None or not self._vigente(pedido):
                    return
                salida.escribir(fragmento.pcm)
            if salida is not None:
                salida.terminar()
                with self._condicion:
                    if self._vigente_sin_cerrojo(pedido):  # ha sonado entera, sin cortes
                        self._fin_anterior = time.monotonic()
        finally:
            if salida is not None:
                salida.detener()

    def _esperar_pausa(self, pedido: _Pedido) -> bool:
        """En modo cola, deja `pausa_s` de silencio tras la línea anterior. False si se corta."""
        with self._condicion:
            if self._modo is not ModoLectura.COLA or self._fin_anterior is None:
                return self._vigente_sin_cerrojo(pedido)
            limite = self._fin_anterior + self._pausa_s
            while self._vigente_sin_cerrojo(pedido) and (falta := limite - time.monotonic()) > 0:
                self._condicion.wait(falta)
            return self._vigente_sin_cerrojo(pedido)

    def _abrir(self, pedido: _Pedido, frecuencia: int) -> Salida | None:
        """Abre la salida y la deja a mano para cortarla, salvo que el pedido ya no valga."""
        salida = self._reproductor.abrir(frecuencia)
        with self._condicion:
            if self._vigente_sin_cerrojo(pedido):
                self._salida = salida
                return salida
        salida.detener()
        return None

    def _atenuar(self, bajar: bool) -> None:
        if self._atenuador is None:
            return
        try:
            if bajar:
                self._atenuador.bajar()
            else:
                self._atenuador.restaurar()
        except Exception:
            # Sin control del volumen, la voz sigue sonando igual.
            _registro.exception("No se pudo cambiar el volumen del juego")

    def _vigente(self, pedido: _Pedido) -> bool:
        with self._condicion:
            return self._vigente_sin_cerrojo(pedido)

    def _vigente_sin_cerrojo(self, pedido: _Pedido) -> bool:
        return pedido.id > self._cortado_hasta and not self._cerrado

    def _audio_guardado(self, clave: Clave, voz: str | None) -> Fragmento | None:
        entrada = self._cache.consultar(clave) if self._cache else None
        if entrada is None or entrada.audio is None or entrada.voz != voz:
            return None  # sin audio, o es de otra voz: se sintetiza con la que toca
        try:
            return opus.decodificar(entrada.audio)
        except VozFallidaError:
            _registro.warning("Audio de la caché ilegible; se vuelve a sintetizar", exc_info=True)
            return None

    def _guardar(self, clave: Clave, fragmentos: list[Fragmento], voz: str | None) -> None:
        if self._cache is None or not fragmentos:
            return
        try:
            self._cache.guardar_audio(clave, opus.codificar(fragmentos), voz)
        except KeyError:
            # La traducción no está en la caché (p. ej. se ha invalidado el juego): no hay dónde guardarlo.
            _registro.debug("Sin traducción guardada para «%s»; el audio no se guarda", clave.texto)
