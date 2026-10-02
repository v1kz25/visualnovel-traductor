"""Orquestador: de cada zona de texto estable a su traducción leída en voz alta.

La captura entrega zonas desde su hilo; el orquestador las procesa en el suyo (OCR, caché o
traducción, voz) y avisa de cada línea para mostrarla. Solo guarda la última zona pendiente:
si el jugador avanza deprisa, las intermedias se descartan sin leerlas.

Si el traductor traduce por partes, la voz empieza con la primera frase mientras se traduce el
resto, y una traducción que ya no hace falta (llega otra línea, se pausa) se cancela.

Con el guion del juego, el texto del OCR solo sirve para encontrar en él los párrafos nuevos, que
se traducen y leen con su texto exacto. Mientras no llega otra zona, se traducen por adelantado
los párrafos siguientes.

El nombre del personaje que habla (de su propia zona o del principio de la línea) no se lee: se
traduce una sola vez, se añade al glosario y acompaña a la línea al mostrarla. Si el personaje tiene
otra voz, su línea se lee con ella.
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
from vn_audiolibro.guion.buscador import SeguidorGuion
from vn_audiolibro.guion.previa import PreparadorGuion
from vn_audiolibro.ocr.lector import TextoLeido
from vn_audiolibro.ocr.personaje import separar_personaje
from vn_audiolibro.textos import _
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

    def decir(self, clave: Clave, texto: str, voz: str | None = None) -> None: ...

    def decir_por_partes(self, clave: Clave, texto: TextoPorPartes, voz: str | None = None) -> None: ...

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
    """False si llegó otra línea mientras se traducía (se guarda, pero no se lee) o si la voz está
    silenciada."""
    tiempos: Tiempos | None = field(default=None, compare=False)
    silenciada: bool = False
    """True si no se leyó porque la voz estaba silenciada: se muestra como una línea normal."""
    personaje: str | None = None
    """Quién habla, ya traducido; None en la narración o si el juego no lo muestra."""

    @property
    def traduccion_con_personaje(self) -> str:
        """La traducción precedida de quién habla («Nombre: traducción»), para mostrarla."""
        if self.personaje is None:
            return self.traduccion
        return _("{personaje}: {traduccion}").format(personaje=self.personaje, traduccion=self.traduccion)


@dataclass(frozen=True)
class GuionJuego:
    """El guion del juego mientras se juega: dónde va el jugador y cómo se traduce cada párrafo."""

    seguidor: SeguidorGuion
    preparador: PreparadorGuion
    anticipo: int = 5
    """Párrafos siguientes que se traducen por adelantado."""


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
    separar_personaje: bool = True
    """Si se quita de la línea el nombre de quien habla (`Nombre：texto`, `【Nombre】texto`…)."""
    voces: tuple[tuple[str, str], ...] = ()
    """Voz de los personajes que no hablan con la del juego: nombre en el juego -> voz del locutor."""


LARGO_MAX_PERSONAJE = 40
"""Una «traducción» de un nombre más larga que esto es que el traductor se ha ido por las ramas."""

_SOBRA_EN_PERSONAJE = " \t\n.,:;!?¡¿\"'«»“”。：「」【】[]"


def _tiene_letras(nombre: str) -> bool:
    return any(caracter.isalnum() for caracter in nombre)


def _limpiar_personaje(traduccion: str) -> str | None:
    """El nombre traducido sin puntuación alrededor, o None si no parece un nombre."""
    limpio = traduccion.strip(_SOBRA_EN_PERSONAJE)
    return limpio if 0 < len(limpio) <= LARGO_MAX_PERSONAJE and "\n" not in limpio else None


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
        guion: GuionJuego | None = None,
        al_personaje: Callable[[str, str], None] = lambda _original, _traduccion: None,
    ) -> None:
        """`al_personaje` avisa la primera vez que habla cada personaje en la partida, con su nombre
        en el juego y su traducción (la misma si no se ha podido traducir), para guardarlo."""
        self._ajustes = ajustes
        self._glosario = ajustes.glosario
        self._personajes: dict[str, str] = dict(ajustes.glosario.terminos)
        self._vistos: set[str] = set()
        self._voces = dict(ajustes.voces)
        self._al_personaje = al_personaje
        self._guion = guion
        self._anticipar = False
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
        self._silenciado = False
        self._cerrado = False
        self._ultimo_texto: tuple[str | None, str] = (None, "")
        self._ultimo_dialogo: tuple[str | None, str] = (None, "")
        self._ultima: tuple[Clave, str, str | None] | None = None
        self._contexto: deque[LineaPrevia] = deque(maxlen=LINEAS_CONTEXTO)
        self._hilo = threading.Thread(target=self._bucle, name="orquestador", daemon=True)
        self._hilo.start()

    @property
    def pausado(self) -> bool:
        with self._condicion:
            return self._pausado

    @property
    def silenciado(self) -> bool:
        with self._condicion:
            return self._silenciado

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
            self._condicion.notify_all()

    def silenciar(self) -> None:
        """Calla la voz, pero sigue traduciendo y avisando de cada línea hasta `quitar_silencio`."""
        with self._condicion:
            self._silenciado = True
        self._voz.callar()

    def quitar_silencio(self) -> None:
        with self._condicion:
            self._silenciado = False

    def repetir(self) -> None:
        """Vuelve a leer la última línea (salvo con la voz silenciada)."""
        with self._condicion:
            ultima = None if self._silenciado else self._ultima
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
                self._condicion.wait_for(
                    lambda: bool(self._pendientes) or self._cerrado or self._toca_anticipar()
                )
                if self._cerrado:
                    return
                zona = self._pendientes.popleft() if self._pendientes else None
                self._ocupado = zona is not None
            try:
                if zona is not None:
                    self._procesar(zona)
                else:
                    self._anticipar_siguiente()
            except Exception as error:
                # El hilo tiene que seguir vivo para la zona siguiente.
                _registro.exception("No se pudo procesar la zona de texto")
                self._al_error(_("Error al procesar la línea: {error}").format(error=error))
            finally:
                with self._condicion:
                    self._ocupado = False
                    self._condicion.notify_all()

    def _procesar(self, zona: ZonaEstable) -> None:
        inicio = time.monotonic()
        texto = self._lector.leer(zona.imagen).texto
        nombre = self._lector.leer(zona.nombre).texto or None if zona.nombre is not None else None
        ocr_s = time.monotonic() - inicio
        if not texto or (nombre, texto) == self._ultimo_texto:
            return  # sin texto, o la misma línea redibujada
        self._ultimo_texto = (nombre, texto)
        if self._guion is not None and (parrafos := self._guion.seguidor.nuevos(texto)) is not None:
            preparador = self._guion.preparador
            for parrafo in parrafos:
                if preparador.hay_que_leer(parrafo):
                    self._leer(preparador.clave(parrafo), preparador.peticion(parrafo), zona, inicio, ocr_s)
            with self._condicion:
                self._anticipar = True
            return
        ajustes = self._ajustes
        if nombre is None and zona.nombre is None and ajustes.separar_personaje:
            nombre, texto = separar_personaje(texto, ajustes.idioma)
        (quien, anterior), self._ultimo_dialogo = self._ultimo_dialogo, (nombre, texto)
        if anterior and quien == nombre and texto.startswith(anterior) and texto != anterior:
            # El juego ha añadido texto a la línea anterior, que ya se leyó: solo va lo nuevo.
            texto = texto[len(anterior) :].strip()
        clave = Clave(ajustes.perfil, ajustes.idioma, texto, ajustes.destino)
        peticion = Peticion(texto, ajustes.idioma, tuple(self._contexto), self._glosario, ajustes.destino)
        self._leer(clave, peticion, zona, inicio, ocr_s, nombre)

    def _personaje(self, nombre: str | None) -> str | None:
        """El nombre traducido: del glosario o, la primera vez que sale, del traductor."""
        if nombre is None:
            return None
        traduccion = self._personajes.get(nombre)
        if traduccion is None:
            # Si no se puede traducir, se queda el original, sin reintentarlo en cada línea.
            traduccion = self._personajes[nombre] = self._traducir_personaje(nombre)
        if nombre not in self._vistos and _tiene_letras(nombre):
            self._vistos.add(nombre)
            self._al_personaje(nombre, traduccion)
        return traduccion

    def _traducir_personaje(self, nombre: str) -> str:
        """Traduce un nombre y lo añade al glosario; si no se puede, devuelve el original."""
        if not _tiene_letras(nombre):
            return nombre  # «？？？» y parecidos se quedan como están
        ajustes = self._ajustes
        try:
            nueva = self._traductor.traducir(
                Peticion(nombre, ajustes.idioma, (), self._glosario, ajustes.destino)
            )
        except TraduccionFallidaError as error:
            _registro.warning("No se pudo traducir el nombre «%s»: %s", nombre, error)
            return nombre
        traduccion = _limpiar_personaje(nueva.texto) or nombre
        if traduccion != nombre:
            self._glosario = self._glosario.unir(Glosario(((nombre, traduccion),)))
        return traduccion

    def _leer(
        self,
        clave: Clave,
        peticion: Peticion,
        zona: ZonaEstable,
        inicio: float,
        ocr_s: float,
        nombre: str | None = None,
    ) -> None:
        """Traduce la línea (o la saca de la caché), la lee y avisa de ella.

        El nombre de quien habla se traduce después de empezar a leer, para no retrasar la voz.
        """
        texto = clave.texto
        voz_personaje = self._voces.get(nombre) if nombre is not None else None
        entrada = self._cache.consultar(clave)
        resultado = (
            _Resultado(entrada.traduccion, True, None)
            if entrada
            else self._traducir(clave, peticion, voz_personaje)
        )
        if resultado is None:
            return
        traduccion_s = time.monotonic() - inicio - ocr_s

        self._contexto.append(LineaPrevia(texto, resultado.texto))
        with self._condicion:
            # Si ya espera otra línea o se ha pausado, esta llega tarde: se guarda pero no se lee.
            silenciada = self._silenciado
            leer = resultado.voz is None and not silenciada and not self._llega_tarde_sin_cerrojo()
            self._ultima = (clave, resultado.texto, voz_personaje)
        voz = resultado.voz
        if leer:
            self._voz.decir(clave, resultado.texto, voz_personaje)
            voz = time.monotonic()
        tiempos = Tiempos(ocr_s, traduccion_s, None if voz is None else voz - zona.instante)
        leida = voz is not None
        personaje = self._personaje(nombre)
        linea = LineaJuego(
            texto, resultado.texto, resultado.desde_cache, leida, tiempos, silenciada and not leida, personaje
        )
        self._al_linea(linea)

    def _llega_tarde_sin_cerrojo(self) -> bool:
        if self._pausado or self._cerrado:
            return True
        # En modo cola, que llegue otra línea no deja vieja a esta: se leerá después.
        return self._ajustes.modo is ModoLectura.ULTIMA and bool(self._pendientes)

    def _llega_tarde(self) -> bool:
        with self._condicion:
            return self._llega_tarde_sin_cerrojo()

    def _toca_anticipar(self) -> bool:
        """Si hay que traducir por adelantado (se llama con el cerrojo tomado)."""
        return self._anticipar and not self._pausado and not self._cerrado

    def _anticipar_siguiente(self) -> None:
        """Traduce el primer párrafo siguiente que falte; si ya están todos, deja de anticipar.

        Se cancela en cuanto llega otra zona, para no hacerla esperar.
        """
        guion = self._guion
        try:
            seguir = guion is not None and self._traducir_por_adelantado(guion)
        except Exception:
            # Hasta la próxima zona: si no, se repetiría el mismo fallo sin parar.
            _registro.exception("Falló la traducción por adelantado")
            seguir = False
        if not seguir:
            with self._condicion:
                self._anticipar = False

    def _traducir_por_adelantado(self, guion: GuionJuego) -> bool:
        """Traduce el primer párrafo siguiente que falte. False si no queda ninguno o falla."""
        preparador = guion.preparador
        siguientes = guion.seguidor.siguientes(guion.anticipo)
        siguiente = next((parrafo for parrafo in siguientes if preparador.pendiente(parrafo)), None)
        if siguiente is None:
            return False
        try:
            preparador.traducir(siguiente, self._llega_otra)
        except TraduccionFallidaError as error:
            _registro.warning("No se pudo traducir por adelantado: %s", error)
            return False
        return True

    def _llega_otra(self) -> bool:
        with self._condicion:
            return bool(self._pendientes) or self._pausado or self._cerrado

    def _traducir(self, clave: Clave, peticion: Peticion, voz: str | None = None) -> _Resultado | None:
        texto = clave.texto
        try:
            if isinstance(self._traductor, TraductorPorPartes):
                return self._traducir_por_partes(clave, peticion, self._traductor, voz)
            nueva = self._traductor.traducir(peticion)
        except TraduccionFallidaError as error:
            _registro.warning("No se pudo traducir «%s»: %s", texto, error)
            self._al_error(_("No se pudo traducir la línea: {error}").format(error=error))
            return None
        self._cache.guardar_traduccion(clave, nueva.texto, nueva.modelo)
        return _Resultado(nueva.texto, False, None)

    def _traducir_por_partes(
        self, clave: Clave, peticion: Peticion, traductor: TraductorPorPartes, voz: str | None
    ) -> _Resultado | None:
        partes = TextoPorPartes()
        empezo: float | None = None

        def al_parte(parte: str) -> None:
            nonlocal empezo
            if empezo is None and not self.silenciado:
                self._voz.decir_por_partes(clave, partes, voz)
                empezo = time.monotonic()
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
            if empezo is not None:
                self._voz.callar()  # cancelada, o lo leído no valía y se leerá la traducción entera
            return None if resultado is None else _Resultado(resultado.traduccion.texto, False, None)
        return _Resultado(resultado.traduccion.texto, False, empezo)
