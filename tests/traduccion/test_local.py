"""Tests del traductor local con un servidor falso que devuelve respuestas fijas."""

from collections.abc import Generator

from vn_audiolibro.traduccion.local import MODELO_LOCAL, TraductorLocal
from vn_audiolibro.traduccion.modelos import Glosario, LineaPrevia, Peticion, ResultadoPorPartes, Traduccion


class ServidorFalso:
    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.prompts: list[str] = []

    def completar(self, prompt: str, max_tokens: int = 512) -> str:
        self.prompts.append(prompt)
        return self.respuestas.pop(0)


def test_traduce_y_limpia_la_salida() -> None:
    servidor = ServidorFalso("“Sí”")

    traduccion = TraductorLocal(servidor).traducir(Peticion("「うん」", "ja"))

    assert (traduccion.texto, traduccion.modelo) == ("«Sí»", MODELO_LOCAL)
    assert "[Background Information]" not in servidor.prompts[0]


def test_traduce_al_ingles() -> None:
    servidor = ServidorFalso("«Yeah»")

    traduccion = TraductorLocal(servidor).traducir(Peticion("「うん」", "ja", destino="en"))

    assert traduccion.texto == "\u201cYeah\u201d"
    assert "into English" in servidor.prompts[0]


def test_usa_las_tres_ultimas_lineas_como_contexto() -> None:
    servidor = ServidorFalso("Exacto: ella murió.")
    contexto = [LineaPrevia(f"第{i}行。", f"Línea {i}.") for i in range(5)]

    TraductorLocal(servidor).traducir(Peticion("沒錯——她，死了。", "zh-Hant", contexto))

    assert "[Background Information]\n第2行。\n第3行。\n第4行。\n\n" in servidor.prompts[0]


def test_une_el_glosario_del_idioma_y_el_del_juego() -> None:
    servidor = ServidorFalso("«Senpai, Kaito-san te espera.»")
    glosario = Glosario.desde_dict({"海斗": "Kaito"})

    TraductorLocal(servidor).traducir(Peticion("「先輩、海斗さんが待ってるよ」", "ja", (), glosario))

    prompt = servidor.prompts[0]
    assert "先輩 translates to senpai" in prompt
    assert "さん translates to -san" in prompt
    assert "海斗 translates to Kaito" in prompt
    assert "ちゃん" not in prompt  # solo los términos presentes


def test_si_repite_el_contexto_vuelve_a_pedirlo_sin_contexto() -> None:
    repetida = "«…Oye, ¿sigues despierto?»\nFuera llovía en silencio.\n«Sí»"
    servidor = ServidorFalso(repetida, "«Sí»")
    contexto = [LineaPrevia("「……ねえ、まだ起きてる？」", "«…Oye, ¿sigues despierto?»")]

    traduccion = TraductorLocal(servidor).traducir(Peticion("「うん」", "ja", contexto))

    assert traduccion.texto == "«Sí»"
    assert len(servidor.prompts) == 2
    assert "[Background Information]" not in servidor.prompts[1]


def test_sin_contexto_no_reintenta() -> None:
    servidor = ServidorFalso("")

    traduccion = TraductorLocal(servidor).traducir(Peticion("無邊無垠的永劫之火。", "zh-Hant"))

    assert traduccion.texto == ""
    assert len(servidor.prompts) == 1


# Traducción por partes (streaming)


class ServidorPorPartes:
    """Devuelve cada respuesta palabra a palabra; apunta si se cortó la generación."""

    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.prompts: list[str] = []
        self.topes: list[int] = []
        self.cortadas = 0

    def completar(self, prompt: str, max_tokens: int = 512) -> str:
        self.prompts.append(prompt)
        self.topes.append(max_tokens)
        return self.respuestas.pop(0)

    def completar_por_partes(self, prompt: str, max_tokens: int = 512) -> Generator[str]:
        self.prompts.append(prompt)
        self.topes.append(max_tokens)
        palabras = self.respuestas.pop(0).split(" ")
        try:
            yield palabras[0]
            for palabra in palabras[1:]:
                yield f" {palabra}"
        except GeneratorExit:
            self.cortadas += 1
            raise


