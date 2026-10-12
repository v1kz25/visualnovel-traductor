"""Tests del cliente y del proceso de `llama-server` con un servidor falso."""

import io
import os
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.traduccion import llama
from vn_audiolibro.traduccion.llama import (
    AjustesServidor,
    ClienteLlama,
    ServidorLlama,
    asegurar_llama_server,
    asegurar_modelo_traduccion,
    puerto_libre,
)
from vn_audiolibro.traduccion.modelos import TraduccionFallidaError

from . import falso_llama

FALSO = Path(falso_llama.__file__)


@pytest.fixture
def url() -> Iterator[str]:
    falso_llama.Manejador.respuesta_forzada = None
    falso_llama.Manejador.salida = None
    falso_llama.Manejador.peticiones = []
    servidor, url = falso_llama.en_hilo()
    yield url
    servidor.shutdown()


def test_completar_envia_el_prompt_y_los_parametros(url: str) -> None:
    cliente = ClienteLlama(url)

    assert cliente.completar("Translate:\n\n你好") == "Traducción de: 你好"

    peticion = falso_llama.Manejador.peticiones[0]
    assert peticion["messages"] == [{"role": "user", "content": "Translate:\n\n你好"}]
    assert (peticion["temperature"], peticion["top_p"], peticion["top_k"]) == (0.7, 0.6, 20)


def test_completar_por_partes(url: str) -> None:
    cliente = ClienteLlama(url)

    partes = list(cliente.completar_por_partes("Translate:\n\n你好", max_tokens=30))

    assert partes == ["Traducción", " de:", " 你好"]
    peticion = falso_llama.Manejador.peticiones[0]
    assert (peticion["stream"], peticion["max_tokens"]) == (True, 30)


def test_completar_por_partes_se_puede_abandonar(url: str) -> None:
    falso_llama.Manejador.salida = " ".join(["palabra"] * 2000)
    partes = ClienteLlama(url).completar_por_partes("x")
    assert next(partes) == "palabra"
    partes.close()  # corta la conexión sin leer el resto


def test_completar_por_partes_con_errores(url: str) -> None:
    falso_llama.Manejador.respuesta_forzada = (500, b"{}")
    with pytest.raises(TraduccionFallidaError, match="streaming"):
        list(ClienteLlama(url).completar_por_partes("x"))


@pytest.mark.parametrize(
    ("linea", "trozo"),
    [
        (b'data: {"choices": [{"delta": {"content": "hola"}}]}', "hola"),
        (b'data: {"choices": [{"delta": {"role": "assistant"}}]}', ""),
        (b'data: {"choices": [{"delta": {"content": null}}]}', ""),
        (b"data: [DONE]", ""),
        (b": comentario", ""),
        (b"", ""),
    ],
)
def test_trozos_del_streaming(linea: bytes, trozo: str) -> None:
    assert llama._trozo_sse(linea) == trozo


def test_evento_de_streaming_inesperado() -> None:
    with pytest.raises(TraduccionFallidaError, match="Evento inesperado"):
        llama._trozo_sse(b'data: {"error": "x"}')


def test_disponible(url: str) -> None:
    assert ClienteLlama(url).disponible()
    assert not ClienteLlama(f"http://127.0.0.1:{puerto_libre()}").disponible()


@pytest.mark.parametrize(
    "respuesta", [(500, b'{"error": "fallo"}'), (200, b"no es json"), (200, b'{"choices": []}')]
)
def test_errores_del_servidor(url: str, respuesta: tuple[int, bytes]) -> None:
    falso_llama.Manejador.respuesta_forzada = respuesta

    with pytest.raises(TraduccionFallidaError):
        ClienteLlama(url).completar("hola")


SOLO_UNIX = pytest.mark.skipif(
    sys.platform == "win32", reason="el llama-server falso es un script con shebang"
)


def ejecutable_falso(tmp_path: Path, codigo: str | None = None) -> Path:
    """Script ejecutable que hace de `llama-server`."""
    ruta = tmp_path / "llama-server"
    arranque = f"import runpy\nrunpy.run_path({str(FALSO)!r}, run_name='__main__')\n"
    cuerpo = codigo or arranque
    ruta.write_text(f"#!{sys.executable}\n{cuerpo}")
    ruta.chmod(0o755)
    return ruta


@SOLO_UNIX
def test_servidor_arranca_en_localhost_y_se_para(tmp_path: Path) -> None:
    servidor = ServidorLlama(ejecutable_falso(tmp_path), tmp_path / "modelo.gguf", registro=tmp_path / "log")

    with servidor as activo:
        assert activo.cliente is not None
        assert activo.cliente.url.startswith("http://127.0.0.1:")
        assert activo.cliente.completar("x\n\n你好") == "Traducción de: 你好"
        assert servidor.iniciar() is activo.cliente  # iniciar dos veces no arranca otro
        proceso = servidor._proceso
        assert proceso is not None

    assert proceso.poll() is not None
    assert servidor.cliente is None


