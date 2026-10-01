"""Banco de pruebas de la traducción local: velocidad y calidad, por idioma de origen.

Uso:
    uv run python -m vn_audiolibro.traduccion
    uv run python -m vn_audiolibro.traduccion --idioma ja --ver
    uv run python -m vn_audiolibro.traduccion --hilos 2 --opciones "--poll 0"
    uv run python -m vn_audiolibro.traduccion --carga 4
    uv run python -m vn_audiolibro.traduccion --modelo otro-modelo.gguf

Traduce frases de VN escritas a mano (no son de ningún juego), cada una con las anteriores como
contexto, igual que al jugar. De cada idioma da la mediana y el máximo del tiempo hasta la
primera frase (cuando empezaría a sonar la voz) y del total, y lo que dice `llama-server` de cada
petición: tiempo de leer el prompt y tokens por segundo al generar. Con `--ver` muestra las
traducciones, para valorar la calidad.

Mientras mide, apunta la frecuencia de la CPU, la memoria libre y el swap (solo en Linux): con
el juego abierto, sirven para saber si la traducción va lenta por falta de memoria o porque la
CPU baja de frecuencia. Para medir con el juego, ábrelo antes de lanzar el banco. `--carga N`
simula N procesos que ocupan la CPU.
"""

import argparse
import multiprocessing
import re
import shlex
import statistics
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.traduccion.llama import (
    AjustesServidor,
    ServidorLlama,
    asegurar_llama_server,
    asegurar_modelo_traduccion,
)
from vn_audiolibro.traduccion.local import TraductorLocal
from vn_audiolibro.traduccion.modelos import LineaPrevia, Peticion, TraduccionFallidaError

FRASES = {
    "zh-Hant": [
        "「你到底想怎樣？」",
        "她低下頭，沉默了很久，才終於開口。",
        "「……我只是不想再一個人了。」",
        "窗外的雨一直下個不停，彷彿永遠不會停止。",
        "「混蛋！你給我站住！」",
    ],
    "zh-Hans": [
        "「你到底想怎么样？」",
        "她低下头，沉默了很久，才终于开口。",
        "「……我只是不想再一个人了。」",
        "窗外的雨一直下个不停，仿佛永远不会停止。",
        "「混蛋！你给我站住！」",
    ],
    "ja": [
        "「……ねえ、まだ起きてる？」",
        "窓の外では、雨が静かに降り続いていた。",
        "「明日も一緒に帰ろうね、約束だよ」",
        "僕は何も答えられず、ただ彼女の背中を見送った。",
        "「先輩のバカ！もう知らない！」",
    ],
    "en": [
        '"Hey... are you still awake?"',
        "Outside the window, the rain kept falling quietly.",
        "\"Let's walk home together tomorrow too. It's a promise.\"",
        "I couldn't answer, and just watched her walk away.",
        '"You idiot! I don\'t care anymore!"',
    ],
}
"""Frases de prueba al estilo de una VN, escritas para el banco. Se traducen en orden, cada una
con las anteriores como contexto."""

_TIEMPO_PROMPT = re.compile(r"prompt eval time =\s*([\d.]+) ms /\s*(\d+) tokens")
_TIEMPO_GENERACION = re.compile(r"\|\s+eval time =.*?([\d.]+) tokens per second")
"""La línea de la generación; la del prompt («prompt eval time») no lleva la barra delante."""


@dataclass(frozen=True)
class Medida:
    """Una frase traducida y lo que ha tardado."""

    idioma: str
    original: str
    traduccion: str
    primera_s: float
    """Hasta la primera frase de la traducción: cuando empezaría a sonar la voz."""
    total_s: float


@dataclass(frozen=True)
class TiempoServidor:
    """Lo que `llama-server` apunta en su registro de una petición."""

    prompt_ms: float
    prompt_tokens: int
    tokens_s: float
    """Tokens por segundo al generar la traducción."""


