"""`llama-server` de llama.cpp: descarga, arranque, parada y cliente HTTP.

El servidor escucha solo en 127.0.0.1, en un puerto libre elegido al arrancar.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from vn_audiolibro.descargas import (
    Cancelado,
    Descarga,
    Progreso,
    asegurar_descarga,
    directorio_modelos,
    extraer_tar,
    extraer_zip,
)
from vn_audiolibro.plataforma import sin_ventana
from vn_audiolibro.rutas import directorio_datos
from vn_audiolibro.textos import _
from vn_audiolibro.traduccion.modelos import TraduccionFallidaError

VERSION_LLAMA = "b11165"

LLAMA_SERVER = Descarga(
    fichero=f"llama-{VERSION_LLAMA}-bin-ubuntu-x64.tar.gz",
    url=(
        f"https://github.com/ggml-org/llama.cpp/releases/download/{VERSION_LLAMA}/"
        f"llama-{VERSION_LLAMA}-bin-ubuntu-x64.tar.gz"
    ),
    sha256="42a45d270b3644c4425dea347412eed33b2abd0187993172236790ca77951b49",
)
"""Binarios oficiales de llama.cpp para Linux, CPU x64 (MIT)."""

LLAMA_SERVER_WINDOWS = Descarga(
    fichero=f"llama-{VERSION_LLAMA}-bin-win-cpu-x64.zip",
    url=(
        f"https://github.com/ggml-org/llama.cpp/releases/download/{VERSION_LLAMA}/"
        f"llama-{VERSION_LLAMA}-bin-win-cpu-x64.zip"
    ),
    sha256="38d5828e4a32d2eca5b23eb912e3a904246e1bdd0aeb5797eeebaf5497549346",
)
"""Binarios oficiales de llama.cpp para Windows, CPU x64 (MIT). Van sin carpeta raíz en el zip."""


@dataclass(frozen=True)
class BinarioLlama:
    """El paquete de `llama-server` de un sistema operativo."""

    descarga: Descarga
    ejecutable: str
    """Ruta del ejecutable dentro del paquete extraído."""
    tamano: int
    """Bytes de la descarga."""


def binario_llama() -> BinarioLlama:
    """El paquete de `llama-server` para este sistema."""
    if sys.platform == "win32":
        return BinarioLlama(LLAMA_SERVER_WINDOWS, "llama-server.exe", 18_567_820)
    return BinarioLlama(LLAMA_SERVER, f"llama-{VERSION_LLAMA}/llama-server", 17_014_425)


HY_MT2_1_8B_Q4 = Descarga(
    fichero="Hy-MT2-1.8B-Q4_K_M.gguf",
    url="https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/main/Hy-MT2-1.8B-Q4_K_M.gguf",
    sha256="dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699",
)
"""Hy-MT2 1.8B cuantizado a 4 bits, de la cuenta verificada de Tencent (Apache-2.0). ~1,1 GB."""

PARAMETROS_HY_MT2: dict[str, Any] = {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05}
"""Parámetros recomendados en la ficha de Hy-MT2 1.8B."""


def ruta_llama_server(directorio: Path | None = None) -> Path:
    """Dónde queda el ejecutable `llama-server` una vez instalado."""
    carpeta = directorio or directorio_datos() / "llama.cpp"
    return carpeta / VERSION_LLAMA / binario_llama().ejecutable


def asegurar_llama_server(
    directorio: Path | None = None, progreso: Progreso | None = None, cancelado: Cancelado | None = None
) -> Path:
    """Ruta del ejecutable `llama-server`; lo descarga y extrae antes si hace falta.

    Se extrae en una carpeta temporal que solo se renombra al terminar: una extracción cortada
    no deja una instalación a medias que parezca completa.
    """
    carpeta = directorio or directorio_datos() / "llama.cpp"
    instalacion = carpeta / VERSION_LLAMA
    ejecutable = ruta_llama_server(directorio)
    if not ejecutable.is_file():
        descarga = binario_llama().descarga
        archivo = asegurar_descarga(descarga, carpeta, progreso=progreso, cancelado=cancelado)
        temporal = carpeta / f"{VERSION_LLAMA}.parcial"
        shutil.rmtree(temporal, ignore_errors=True)
        shutil.rmtree(instalacion, ignore_errors=True)
        extraer = extraer_zip if descarga.fichero.endswith(".zip") else extraer_tar
        extraer(archivo, temporal)
        temporal.rename(instalacion)
        archivo.unlink()
    return ejecutable


def asegurar_modelo_traduccion(
    directorio: Path | None = None, progreso: Progreso | None = None, cancelado: Cancelado | None = None
) -> Path:
    """Ruta del modelo Hy-MT2; lo descarga antes si hace falta."""
    carpeta = directorio or directorio_modelos()
    return asegurar_descarga(HY_MT2_1_8B_Q4, carpeta, progreso=progreso, cancelado=cancelado)


def puerto_libre() -> int:
    """Un puerto TCP libre en 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexion:
        conexion.bind(("127.0.0.1", 0))
        puerto: int = conexion.getsockname()[1]
        return puerto


