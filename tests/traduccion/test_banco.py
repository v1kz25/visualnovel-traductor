"""Tests del banco de pruebas de la traducción, sin el modelo real."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vn_audiolibro.traduccion import banco
from vn_audiolibro.traduccion.banco import (
    FRASES,
    Medida,
    Sistema,
    TiempoServidor,
    Vigia,
    medir,
    resumir,
    sistema,
    tiempos_servidor,
)
from vn_audiolibro.traduccion.modelos import Peticion, ResultadoPorPartes, Traduccion, TraduccionFallidaError

SLOT = "slot print_timing: id  0 | task 7 | "
REGISTRO = "\n".join(
    [
        "srv  log_server_r: request: POST /v1/chat/completions 127.0.0.1 200",
        SLOT + "prompt eval time =  300.56 ms /  56 tokens ( 5.37 ms per token, 186.32 tokens per second)",
        SLOT + "       eval time = 1329.87 ms /  18 tokens (78.23 ms per token,  12.78 tokens per second)",
        SLOT + "      total time = 1648.84 ms /  76 tokens",
        SLOT + "prompt eval time =  100.00 ms /  40 tokens ( 2.50 ms per token, 400.00 tokens per second)",
        SLOT + "       eval time =  500.00 ms /  10 tokens (50.00 ms per token,  20.00 tokens per second)",
    ]
)


def test_lee_los_tiempos_del_registro_de_llama_server() -> None:
    assert tiempos_servidor(REGISTRO) == [TiempoServidor(300.56, 56, 12.78), TiempoServidor(100.0, 40, 20.0)]
    assert tiempos_servidor("") == []


def test_las_frases_de_prueba_cubren_todos_los_idiomas() -> None:
    from vn_audiolibro.perfiles.modelos import IDIOMAS

    assert set(FRASES) == set(IDIOMAS)
    assert all(len(frases) >= 5 for frases in FRASES.values())


def proc_falso(raiz: Path, mhz: list[int], libre_kb: int = 2_048_000, swap_libre_kb: int = 1_024_000) -> None:
    for n, valor in enumerate(mhz):
        carpeta = raiz / f"sys/devices/system/cpu/cpu{n}/cpufreq"
        carpeta.mkdir(parents=True)
        (carpeta / "scaling_cur_freq").write_text(f"{valor * 1000}\n")
    (raiz / "proc").mkdir()
    memoria = {
        "MemTotal": 8_000_000,
        "MemAvailable": libre_kb,
        "SwapTotal": 2_048_000,
        "SwapFree": swap_libre_kb,
    }
    (raiz / "proc/meminfo").write_text("".join(f"{clave}: {kb} kB\n" for clave, kb in memoria.items()))
    (raiz / "proc/vmstat").write_text("nr_free_pages 1\npswpin 10\npswpout 5\n")


def test_sistema_lee_cpu_memoria_y_swap(tmp_path: Path) -> None:
    proc_falso(tmp_path, [800, 4200, 1200])

    assert sistema(tmp_path) == Sistema(mhz=4200, memoria_libre_mb=2000, swap_usado_mb=1000, paginas_swap=15)


def test_sistema_sin_proc_no_tiene_datos(tmp_path: Path) -> None:
    assert sistema(tmp_path) == Sistema()


def test_vigia_toma_muestras_mientras_mide() -> None:
    muestras = iter([Sistema(4000, 2000, 0, 0), Sistema(1000, 500, 300, 40), Sistema(2000, 900, 300, 60)])
    with Vigia(lambda: next(muestras), intervalo_s=60) as vigia:
        vigia.muestras.append(next(muestras))

    assert vigia.resumen() == (
        "CPU hasta 2333 MHz de media (mínimo 1000), memoria libre mínima 500 MB, "
        "swap 300 MB, 60 páginas movidas"
    )


class TraductorFalso:
    def __init__(self, fallar_en: str | None = None) -> None:
        self.peticiones: list[Peticion] = []
        self.fallar_en = fallar_en

    def traducir_por_partes(
        self, peticion: Peticion, al_parte: Callable[[str], None], cancelado: Callable[[], bool]
    ) -> ResultadoPorPartes | None:
        self.peticiones.append(peticion)
        if peticion.texto == self.fallar_en:
            return None
        al_parte("Primera.")
        return ResultadoPorPartes(Traduccion(f"T({peticion.texto})", "falso"), por_partes=True)

    def calentar(self, idioma: str, destino: str = "es") -> None:
        pass


def test_medir_traduce_en_orden_con_las_anteriores_como_contexto() -> None:
    traductor = TraductorFalso(fallar_en="b")

    medidas = list(medir(traductor, "ja", ["a", "b", "c"]))  # type: ignore[arg-type]

    assert [m.traduccion for m in medidas] == ["T(a)", "", "T(c)"]
    assert [len(p.contexto) for p in traductor.peticiones] == [0, 1, 2]
    assert all(m.primera_s <= m.total_s for m in medidas)


def test_resumir() -> None:
    medidas = [Medida("ja", "a", "A", 1.0, 2.0), Medida("ja", "b", "B", 3.0, 4.0)]

    assert resumir("ja", medidas, []) == "ja       primera frase 2.00 s (máx. 3.00), total 3.00 s (máx. 4.00)"
    con_servidor = resumir("ja", medidas, [TiempoServidor(300, 50, 12.5)])
    assert con_servidor.endswith("; prompt 300 ms, 12.5 tokens/s")


def test_carga_arranca_y_para_los_procesos() -> None:
    with banco.carga(1):
        pass
    with banco.carga(0):
        pass


class ServidorFalso:
    def __init__(self, ejecutable: Path, modelo: Path, ajustes: Any) -> None:
        self.modelo, self.ajustes = modelo, ajustes
        self.registro = Path("/no/existe.log")
        ServidorFalso.ultimo = self

    ultimo: "ServidorFalso"

    def __enter__(self) -> "ServidorFalso":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def iniciar(self) -> str:
        return "cliente"


@pytest.fixture
def falsos(monkeypatch: pytest.MonkeyPatch) -> TraductorFalso:
    traductor = TraductorFalso()
    monkeypatch.setattr(banco, "asegurar_llama_server", lambda: Path("llama-server"))
    monkeypatch.setattr(banco, "asegurar_modelo_traduccion", lambda: Path("Hy-MT2.gguf"))
    monkeypatch.setattr(banco, "ServidorLlama", ServidorFalso)
    monkeypatch.setattr(banco, "TraductorLocal", lambda cliente: traductor)
    monkeypatch.setattr(banco, "sistema", lambda: Sistema())
    return traductor


def test_main_mide_los_idiomas_pedidos(falsos: TraductorFalso, capsys: pytest.CaptureFixture[str]) -> None:
    assert banco.main(["--idioma", "ja", "--hilos", "2", "--opciones", "--poll 0", "--ver"]) == 0

    salida = capsys.readouterr().out
    assert salida.startswith("Hy-MT2.gguf en llama-server con 2 hilos --poll 0")
    assert ServidorFalso.ultimo.ajustes.opciones == ("--poll", "0")
    assert "ja       primera frase" in salida
    assert f"→ T({FRASES['ja'][0]})" in salida
    assert {p.idioma for p in falsos.peticiones} == {"ja"}


def test_main_con_otro_modelo_y_todos_los_idiomas(
    falsos: TraductorFalso, capsys: pytest.CaptureFixture[str]
) -> None:
    assert banco.main(["--modelo", "otro.gguf"]) == 0

    assert ServidorFalso.ultimo.modelo == Path("otro.gguf")
    assert {p.idioma for p in falsos.peticiones} == set(FRASES)
    assert "→" not in capsys.readouterr().out


def test_main_si_falla_el_servidor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fallar() -> Path:
        raise TraduccionFallidaError("llama-server no arrancó")

    monkeypatch.setattr(banco, "asegurar_modelo_traduccion", fallar)

    assert banco.main([]) == 1
    assert "no arrancó" in capsys.readouterr().err
