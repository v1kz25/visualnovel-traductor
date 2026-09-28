"""Tests de la descarga, verificación y extracción de ficheros externos (sin red)."""

import hashlib
import io
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from vn_audiolibro import descargas
from vn_audiolibro.descargas import (
    Descarga,
    DescargaCanceladaError,
    DescargaFallidaError,
    asegurar_descarga,
    descargar_https,
    directorio_modelos,
    extraer_tar,
    extraer_zip,
)

CONTENIDO = b"modelo de prueba"
MODELO = Descarga("prueba.onnx", "https://ejemplo.invalid/prueba.onnx", hashlib.sha256(CONTENIDO).hexdigest())


class DescargadorFalso:
    def __init__(self, contenido: bytes = CONTENIDO) -> None:
        self.contenido = contenido
        self.llamadas: list[str] = []

    def __call__(self, url: str, destino: Path, progreso: object = None, cancelado: object = None) -> None:
        self.llamadas.append(url)
        destino.write_bytes(self.contenido)


def test_descarga_el_modelo_si_no_existe(tmp_path: Path) -> None:
    descargador = DescargadorFalso()

    ruta = asegurar_descarga(MODELO, tmp_path, descargador)

    assert ruta == tmp_path / "prueba.onnx"
    assert ruta.read_bytes() == CONTENIDO
    assert descargador.llamadas == [MODELO.url]


def test_no_vuelve_a_descargar_un_modelo_correcto(tmp_path: Path) -> None:
    (tmp_path / "prueba.onnx").write_bytes(CONTENIDO)
    descargador = DescargadorFalso()

    asegurar_descarga(MODELO, tmp_path, descargador)

    assert descargador.llamadas == []


def test_sustituye_un_modelo_corrupto(tmp_path: Path) -> None:
    (tmp_path / "prueba.onnx").write_bytes(b"a medias")

    ruta = asegurar_descarga(MODELO, tmp_path, DescargadorFalso())

    assert ruta.read_bytes() == CONTENIDO


def test_rechaza_una_descarga_con_otra_huella_y_no_deja_restos(tmp_path: Path) -> None:
    with pytest.raises(DescargaFallidaError, match="SHA-256"):
        asegurar_descarga(MODELO, tmp_path, DescargadorFalso(b"otro fichero"))

    assert list(tmp_path.iterdir()) == []


def test_convierte_los_errores_de_red_en_modelo_no_disponible(tmp_path: Path) -> None:
    def sin_red(url: str, destino: Path, *_: object) -> None:
        raise OSError("sin conexión")

    with pytest.raises(DescargaFallidaError, match="sin conexión"):
        asegurar_descarga(MODELO, tmp_path, sin_red)


def test_solo_descarga_por_https(tmp_path: Path) -> None:
    with pytest.raises(DescargaFallidaError, match="HTTPS"):
        descargar_https("file:///etc/passwd", tmp_path / "x")


def test_directorio_de_modelos_sigue_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert directorio_modelos() == tmp_path / "vn-audiolibro" / "modelos"

    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setattr(sys, "platform", "linux")
    assert directorio_modelos() == Path.home() / ".local" / "share" / "vn-audiolibro" / "modelos"


def crear_tar(ruta: Path, miembros: list[tarfile.TarInfo], contenido: bytes = b"#!/bin/sh\n") -> Path:
    with tarfile.open(ruta, "w:gz") as tar:
        for miembro in miembros:
            if miembro.isfile():
                miembro.size = len(contenido)
                tar.addfile(miembro, io.BytesIO(contenido))
            else:
                tar.addfile(miembro)
    return ruta


def test_extrae_conservando_permisos_y_enlaces_internos(tmp_path: Path) -> None:
    ejecutable = tarfile.TarInfo("llama/llama-server")
    ejecutable.mode = 0o755
    biblioteca = tarfile.TarInfo("llama/libggml.so.0")
    enlace = tarfile.TarInfo("llama/libggml.so")
    enlace.type = tarfile.SYMTYPE
    enlace.linkname = "libggml.so.0"
    archivo = crear_tar(tmp_path / "llama.tar.gz", [ejecutable, biblioteca, enlace])

    destino = extraer_tar(archivo, tmp_path / "destino")

    assert os.access(destino / "llama" / "llama-server", os.X_OK)
    assert (destino / "llama" / "libggml.so").is_symlink()
    assert (destino / "llama" / "libggml.so").read_bytes() == b"#!/bin/sh\n"


