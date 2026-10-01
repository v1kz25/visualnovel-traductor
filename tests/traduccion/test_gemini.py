"""Tests del traductor de Gemini con un servidor falso de su API (sin clave ni conexión)."""

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from vn_audiolibro.traduccion.gemini import (
    URL_CLAVES,
    ClienteGemini,
    CuotaAgotadaError,
    LimitePeticiones,
    TraductorConRespaldo,
    TraductorGemini,
    avisos_privacidad,
    cuerpo_peticion,
)
from vn_audiolibro.traduccion.modelos import (
    Glosario,
    LineaPrevia,
    Peticion,
    ResultadoPorPartes,
    Traduccion,
    TraduccionFallidaError,
)

CLAVE = "clave-de-prueba-123"


def respuesta(texto: str, motivo: str = "STOP") -> dict[str, Any]:
    return {
        "candidates": [{"content": {"parts": [{"text": texto}], "role": "model"}, "finishReason": motivo}]
    }


class Manejador(BaseHTTPRequestHandler):
    peticiones: list[tuple[str, dict[str, str], dict[str, Any]]] = []  # noqa: RUF012 - compartida
    estado = 200
    cuerpo: Any = respuesta("Hola.")
    trozos: list[str] = ["Hola, ", "¿qué tal? ", "Bien."]  # noqa: RUF012

    def do_POST(self) -> None:
        datos = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).peticiones.append((self.path, dict(self.headers), datos))
        if "alt=sse" in self.path and self.estado == 200:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for trozo in self.trozos:
                    self.wfile.write(f"data: {json.dumps(respuesta(trozo))}\n\n".encode())
            except BrokenPipeError:
                pass  # el cliente ha cancelado
            return
        cuerpo = self.cuerpo if isinstance(self.cuerpo, bytes) else json.dumps(self.cuerpo).encode()
        self.send_response(self.estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def servidor() -> Iterator[type[Manejador]]:
    class Propio(Manejador):
        peticiones = []  # noqa: RUF012
        estado = 200
        cuerpo = respuesta("Hola.")

    http = ThreadingHTTPServer(("127.0.0.1", 0), Propio)
    hilo = threading.Thread(target=http.serve_forever, args=(0.05,), daemon=True)
    hilo.start()
    Propio.url = f"http://127.0.0.1:{http.server_address[1]}"  # type: ignore[attr-defined]
    yield Propio
    http.shutdown()


def cliente(servidor: type[Manejador]) -> ClienteGemini:
    return ClienteGemini(CLAVE, url=servidor.url)  # type: ignore[attr-defined]


PETICION = Peticion(
    "「先輩、待って！」", "ja", (LineaPrevia("雨だ。", "Llueve."),), Glosario.desde_dict({"待って": "espera"})
)


# La petición


def test_la_peticion_lleva_contexto_glosario_y_la_linea() -> None:
    cuerpo = cuerpo_peticion(PETICION)

    texto = cuerpo["contents"][0]["parts"][0]["text"]
    assert texto.split("\n\n") == [
        "[Background]\n雨だ。",
        "[Glossary]\n先輩 = senpai\n待って = espera",
        "[Source Text]\n「先輩、待って！」",
    ]
    assert "Spanish" in cuerpo["systemInstruction"]["parts"][0]["text"]
    assert {ajuste["threshold"] for ajuste in cuerpo["safetySettings"]} == {"BLOCK_NONE"}


def test_sin_contexto_ni_glosario_solo_va_la_linea() -> None:
    cuerpo = cuerpo_peticion(Peticion("你好", "zh-Hant", destino="en"))

    assert cuerpo["contents"][0]["parts"][0]["text"] == "[Source Text]\n你好"
    assert "English" in cuerpo["systemInstruction"]["parts"][0]["text"]


# El cliente


def test_la_clave_va_en_la_cabecera_y_no_en_la_url(servidor: type[Manejador]) -> None:
    assert cliente(servidor).generar({"contents": []}) == "Hola."

    ((ruta, cabeceras, _),) = servidor.peticiones
    assert ruta == "/models/gemini-flash-lite-latest:generateContent"
    assert CLAVE not in ruta
    assert {nombre.lower(): valor for nombre, valor in cabeceras.items()}["x-goog-api-key"] == CLAVE


def test_por_partes(servidor: type[Manejador]) -> None:
    assert list(cliente(servidor).generar_por_partes({})) == ["Hola, ", "¿qué tal? ", "Bien."]
    assert servidor.peticiones[0][0].endswith(":streamGenerateContent?alt=sse")


@pytest.mark.parametrize(
    ("estado", "cuerpo", "error", "mensaje"),
    [
        (429, {"error": {"code": 429, "message": "Resource exhausted"}}, CuotaAgotadaError, "límite"),
        (400, {"error": {"code": 400, "message": "API key not valid."}}, TraduccionFallidaError, "clave"),
        (500, {"error": {"code": 500, "message": "Internal"}}, TraduccionFallidaError, "500"),
        (503, b"no es json", TraduccionFallidaError, "503"),
        (200, {"promptFeedback": {"blockReason": "SAFETY"}}, TraduccionFallidaError, "bloqueado"),
        (200, respuesta("", "SAFETY"), TraduccionFallidaError, "SAFETY"),
        (200, {"candidates": []}, TraduccionFallidaError, "ninguna"),
        (200, b"{roto", TraduccionFallidaError, "no válida"),
    ],
)
def test_errores_de_la_api(
    servidor: type[Manejador], estado: int, cuerpo: Any, error: type[Exception], mensaje: str
) -> None:
    servidor.estado, servidor.cuerpo = estado, cuerpo

    with pytest.raises(error, match=mensaje) as excepcion:
        cliente(servidor).generar({})
    assert CLAVE not in str(excepcion.value)


def test_sin_conexion() -> None:
    with pytest.raises(TraduccionFallidaError, match="conectar"):
        ClienteGemini(CLAVE, url="http://127.0.0.1:9").generar({})


def test_ignora_el_razonamiento_del_modelo() -> None:
    from vn_audiolibro.traduccion.gemini import _texto

    pensado = {
        "candidates": [{"content": {"parts": [{"text": "pienso…", "thought": True}, {"text": "Hola"}]}}]
    }
    assert _texto(pensado) == "Hola"


# El traductor


def test_traduce_y_pone_las_comillas_del_dialogo(servidor: type[Manejador]) -> None:
    servidor.cuerpo = respuesta("“¡Senpai, espera!”")

    traduccion = TraductorGemini(cliente(servidor)).traducir(PETICION)

    assert traduccion == Traduccion("«¡Senpai, espera!»", "gemini-flash-lite-latest")


def test_traduce_por_partes(servidor: type[Manejador]) -> None:
    partes: list[str] = []

    resultado = TraductorGemini(cliente(servidor)).traducir_por_partes(PETICION, partes.append, lambda: False)

    assert resultado is not None
    assert resultado.por_partes
    assert resultado.traduccion.texto == "«Hola, ¿qué tal? Bien.»"
    assert " ".join(partes) == "Hola, ¿qué tal? Bien."  # el segmentador corta tras cada fin de frase


def test_por_partes_se_puede_cancelar(servidor: type[Manejador]) -> None:
    assert (
        TraductorGemini(cliente(servidor)).traducir_por_partes(PETICION, lambda _: None, lambda: True) is None
    )


def test_por_partes_sin_texto_es_un_fallo(servidor: type[Manejador]) -> None:
    servidor.trozos = []
    with pytest.raises(TraduccionFallidaError, match="ninguna"):
        TraductorGemini(cliente(servidor)).traducir_por_partes(PETICION, lambda _: None, lambda: False)


# Límite de peticiones


def test_limite_por_minuto_y_por_dia() -> None:
    ahora = [0.0]
    limite = LimitePeticiones(por_minuto=2, por_dia=3, reloj=lambda: ahora[0])

    assert [limite.reservar() for _ in range(3)] == [True, True, False]
    ahora[0] = 61
    assert limite.reservar()
    assert not limite.reservar()  # tres en el día
    ahora[0] = 24 * 3600 + 1
    assert limite.reservar()


def test_pausa_tras_un_limite_agotado() -> None:
    ahora = [0.0]
    limite = LimitePeticiones(reloj=lambda: ahora[0])

    limite.pausar(60)
    assert not limite.reservar()
    ahora[0] = 60
    assert limite.reservar()


# Respaldo local


class Falso:
    """Traductor de pega: traduce o falla según se le diga."""

    def __init__(self, nombre: str, fallo: Exception | None = None, partes_antes: int = 0) -> None:
        self.nombre, self.fallo, self.partes_antes = nombre, fallo, partes_antes
        self.llamadas = 0
        self.modelo = nombre

    def traducir(self, peticion: Peticion) -> Traduccion:
        self.llamadas += 1
        if self.fallo:
            raise self.fallo
        return Traduccion(f"{self.nombre}: {peticion.texto}", self.nombre)

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        self.llamadas += 1
        for n in range(self.partes_antes):
            al_parte(f"parte {n}")
        if self.fallo:
            raise self.fallo
        al_parte(self.nombre)
        return ResultadoPorPartes(Traduccion(self.nombre, self.nombre), por_partes=True)


class SinPartes:
    def __init__(self) -> None:
        self.modelo = "local"

    def traducir(self, peticion: Peticion) -> Traduccion:
        return Traduccion("local", "local")


def respaldo(
    principal: Falso, local: Any = None, limite: LimitePeticiones | None = None
) -> tuple[TraductorConRespaldo, list[str]]:
    avisos: list[str] = []
    traductor = TraductorConRespaldo(principal, local or Falso("local"), avisos.append, limite)  # type: ignore[arg-type]
    return traductor, avisos


def test_usa_gemini_si_funciona() -> None:
    traductor, avisos = respaldo(Falso("gemini"))

    assert traductor.traducir(PETICION).modelo == "gemini"
    assert (
        traductor.traducir_por_partes(PETICION, lambda _: None, lambda: False).traduccion.modelo == "gemini"
    )  # type: ignore[union-attr]
    assert avisos == []


def test_si_falla_traduce_en_local_y_avisa_una_vez() -> None:
    gemini = Falso("gemini", TraduccionFallidaError("sin conexión"))
    traductor, avisos = respaldo(gemini)

    assert traductor.traducir(PETICION).modelo == "local"
    assert traductor.traducir(PETICION).modelo == "local"
    assert avisos == ["Se traduce en local mientras Gemini no esté disponible: sin conexión"]

    gemini.fallo = None
    assert traductor.traducir(PETICION).modelo == "gemini"
    assert avisos[-1] == "Gemini vuelve a traducir"


def test_con_el_limite_agotado_no_llama_a_gemini() -> None:
    gemini = Falso("gemini")
    traductor, avisos = respaldo(gemini, limite=LimitePeticiones(por_minuto=0))

    assert traductor.traducir(PETICION).modelo == "local"
    partes: list[str] = []
    resultado = traductor.traducir_por_partes(PETICION, partes.append, lambda: False)
    assert resultado is not None
    assert resultado.traduccion.modelo == "local"
    assert partes == ["local"]
    assert gemini.llamadas == 0
    assert "límite de peticiones" in avisos[0]


def test_si_google_agota_el_limite_se_pausa_gemini() -> None:
    gemini = Falso("gemini", CuotaAgotadaError("429"))
    traductor, _ = respaldo(gemini)

    traductor.traducir(PETICION)
    gemini.fallo = None
    assert traductor.traducir(PETICION).modelo == "local"  # sigue en pausa
    assert gemini.llamadas == 1


def test_si_falla_a_medias_se_descarta_lo_leido_y_se_lee_la_local() -> None:
    traductor, _ = respaldo(Falso("gemini", TraduccionFallidaError("corte"), partes_antes=1))
    partes: list[str] = []

    resultado = traductor.traducir_por_partes(PETICION, partes.append, lambda: False)

    assert partes == ["parte 0"]
    assert resultado == ResultadoPorPartes(Traduccion(f"local: {PETICION.texto}", "local"), por_partes=False)


def test_respaldo_sin_streaming() -> None:
    traductor, _ = respaldo(Falso("gemini", TraduccionFallidaError("x")), SinPartes())

    resultado = traductor.traducir_por_partes(PETICION, lambda _: None, lambda: False)

    assert resultado == ResultadoPorPartes(Traduccion("local", "local"), por_partes=False)


def test_avisos_de_privacidad() -> None:
    avisos = avisos_privacidad()
    assert any("Google" in aviso for aviso in avisos)
    assert any(URL_CLAVES in aviso for aviso in avisos)
