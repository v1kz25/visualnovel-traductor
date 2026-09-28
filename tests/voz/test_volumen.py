"""Tests de la bajada de volumen del juego con un cliente de PulseAudio falso."""

import json
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from vn_audiolibro.voz.volumen import (
    AtenuadorJuego,
    Criterio,
    Flujo,
    Juego,
    Seleccion,
    Volumen,
    fichero_estado,
    juego_de_pid,
)

from .falsos import ESPERA_S

JUEGO = Flujo(7, "Juego.exe", "wine64-preloader", 100, (1.0, 1.0))
NAVEGADOR = Flujo(8, "Firefox", "firefox", 200, (0.8, 0.8))
VOZ = Flujo(9, "vn-audiolibro", "paplay", 300, (1.0, 1.0))


class ClienteFalso:
    """Servidor de sonido en memoria."""

    def __init__(self, *flujos: Flujo) -> None:
        self.volumenes = {f.indice: f.volumen for f in flujos}
        self._flujos = {f.indice: f for f in flujos}
        self.cambios = 0

    def flujos(self) -> list[Flujo]:
        return [
            Flujo(f.indice, f.aplicacion, f.binario, f.pid, self.volumenes[f.indice])
            for f in self._flujos.values()
        ]

    def poner_volumen(self, indice: int, volumen: Volumen) -> None:
        if indice in self._flujos:
            self.volumenes[indice] = volumen
            self.cambios += 1

    def anadir(self, flujo: Flujo) -> None:
        self._flujos[flujo.indice] = flujo
        self.volumenes[flujo.indice] = flujo.volumen

    def quitar(self, indice: int) -> None:
        del self._flujos[indice]


def al(nivel: float) -> Criterio:
    """Criterio que baja solo el juego, a ese nivel."""
    return lambda flujo: nivel if flujo.aplicacion == "Juego.exe" else None


@pytest.fixture
def estado(tmp_path: Path) -> Path:
    return tmp_path / "estado" / "volumen.json"


@pytest.fixture
def cliente() -> ClienteFalso:
    return ClienteFalso(JUEGO, NAVEGADOR, VOZ)


@pytest.fixture
def atenuador(cliente: ClienteFalso, estado: Path) -> Iterator[AtenuadorJuego]:
    atenuador = AtenuadorJuego(cliente, al(0.25), estado=estado, intervalo_s=60)
    yield atenuador
    atenuador.cerrar()


def test_baja_solo_el_juego_y_lo_restaura(atenuador: AtenuadorJuego, cliente: ClienteFalso) -> None:
    atenuador.bajar()
    assert cliente.volumenes == {7: (0.25, 0.25), 8: (0.8, 0.8), 9: (1.0, 1.0)}

    atenuador.restaurar()
    assert cliente.volumenes == {7: (1.0, 1.0), 8: (0.8, 0.8), 9: (1.0, 1.0)}


def test_bajar_dos_veces_no_lo_baja_mas(atenuador: AtenuadorJuego, cliente: ClienteFalso) -> None:
    atenuador.bajar()
    atenuador.bajar()
    assert cliente.volumenes[7] == (0.25, 0.25)
    atenuador.restaurar()
    assert cliente.volumenes[7] == (1.0, 1.0)


def test_restaurar_sin_haber_bajado_no_toca_nada(atenuador: AtenuadorJuego, cliente: ClienteFalso) -> None:
    atenuador.restaurar()
    assert cliente.cambios == 0


def test_baja_los_flujos_que_aparecen_mientras_habla(
    atenuador: AtenuadorJuego, cliente: ClienteFalso
) -> None:
    atenuador.bajar()
    cliente.anadir(Flujo(10, "Juego.exe", "wine64-preloader", 100, (0.5, 0.5)))
    atenuador.revisar()
    assert cliente.volumenes[10] == (0.125, 0.125)

    atenuador.restaurar()
    cliente.anadir(Flujo(11, "Juego.exe", "wine64-preloader", 100, (1.0, 1.0)))
    atenuador.revisar()
    assert cliente.volumenes[10] == (0.5, 0.5)
    assert cliente.volumenes[11] == (1.0, 1.0)


def test_la_vigilancia_revisa_sola(cliente: ClienteFalso, estado: Path) -> None:
    atenuador = AtenuadorJuego(cliente, al(0.5), estado=estado, intervalo_s=0.01)
    atenuador.bajar()
    cliente.anadir(Flujo(10, "Juego.exe", "wine64-preloader", 100, (1.0, 1.0)))
    limite = time.monotonic() + ESPERA_S
    while cliente.volumenes[10] != (0.5, 0.5) and time.monotonic() < limite:
        time.sleep(0.01)
    atenuador.cerrar()
    assert cliente.volumenes[10] == (1.0, 1.0)