@dataclass(frozen=True)
class Sistema:
    """Estado del equipo en un instante (Linux; en otros sistemas, todo None)."""

    mhz: float | None = None
    """Frecuencia del núcleo más rápido: la media engaña, porque cuenta los núcleos parados."""
    memoria_libre_mb: float | None = None
    swap_usado_mb: float | None = None
    paginas_swap: int | None = None
    """Páginas leídas y escritas en el swap desde el arranque: si crece, falta memoria."""


def tiempos_servidor(registro: str) -> list[TiempoServidor]:
    """Tiempos de cada petición en el texto del registro de `llama-server`."""
    prompts = _TIEMPO_PROMPT.findall(registro)
    generaciones = _TIEMPO_GENERACION.findall(registro)
    return [
        TiempoServidor(float(ms), int(tokens), float(tps))
        for (ms, tokens), tps in zip(prompts, generaciones, strict=False)
    ]


def _leer(ruta: Path) -> str | None:
    try:
        return ruta.read_text(encoding="utf-8")
    except OSError:
        return None


def sistema(raiz: Path = Path("/")) -> Sistema:
    """Frecuencia de la CPU, memoria y swap ahora mismo, leídos de /proc y /sys."""
    frecuencias = [
        int(texto) / 1000
        for ruta in sorted((raiz / "sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq"))
        if (texto := _leer(ruta)) and texto.strip().isdigit()
    ]
    memoria = {
        linea.split(":")[0]: int(linea.split()[1])
        for linea in (_leer(raiz / "proc/meminfo") or "").splitlines()
        if linea.count(":") == 1 and linea.split()[1:2] and linea.split()[1].isdigit()
    }
    vmstat = dict(linea.split() for linea in (_leer(raiz / "proc/vmstat") or "").splitlines() if " " in linea)
    swap = memoria.get("SwapTotal", 0) - memoria.get("SwapFree", 0) if "SwapTotal" in memoria else None
    paginas = (
        int(vmstat["pswpin"]) + int(vmstat["pswpout"]) if {"pswpin", "pswpout"} <= vmstat.keys() else None
    )
    return Sistema(
        mhz=max(frecuencias) if frecuencias else None,
        memoria_libre_mb=memoria["MemAvailable"] / 1024 if "MemAvailable" in memoria else None,
        swap_usado_mb=swap / 1024 if swap is not None else None,
        paginas_swap=paginas,
    )


class Vigia:
    """Toma muestras del sistema en segundo plano mientras se mide."""

    def __init__(self, muestrear: Callable[[], Sistema] = sistema, intervalo_s: float = 0.5) -> None:
        self._muestrear = muestrear
        self._intervalo_s = intervalo_s
        self._parar = threading.Event()
        self.muestras: list[Sistema] = []
        self._hilo = threading.Thread(target=self._bucle, name="vigia", daemon=True)

    def __enter__(self) -> "Vigia":
        self.muestras.append(self._muestrear())
        self._hilo.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._parar.set()
        self._hilo.join()
        self.muestras.append(self._muestrear())

    def _bucle(self) -> None:
        while not self._parar.wait(self._intervalo_s):
            self.muestras.append(self._muestrear())

    def resumen(self) -> str:
        """Frecuencia media y mínima, memoria libre mínima y swap durante la medición."""
        partes = []
        if mhz := [m.mhz for m in self.muestras if m.mhz is not None]:
            partes.append(f"CPU hasta {statistics.mean(mhz):.0f} MHz de media (mínimo {min(mhz):.0f})")
        if libre := [m.memoria_libre_mb for m in self.muestras if m.memoria_libre_mb is not None]:
            partes.append(f"memoria libre mínima {min(libre):.0f} MB")
        paginas = [m.paginas_swap for m in self.muestras if m.paginas_swap is not None]
        usado = [m.swap_usado_mb for m in self.muestras if m.swap_usado_mb is not None]
        if paginas and usado:
            partes.append(f"swap {usado[-1]:.0f} MB, {paginas[-1] - paginas[0]} páginas movidas")
        return ", ".join(partes) or "sin datos del sistema"