@SOLO_UNIX
def test_pasa_las_opciones_extra_a_llama_server(tmp_path: Path) -> None:
    argumentos = tmp_path / "argumentos"
    codigo = (
        f"import runpy, sys\nopen({str(argumentos)!r}, 'w').write(' '.join(sys.argv[1:]))\n"
        f"runpy.run_path({str(FALSO)!r}, run_name='__main__')\n"
    )
    ajustes = AjustesServidor(hilos=2, opciones=("--poll", "0"))
    with ServidorLlama(ejecutable_falso(tmp_path, codigo), tmp_path / "m.gguf", ajustes, tmp_path / "log"):
        pass

    orden = argumentos.read_text()
    assert "--threads 2" in orden
    assert orden.endswith("--parallel 1 --poll 0")


@SOLO_UNIX
def test_error_si_el_servidor_termina_al_arrancar(tmp_path: Path) -> None:
    ejecutable = ejecutable_falso(tmp_path, "import sys\nprint('modelo no encontrado')\nsys.exit(1)\n")
    servidor = ServidorLlama(ejecutable, tmp_path / "modelo.gguf", registro=tmp_path / "log")

    with pytest.raises(TraduccionFallidaError, match="no arrancó"):
        servidor.iniciar()

    assert "modelo no encontrado" in (tmp_path / "log").read_text()


@SOLO_UNIX
def test_error_si_el_servidor_no_responde_a_tiempo(tmp_path: Path) -> None:
    ejecutable = ejecutable_falso(tmp_path, "import time\ntime.sleep(30)\n")
    ajustes = AjustesServidor(arranque_s=0.5)
    servidor = ServidorLlama(ejecutable, tmp_path / "modelo.gguf", ajustes, registro=tmp_path / "log")

    with pytest.raises(TraduccionFallidaError):
        servidor.iniciar()

    servidor.detener()  # ya parado: no falla


@SOLO_UNIX
def test_detiene_con_sigkill_si_ignora_sigterm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    servidor = ServidorLlama(ejecutable_falso(tmp_path), tmp_path / "modelo.gguf", registro=tmp_path / "log")
    servidor.iniciar()
    proceso = servidor._proceso
    assert proceso is not None
    monkeypatch.setattr(proceso, "terminate", lambda: None)
    esperas: list[float | None] = []
    espera_real = proceso.wait

    def wait(timeout: float | None = None) -> int:
        esperas.append(timeout)
        if timeout is not None:
            raise llama.subprocess.TimeoutExpired("llama-server", timeout)
        return espera_real()

    monkeypatch.setattr(proceso, "wait", wait)

    servidor.detener()

    assert esperas == [5, None]
    assert proceso.poll() is not None


def test_instala_llama_server_desde_el_tar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    archivo = tmp_path / "descarga.tar.gz"
    with tarfile.open(archivo, "w:gz") as tar:
        miembro = tarfile.TarInfo(f"llama-{llama.VERSION_LLAMA}/llama-server")
        miembro.mode, miembro.size = 0o755, 2
        tar.addfile(miembro, io.BytesIO(b"ok"))
    monkeypatch.setattr(llama, "asegurar_descarga", lambda descarga, carpeta, **_: archivo)

    ejecutable = asegurar_llama_server(tmp_path / "llama.cpp")

    assert os.access(ejecutable, os.X_OK)
    assert not archivo.exists()
    # La segunda vez ya está instalado y no descarga nada.
    monkeypatch.setattr(llama, "asegurar_descarga", lambda *_: pytest.fail("no debería descargar"))
    assert asegurar_llama_server(tmp_path / "llama.cpp") == ejecutable


def test_en_windows_instala_llama_server_desde_el_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    archivo = tmp_path / "descarga.zip"
    with zipfile.ZipFile(archivo, "w") as zip_:
        zip_.writestr("llama-server.exe", b"MZ")
        zip_.writestr("ggml-base.dll", b"MZ")
    pedidas: list[str] = []

    def descargar(descarga: llama.Descarga, carpeta: Path, **_: object) -> Path:
        pedidas.append(descarga.fichero)
        return archivo

    monkeypatch.setattr(llama, "asegurar_descarga", descargar)

    ejecutable = asegurar_llama_server(tmp_path / "llama.cpp")

    assert pedidas == [f"llama-{llama.VERSION_LLAMA}-bin-win-cpu-x64.zip"]
    assert ejecutable == tmp_path / "llama.cpp" / llama.VERSION_LLAMA / "llama-server.exe"
    assert ejecutable.read_bytes() == b"MZ"
    assert (ejecutable.parent / "ggml-base.dll").is_file()
    assert not archivo.exists()


def test_una_extraccion_fallida_no_deja_una_instalacion_a_medias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archivo = tmp_path / "roto.tar.gz"
    archivo.write_bytes(b"no es un tar")
    monkeypatch.setattr(llama, "asegurar_descarga", lambda descarga, carpeta, **_: archivo)

    with pytest.raises(DescargaFallidaError):
        asegurar_llama_server(tmp_path / "llama.cpp")

    assert not (tmp_path / "llama.cpp" / llama.VERSION_LLAMA).exists()


def test_modelo_de_traduccion_en_el_directorio_de_modelos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pedidas: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        llama, "asegurar_descarga", lambda d, c, **_: pedidas.append((d.fichero, c)) or c / d.fichero
    )

    ruta = asegurar_modelo_traduccion(tmp_path)

    assert ruta == tmp_path / "Hy-MT2-1.8B-Q4_K_M.gguf"
    assert pedidas == [("Hy-MT2-1.8B-Q4_K_M.gguf", tmp_path)]