def test_un_flujo_que_desaparece_no_falla(atenuador: AtenuadorJuego, cliente: ClienteFalso) -> None:
    atenuador.bajar()
    cliente.quitar(7)
    atenuador.restaurar()
    assert 7 not in {f.indice for f in cliente.flujos()}


def test_apunta_el_volumen_original_mientras_esta_bajado(atenuador: AtenuadorJuego, estado: Path) -> None:
    atenuador.bajar()
    assert json.loads(estado.read_text()) == {"wine64-preloader|Juego.exe": [1.0, 1.0]}
    atenuador.restaurar()
    assert not estado.exists()


def test_recupera_el_volumen_si_la_app_se_cerro_de_golpe(estado: Path) -> None:
    # La ejecución anterior se cerró con el juego bajado y PulseAudio lo recordó.
    estado.parent.mkdir(parents=True)
    estado.write_text(json.dumps({"wine64-preloader|Juego.exe": [0.9, 0.9]}))
    cliente = ClienteFalso(Flujo(7, "Juego.exe", "wine64-preloader", 100, (0.225, 0.225)), NAVEGADOR)

    atenuador = AtenuadorJuego(cliente, al(0.3), estado=estado, intervalo_s=60)

    assert cliente.volumenes[7] == (0.9, 0.9)
    assert not estado.exists()
    atenuador.cerrar()


def test_si_el_juego_no_esta_abierto_lo_recupera_cuando_aparece(estado: Path) -> None:
    estado.parent.mkdir(parents=True)
    estado.write_text(json.dumps({"wine64-preloader|Juego.exe": [0.9, 0.9]}))
    cliente = ClienteFalso(NAVEGADOR)

    atenuador = AtenuadorJuego(cliente, al(0.5), estado=estado, intervalo_s=60)
    assert estado.exists()  # el juego no está abierto: se sigue apuntando

    cliente.anadir(Flujo(7, "Juego.exe", "wine64-preloader", 100, (0.45, 0.45)))
    atenuador.bajar()
    assert cliente.volumenes[7] == (0.45, 0.45)  # la mitad del original, no de lo que quedó
    atenuador.restaurar()
    assert cliente.volumenes[7] == (0.9, 0.9)
    assert not estado.exists()
    atenuador.cerrar()


@pytest.mark.parametrize("contenido", ["no es json", "[1, 2]", '{"a": "b"}'])
def test_estado_ilegible_se_ignora(
    estado: Path, cliente: ClienteFalso, contenido: str, caplog: pytest.LogCaptureFixture
) -> None:
    estado.parent.mkdir(parents=True)
    estado.write_text(contenido)
    atenuador = AtenuadorJuego(cliente, al(0.3), estado=estado, intervalo_s=60)
    atenuador.cerrar()
    assert "ilegible" in caplog.text
    assert cliente.volumenes[7] == (1.0, 1.0)


