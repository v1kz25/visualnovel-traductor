"""Tests del locutor: corte, descarte y caché, con un sintetizador y un reproductor falsos."""

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from vn_audiolibro.cache.modelos import Clave
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.voz import opus
from vn_audiolibro.voz.locutor import Locutor, TextoPorPartes
from vn_audiolibro.voz.modelos import Fragmento, ModoLectura

from .falsos import ESPERA_S, FRECUENCIA, AtenuadorFalso, ReproductorFalso, SintetizadorFalso


def clave(texto: str) -> Clave:
    return Clave("juego", "ja", f"original de {texto}")


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[CacheSQLite]:
    cache = CacheSQLite(tmp_path)
    yield cache
    cache.cerrar()


def iniciar(
    sintetizador: SintetizadorFalso,
    reproductor: ReproductorFalso,
    cache: CacheSQLite | None = None,
    modo: ModoLectura = ModoLectura.COLA,
    pausa_s: float = 0,
) -> Locutor:
    return Locutor(sintetizador, reproductor, cache, modo=modo, pausa_s=pausa_s)


def test_lee_todas_las_frases_en_una_salida() -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor)

    locutor.decir(clave("a"), "hola|qué tal")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    (salida,) = reproductor.salidas
    assert salida.valores == [4, 7]
    assert salida.frecuencia == 22050
    assert salida.terminada


def test_en_modo_ultima_una_linea_nueva_corta_la_que_suena() -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso(bloquear=True)
    locutor = iniciar(sintetizador, reproductor, modo=ModoLectura.ULTIMA)

    locutor.decir(clave("a"), "primera")
    reproductor.esperar_sonando(0)
    locutor.decir(clave("b"), "segunda")
    reproductor.esperar_sonando(1).soltar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    primera, segunda = reproductor.salidas
    assert primera.detenida.is_set()
    assert not primera.terminada
    assert segunda.valores == [len("segunda")]
    assert segunda.terminada


def test_en_modo_ultima_solo_suena_la_ultima_pendiente() -> None:
    puerta = threading.Event()
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso(puerta=puerta)
    locutor = iniciar(sintetizador, reproductor, modo=ModoLectura.ULTIMA)

    locutor.decir(clave("a"), "a")
    assert reproductor.abriendo.wait(ESPERA_S)
    # El hilo está atascado abriendo la salida de «a»: llegan dos líneas más.
    locutor.decir(clave("b"), "bb")
    locutor.decir(clave("c"), "ccc")
    puerta.set()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.textos == ["a", "ccc"]
    descartada, ultima = reproductor.salidas
    assert descartada.escrito == []
    assert descartada.detenida.is_set()
    assert ultima.valores == [3]


def test_cortar_a_media_sintesis_no_sintetiza_el_resto() -> None:
    pausa = threading.Event()
    sintetizador, reproductor = SintetizadorFalso(pausa), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor)

    locutor.decir(clave("a"), "uno|dos|tres")
    assert reproductor.abriendo.wait(ESPERA_S)
    locutor.callar()
    pausa.set()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.frases == ["uno", "dos"]  # «dos» ya estaba en marcha; «tres» no se pide
    assert reproductor.salidas[0].detenida.is_set()


def test_callar_sin_nada_sonando_no_falla() -> None:
    locutor = iniciar(SintetizadorFalso(), ReproductorFalso())
    locutor.callar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()


def test_un_fallo_no_para_el_locutor(caplog: pytest.LogCaptureFixture) -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor)

    locutor.decir(clave("x"), "error")
    assert locutor.esperar(ESPERA_S)
    locutor.decir(clave("a"), "sigue")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert "No se pudo leer «error»" in caplog.text
    assert [s.valores for s in reproductor.salidas] == [[len("sigue")]]


def test_texto_sin_frases_no_abre_salida() -> None:
    reproductor = ReproductorFalso()
    locutor = Locutor(VacioFalso(), reproductor, pausa_s=0)
    locutor.decir(clave("a"), "")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()
    assert reproductor.salidas == []


class VacioFalso:
    def sintetizar(self, texto: str) -> Iterator[Fragmento]:
        return iter(())


