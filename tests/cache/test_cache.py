"""Tests de la caché con una base de datos temporal."""

import hashlib
import threading
from pathlib import Path

import pytest

from vn_audiolibro.cache.modelos import Clave, normalizar_para_clave
from vn_audiolibro.cache.sqlite import CacheSQLite, directorio_cache

LINEA = Clave("juego-chino", "zh-Hant", "「我們走吧。」")
OTRA = Clave("juego-chino", "zh-Hant", "她沒有回答。")
DE_OTRO_JUEGO = Clave("otro-juego", "ja", "先輩、帰りましょう。")


class Reloj:
    """Reloj manual para controlar el orden de uso."""

    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        self.ahora += 1
        return self.ahora


@pytest.fixture
def cache(tmp_path: Path) -> CacheSQLite:
    return CacheSQLite(tmp_path, reloj=Reloj())


def test_guarda_y_recupera_una_traduccion(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(LINEA, "«Vámonos.»", "hy-mt2")

    entrada = cache.consultar(LINEA)

    assert entrada is not None
    assert entrada.original == "「我們走吧。」"
    assert (entrada.traduccion, entrada.modelo) == ("«Vámonos.»", "hy-mt2")
    assert entrada.audio is None
    assert cache.consultar(OTRA) is None


def test_persiste_al_reabrir(tmp_path: Path) -> None:
    CacheSQLite(tmp_path).guardar_traduccion(LINEA, "«Vámonos.»", "hy-mt2")

    entrada = CacheSQLite(tmp_path).consultar(LINEA)

    assert entrada is not None
    assert entrada.traduccion == "«Vámonos.»"


@pytest.mark.parametrize("variante", ["「我們 走吧。」", " 「我們走吧。」\n", "「我們走吧｡」"])
def test_espacios_y_anchos_distintos_dan_la_misma_clave(variante: str) -> None:
    assert Clave("juego-chino", "zh-Hant", variante).id == LINEA.id


def test_el_perfil_y_el_idioma_forman_parte_de_la_clave() -> None:
    assert Clave("otro", "zh-Hant", LINEA.texto).id != LINEA.id
    assert Clave("juego-chino", "ja", LINEA.texto).id != LINEA.id


def test_el_destino_ingles_forma_parte_de_la_clave() -> None:
    assert Clave(LINEA.perfil, LINEA.idioma, LINEA.texto, "en").id != LINEA.id


def test_el_destino_espanol_no_cambia_las_claves_de_antes() -> None:
    # Hash de antes de poder elegir el destino: las líneas ya guardadas siguen valiendo.
    antes = hashlib.sha256("\0".join(("juego-chino", "zh-Hant", "「我們走吧。」")).encode()).hexdigest()
    assert Clave("juego-chino", "zh-Hant", "「我們走吧。」", "es").id == LINEA.id == antes


def test_normalizar_para_clave() -> None:
    assert normalizar_para_clave("ｱ！ 1") == "ア!1"


def test_guarda_el_audio_en_un_fichero(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(LINEA, "«Vámonos.»", "hy-mt2")

    ruta = cache.guardar_audio(LINEA, b"opus")

    entrada = cache.consultar(LINEA)
    assert entrada is not None
    assert entrada.audio == ruta
    assert ruta.read_bytes() == b"opus"
    assert ruta.parent == cache.directorio_audio


def test_no_guarda_audio_sin_traduccion(cache: CacheSQLite) -> None:
    with pytest.raises(KeyError):
        cache.guardar_audio(LINEA, b"opus")


def test_si_falta_el_fichero_de_audio_la_entrada_queda_sin_audio(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(LINEA, "«Vámonos.»", "hy-mt2")
    cache.guardar_audio(LINEA, b"opus").unlink()

    entrada = cache.consultar(LINEA)

    assert entrada is not None
    assert entrada.audio is None
    assert cache.tamano() == len("「我們走吧。」«Vámonos.»".encode())


def test_una_traduccion_nueva_borra_el_audio_anterior(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(LINEA, "«Vámonos.»", "hy-mt2")
    ruta = cache.guardar_audio(LINEA, b"opus")

    cache.guardar_traduccion(LINEA, "«Nos vamos.»", "groq")

    entrada = cache.consultar(LINEA)
    assert entrada is not None
    assert (entrada.traduccion, entrada.modelo, entrada.audio) == ("«Nos vamos.»", "groq", None)
    assert not ruta.exists()


def test_la_misma_traduccion_conserva_el_audio(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(LINEA, "«Vámonos.»", "hy-mt2")
    ruta = cache.guardar_audio(LINEA, b"opus")

    cache.guardar_traduccion(LINEA, "«Vámonos.»", "hy-mt2")

    entrada = cache.consultar(LINEA)
    assert entrada is not None
    assert entrada.audio == ruta
    assert ruta.exists()


def test_invalidar_un_perfil_solo_borra_ese_juego(cache: CacheSQLite) -> None:
    for clave in (LINEA, OTRA, DE_OTRO_JUEGO):
        cache.guardar_traduccion(clave, "traducción", "hy-mt2")
    ruta = cache.guardar_audio(LINEA, b"opus")
    otro = cache.guardar_audio(DE_OTRO_JUEGO, b"opus")

    assert cache.invalidar("juego-chino") == 2

    assert cache.consultar(LINEA) is None
    assert cache.consultar(OTRA) is None
    assert cache.consultar(DE_OTRO_JUEGO) is not None
    assert not ruta.exists()
    assert otro.exists()


def test_vaciar_borra_todo(cache: CacheSQLite) -> None:
    for clave in (LINEA, DE_OTRO_JUEGO):
        cache.guardar_traduccion(clave, "traducción", "hy-mt2")
        cache.guardar_audio(clave, b"opus")

    assert cache.vaciar() == 2

    assert cache.tamano() == 0
    assert list(cache.directorio_audio.iterdir()) == []


def test_resumen_por_juego(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(LINEA, "a", "hy-mt2")
    cache.guardar_traduccion(OTRA, "b", "hy-mt2")
    cache.guardar_audio(OTRA, b"x" * 100)
    cache.guardar_traduccion(DE_OTRO_JUEGO, "c", "hy-mt2")

    juego_chino, otro = cache.resumen()

    texto = len(LINEA.texto.encode()) + len(OTRA.texto.encode()) + 2
    assert (juego_chino.perfil, juego_chino.entradas, juego_chino.bytes) == ("juego-chino", 2, texto + 100)
    assert (otro.perfil, otro.entradas) == ("otro-juego", 1)
    assert cache.tamano() == juego_chino.bytes + otro.bytes


def test_el_limite_borra_primero_lo_usado_hace_mas_tiempo(tmp_path: Path) -> None:
    cache = CacheSQLite(tmp_path, limite_bytes=300, reloj=Reloj())  # caben dos entradas, no tres
    for clave in (LINEA, OTRA):
        cache.guardar_traduccion(clave, "traducción", "hy-mt2")
        cache.guardar_audio(clave, b"x" * 100)
    cache.consultar(LINEA)  # ahora OTRA es la usada hace más tiempo

    cache.guardar_traduccion(DE_OTRO_JUEGO, "traducción", "hy-mt2")
    cache.guardar_audio(DE_OTRO_JUEGO, b"x" * 100)

    assert cache.consultar(OTRA) is None
    assert cache.consultar(LINEA) is not None
    assert cache.consultar(DE_OTRO_JUEGO) is not None
    assert cache.tamano() <= 300
    assert len(list(cache.directorio_audio.iterdir())) == 2


def test_el_limite_no_borra_la_entrada_recien_guardada(tmp_path: Path) -> None:
    cache = CacheSQLite(tmp_path, limite_bytes=10)
    cache.guardar_traduccion(LINEA, "traducción", "hy-mt2")

    ruta = cache.guardar_audio(LINEA, b"x" * 100)

    assert ruta.exists()
    assert cache.consultar(LINEA) is not None


def test_se_puede_usar_desde_varios_hilos(cache: CacheSQLite) -> None:
    def trabajar(n: int) -> None:
        for i in range(20):
            clave = Clave("juego-chino", "zh-Hant", f"línea {n}-{i}")
            cache.guardar_traduccion(clave, "traducción", "hy-mt2")
            cache.guardar_audio(clave, b"opus")
            assert cache.consultar(clave) is not None

    hilos = [threading.Thread(target=trabajar, args=(n,)) for n in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert cache.resumen()[0].entradas == 80


def test_directorio_por_defecto_en_los_datos_del_usuario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert directorio_cache() == tmp_path / "vn-audiolibro" / "cache"
    cache = CacheSQLite()
    assert (tmp_path / "vn-audiolibro" / "cache" / "cache.sqlite3").is_file()
    cache.cerrar()


def test_borrar_audio_conserva_las_traducciones(cache: CacheSQLite) -> None:
    cache.guardar_traduccion(LINEA, "a", "hy-mt2")
    cache.guardar_traduccion(OTRA, "b", "hy-mt2")
    ruta = cache.guardar_audio(LINEA, b"x" * 100)
    cache.guardar_traduccion(DE_OTRO_JUEGO, "c", "hy-mt2")
    audio_otro = cache.guardar_audio(DE_OTRO_JUEGO, b"y" * 50)

    assert cache.borrar_audio(LINEA.perfil) == 1

    entrada = cache.consultar(LINEA)
    assert entrada is not None
    assert (entrada.traduccion, entrada.audio) == ("a", None)
    assert not ruta.exists()
    assert audio_otro.exists()  # el de otro juego no se toca
    juego_chino = next(r for r in cache.resumen() if r.perfil == LINEA.perfil)
    assert juego_chino.bytes == len(LINEA.texto.encode()) + len(OTRA.texto.encode()) + 2


def test_recortar_aplica_un_limite_nuevo(tmp_path: Path) -> None:
    cache = CacheSQLite(tmp_path, reloj=Reloj())
    for texto in ["uno", "dos", "tres"]:
        clave = Clave("juego", "ja", texto)
        cache.guardar_traduccion(clave, texto, "hy-mt2")
        cache.guardar_audio(clave, b"x" * 100)
    cache.recortar()  # sin límite: no hace nada
    assert len(cache.resumen()) == 1

    cache.limite_bytes = 250
    cache.recortar()

    assert cache.tamano() <= 250
    assert cache.consultar(Clave("juego", "ja", "uno")) is None  # la usada hace más tiempo
    assert cache.consultar(Clave("juego", "ja", "tres")) is not None
    cache.cerrar()