def medir(traductor: TraductorLocal, idioma: str, frases: Sequence[str]) -> Iterator[Medida]:
    """Traduce las frases en orden, en streaming y con las anteriores como contexto."""
    previas: list[LineaPrevia] = []
    for frase in frases:
        inicio = time.perf_counter()
        primera: list[float] = []

        def al_parte(_: str, inicio: float = inicio, primera: list[float] = primera) -> None:
            if not primera:
                primera.append(time.perf_counter() - inicio)

        resultado = traductor.traducir_por_partes(
            Peticion(frase, idioma, tuple(previas)), al_parte, lambda: False
        )
        total = time.perf_counter() - inicio
        traduccion = resultado.traduccion.texto if resultado is not None else ""
        previas.append(LineaPrevia(frase, traduccion))
        yield Medida(idioma, frase, traduccion, primera[0] if primera else total, total)


def resumir(idioma: str, medidas: Sequence[Medida], servidor: Sequence[TiempoServidor]) -> str:
    """Una línea con los tiempos de un idioma."""
    primeras = [m.primera_s for m in medidas]
    totales = [m.total_s for m in medidas]
    linea = (
        f"{idioma:8} primera frase {statistics.median(primeras):.2f} s (máx. {max(primeras):.2f}), "
        f"total {statistics.median(totales):.2f} s (máx. {max(totales):.2f})"
    )
    if servidor:
        prompt = statistics.median(t.prompt_ms for t in servidor)
        tokens = statistics.median(t.tokens_s for t in servidor)
        linea += f"; prompt {prompt:.0f} ms, {tokens:.1f} tokens/s"
    return linea


def _ocupar() -> None:
    while True:
        pass


@contextmanager
def carga(procesos: int) -> Iterator[None]:
    """Procesos que ocupan la CPU mientras dura el bloque, para simular un juego."""
    contexto = multiprocessing.get_context("spawn")  # fork con hilos puede bloquearse
    activos = [contexto.Process(target=_ocupar, daemon=True) for _ in range(procesos)]
    for proceso in activos:
        proceso.start()
    try:
        yield
    finally:
        for proceso in activos:
            proceso.terminate()
            proceso.join()


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m vn_audiolibro.traduccion", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--idioma", action="append", choices=FRASES, help="idioma de origen (por defecto, todos)"
    )
    parser.add_argument("--hilos", type=int, help="hilos de llama-server (por defecto, los de la app)")
    parser.add_argument("--opciones", default="", help='opciones extra de llama-server, p. ej. "--poll 0"')
    parser.add_argument("--modelo", type=Path, help="otro modelo GGUF (por defecto, el de la app)")
    parser.add_argument("--carga", type=int, default=0, help="procesos que ocupan la CPU mientras se mide")
    parser.add_argument("--ver", action="store_true", help="muestra cada traducción")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la herramienta."""
    args = _argumentos(argv)
    por_defecto = AjustesServidor()
    ajustes = AjustesServidor(
        hilos=args.hilos or por_defecto.hilos, opciones=tuple(shlex.split(args.opciones))
    )
    try:
        modelo = args.modelo or asegurar_modelo_traduccion()
        print(
            f"{modelo.name} en llama-server con {ajustes.hilos} hilos {' '.join(ajustes.opciones)}".rstrip()
        )
        servidor = ServidorLlama(asegurar_llama_server(), modelo, ajustes)
        with servidor, carga(args.carga):
            traductor = TraductorLocal(servidor.iniciar())  # ya arrancado: devuelve su cliente
            for idioma in args.idioma or list(FRASES):
                traductor.calentar(idioma)
                antes = len(tiempos_servidor(_leer(servidor.registro) or ""))
                with Vigia() as vigia:
                    medidas = list(medir(traductor, idioma, FRASES[idioma]))
                tiempos = tiempos_servidor(_leer(servidor.registro) or "")[antes:]
                print(resumir(idioma, medidas, tiempos))
                print(f"         {vigia.resumen()}")
                if args.ver:
                    for medida in medidas:
                        print(f"           {medida.original}\n           → {medida.traduccion}")
    except (TraduccionFallidaError, DescargaFallidaError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0