def test_guarda_el_audio_y_la_segunda_vez_no_sintetiza(cache: CacheSQLite) -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor, cache)
    cache.guardar_traduccion(clave("a"), "hola|adiós", "hy-mt2")

    locutor.decir(clave("a"), "hola|adiós")
    assert locutor.esperar(ESPERA_S)
    entrada = cache.consultar(clave("a"))
    assert entrada is not None
    assert entrada.audio is not None

    locutor.decir(clave("a"), "hola|adiós")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.textos == ["hola|adiós"]
    desde_cache = reproductor.salidas[1]
    assert desde_cache.frecuencia == opus.FRECUENCIA_OPUS
    assert len(desde_cache.escrito) == 1


def test_se_guarda_aunque_se_corte_despues_de_sintetizar(cache: CacheSQLite) -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso(bloquear=True)
    locutor = iniciar(sintetizador, reproductor, cache)
    cache.guardar_traduccion(clave("a"), "hola", "hy-mt2")

    locutor.decir(clave("a"), "hola")
    reproductor.esperar_sonando(0)
    locutor.callar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    entrada = cache.consultar(clave("a"))
    assert entrada is not None
    assert entrada.audio is not None


def test_no_se_guarda_si_se_corta_a_media_sintesis(cache: CacheSQLite) -> None:
    pausa = threading.Event()
    sintetizador, reproductor = SintetizadorFalso(pausa), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor, cache)
    cache.guardar_traduccion(clave("a"), "uno|dos", "hy-mt2")

    locutor.decir(clave("a"), "uno|dos")
    assert reproductor.abriendo.wait(ESPERA_S)
    locutor.callar()
    pausa.set()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    entrada = cache.consultar(clave("a"))
    assert entrada is not None
    assert entrada.audio is None


def test_sin_traduccion_en_la_cache_no_guarda_ni_falla(cache: CacheSQLite) -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor, cache)

    locutor.decir(clave("a"), "hola")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert reproductor.salidas[0].valores == [4]
    assert cache.consultar(clave("a")) is None


def test_audio_ilegible_en_la_cache_se_vuelve_a_sintetizar(cache: CacheSQLite) -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor, cache)
    cache.guardar_traduccion(clave("a"), "hola", "hy-mt2")
    cache.guardar_audio(clave("a"), b"esto no es opus")

    locutor.decir(clave("a"), "hola")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.textos == ["hola"]
    entrada = cache.consultar(clave("a"))
    assert entrada is not None
    assert entrada.audio is not None
    assert opus.decodificar(entrada.audio).duracion_s == pytest.approx(0.1, abs=0.02)


def test_el_audio_de_la_cache_es_el_sintetizado(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(clave("a"), "hola", "hy-mt2")
    tono = (np.sin(2 * np.pi * 440 * np.arange(FRECUENCIA) / FRECUENCIA) * 8000).astype(np.int16)
    cache.guardar_audio(clave("a"), opus.codificar([Fragmento(tono, FRECUENCIA)]))
    reproductor = ReproductorFalso()
    locutor = iniciar(SintetizadorFalso(), reproductor, cache)

    locutor.decir(clave("a"), "hola")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    (pcm,) = reproductor.salidas[0].escrito
    assert len(pcm) == pytest.approx(opus.FRECUENCIA_OPUS, rel=0.05)
    assert float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2))) == pytest.approx(8000 / np.sqrt(2), rel=0.1)


# Volumen del juego


def test_baja_el_juego_mientras_habla_y_lo_restaura_al_acabar() -> None:
    atenuador = AtenuadorFalso()
    locutor = Locutor(SintetizadorFalso(), ReproductorFalso(), atenuador=atenuador, pausa_s=0)

    locutor.decir(clave("a"), "hola|adiós")
    assert locutor.esperar(ESPERA_S)

    assert atenuador.llamadas == ["bajar", "restaurar"]
    locutor.cerrar()


def test_no_restaura_entre_una_linea_cortada_y_la_siguiente() -> None:
    atenuador = AtenuadorFalso()
    reproductor = ReproductorFalso(bloquear=True)
    locutor = Locutor(
        SintetizadorFalso(), reproductor, atenuador=atenuador, modo=ModoLectura.ULTIMA, pausa_s=0
    )

    locutor.decir(clave("a"), "primera")
    reproductor.esperar_sonando(0)
    locutor.decir(clave("b"), "segunda")
    reproductor.esperar_sonando(1).soltar()
    assert locutor.esperar(ESPERA_S)

    assert atenuador.llamadas == ["bajar", "bajar", "restaurar"]
    locutor.cerrar()


