"""Sesión de juego: monta el pipeline completo a partir de un perfil y lo desmonta al salir."""

import contextlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Self

from vn_audiolibro import claves
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.captura.bucle import BucleCaptura
from vn_audiolibro.configuracion import cargar_ajustes
from vn_audiolibro.descargas import asegurar_descarga
from vn_audiolibro.guion.buscador import BuscadorGuion, SeguidorGuion
from vn_audiolibro.guion.modelos import GuionNoEncontradoError, OrigenGuion
from vn_audiolibro.guion.outputline import leer_guion
from vn_audiolibro.guion.previa import IDIOMA_INGLES, AjustesTraduccionGuion, PreparadorGuion
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR
from vn_audiolibro.ocr.modelos import DET_PPOCRV5_MOBILE, REC_PPOCRV5_MOBILE
from vn_audiolibro.ocr.preprocesado import BusquedaTexto
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import AjustesOrquestador, GuionJuego, LineaJuego, Orquestador
from vn_audiolibro.plataforma import capturador, cliente_audio, gestor_ventanas, juego_de_pid, reproductor
from vn_audiolibro.textos import _
from vn_audiolibro.traduccion.gemini import ClienteGemini, TraductorConRespaldo, TraductorGemini
from vn_audiolibro.traduccion.llama import ServidorLlama, asegurar_llama_server, asegurar_modelo_traduccion
from vn_audiolibro.traduccion.local import TraductorLocal
from vn_audiolibro.traduccion.modelos import Glosario, Motor, Traductor
from vn_audiolibro.voz.locutor import Locutor
from vn_audiolibro.voz.modelos import Atenuador, Sintetizador
from vn_audiolibro.voz.piper import SintetizadorPiper, VozElegida, asegurar_voz, elegir_voz
from vn_audiolibro.voz.volumen import AtenuadorJuego, Juego

_registro = logging.getLogger(__name__)


def ajustes_guion(perfil: Perfil) -> AjustesTraduccionGuion:
    """Cómo se traduce el guion del juego."""
    origen = perfil.guion.origen if perfil.guion is not None else OrigenGuion.ORIGINAL
    return AjustesTraduccionGuion(perfil.id, perfil.idioma, origen, perfil.glosario, perfil.destino)


@contextlib.contextmanager
def traductor_guion(
    perfil: Perfil, al_estado: Callable[[str], None] = lambda _: None
) -> Iterator[PreparadorGuion]:
    """Lee el guion del juego y arranca el traductor para traducirlo sin jugar.

    Lanza `GuionNoEncontradoError` si el juego no tiene guion configurado o no se puede leer.
    """
    if perfil.guion is None:
        raise GuionNoEncontradoError(
            _("«{nombre}» no tiene configurado el guion del juego").format(nombre=perfil.nombre)
        )
    al_estado(_("Leyendo el guion del juego…"))
    guion = leer_guion(Path(perfil.guion.carpeta))
    al_estado(_("Preparando el traductor (la primera vez se descarga)…"))
    llama, modelo = asegurar_llama_server(), asegurar_modelo_traduccion()
    with contextlib.ExitStack() as pila:
        al_estado(_("Arrancando el traductor…"))
        servidor = ServidorLlama(llama, modelo)
        cliente = servidor.iniciar()
        pila.callback(servidor.detener)
        cache = CacheSQLite(limite_bytes=cargar_ajustes().limite_cache_bytes)
        pila.callback(cache.cerrar)
        yield PreparadorGuion(guion, ajustes_guion(perfil), TraductorLocal(cliente), cache)


