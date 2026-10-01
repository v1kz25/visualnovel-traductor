"""Tests de la búsqueda en el guion de lo que se ve en pantalla."""

from vn_audiolibro.guion.buscador import BuscadorGuion, SeguidorGuion, clave_busqueda
from vn_audiolibro.guion.modelos import Guion

from .sinteticos import guion, pantalla


def _buscador(g: Guion | None = None) -> BuscadorGuion:
    return BuscadorGuion(g or guion(), "ja")


def _con_errores(texto: str, cada: int = 5) -> str:
    """Cambia uno de cada `cada` caracteres por otro, como un OCR que falla un 20 %."""
    return "".join("口" if i % cada == cada - 1 else c for i, c in enumerate(texto))


def test_clave_de_busqueda_solo_letras() -> None:
    assert clave_busqueda("「おはよう、 今日は！」", "ja") == "おはよう今日は"
    assert clave_busqueda("Hello, World!", "ja") == "helloworld"


def test_encuentra_el_ultimo_fragmento_de_la_pagina() -> None:
    g = guion()
    buscador = _buscador(g)

    for i in range(len(g.fragmentos)):
        assert buscador.buscar(pantalla(g, i)) == i


def test_aguanta_los_errores_del_ocr_y_lo_que_hay_alrededor() -> None:
    g = guion()
    texto = "セーブ　ロード" + _con_errores(pantalla(g, 2)) + "オート"

    assert _buscador(g).buscar(texto, cerca=1) == 2


def test_sin_coincidencias() -> None:
    assert _buscador().buscar("まったく関係のない文字列がここに並んでいます") is None
    assert _buscador().buscar("") is None


def test_no_toma_un_fragmento_posterior_que_repite_palabras_del_visible() -> None:
    g = guion(
        [
            [
                [("命令を下したのは誰なのか。", "")],
                [("実行したのは誰なのか。", "")],
            ]
        ]
    )

    assert _buscador(g).buscar(pantalla(g, 0)) == 0


def test_prefiere_la_pagina_cercana_si_el_texto_se_repite() -> None:
    repetido = [[("同じ言葉が何度も繰り返される場面です。", "")]]
    g = guion([repetido, [[("間にある別の場面の文章です。", "")]], repetido])

    assert _buscador(g).buscar(pantalla(g, 2), cerca=1) == 2
    assert _buscador(g).buscar(pantalla(g, 0), cerca=0) == 0


def test_para_saltar_lejos_hace_falta_mas_texto() -> None:
    g = guion(
        [
            [[("ごめんなさい、ごめんなさい、ごめんなさい。", "")]],
            *[[[(f"第{n}の場面", "")]] for n in range(9)],
        ]
    )
    buscador = _buscador(g)

    assert buscador.buscar("ごめんなさいと謝った", cerca=len(g.fragmentos) - 1) is None
    assert buscador.buscar("ごめんなさいと謝った", cerca=0) == 0


def test_los_fragmentos_muy_cortos_no_se_identifican_solos() -> None:
    g = guion([[[("あ。", "")]]])

    assert _buscador(g).buscar("あ。") is None


def test_seguidor_lee_cada_parrafo_una_vez() -> None:
    g = guion()
    seguidor = SeguidorGuion(g, _buscador(g))

    nuevos = [seguidor.nuevos(pantalla(g, i)) for i in range(len(g.fragmentos))]

    leidos = [[p.indice for p in lista or []] for lista in nuevos]
    assert leidos == [[0], [1], [], [2], [3], [4], [5], [6]]  # el diálogo 1 tiene dos fragmentos
    assert seguidor.parrafo_actual == 6


def test_seguidor_lee_los_parrafos_que_se_ha_saltado_en_la_misma_pagina() -> None:
    g = guion()
    seguidor = SeguidorGuion(g, _buscador(g))
    seguidor.nuevos(pantalla(g, 0))

    nuevos = seguidor.nuevos(pantalla(g, 3)) or []

    assert [p.indice for p in nuevos] == [1, 2]


def test_seguidor_no_vuelve_atras_en_la_misma_pagina() -> None:
    g = guion()
    seguidor = SeguidorGuion(g, _buscador(g))
    seguidor.nuevos(pantalla(g, 3))

    # El OCR de la última línea falla y solo encaja la primera.
    assert seguidor.nuevos(pantalla(g, 0)) == []
    assert seguidor.parrafo_actual == 2


def test_seguidor_al_cargar_partida_salta_al_parrafo() -> None:
    g = guion()
    seguidor = SeguidorGuion(g, _buscador(g))
    seguidor.nuevos(pantalla(g, 7))

    nuevos = seguidor.nuevos(pantalla(g, 0)) or []

    assert [p.indice for p in nuevos] == [0]


def test_seguidor_texto_que_no_esta_en_el_guion() -> None:
    seguidor = SeguidorGuion(guion(), _buscador())

    assert seguidor.nuevos("メニューを開きます、設定画面") is None
    assert seguidor.siguientes(3) == ()


def test_siguientes_y_anteriores() -> None:
    g = guion()
    seguidor = SeguidorGuion(g, _buscador(g))
    seguidor.nuevos(pantalla(g, 3))

    assert [p.indice for p in seguidor.siguientes(2)] == [3, 4]
    assert [p.indice for p in seguidor.anteriores(g.parrafos[2], 5)] == [0, 1]
