"""Tests del traductor de Gemini con un servidor falso de su API (sin clave ni conexión)."""

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
    cuerpo_lote,
    cuerpo_peticion,
    leer_lote,
)
from vn_audiolibro.traduccion.modelos import (
    Glosario,
    LimiteAgotadoError,
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


# Lotes (el guion por adelantado)

LOTE = [
    PETICION,
    Peticion("雨が降っていた。", "ja"),
    Peticion("「うん」", "ja"),
]


def json_lote(*elementos: tuple[object, object]) -> str:
    return json.dumps([{"n": n, "t": t} for n, t in elementos])


def test_el_lote_lleva_las_lineas_numeradas_y_pide_json() -> None:
    cuerpo = cuerpo_lote(LOTE)

    texto = cuerpo["contents"][0]["parts"][0]["text"]
    assert texto.split("\n\n") == [
        "[Background]\n雨だ。",
        "[Glossary]\n先輩 = senpai\n待って = espera",
        "[Lines]\n1. 「先輩、待って！」\n2. 雨が降っていた。\n3. 「うん」",
    ]
    configuracion = cuerpo["generationConfig"]
    assert configuracion["responseMimeType"] == "application/json"
    assert configuracion["responseSchema"]["items"]["required"] == ["n", "t"]
    assert configuracion["maxOutputTokens"] > 3 * 32
    assert "Spanish" in cuerpo["systemInstruction"]["parts"][0]["text"]


def test_cada_linea_del_lote_va_en_una_sola_linea() -> None:
    cuerpo = cuerpo_lote([Peticion("雨が\n降っていた。", "ja", destino="fr")])
    assert cuerpo["contents"][0]["parts"][0]["text"] == "[Lines]\n1. 雨が 降っていた。"
    assert "French" in cuerpo["systemInstruction"]["parts"][0]["text"]


def test_leer_un_lote_completo_y_desordenado() -> None:
    salida = json_lote((3, "«Sí»"), (1, "「Senpai, ¡espera!」"), (2, "Llovía."))
    assert leer_lote(salida, LOTE) == ["«Senpai, ¡espera!»", "Llovía.", "«Sí»"]


@pytest.mark.parametrize(
    "salida",
    [
        json_lote((1, "«Senpai, ¡espera!»"), (3, "«Sí»")),  # falta la 2
        json_lote((1, "«Senpai, ¡espera!»"), (2, ""), (3, "«Sí»")),  # vacía
        json_lote((1, "«Senpai, ¡espera!»"), (2, "Llovía.\nY hacía frío."), (3, "«Sí»")),  # varias líneas
        json_lote((1, "«Senpai, ¡espera!»"), (2, "palabra " * 40), (3, "«Sí»")),  # desproporcionada
        json_lote((1, "«Senpai, ¡espera!»"), ("2", "Llovía."), (3, "«Sí»")),  # número como texto
        json_lote((1, "«Senpai, ¡espera!»"), (True, "Llovía."), (3, "«Sí»")),
        json_lote((1, "«Senpai, ¡espera!»"), (2, None), (3, "«Sí»"), (4, "Sobra.")),
    ],
)
def test_las_lineas_que_faltan_o_no_valen_son_none(salida: str) -> None:
    assert leer_lote(salida, LOTE) == ["«Senpai, ¡espera!»", None, "«Sí»"]


def test_una_linea_repetida_vale_la_primera_vez() -> None:
    salida = json_lote((1, "«Uno»"), (1, "«Otro»"), (2, "Llovía."), (3, "«Sí»"))
    assert leer_lote(salida, LOTE) == ["«Uno»", "Llovía.", "«Sí»"]


@pytest.mark.parametrize("salida", ["no es json", '{"n": 1, "t": "x"}', "[1, 2, 3]", '[{"n": 1}]'])
def test_respuesta_de_lote_rota(salida: str) -> None:
    assert leer_lote(salida, LOTE) == [None, None, None]


def test_traducir_un_lote_con_la_api(servidor: type[Manejador]) -> None:
    servidor.cuerpo = respuesta(json_lote((1, "«Senpai, ¡espera!»"), (3, "«Sí»")))
    traducciones = TraductorGemini(cliente(servidor)).traducir_lote(LOTE)

    modelo = "gemini-flash-lite-latest"
    assert traducciones == [Traduccion("«Senpai, ¡espera!»", modelo), None, Traduccion("«Sí»", modelo)]
    ((ruta, _, cuerpo),) = servidor.peticiones
    assert ruta.endswith(":generateContent")
    assert cuerpo["generationConfig"]["responseMimeType"] == "application/json"


# Límite diario guardado entre ejecuciones


def test_el_limite_diario_se_guarda_entre_ejecuciones(tmp_path: Path) -> None:
    ruta = tmp_path / "estado" / "gemini.json"
    ahora = [1_800_000_000.0]
    limite = LimitePeticiones(por_minuto=10, por_dia=3, reloj=lambda: ahora[0], ruta=ruta)
    assert limite.reservar()
    assert limite.reservar()

    otra = LimitePeticiones(por_minuto=10, por_dia=3, reloj=lambda: ahora[0], ruta=ruta)
    assert not otra.lleno_hoy()
    assert otra.reservar()
    assert otra.lleno_hoy()
    assert not otra.reservar()

    ahora[0] += 24 * 3600  # al día siguiente ya no cuentan
    assert not LimitePeticiones(por_dia=3, reloj=lambda: ahora[0], ruta=ruta).lleno_hoy()


def test_el_limite_ignora_horas_del_futuro_y_ficheros_rotos(tmp_path: Path) -> None:
    ruta = tmp_path / "gemini.json"
    ruta.write_text(json.dumps({"peticiones": [2_000_000_000.0, "x", 1_800_000_000.0]}), encoding="utf-8")
    limite = LimitePeticiones(por_dia=1, reloj=lambda: 1_800_000_100.0, ruta=ruta)
    assert limite.lleno_hoy()  # solo cuenta la de hace 100 s

    ruta.write_text("roto", encoding="utf-8")
    assert not LimitePeticiones(por_dia=1, ruta=ruta).lleno_hoy()


def test_el_limite_compartido_va_en_el_estado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    limite = LimitePeticiones.compartido()
    assert limite.reservar()
    assert (tmp_path / "vn-audiolibro" / "gemini-peticiones.json").is_file()


# Lotes con respaldo local


class FalsoLote(Falso):
    """Gemini de pega para lotes: devuelve `respuestas` en orden (una lista o un error)."""

    def __init__(self, *respuestas: list[Traduccion | None] | Exception) -> None:
        super().__init__("gemini")
        self.respuestas = list(respuestas)
        self.lotes: list[list[str]] = []

    def traducir_lote(self, peticiones: list[Peticion]) -> list[Traduccion | None]:
        self.lotes.append([peticion.texto for peticion in peticiones])
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def gemini_(texto: str) -> Traduccion:
    return Traduccion(texto, "gemini")


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1_800_000_000.0
        self.dormido = 0.0

    def __call__(self) -> float:
        return self.ahora

    def dormir(self, segundos: float) -> None:
        self.ahora += segundos
        self.dormido += segundos


def respaldo_lotes(
    gemini: FalsoLote, limite: LimitePeticiones | None = None, reloj: Reloj | None = None
) -> tuple[TraductorConRespaldo, list[str], Falso]:
    reloj = reloj or Reloj()
    avisos: list[str] = []
    local = Falso("local")
    limite = limite or LimitePeticiones(reloj=reloj)
    traductor = TraductorConRespaldo(gemini, local, avisos.append, limite, reloj.dormir)  # type: ignore[arg-type]
    return traductor, avisos, local


def test_lote_completo_con_gemini() -> None:
    gemini = FalsoLote([gemini_("uno"), gemini_("dos"), gemini_("tres")])
    traductor, avisos, local = respaldo_lotes(gemini)

    assert traductor.traducir_lote(LOTE, lambda: False) == [gemini_("uno"), gemini_("dos"), gemini_("tres")]
    assert len(gemini.lotes) == 1
    assert local.llamadas == 0
    assert avisos == []


def test_lo_que_falta_del_lote_va_en_local() -> None:
    traductor, avisos, local = respaldo_lotes(FalsoLote([gemini_("uno"), None, gemini_("tres")]))

    traducciones = traductor.traducir_lote(LOTE, lambda: False)
    assert traducciones is not None
    assert [t.modelo for t in traducciones] == ["gemini", "local", "gemini"]
    assert local.llamadas == 1
    assert avisos == []


def test_si_gemini_falla_el_lote_entero_va_en_local_y_avisa() -> None:
    traductor, avisos, local = respaldo_lotes(FalsoLote(TraduccionFallidaError("sin conexión")))

    traducciones = traductor.traducir_lote(LOTE, lambda: False)
    assert traducciones is not None
    assert {t.modelo for t in traducciones} == {"local"}
    assert local.llamadas == 3
    assert avisos == ["Se traduce en local mientras Gemini no esté disponible: sin conexión"]


def test_con_el_limite_por_minuto_espera_su_turno() -> None:
    reloj = Reloj()
    gemini = FalsoLote([gemini_("a"), gemini_("b"), gemini_("c")], [gemini_("d"), gemini_("e"), gemini_("f")])
    traductor, _, _ = respaldo_lotes(gemini, LimitePeticiones(por_minuto=1, reloj=reloj), reloj)

    traductor.traducir_lote(LOTE, lambda: False)
    traductor.traducir_lote(LOTE, lambda: False)
    assert len(gemini.lotes) == 2
    assert 59 <= reloj.dormido <= 61


def test_si_google_agota_el_limite_espera_y_lo_vuelve_a_intentar() -> None:
    reloj = Reloj()
    gemini = FalsoLote(CuotaAgotadaError("429"), [gemini_("a"), gemini_("b"), gemini_("c")])
    traductor, avisos, local = respaldo_lotes(gemini, reloj=reloj)

    traducciones = traductor.traducir_lote(LOTE, lambda: False)
    assert traducciones is not None
    assert {t.modelo for t in traducciones} == {"gemini"}
    assert local.llamadas == 0
    assert reloj.dormido >= 60  # la pausa tras el «límite agotado»
    assert avisos[-1] == "Gemini vuelve a traducir"


def test_si_google_sigue_sin_dejar_se_para_hasta_otro_dia() -> None:
    gemini = FalsoLote(*[CuotaAgotadaError("429")] * 3)
    traductor, _, local = respaldo_lotes(gemini)

    with pytest.raises(LimiteAgotadoError, match="sigue mañana"):
        traductor.traducir_lote(LOTE, lambda: False)
    assert local.llamadas == 0


def test_con_el_limite_diario_agotado_no_llama_a_gemini() -> None:
    reloj = Reloj()
    limite = LimitePeticiones(por_dia=1, reloj=reloj)
    assert limite.reservar()
    gemini = FalsoLote()
    traductor, _, local = respaldo_lotes(gemini, limite, reloj)

    with pytest.raises(LimiteAgotadoError, match=r"límite diario de Gemini \(1 peticiones\)"):
        traductor.traducir_lote(LOTE, lambda: False)
    assert gemini.lotes == []
    assert local.llamadas == 0


def test_lote_cancelado() -> None:
    gemini = FalsoLote()
    traductor, _, _ = respaldo_lotes(gemini)
    assert traductor.traducir_lote(LOTE, lambda: True) is None
    assert gemini.lotes == []

    # También mientras espera su turno.
    reloj = Reloj()
    limite = LimitePeticiones(por_minuto=0, reloj=reloj)
    traductor, _, _ = respaldo_lotes(gemini, limite, reloj)
    esperas = iter([False, False, True])
    assert traductor.traducir_lote(LOTE, lambda: next(esperas)) is None
    assert gemini.lotes == []