def test_sin_audio_no_baja_el_juego() -> None:
    atenuador = AtenuadorFalso()
    locutor = Locutor(VacioFalso(), ReproductorFalso(), atenuador=atenuador, pausa_s=0)
    locutor.decir(clave("a"), "")
    assert locutor.esperar(ESPERA_S)
    assert "bajar" not in atenuador.llamadas
    locutor.cerrar()


def test_cerrar_restaura_el_volumen() -> None:
    atenuador = AtenuadorFalso()
    locutor = Locutor(SintetizadorFalso(), ReproductorFalso(), atenuador=atenuador, pausa_s=0)
    locutor.cerrar()
    assert atenuador.llamadas == ["restaurar"]


def test_si_falla_el_volumen_la_voz_suena_igual(caplog: pytest.LogCaptureFixture) -> None:
    reproductor = ReproductorFalso()
    locutor = Locutor(SintetizadorFalso(), reproductor, atenuador=AtenuadorFalso(fallar=True), pausa_s=0)

    locutor.decir(clave("a"), "hola")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert reproductor.salidas[0].valores == [4]
    assert "No se pudo cambiar el volumen" in caplog.text


# Lectura por partes (traducción en streaming)


def test_lee_cada_parte_en_cuanto_llega_y_guarda_el_audio_completo(cache: CacheSQLite) -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor, cache)
    texto = TextoPorPartes()

    locutor.decir_por_partes(clave("a"), texto)
    texto.anadir("hola")
    reproductor.abriendo.wait(ESPERA_S)  # la primera parte suena sin esperar a la segunda
    cache.guardar_traduccion(clave("a"), "hola adiós", "hy-mt2")
    texto.anadir("adiós")
    texto.terminar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.textos == ["hola", "adiós"]
    assert reproductor.salidas[0].valores == [4, 5]  # las dos partes en la misma salida
    entrada = cache.consultar(clave("a"))
    assert entrada is not None
    assert entrada.audio is not None
    assert opus.decodificar(entrada.audio).duracion_s == pytest.approx(0.2, abs=0.03)


def test_una_linea_nueva_deja_de_esperar_las_partes(cache: CacheSQLite) -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso()
    locutor = iniciar(sintetizador, reproductor, cache, ModoLectura.ULTIMA)
    texto = TextoPorPartes()
    cache.guardar_traduccion(clave("a"), "hola", "hy-mt2")

    locutor.decir_por_partes(clave("a"), texto)
    texto.anadir("hola")
    assert reproductor.abriendo.wait(ESPERA_S)
    locutor.decir(clave("b"), "otra")  # la traducción de «a» nunca termina
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.textos == ["hola", "otra"]
    entrada = cache.consultar(clave("a"))
    assert entrada is not None
    assert entrada.audio is None  # audio incompleto: no se guarda


def test_por_partes_sin_ninguna_parte() -> None:
    reproductor = ReproductorFalso()
    locutor = iniciar(SintetizadorFalso(), reproductor)
    texto = TextoPorPartes()
    locutor.decir_por_partes(clave("a"), texto)
    texto.terminar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()
    assert reproductor.salidas == []


# Modo cola


def test_en_cola_lee_todas_las_lineas_en_orden() -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso(bloquear=True)
    locutor = iniciar(sintetizador, reproductor)

    locutor.decir(clave("a"), "uno")
    reproductor.esperar_sonando(0)
    locutor.decir(clave("b"), "dos")
    locutor.decir(clave("c"), "tres")
    reproductor.salidas[0].soltar()  # «uno» termina de sonar entera
    reproductor.esperar_sonando(1).soltar()
    reproductor.esperar_sonando(2).soltar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert [s.valores for s in reproductor.salidas] == [[3], [3], [4]]
    assert all(s.terminada for s in reproductor.salidas)


