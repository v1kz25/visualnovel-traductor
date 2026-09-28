"""Sesión de juego: monta el pipeline completo a partir de un perfil y lo desmonta al salir."""

import contextlib
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Self

from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.captura.bucle import BucleCaptura
from vn_audiolibro.configuracion import cargar_ajustes
from vn_audiolibro.descargas import asegurar_descarga
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR
from vn_audiolibro.ocr.modelos import REC_PPOCRV5_MOBILE
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import AjustesOrquestador, LineaJuego, Orquestador
from vn_audiolibro.plataforma import capturador, cliente_audio, gestor_ventanas, juego_de_pid, reproductor
from vn_audiolibro.traduccion.llama import ServidorLlama, asegurar_llama_server, asegurar_modelo_traduccion
from vn_audiolibro.traduccion.local import TraductorLocal
from vn_audiolibro.voz.locutor import Locutor
from vn_audiolibro.voz.modelos import Atenuador
from vn_audiolibro.voz.piper import SintetizadorPiper, asegurar_voz, elegir_voz
from vn_audiolibro.voz.volumen import AtenuadorJuego, Juego

_registro = logging.getLogger(__name__)


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
    ) -> None:
        self.perfil = perfil
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
        self._al_estado(f"Buscando la ventana «{perfil.ventana}»…")
        ventanas = gestor_ventanas()
        ventana = ventanas.buscar(perfil.ventana)

        self._al_estado("Preparando los modelos (la primera vez se descargan)…")
        modelo_ocr = asegurar_descarga(REC_PPOCRV5_MOBILE)
        voz = elegir_voz(perfil.destino, perfil.voz.hablante)
        modelo_voz = asegurar_voz(voz.voz)
        llama, modelo_traduccion = asegurar_llama_server(), asegurar_modelo_traduccion()

        self._al_estado("Arrancando el traductor…")
        servidor = ServidorLlama(llama, modelo_traduccion)
        cliente = servidor.iniciar()
        pila.callback(servidor.detener)

        cache = CacheSQLite(limite_bytes=cargar_ajustes().limite_cache_bytes)
        pila.callback(cache.cerrar)
        juego = juego_de_pid(ventana.pid) if ventana.pid is not None else None
        locutor = Locutor(
            SintetizadorPiper(modelo_voz, voz.hablante, perfil.voz.velocidad),
            reproductor(),
            cache,
            self._atenuador(juego),
            modo=perfil.lectura.modo,
            pausa_s=perfil.lectura.pausa_s,
        )
        pila.callback(locutor.cerrar)

        self._al_estado("Calentando el traductor…")
        traductor = TraductorLocal(cliente)
        traductor.calentar(perfil.idioma, perfil.destino)

        lector = LectorOCR(
            ReconocedorRapidOCR(modelo_ocr),
            AjustesLector(perfil.idioma, perfil.color.color_texto, perfil.orientacion),
        )
        orquestador = Orquestador(
            AjustesOrquestador(
                perfil.id, perfil.idioma, perfil.glosario, perfil.lectura.modo, destino=perfil.destino
            ),
            lector,
            traductor,
            cache,
            locutor,
            self._al_linea,
            self._al_error,
        )
        pila.callback(orquestador.cerrar)

        bucle = BucleCaptura(
            ventana.id, perfil.zona, orquestador.recibir_zona, ventanas, capturador(ventanas)
        )
        bucle.iniciar()
        pila.callback(bucle.detener)
        self._al_estado(f"Leyendo «{ventana.titulo}».")
        self.orquestador = orquestador
        return orquestador

    def _atenuador(self, juego: Juego | None) -> Atenuador | None:
        seleccion = self.perfil.volumen.seleccion(juego)
        if seleccion is None:
            return None
        try:
            atenuador = AtenuadorJuego(cliente_audio(), seleccion)
        except Exception as error:
            # Sin control del volumen se puede jugar igual.
            _registro.warning("No se podrá bajar el volumen del juego: %s", error)
            self._al_error(f"No se podrá bajar el volumen del juego: {error}")
            return None
        self._pila.callback(atenuador.cerrar)
        return atenuador