def test_no_poder_guardar_el_estado_no_impide_bajar(
    cliente: ClienteFalso, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ocupado = tmp_path / "fichero"
    ocupado.write_text("")
    atenuador = AtenuadorJuego(cliente, al(0.3), estado=ocupado / "volumen.json", intervalo_s=60)
    atenuador.bajar()
    assert cliente.volumenes[7] == (0.3, 0.3)
    atenuador.cerrar()
    assert "No se pudo guardar" in caplog.text


def test_nivel_fuera_de_rango() -> None:
    with pytest.raises(ValueError, match="entre 0 y 1"):
        Seleccion(nivel_juego=1.5)
    with pytest.raises(ValueError, match="entre 0 y 1"):
        Seleccion.de_nombres(otras={"Firefox": -0.1})


def test_fichero_estado_en_el_directorio_de_estado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert fichero_estado() == tmp_path / "vn-audiolibro" / "volumen-juego.json"


def test_el_hilo_de_vigilancia_sobrevive_a_un_fallo(estado: Path, caplog: pytest.LogCaptureFixture) -> None:
    fallos = threading.Event()

    class ClienteQueFalla(ClienteFalso):
        def flujos(self) -> list[Flujo]:
            if self.cambios == 0 and not fallos.is_set():
                fallos.set()
                raise RuntimeError("servidor caído")
            return super().flujos()

    cliente = ClienteQueFalla(JUEGO)
    atenuador = AtenuadorJuego(cliente, al(0.5), estado=estado, intervalo_s=0.01)
    with atenuador._cerrojo:  # el primer barrido lo hace el hilo, y falla
        atenuador._bajado = True
    assert fallos.wait(ESPERA_S)
    limite = time.monotonic() + ESPERA_S
    while cliente.volumenes[7] != (0.5, 0.5) and time.monotonic() < limite:
        time.sleep(0.01)
    atenuador.cerrar()
    assert "No se pudo revisar" in caplog.text
    assert cliente.volumenes[7] == (1.0, 1.0)


# Reconocer el juego


def test_reconoce_por_pid_y_por_nombre() -> None:
    juego = Juego(frozenset({100, 101}), frozenset({"juego.exe"}))

    assert juego.es_suyo(Flujo(1, "Otro", "otro", 101, (1.0,)))
    assert juego.es_suyo(Flujo(1, "Juego.exe", "wine64-preloader", 555, (1.0,)))
    assert not juego.es_suyo(NAVEGADOR)
    assert not juego.es_suyo(Flujo(1, "vn-audiolibro", "paplay", 100, (1.0,)))


def test_el_nombre_se_compara_recortado_como_en_proc() -> None:
    juego = Juego(frozenset(), frozenset({"unjuegoconnombr"}))
    assert juego.es_suyo(Flujo(1, "UnJuegoConNombreLargo.exe", "wine64-preloader", None, (1.0,)))


def escribir_proceso(proc: Path, pid: int, nombre: str, ppid: int) -> None:
    carpeta = proc / str(pid)
    carpeta.mkdir(parents=True)
    (carpeta / "stat").write_text(f"{pid} ({nombre}) S {ppid} 1 1 0 -1")


def test_juego_de_pid_incluye_los_descendientes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")  # /proc falso, también en Windows
    escribir_proceso(tmp_path, 1, "systemd", 0)
    escribir_proceso(tmp_path, 50, "steam", 1)
    escribir_proceso(tmp_path, 100, "Juego (1).exe", 50)
    escribir_proceso(tmp_path, 101, "wine64-preloader", 100)
    escribir_proceso(tmp_path, 102, "Voces.exe", 101)
    escribir_proceso(tmp_path, 200, "firefox", 1)
    (tmp_path / "self").mkdir()
    (tmp_path / "300").mkdir()  # proceso que ha terminado mientras se leía

    juego = juego_de_pid(100, tmp_path)

    assert juego.pids == {100, 101, 102}
    assert juego.nombres == {"juego (1).exe", "voces.exe"}  # sin los genéricos de Wine


# Elegir qué aplicaciones se bajan y a qué nivel


def test_seleccion_juego_con_su_nivel_y_otras_con_el_suyo() -> None:
    juego = Juego(frozenset({100}), frozenset())
    musica = Flujo(10, "Spotify", "spotify", 400, (1.0,))
    seleccion = Seleccion.de_nombres(juego, 0.7, otras={"SPOTIFY": 0.5, "firefox": 0})

    assert seleccion(JUEGO) == 0.7
    assert seleccion(musica) == 0.5
    assert seleccion(NAVEGADOR) == 0  # silenciado mientras habla la voz
    assert seleccion(VOZ) is None


def test_las_aplicaciones_no_elegidas_no_se_tocan() -> None:
    seleccion = Seleccion.de_nombres(Juego(frozenset({100}), frozenset()))
    assert seleccion(NAVEGADOR) is None
    assert seleccion(JUEGO) == 0.7  # nivel por defecto


def test_excluir_gana_incluso_al_juego() -> None:
    seleccion = Seleccion.de_nombres(
        Juego(frozenset({100}), frozenset()), otras={"juego.exe": 0.2}, excluir=["JUEGO.EXE"]
    )
    assert seleccion(JUEGO) is None


def test_sin_juego_solo_las_elegidas() -> None:
    seleccion = Seleccion.de_nombres(otras={"firefox": 0.4})
    assert seleccion(NAVEGADOR) == 0.4
    assert seleccion(JUEGO) is None


def test_nunca_baja_la_propia_voz() -> None:
    assert Seleccion.de_nombres(otras={"vn-audiolibro": 0, "paplay": 0})(VOZ) is None


def test_cada_flujo_baja_a_su_nivel(cliente: ClienteFalso, estado: Path) -> None:
    seleccion = Seleccion.de_nombres(Juego(frozenset({100}), frozenset()), 0.5, otras={"Firefox": 0})
    atenuador = AtenuadorJuego(cliente, seleccion, estado=estado, intervalo_s=60)

    atenuador.bajar()
    assert cliente.volumenes == {7: (0.5, 0.5), 8: (0.0, 0.0), 9: (1.0, 1.0)}
    atenuador.cerrar()
    assert cliente.volumenes == {7: (1.0, 1.0), 8: (0.8, 0.8), 9: (1.0, 1.0)}


def test_sin_libpulse_el_modulo_carga_y_avisa() -> None:
    # En otro proceso, como en un sistema sin libpulse: importar pulsectl falla y todo carga igual.
    codigo = """
import sys
sys.modules["pulsectl"] = None
from vn_audiolibro import cli, preparacion
from vn_audiolibro.voz import volumen
assert not volumen.hay_control_de_volumen()
try:
    volumen.ClientePulse()
except volumen.VozFallidaError as error:
    print(error)
"""
    orden = [sys.executable, "-c", codigo]
    salida = subprocess.run(orden, capture_output=True, text=True, check=True)  # noqa: S603 - código fijo
    assert "Falta libpulse" in salida.stdout
