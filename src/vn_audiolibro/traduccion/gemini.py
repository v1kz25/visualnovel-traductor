"""Traductor opcional en la nube: Gemini de Google, con la clave de API del propio usuario.

Se activa por juego y está desactivado por defecto: el texto del juego se envía a Google. Si
Gemini falla (sin conexión, clave no válida, límite de peticiones agotado, respuesta bloqueada),
`TraductorConRespaldo` traduce esa línea con el traductor local y avisa.

La clave va en la cabecera `x-goog-api-key`, nunca en la URL, y no se escribe en ningún mensaje
ni registro.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import Any

from vn_audiolibro.rutas import directorio_estado
from vn_audiolibro.textos import N_, _
from vn_audiolibro.traduccion import postprocesado
from vn_audiolibro.traduccion.modelos import (
    Glosario,
    LimiteAgotadoError,
    Peticion,
    ResultadoPorPartes,
    Traduccion,
    TraduccionFallidaError,
    Traductor,
    TraductorPorPartes,
    glosario_por_defecto,
)
from vn_audiolibro.traduccion.partes import Segmentador
from vn_audiolibro.traduccion.prompt import DESTINOS

_registro = logging.getLogger(__name__)

MODELO_GEMINI = "gemini-flash-lite-latest"
"""Flash-Lite, el recomendado para mucho volumen y poca espera; el alias sigue a la última versión."""

URL_API = "https://generativelanguage.googleapis.com/v1beta"

URL_CLAVES = "https://aistudio.google.com/apikey"
"""Donde cada usuario crea su clave gratuita con su cuenta de Google."""

POR_MINUTO = 15
POR_DIA = 1000
"""Límites del plan gratuito de Flash-Lite (octubre de 2026). Al llegar, se traduce en local."""

PAUSA_CUOTA_S = 60.0
"""Tras un «límite agotado» de Google, tiempo sin intentarlo antes de volver a Gemini."""

LINEAS_CONTEXTO = 3

TAMANO_LOTE = 40
"""Líneas del guion por petición al traducirlo por adelantado: con 1000 peticiones al día caben
40 000 líneas, y la respuesta (unos 2000-4000 tokens) sale en pocos segundos."""

REINTENTOS_CUOTA = 3
"""«Límite agotado» seguidos de Google con los que se da el día por terminado."""

INSTRUCCIONES = (
    "You translate dialogue and narration from a visual novel into {destino}. Translate the "
    "[Source Text] faithfully and naturally, keeping its tone and register: do not soften insults "
    "or swearing, and do not add or omit anything. Use the given translations for names and terms. "
    "The [Background] lines are only context: never translate or repeat them. Output only the "
    "translation, on a single line, without quotes around it unless the source has them, notes "
    "or explanations."
)

INSTRUCCIONES_LOTE = (
    "You translate dialogue and narration from a visual novel into {destino}. The [Lines] are "
    "numbered and in order: translate each one faithfully and naturally, keeping its tone and "
    "register: do not soften insults or swearing, and do not add, omit, merge or split lines. Use "
    "the given translations for names and terms. The [Background] lines are only context: never "
    'translate them. Answer with one item per line: its number in "n" and its translation, on a '
    'single line, in "t". Keep quotes only where the source has them.'
)

ESQUEMA_LOTE = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {"n": {"type": "INTEGER"}, "t": {"type": "STRING"}},
        "required": ["n", "t"],
    },
}
"""Respuesta estructurada de un lote: Gemini devuelve JSON con este esquema."""

CATEGORIAS = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)
"""Las VN tienen insultos y violencia: sin esto, Google bloquea líneas normales del juego."""


class CuotaAgotadaError(TraduccionFallidaError):
    """Google ha rechazado la petición por el límite de peticiones (HTTP 429)."""


class ClienteGemini:
    """Cliente mínimo de la API REST de Gemini (`generateContent`)."""

    def __init__(
        self, clave: str, modelo: str = MODELO_GEMINI, url: str = URL_API, timeout_s: float = 20
    ) -> None:
        self._clave = clave
        self.modelo = modelo
        self._url = url.rstrip("/")
        self._timeout_s = timeout_s

    def generar(self, cuerpo: dict[str, Any]) -> str:
        """Texto de la respuesta completa."""
        try:
            with self._abrir("generateContent", cuerpo) as respuesta:
                return _texto(json.load(respuesta))
        except _ERRORES_RESPUESTA as error:
            raise _respuesta_rota(error) from None

    def generar_por_partes(self, cuerpo: dict[str, Any]) -> Generator[str]:
        """Texto de la respuesta a medida que llega (SSE). Cerrar el generador corta la conexión."""
        try:
            with self._abrir("streamGenerateContent?alt=sse", cuerpo) as respuesta:
                for linea in respuesta:
                    datos = linea.decode("utf-8").strip()
                    if datos.startswith("data: "):
                        trozo = _texto(json.loads(datos[len("data: ") :]), parcial=True)
                        if trozo:
                            yield trozo
        except _ERRORES_RESPUESTA as error:
            raise _respuesta_rota(error) from None

    def _abrir(self, accion: str, cuerpo: dict[str, Any]) -> Any:
        url = f"{self._url}/models/{self.modelo}:{accion}"
        cabeceras = {"Content-Type": "application/json", "x-goog-api-key": self._clave}
        peticion = urllib.request.Request(url, json.dumps(cuerpo).encode(), cabeceras)  # noqa: S310 - https fijo
        try:
            return urllib.request.urlopen(peticion, timeout=self._timeout_s)  # noqa: S310
        except urllib.error.HTTPError as error:
            raise _error_http(error) from None
        except OSError as error:
            raise TraduccionFallidaError(
                _("No se pudo conectar con Gemini: {error}").format(error=error)
            ) from None


_ERRORES_RESPUESTA = (OSError, ValueError, KeyError, TypeError, AttributeError)
"""Conexión cortada a medias o respuesta que no es el JSON esperado."""


def _respuesta_rota(error: Exception) -> TraduccionFallidaError:
    return TraduccionFallidaError(_("Respuesta de Gemini no válida: {error}").format(error=error))


def _error_http(error: urllib.error.HTTPError) -> TraduccionFallidaError:
    """Error de la API con su mensaje (que no incluye la clave)."""
    try:
        mensaje = json.load(error)["error"]["message"]
    except (ValueError, KeyError, TypeError, OSError):
        mensaje = error.reason
    if error.code == 429:
        return CuotaAgotadaError(
            _("Gemini: límite de peticiones agotado ({mensaje})").format(mensaje=mensaje)
        )
    if error.code in (400, 401, 403) and "key" in str(mensaje).lower():
        return TraduccionFallidaError(_("Gemini no acepta la clave de API: revísala en el editor del juego"))
    return TraduccionFallidaError(
        _("Error de Gemini ({codigo}): {mensaje}").format(codigo=error.code, mensaje=mensaje)
    )


def _texto(respuesta: dict[str, Any], parcial: bool = False) -> str:
    """Texto de una respuesta de `generateContent`; error si Google la ha bloqueado."""
    if bloqueo := respuesta.get("promptFeedback", {}).get("blockReason"):
        raise TraduccionFallidaError(_("Gemini ha bloqueado la línea ({motivo})").format(motivo=bloqueo))
    candidatos = respuesta.get("candidates") or []
    if not candidatos:
        if parcial:
            return ""
        raise TraduccionFallidaError(_("Gemini no ha devuelto ninguna traducción"))
    candidato = candidatos[0]
    partes = candidato.get("content", {}).get("parts") or []
    texto = "".join(parte.get("text", "") for parte in partes if not parte.get("thought"))
    if not texto and candidato.get("finishReason") not in (None, "STOP"):
        raise TraduccionFallidaError(
            _("Gemini no ha traducido la línea ({motivo})").format(motivo=candidato["finishReason"])
        )
    return texto


def cuerpo_peticion(peticion: Peticion) -> dict[str, Any]:
    """La petición a Gemini: instrucciones, contexto, glosario y la línea a traducir."""
    glosario = glosario_por_defecto(peticion.idioma).unir(peticion.glosario)
    bloques = []
    if contexto := list(peticion.contexto)[-LINEAS_CONTEXTO:]:
        bloques.append("[Background]\n" + "\n".join(linea.original for linea in contexto))
    if terminos := glosario.presentes(peticion.texto):
        bloques.append("[Glossary]\n" + "\n".join(f"{t} = {d}" for t, d in terminos))
    bloques.append(f"[Source Text]\n{peticion.texto}")
    return {
        "systemInstruction": {"parts": [{"text": INSTRUCCIONES.format(destino=DESTINOS[peticion.destino])}]},
        "contents": [{"role": "user", "parts": [{"text": "\n\n".join(bloques)}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 64 + 4 * len(peticion.texto)},
        "safetySettings": _ajustes_seguridad(),
    }


def _ajustes_seguridad() -> list[dict[str, str]]:
    return [{"category": categoria, "threshold": "BLOCK_NONE"} for categoria in CATEGORIAS]


def cuerpo_lote(peticiones: Sequence[Peticion]) -> dict[str, Any]:
    """La petición de un lote: las líneas numeradas, el contexto de la primera y el glosario.

    Todas las líneas van al mismo idioma de destino; el contexto es el de antes de la primera,
    porque cada línea tiene las anteriores del lote justo encima.
    """
    primera = peticiones[0]
    glosario = Glosario()
    for idioma in dict.fromkeys(peticion.idioma for peticion in peticiones):
        glosario = glosario.unir(glosario_por_defecto(idioma))
    glosario = glosario.unir(primera.glosario)
    lineas = [" ".join(peticion.texto.split()) for peticion in peticiones]
    bloques = []
    if contexto := list(primera.contexto)[-LINEAS_CONTEXTO:]:
        bloques.append("[Background]\n" + "\n".join(linea.original for linea in contexto))
    if terminos := glosario.presentes("\n".join(lineas)):
        bloques.append("[Glossary]\n" + "\n".join(f"{t} = {d}" for t, d in terminos))
    bloques.append("[Lines]\n" + "\n".join(f"{n}. {linea}" for n, linea in enumerate(lineas, 1)))
    caracteres = sum(len(linea) for linea in lineas)
    instrucciones = INSTRUCCIONES_LOTE.format(destino=DESTINOS[primera.destino])
    return {
        "systemInstruction": {"parts": [{"text": instrucciones}]},
        "contents": [{"role": "user", "parts": [{"text": "\n\n".join(bloques)}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 256 + 32 * len(lineas) + 4 * caracteres,
            "responseMimeType": "application/json",
            "responseSchema": ESQUEMA_LOTE,
        },
        "safetySettings": _ajustes_seguridad(),
    }


def leer_lote(salida: str, peticiones: Sequence[Peticion]) -> list[str | None]:
    """La traducción de cada línea del lote, en orden; None en las que falten o no valgan.

    Se ordenan por su número, no por su posición en la respuesta. Una línea repetida vale la
    primera vez; una vacía, desproporcionada o con varias líneas no vale.
    """
    textos: list[str | None] = [None] * len(peticiones)
    try:
        elementos = json.loads(salida)
    except ValueError:
        _registro.warning("Gemini ha devuelto un lote que no es JSON válido")
        return textos
    for elemento in elementos if isinstance(elementos, list) else ():
        leido = _elemento_lote(elemento, len(peticiones))
        if leido is None or textos[leido[0] - 1] is not None:
            continue
        numero, texto = leido
        peticion = peticiones[numero - 1]
        if postprocesado.es_valida(texto, peticion.texto):
            textos[numero - 1] = postprocesado.limpiar(texto, peticion.texto, peticion.destino)
    return textos


def _elemento_lote(elemento: object, lineas: int) -> tuple[int, str] | None:
    """El número (de 1 a `lineas`) y el texto de un elemento de la respuesta, o None si no vale."""
    if not isinstance(elemento, dict):
        return None
    numero, texto = elemento.get("n"), elemento.get("t")
    if isinstance(numero, bool) or not isinstance(numero, int) or not isinstance(texto, str):
        return None
    return (numero, texto) if 1 <= numero <= lineas else None


class TraductorGemini:
    """Traduce con Gemini, en streaming si se pide por partes, o varias líneas en una petición."""

    def __init__(self, cliente: ClienteGemini) -> None:
        self._cliente = cliente
        self.modelo = cliente.modelo

    def traducir(self, peticion: Peticion) -> Traduccion:
        salida = self._cliente.generar(cuerpo_peticion(peticion))
        return self._traduccion(salida, peticion)

    def traducir_lote(self, peticiones: Sequence[Peticion]) -> list[Traduccion | None]:
        """Una traducción por línea, en orden; None en las que Gemini no haya traducido bien."""
        textos = leer_lote(self._cliente.generar(cuerpo_lote(peticiones)), peticiones)
        return [None if texto is None else Traduccion(texto, self.modelo) for texto in textos]

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        segmentador = Segmentador()
        salida = ""
        trozos = self._cliente.generar_por_partes(cuerpo_peticion(peticion))
        try:
            for trozo in trozos:
                if cancelado():
                    return None
                salida += trozo
                for parte in segmentador.anadir(trozo):
                    al_parte(parte)
        finally:
            trozos.close()
        if not salida.strip():
            raise TraduccionFallidaError(_("Gemini no ha devuelto ninguna traducción"))
        if resto := segmentador.terminar():
            al_parte(resto)
        return ResultadoPorPartes(self._traduccion(salida, peticion), por_partes=True)

    def _traduccion(self, salida: str, peticion: Peticion) -> Traduccion:
        return Traduccion(postprocesado.limpiar(salida, peticion.texto, peticion.destino), self.modelo)


DIA_S = 24 * 3600


def fichero_peticiones() -> Path:
    """Donde se apuntan las peticiones a Gemini, para respetar el límite diario entre ejecuciones."""
    return directorio_estado() / "gemini-peticiones.json"


class LimitePeticiones:
    """Cuenta las peticiones del último minuto y del último día para no pasar los límites.

    Con `ruta`, guarda la hora de cada petición del último día en ese fichero: el límite diario se
    respeta aunque se cierre la app, y lo comparten la partida y la traducción del guion.
    """

    def __init__(
        self,
        por_minuto: int = POR_MINUTO,
        por_dia: int = POR_DIA,
        reloj: Callable[[], float] = time.time,
        ruta: Path | None = None,
    ) -> None:
        self.por_dia = por_dia
        self._por_minuto = por_minuto
        self._reloj = reloj
        self._ruta = ruta
        self._instantes: deque[float] = deque(self._cargar())
        self._pausa_hasta = 0.0
        self._cerrojo = threading.Lock()

    @classmethod
    def compartido(cls) -> "LimitePeticiones":
        """El límite guardado en el fichero de estado de la app."""
        return cls(ruta=fichero_peticiones())

    def _cargar(self) -> list[float]:
        if self._ruta is None:
            return []
        try:
            datos = json.loads(self._ruta.read_text(encoding="utf-8"))
            ahora = self._reloj()
            # Las de más de un día ya no cuentan; las del futuro (el reloj ha cambiado), tampoco.
            return sorted(
                float(instante)
                for instante in datos["peticiones"]
                if isinstance(instante, int | float) and 0 <= ahora - instante < DIA_S
            )
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError):
            _registro.warning("No se pudo leer %s: se empieza la cuenta de cero", self._ruta, exc_info=True)
            return []

    def _guardar(self) -> None:
        if self._ruta is None:
            return
        try:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            temporal = self._ruta.with_name(self._ruta.name + ".parcial")
            temporal.write_text(json.dumps({"peticiones": list(self._instantes)}), encoding="utf-8")
            temporal.replace(self._ruta)
        except OSError:
            _registro.warning("No se pudo guardar la cuenta de peticiones a Gemini", exc_info=True)

    def _olvidar_viejas(self, ahora: float) -> None:
        while self._instantes and ahora - self._instantes[0] >= DIA_S:
            self._instantes.popleft()

    def reservar(self) -> bool:
        """Apunta una petición si cabe en los límites; False si hay que esperar."""
        with self._cerrojo:
            ahora = self._reloj()
            self._olvidar_viejas(ahora)
            ultimo_minuto = sum(1 for instante in self._instantes if ahora - instante < 60)
            if (
                ahora < self._pausa_hasta
                or ultimo_minuto >= self._por_minuto
                or len(self._instantes) >= self.por_dia
            ):
                return False
            self._instantes.append(ahora)
            self._guardar()
            return True

    def lleno_hoy(self) -> bool:
        """Si ya se han hecho todas las peticiones del día."""
        with self._cerrojo:
            self._olvidar_viejas(self._reloj())
            return len(self._instantes) >= self.por_dia

    def pausar(self, segundos: float = PAUSA_CUOTA_S) -> None:
        """No deja hacer peticiones durante un rato (tras un «límite agotado» de Google)."""
        with self._cerrojo:
            self._pausa_hasta = self._reloj() + segundos


SEGUIR = N_(
    "Lo traducido se conserva: sigue mañana, o elige el traductor local en el editor del juego "
    "para seguir ahora."
)


class TraductorConRespaldo:
    """Traduce con el traductor en la nube y, si no puede, con el local.

    Avisa (con `al_aviso`) la primera vez que una línea va al local, y otra vez cuando la nube
    vuelve a funcionar, sin repetir el aviso en cada línea.
    """

    tamano_lote = TAMANO_LOTE

    def __init__(
        self,
        principal: TraductorGemini,
        respaldo: Traductor,
        al_aviso: Callable[[str], None] = lambda _: None,
        limite: LimitePeticiones | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._principal = principal
        self._respaldo = respaldo
        self._al_aviso = al_aviso
        self._limite = limite or LimitePeticiones()
        self._dormir = dormir
        self._avisado = False

    def traducir(self, peticion: Peticion) -> Traduccion:
        if self._limite.reservar():
            try:
                traduccion = self._principal.traducir(peticion)
            except TraduccionFallidaError as error:
                self._fallo(error)
            else:
                self._funciona()
                return traduccion
        else:
            self._fallo(None)
        return self._respaldo.traducir(peticion)

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        entregadas: list[str] = []

        def anotar(parte: str) -> None:
            entregadas.append(parte)
            al_parte(parte)

        if self._limite.reservar():
            try:
                resultado = self._principal.traducir_por_partes(peticion, anotar, cancelado)
            except TraduccionFallidaError as error:
                self._fallo(error)
            else:
                self._funciona()
                return resultado
        else:
            self._fallo(None)
        if entregadas:
            # La voz ya ha empezado a leer la de Gemini: se descarta y se lee la local entera.
            return ResultadoPorPartes(self._respaldo.traducir(peticion), por_partes=False)
        if isinstance(self._respaldo, TraductorPorPartes):
            return self._respaldo.traducir_por_partes(peticion, al_parte, cancelado)
        return ResultadoPorPartes(self._respaldo.traducir(peticion), por_partes=False)

    def traducir_lote(
        self, peticiones: Sequence[Peticion], cancelado: Callable[[], bool]
    ) -> list[Traduccion] | None:
        """Traduce el lote con Gemini en una petición; lo que no traduzca bien, en local.

        Espera si se ha llegado al límite por minuto. Lanza `LimiteAgotadoError` si no quedan
        peticiones por hoy o si Google sigue diciendo que se ha agotado el límite.
        """
        parciales = self._lote_gemini(peticiones, cancelado)
        if parciales is None:
            return None
        traducciones = []
        for peticion, traduccion in zip(peticiones, parciales, strict=True):
            if cancelado():
                return None
            traducciones.append(traduccion or self._respaldo.traducir(peticion))
        if faltan := parciales.count(None):
            _registro.info(
                "Gemini no ha traducido %d de %d líneas del lote: van en local", faltan, len(peticiones)
            )
        return traducciones

    def _lote_gemini(
        self, peticiones: Sequence[Peticion], cancelado: Callable[[], bool]
    ) -> list[Traduccion | None] | None:
        """Lo que traduce Gemini del lote (None en lo que falte), o None si se cancela."""
        for _intento in range(REINTENTOS_CUOTA):
            if not self._esperar_turno(cancelado):
                return None
            try:
                parciales = self._principal.traducir_lote(peticiones)
            except CuotaAgotadaError as error:
                self._fallo(error)  # pausa Gemini un minuto y se vuelve a intentar
                continue
            except TraduccionFallidaError as error:
                self._fallo(error)
                return [None] * len(peticiones)
            self._funciona()
            return parciales
        raise LimiteAgotadoError(
            _("Google sigue diciendo que se ha agotado el límite de Gemini. {seguir}").format(
                seguir=_(SEGUIR)
            )
        )

    def _esperar_turno(self, cancelado: Callable[[], bool]) -> bool:
        """Espera a que quepa una petición en el límite por minuto; False si se cancela."""
        while not self._limite.reservar():
            if self._limite.lleno_hoy():
                raise LimiteAgotadoError(
                    _("Se ha agotado el límite diario de Gemini ({peticiones} peticiones). {seguir}").format(
                        peticiones=self._limite.por_dia, seguir=_(SEGUIR)
                    )
                )
            if cancelado():
                return False
            self._dormir(1)
        return not cancelado()

    def _fallo(self, error: TraduccionFallidaError | None) -> None:
        if isinstance(error, CuotaAgotadaError):
            self._limite.pausar()
        if error is not None:
            _registro.warning("Gemini no ha traducido la línea: %s", error)
        if self._avisado:
            return
        self._avisado = True
        motivo = str(error) if error is not None else _("límite de peticiones por minuto o por día")
        self._al_aviso(
            _("Se traduce en local mientras Gemini no esté disponible: {motivo}").format(motivo=motivo)
        )

    def _funciona(self) -> None:
        if self._avisado:
            self._avisado = False
            self._al_aviso(_("Gemini vuelve a traducir"))


def avisos_privacidad() -> Sequence[str]:
    """Lo que hay que saber antes de activar Gemini. Se traduce al mostrarlo."""
    return (
        _("El texto del juego se envía a Google para traducirlo."),
        _("En el plan gratuito, Google puede usar ese texto para mejorar sus productos."),
        _("Necesitas tu propia clave gratuita de Google AI Studio: {url}").format(url=URL_CLAVES),
    )