class ClienteLlama:
    """Cliente mínimo de la API compatible con OpenAI de `llama-server`."""

    def __init__(self, url: str, parametros: dict[str, Any] | None = None, timeout_s: float = 60) -> None:
        self.url = url.rstrip("/")
        self._parametros = PARAMETROS_HY_MT2 if parametros is None else parametros
        self._timeout_s = timeout_s

    def completar(self, prompt: str, max_tokens: int = 512) -> str:
        """Respuesta del modelo a un único mensaje de usuario."""
        cuerpo = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            **self._parametros,
        }
        respuesta = self._pedir("/v1/chat/completions", json.dumps(cuerpo).encode())
        try:
            texto: str = respuesta["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise TraduccionFallidaError(
                _("Respuesta inesperada de llama-server: {respuesta}").format(respuesta=respuesta)
            ) from error
        return texto

    def completar_por_partes(self, prompt: str, max_tokens: int = 512) -> Generator[str]:
        """Respuesta del modelo a medida que se genera, trozo a trozo (streaming).

        Si se deja de iterar (se cierra el generador), se corta la conexión y el servidor deja
        de generar: sirve para abandonar una traducción que ya no hace falta.
        """
        cuerpo = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
            **self._parametros,
        }
        url = self.url + "/v1/chat/completions"
        cabeceras = {"Content-Type": "application/json"}
        peticion = urllib.request.Request(url, json.dumps(cuerpo).encode(), cabeceras)  # noqa: S310 - 127.0.0.1
        try:
            with urllib.request.urlopen(peticion, timeout=self._timeout_s) as respuesta:  # noqa: S310
                for linea in respuesta:
                    trozo = _trozo_sse(linea)
                    if trozo:
                        yield trozo
        except (OSError, ValueError) as error:
            raise TraduccionFallidaError(
                _("Error al llamar a llama-server en streaming: {error}").format(error=error)
            ) from error

    def disponible(self) -> bool:
        """Si el servidor ha cargado el modelo y acepta peticiones."""
        try:
            return self._pedir("/health", None, timeout_s=2).get("status") == "ok"
        except TraduccionFallidaError:
            return False

    def _pedir(self, ruta: str, cuerpo: bytes | None, timeout_s: float | None = None) -> dict[str, Any]:
        peticion = urllib.request.Request(  # noqa: S310 - siempre http://127.0.0.1
            self.url + ruta, cuerpo, {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(peticion, timeout=timeout_s or self._timeout_s) as respuesta:  # noqa: S310
                datos: dict[str, Any] = json.load(respuesta)
                return datos
        except (OSError, ValueError) as error:
            raise TraduccionFallidaError(
                _("Error al llamar a llama-server ({ruta}): {error}").format(ruta=ruta, error=error)
            ) from error


def _trozo_sse(linea: bytes) -> str:
    """Texto de un evento `data: {...}` del streaming; vacío si no trae texto."""
    datos = linea.decode("utf-8").strip()
    if not datos.startswith("data: ") or datos == "data: [DONE]":
        return ""
    try:
        trozo = json.loads(datos[len("data: ") :])["choices"][0]["delta"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise TraduccionFallidaError(
            _("Evento inesperado de llama-server: {datos}").format(datos=datos)
        ) from error
    return trozo if isinstance(trozo, str) else ""


@dataclass(frozen=True)
class AjustesServidor:
    """Opciones de arranque de `llama-server`."""

    contexto: int = 2048
    """Tokens de contexto: sobran para una línea con tres de contexto y el glosario."""
    hilos: int = max(1, min(4, (os.cpu_count() or 2) // 2))
    """Hilos de CPU: la mitad de los núcleos, hasta 4, para dejar sitio al juego."""
    arranque_s: float = 120
    """Tiempo máximo para cargar el modelo."""


class ServidorLlama:
    """Proceso de `llama-server` con un modelo cargado. Usar con `with` para pararlo al salir."""

    def __init__(
        self,
        ejecutable: Path,
        modelo: Path,
        ajustes: AjustesServidor | None = None,
        registro: Path | None = None,
    ) -> None:
        self.ejecutable = ejecutable
        self.modelo = modelo
        self.ajustes = ajustes or AjustesServidor()
        self.registro = registro or directorio_datos() / "registros" / "llama-server.log"
        self._proceso: subprocess.Popen[bytes] | None = None
        self.cliente: ClienteLlama | None = None

    def iniciar(self) -> ClienteLlama:
        """Arranca el servidor y espera a que cargue el modelo. Devuelve su cliente."""
        if self._proceso is not None and self.cliente is not None:
            return self.cliente
        puerto = puerto_libre()
        orden = [
            str(self.ejecutable),
            *("--model", str(self.modelo)),
            *("--host", "127.0.0.1"),
            *("--port", str(puerto)),
            *("--ctx-size", str(self.ajustes.contexto)),
            *("--threads", str(self.ajustes.hilos)),
            *("--parallel", "1"),
        ]
        self.registro.parent.mkdir(parents=True, exist_ok=True)
        with self.registro.open("wb") as registro:
            self._proceso = subprocess.Popen(  # noqa: S603 - orden fija, sin shell
                orden, stdout=registro, stderr=subprocess.STDOUT, creationflags=sin_ventana()
            )
        cliente = ClienteLlama(f"http://127.0.0.1:{puerto}")
        limite = time.monotonic() + self.ajustes.arranque_s
        while not cliente.disponible():
            if self._proceso.poll() is not None or time.monotonic() > limite:
                self.detener()
                raise TraduccionFallidaError(
                    _("llama-server no arrancó; detalles en {registro}").format(registro=self.registro)
                )
            time.sleep(0.2)
        self.cliente = cliente
        return cliente

    def detener(self) -> None:
        """Para el servidor, primero con SIGTERM y, si no responde, con SIGKILL."""
        proceso, self._proceso, self.cliente = self._proceso, None, None
        if proceso is None or proceso.poll() is not None:
            return
        proceso.terminate()
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proceso.kill()
            proceso.wait()

    def __enter__(self) -> Self:
        self.iniciar()
        return self

    def __exit__(
        self, tipo: type[BaseException] | None, error: BaseException | None, traza: TracebackType | None
    ) -> None:
        self.detener()