def test_rechaza_rutas_fuera_del_destino(tmp_path: Path) -> None:
    archivo = crear_tar(tmp_path / "malo.tar.gz", [tarfile.TarInfo("../fuera")])

    with pytest.raises(DescargaFallidaError, match="extraer"):
        extraer_tar(archivo, tmp_path / "destino")

    assert not (tmp_path / "fuera").exists()


def test_error_si_el_archivo_no_es_un_tar(tmp_path: Path) -> None:
    archivo = tmp_path / "roto.tar.gz"
    archivo.write_bytes(b"no es un tar")

    with pytest.raises(DescargaFallidaError):
        extraer_tar(archivo, tmp_path / "destino")


def test_extrae_un_zip(tmp_path: Path) -> None:
    archivo = tmp_path / "llama.zip"
    with zipfile.ZipFile(archivo, "w") as zip_:
        zip_.writestr("llama-server.exe", b"MZ")
        zip_.writestr("sub/ggml.dll", b"dll")

    destino = extraer_zip(archivo, tmp_path / "destino")

    assert (destino / "llama-server.exe").read_bytes() == b"MZ"
    assert (destino / "sub" / "ggml.dll").read_bytes() == b"dll"


@pytest.mark.parametrize("nombre", ["../fuera", "sub/../../fuera"])
def test_zip_rechaza_rutas_fuera_del_destino(tmp_path: Path, nombre: str) -> None:
    archivo = tmp_path / "malo.zip"
    with zipfile.ZipFile(archivo, "w") as zip_:
        zip_.writestr("bueno.txt", b"ok")
        zip_.writestr(nombre, b"malo")

    with pytest.raises(DescargaFallidaError, match="sale del destino"):
        extraer_zip(archivo, tmp_path / "destino")

    assert not (tmp_path / "fuera").exists()
    assert not (tmp_path / "destino" / "bueno.txt").exists()  # no extrae nada


def test_error_si_el_archivo_no_es_un_zip(tmp_path: Path) -> None:
    archivo = tmp_path / "roto.zip"
    archivo.write_bytes(b"no es un zip")

    with pytest.raises(DescargaFallidaError, match="extraer"):
        extraer_zip(archivo, tmp_path / "destino")


class RespuestaFalsa:
    """Respuesta HTTP en memoria que entrega el contenido en bloques pequeños."""

    def __init__(self, contenido: bytes, con_longitud: bool = True) -> None:
        self._bloques = [contenido[i : i + 4] for i in range(0, len(contenido), 4)]
        self.headers = {"Content-Length": str(len(contenido))} if con_longitud else {}

    def read(self, _: int) -> bytes:
        return self._bloques.pop(0) if self._bloques else b""

    def __enter__(self) -> "RespuestaFalsa":
        return self

    def __exit__(self, *_: object) -> None:
        pass


@pytest.mark.parametrize("con_longitud", [True, False])
def test_descargar_https_informa_del_progreso(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, con_longitud: bool
) -> None:
    monkeypatch.setattr(
        descargas.urllib.request, "urlopen", lambda *_, **__: RespuestaFalsa(CONTENIDO, con_longitud)
    )
    avisos: list[tuple[int, int | None]] = []

    ruta = asegurar_descarga(MODELO, tmp_path, progreso=lambda h, t: avisos.append((h, t)))

    assert ruta.read_bytes() == CONTENIDO
    total = len(CONTENIDO) if con_longitud else None
    assert avisos[-1] == (len(CONTENIDO), total)
    assert [hecho for hecho, _ in avisos] == sorted(hecho for hecho, _ in avisos)


def test_descargar_https_se_puede_cancelar_sin_dejar_restos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(descargas.urllib.request, "urlopen", lambda *_, **__: RespuestaFalsa(CONTENIDO))
    avisos: list[int] = []

    with pytest.raises(DescargaCanceladaError, match="cancelada"):
        asegurar_descarga(
            MODELO, tmp_path, progreso=lambda h, _: avisos.append(h), cancelado=lambda: len(avisos) >= 2
        )

    assert list(tmp_path.iterdir()) == []
    assert avisos == [4, 8]