def test_en_cola_como_mucho_esperan_tres_y_se_descartan_las_mas_antiguas() -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso(bloquear=True)
    locutor = iniciar(sintetizador, reproductor)

    locutor.decir(clave("a"), "a")
    reproductor.esperar_sonando(0)
    for texto in ["b", "cc", "ddd", "eeee"]:
        locutor.decir(clave(texto), texto)
    for i in range(4):
        reproductor.esperar_sonando(i).soltar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.textos == ["a", "cc", "ddd", "eeee"]  # «b» era la más antigua de la cola


def test_en_cola_saltar_pasa_a_la_siguiente() -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso(bloquear=True)
    locutor = iniciar(sintetizador, reproductor)

    locutor.decir(clave("a"), "uno")
    reproductor.esperar_sonando(0)
    locutor.decir(clave("b"), "dos")
    locutor.saltar()
    reproductor.esperar_sonando(1).soltar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    primera, segunda = reproductor.salidas
    assert primera.detenida.is_set()
    assert segunda.terminada


def test_en_cola_callar_vacia_la_cola() -> None:
    sintetizador, reproductor = SintetizadorFalso(), ReproductorFalso(bloquear=True)
    locutor = iniciar(sintetizador, reproductor)

    locutor.decir(clave("a"), "uno")
    reproductor.esperar_sonando(0)
    locutor.decir(clave("b"), "dos")
    locutor.callar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert sintetizador.textos == ["uno"]


def test_saltar_sin_nada_sonando_no_falla() -> None:
    locutor = iniciar(SintetizadorFalso(), ReproductorFalso())
    locutor.saltar()
    locutor.cerrar()


def test_en_cola_no_restaura_el_volumen_entre_lineas() -> None:
    atenuador = AtenuadorFalso()
    reproductor = ReproductorFalso(bloquear=True)
    locutor = Locutor(SintetizadorFalso(), reproductor, atenuador=atenuador, pausa_s=0)

    locutor.decir(clave("a"), "uno")
    reproductor.esperar_sonando(0)
    locutor.decir(clave("b"), "dos")
    reproductor.salidas[0].soltar()
    reproductor.esperar_sonando(1).soltar()
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert atenuador.llamadas[:3] == ["bajar", "bajar", "restaurar"]


# Pausa entre líneas (modo cola)


def test_en_cola_deja_una_pausa_entre_lineas() -> None:
    reproductor = ReproductorFalso()
    locutor = iniciar(SintetizadorFalso(), reproductor, pausa_s=0.3)

    inicio = time.monotonic()
    locutor.decir(clave("a"), "uno")
    locutor.decir(clave("b"), "dos")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()

    assert len(reproductor.salidas) == 2
    assert time.monotonic() - inicio >= 0.3


def test_sin_linea_anterior_no_hay_pausa() -> None:
    reproductor = ReproductorFalso()
    locutor = iniciar(SintetizadorFalso(), reproductor, pausa_s=ESPERA_S)
    inicio = time.monotonic()
    locutor.decir(clave("a"), "uno")
    assert locutor.esperar(ESPERA_S)
    locutor.cerrar()
    assert time.monotonic() - inicio < 1


def test_saltar_o_callar_no_esperan_la_pausa() -> None:
    reproductor = ReproductorFalso()
    locutor = iniciar(SintetizadorFalso(), reproductor, pausa_s=ESPERA_S * 10)

    locutor.decir(clave("a"), "uno")
    assert locutor.esperar(ESPERA_S)
    inicio = time.monotonic()
    locutor.decir(clave("b"), "dos")  # tendría que esperar la pausa larga…
    time.sleep(0.05)
    locutor.saltar()  # …pero saltar la cancela: la siguiente suena sin esperar
    locutor.decir(clave("c"), "tres")
    assert locutor.esperar(ESPERA_S)
    locutor.callar()
    locutor.cerrar()

    assert time.monotonic() - inicio < ESPERA_S
    assert reproductor.salidas[-1].valores == [4]


def test_en_modo_ultima_no_hay_pausa() -> None:
    reproductor = ReproductorFalso()
    locutor = iniciar(SintetizadorFalso(), reproductor, modo=ModoLectura.ULTIMA, pausa_s=ESPERA_S * 10)

    locutor.decir(clave("a"), "uno")
    assert locutor.esperar(ESPERA_S)
    locutor.decir(clave("b"), "dos")

    assert locutor.esperar(ESPERA_S)  # no espera la pausa larga
    locutor.cerrar()
    assert len(reproductor.salidas) == 2