class Sesion:
    """Todo lo necesario para jugar con un perfil. Usar con `with` para desmontarlo al salir.

    Si algo falla al montar, se desmonta lo que ya estuviera en marcha (el servidor de
    traducción, el volumen del juego…) antes de propagar el error.
    """

    def __init__(
        self,
        perfil: Perfil,
        al_linea: Callable[[LineaJuego], None],
        al_error: Callable[[str], None],
        al_estado: Callable[[str], None] = lambda _: None,
        almacen: AlmacenPerfiles | None = None,
    ) -> None:
        """`almacen` es donde se guardan los nombres de personaje aprendidos al jugar."""
        self.perfil = perfil
        self._almacen = almacen or AlmacenPerfiles()
        self._al_linea = al_linea
        self._al_error = al_error
        self._al_estado = al_estado
        self._pila = contextlib.ExitStack()
        self.orquestador: Orquestador | None = None

    def iniciar(self) -> Orquestador:
        """Busca la ventana, prepara los modelos, arranca todo y empieza a capturar."""
        try:
            return self._montar()
        except BaseException:
            self.detener()
            raise

    def detener(self) -> None:
        """Para la captura, la voz y el traductor, y devuelve el volumen del juego."""
        self.orquestador = None
        self._pila.close()

    def __enter__(self) -> Self:
        self.iniciar()
        return self

    def __exit__(
        self, tipo: type[BaseException] | None, error: BaseException | None, traza: TracebackType | None
    ) -> None:
        self.detener()

    def _montar(self) -> Orquestador:
        perfil, pila = self.perfil, self._pila
        self._al_estado(_("Buscando la ventana «{ventana}»…").format(ventana=perfil.ventana))
        ventanas = gestor_ventanas()
        ventana = ventanas.buscar(perfil.ventana)

        self._al_estado(_("Preparando los modelos (la primera vez se descargan)…"))
        modelo_ocr = asegurar_descarga(REC_PPOCRV5_MOBILE)
        con_detector = perfil.busqueda is BusquedaTexto.DETECTOR
        modelo_detector = asegurar_descarga(DET_PPOCRV5_MOBILE) if con_detector else None
        voz = elegir_voz(perfil.destino, perfil.voz.hablante)
        modelo_voz = asegurar_voz(voz.voz)
        voces_personajes = perfil.voces_personajes()
        otras_voces = {h: elegir_voz(perfil.destino, h) for h in set(voces_personajes.values())}
        modelos_otras = {h: asegurar_voz(elegida.voz) for h, elegida in otras_voces.items()}
        llama, modelo_traduccion = asegurar_llama_server(), asegurar_modelo_traduccion()

        self._al_estado(_("Arrancando el traductor…"))
        servidor = ServidorLlama(llama, modelo_traduccion)
        cliente = servidor.iniciar()
        pila.callback(servidor.detener)

        cache = CacheSQLite(limite_bytes=cargar_ajustes().limite_cache_bytes)
        pila.callback(cache.cerrar)
        juego = juego_de_pid(ventana.pid) if ventana.pid is not None else None
        sintetizador = SintetizadorPiper(modelo_voz, voz.hablante, perfil.voz.velocidad)
        locutor = Locutor(
            sintetizador,
            reproductor(),
            cache,
            self._atenuador(juego),
            modo=perfil.lectura.modo,
            pausa_s=perfil.lectura.pausa_s,
            voces={
                h.value: self._sintetizador_de(voz, sintetizador, elegida, modelos_otras[h])
                for h, elegida in otras_voces.items()
            },
        )
        pila.callback(locutor.cerrar)

        self._al_estado(_("Calentando el traductor…"))
        local = TraductorLocal(cliente)
        desde_ingles = perfil.guion is not None and perfil.guion.origen is OrigenGuion.INGLES
        local.calentar(IDIOMA_INGLES if desde_ingles else perfil.idioma, perfil.destino)
        traductor = self._traductor(local)
        guion = self._guion(traductor, cache)

        reconocedor = ReconocedorRapidOCR(modelo_ocr, modelo_detector)
        lector = LectorOCR(
            reconocedor,
            AjustesLector(perfil.idioma, perfil.color.color_texto, perfil.orientacion, perfil.busqueda),
            reconocedor if con_detector else None,
        )
        orquestador = Orquestador(
            AjustesOrquestador(
                perfil.id,
                perfil.idioma,
                perfil.glosario,
                perfil.lectura.modo,
                destino=perfil.destino,
                separar_personaje=perfil.separar_personaje,
                voces=tuple((nombre, hablante.value) for nombre, hablante in voces_personajes.items()),
            ),
            lector,
            traductor,
            cache,
            locutor,
            self._al_linea,
            self._al_error,
            guion,
            al_personaje=self.guardar_personaje,
        )
        pila.callback(orquestador.cerrar)

        bucle = BucleCaptura(
            ventana.id,
            perfil.zona,
            orquestador.recibir_zona,
            ventanas,
            capturador(ventanas),
            zona_nombre=perfil.zona_nombre,
        )
        bucle.iniciar()
        pila.callback(bucle.detener)
        self._al_estado(_("Leyendo «{ventana}».").format(ventana=ventana.titulo))
        self.orquestador = orquestador
        return orquestador

    def _sintetizador_de(
        self, del_juego: VozElegida, sintetizador: SintetizadorPiper, otra: VozElegida, modelo: Path
    ) -> Sintetizador:
        """Sintetizador de otra voz; si es otro hablante del mismo modelo, no lo carga dos veces."""
        if otra.voz == del_juego.voz:
            return sintetizador.con_hablante(otra.hablante)
        return SintetizadorPiper(modelo, otra.hablante, self.perfil.voz.velocidad)

    def guardar_personaje(self, original: str, traduccion: str) -> None:
        """Apunta en el juego al personaje que ha hablado y añade su nombre traducido al glosario.

        Lo que el usuario ya haya puesto (la voz del personaje o otra traducción) se respeta. Se
        relee el juego guardado para no pisar lo que haya cambiado desde que empezó la partida.
        """
        try:
            actual = self._almacen.cargar(self.perfil.id)
            nuevo = actual
            if all(nombre != original for nombre, _voz in actual.personajes):
                nuevo = replace(nuevo, personajes=(*actual.personajes, (original, None)))
            conocido = any(termino == original for termino, _traduccion in actual.glosario.terminos)
            if traduccion != original and not conocido:
                nuevo = replace(nuevo, glosario=actual.glosario.unir(Glosario(((original, traduccion),))))
            if nuevo != actual:
                self._almacen.guardar(nuevo)
        except (KeyError, OSError, ValueError):
            # Sin guardarlo se puede seguir jugando: se volverá a traducir en la próxima partida.
            _registro.warning("No se pudo guardar el nombre «%s» en el glosario", original, exc_info=True)

    def _traductor(self, local: TraductorLocal) -> Traductor:
        """El traductor del juego: el local o Gemini, que recurre al local si falla."""
        if self.perfil.traductor is not Motor.GEMINI:
            return local
        clave = claves.leer()
        if clave is None:
            self._al_error(
                _("Falta la clave de Gemini: se traducirá en local. Añádela en el editor del juego.")
            )
            return local
        gemini = TraductorGemini(ClienteGemini(clave))
        return TraductorConRespaldo(gemini, local, self._al_error)

    def _guion(self, traductor: Traductor, cache: CacheSQLite) -> GuionJuego | None:
        """El guion del juego, si se ha configurado y se puede leer; si no, se juega con el OCR."""
        perfil = self.perfil
        if perfil.guion is None:
            return None
        self._al_estado(_("Leyendo el guion del juego…"))
        try:
            guion = leer_guion(Path(perfil.guion.carpeta))
        except GuionNoEncontradoError as error:
            _registro.warning("No se usará el guion: %s", error)
            self._al_error(_("No se usará el guion, solo el OCR: {error}").format(error=error))
            return None
        return GuionJuego(
            SeguidorGuion(guion, BuscadorGuion(guion, perfil.idioma)),
            PreparadorGuion(guion, ajustes_guion(perfil), traductor, cache),
        )

    def _atenuador(self, juego: Juego | None) -> Atenuador | None:
        seleccion = self.perfil.volumen.seleccion(juego)
        if seleccion is None:
            return None
        try:
            atenuador = AtenuadorJuego(cliente_audio(), seleccion)
        except Exception as error:
            # Sin control del volumen se puede jugar igual.
            _registro.warning("No se podrá bajar el volumen del juego: %s", error)
            self._al_error(_("No se podrá bajar el volumen del juego: {error}").format(error=error))
            return None
        self._pila.callback(atenuador.cerrar)
        return atenuador