def test_por_partes_entrega_cada_frase_y_la_traduccion_limpia() -> None:
    servidor = ServidorPorPartes("“Hoy hace mucho frío. ¿Volvemos a casa?”")
    partes: list[str] = []

    resultado = TraductorLocal(servidor).traducir_por_partes(
        Peticion("「今日は寒いね。帰ろうか？」", "ja"), partes.append, lambda: False
    )

    assert partes == ["“Hoy hace mucho frío.", "¿Volvemos a casa?”"]
    traduccion = Traduccion("«Hoy hace mucho frío. ¿Volvemos a casa?»", MODELO_LOCAL)
    assert resultado == ResultadoPorPartes(traduccion, por_partes=True)
    assert servidor.topes == [64 + 3 * len("「今日は寒いね。帰ろうか？」")]


def test_por_partes_cancelada_corta_la_generacion() -> None:
    servidor = ServidorPorPartes("Una frase larga. Otra frase más. Y otra.")
    partes: list[str] = []

    resultado = TraductorLocal(servidor).traducir_por_partes(
        Peticion("長い文。", "ja"), partes.append, lambda: len(partes) > 0
    )

    assert resultado is None
    assert partes == ["Una frase larga."]
    assert servidor.cortadas == 1


def test_por_partes_si_repite_el_contexto_corta_y_repite_sin_contexto() -> None:
    contexto = [LineaPrevia("雨が降っていた。", "Fuera llovía en silencio.")]
    servidor = ServidorPorPartes("Sí. Fuera llovía en silencio. Sí.", "«Sí»")
    partes: list[str] = []

    resultado = TraductorLocal(servidor).traducir_por_partes(
        Peticion("「うん」", "ja", contexto), partes.append, lambda: False
    )

    assert resultado == ResultadoPorPartes(Traduccion("«Sí»", MODELO_LOCAL), False)
    assert servidor.cortadas == 1
    assert "[Background Information]" not in servidor.prompts[1]


def test_por_partes_valida_al_final_lo_que_no_se_ve_hasta_el_final() -> None:
    # Salida vacía: parcialmente válida, pero no como traducción final.
    contexto = [LineaPrevia("一", "Uno.")]
    servidor = ServidorPorPartes("", "Dos.")
    resultado = TraductorLocal(servidor).traducir_por_partes(
        Peticion("二", "zh-Hant", contexto), lambda _: None, lambda: False
    )
    assert resultado == ResultadoPorPartes(Traduccion("Dos.", MODELO_LOCAL), False)


def test_por_partes_sin_contexto_no_valida() -> None:
    servidor = ServidorPorPartes("x " * 200)
    traductor = TraductorLocal(servidor)
    resultado = traductor.traducir_por_partes(Peticion("一", "zh-Hant"), lambda _: None, lambda: False)
    assert resultado is not None
    assert resultado.por_partes


def test_traducir_usa_el_tope_de_tokens() -> None:
    servidor = ServidorPorPartes("Uno.")
    TraductorLocal(servidor).traducir(Peticion("一二三", "zh-Hant"))
    assert servidor.topes == [64 + 9]


def test_calentar_hace_una_traduccion_en_el_idioma_del_juego() -> None:
    servidor = ServidorPorPartes("Hola.", "Hola.")
    TraductorLocal(servidor).calentar("ja")
    TraductorLocal(servidor).calentar("ko")  # idioma sin frase propia: usa la china
    assert "こんにちは。" in servidor.prompts[0]
    assert "你好。" in servidor.prompts[1]


def test_calentar_en_el_idioma_de_destino() -> None:
    servidor = ServidorPorPartes("Hello.")
    TraductorLocal(servidor).calentar("ja", "en")
    assert "into English" in servidor.prompts[0]


def test_repetir_una_linea_anterior_contenida_en_el_original_es_valido() -> None:
    # El juego amplió la línea: el original contiene la anterior y la salida su traducción.
    contexto = [LineaPrevia("那份絕望，", "Esa desesperación,")]
    servidor = ServidorPorPartes("Esa desesperación, se llama fuego.")
    traduccion = TraductorLocal(servidor).traducir(Peticion("那份絕望，名為火焰。", "zh-Hant", contexto))
    assert traduccion.texto == "Esa desesperación, se llama fuego."
    assert len(servidor.prompts) == 1  # sin reintento


def test_aunque_la_anterior_este_en_el_original_se_valida_el_resto() -> None:
    contexto = [LineaPrevia("一", "Uno.")]
    servidor = ServidorPorPartes("Uno.\nDos.\nTres.", "Uno, dos.")
    traduccion = TraductorLocal(servidor).traducir(Peticion("一二", "zh-Hant", contexto))
    assert traduccion.texto == "Uno, dos."  # varias líneas: se repite sin contexto
