"""Tests del cliente de sesiones de audio de Windows, con sesiones falsas en lugar de `pycaw`."""

import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from vn_audiolibro.procesos import Proceso
from vn_audiolibro.voz.coreaudio import ClienteCoreAudio, Sesion, _SesionPycaw, a_amplitud, a_escala_pulse
from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.reproductor import NOMBRE_CLIENTE
from vn_audiolibro.voz.volumen import AtenuadorJuego, Juego, Seleccion

PROCESOS = {
    100: Proceso(100, 4, "Juego.exe"),
    200: Proceso(200, 4, "firefox.exe"),
    os.getpid(): Proceso(os.getpid(), 4, "python.exe"),
}


@dataclass
class SesionFalsa:
    identificador: str
    pid: int
    nombre: str = ""
    amplitud: float = 1.0
    hilos: set[str] = field(default_factory=set)

    def volumen(self) -> float:
        self.hilos.add(threading.current_thread().name)
        return self.amplitud

    def poner_volumen(self, volumen: float) -> None:
        self.hilos.add(threading.current_thread().name)
        self.amplitud = volumen


def cliente(sesiones: list[SesionFalsa]) -> ClienteCoreAudio:
    def listar() -> list[Sesion]:
        return list(sesiones)

    return ClienteCoreAudio(listar, lambda: PROCESOS, iniciar_hilo=lambda: None)


def test_convierte_entre_amplitud_y_escala_de_pulseaudio() -> None:
    assert a_escala_pulse(0.343) == pytest.approx(0.7)
    assert a_amplitud((0.7,)) == pytest.approx(0.343)
    assert a_amplitud((2.0, 0.5)) == 1.0  # Windows no amplifica
    assert a_amplitud(()) == 0.0
    assert a_escala_pulse(-0.1) == 0.0


def test_cada_sesion_es_un_flujo_con_su_ejecutable() -> None:
    sesiones = [
        SesionFalsa("juego", 100, amplitud=0.125),
        SesionFalsa("firefox", 200, nombre="Firefox"),
        SesionFalsa("sistema", 0, nombre="@%SystemRoot%\\System32\\AudioSrv.Dll"),
        SesionFalsa("voz", os.getpid()),
        SesionFalsa("desaparecido", 999),
    ]
    flujos = cliente(sesiones).flujos()

    assert [(f.indice, f.aplicacion, f.binario, f.pid) for f in flujos] == [
        (0, "Juego.exe", "Juego.exe", 100),
        (1, "Firefox", "firefox.exe", 200),
        (2, "@%SystemRoot%\\System32\\AudioSrv.Dll", "", None),
        (3, NOMBRE_CLIENTE, "python.exe", os.getpid()),
        (4, "", "", 999),
    ]
    assert flujos[0].volumen == pytest.approx((0.5,))


def test_los_indices_se_mantienen_entre_listados() -> None:
    sesiones = [SesionFalsa("a", 100), SesionFalsa("b", 200)]
    audio = cliente(sesiones)
    assert [f.indice for f in audio.flujos()] == [0, 1]

    sesiones.pop(0)
    sesiones.append(SesionFalsa("c", 100))
    assert [f.indice for f in audio.flujos()] == [1, 2]


def test_poner_volumen_en_una_sesion_que_ya_no_esta_no_hace_nada() -> None:
    sesiones = [SesionFalsa("a", 100)]
    audio = cliente(sesiones)
    audio.flujos()
    audio.poner_volumen(0, (0.5,))
    audio.poner_volumen(7, (0.5,))
    assert sesiones[0].amplitud == pytest.approx(0.125)


def test_todas_las_llamadas_van_por_el_mismo_hilo() -> None:
    sesion = SesionFalsa("a", 100)
    audio = cliente([sesion])
    audio.flujos()
    otro = threading.Thread(target=audio.poner_volumen, args=(0, (0.5,)))
    otro.start()
    otro.join()
    audio.cerrar()
    assert len(sesion.hilos) == 1
    assert next(iter(sesion.hilos)).startswith("coreaudio")


def test_si_no_hay_audio_avisa() -> None:
    def sin_dispositivo() -> list[Sesion]:
        raise OSError("no hay dispositivo de salida")

    with pytest.raises(VozFallidaError, match="audio de Windows: OSError: no hay dispositivo") as error:
        ClienteCoreAudio(sin_dispositivo, lambda: PROCESOS, iniciar_hilo=lambda: None)
    # Solo queda el error con el mensaje, sin el original ni su traceback.
    assert isinstance(error.value.__context__, VozFallidaError)
    assert error.value.__context__.__context__ is None


def test_los_errores_no_sacan_objetos_com_del_hilo() -> None:
    """El traceback del error original, con sus objetos COM, no llega al hilo que llama."""
    sesiones: list[SesionFalsa] = []
    audio = cliente(sesiones)
    sesiones.append(SesionFalsa("rota", 100))
    del sesiones[0].pid  # leer el PID falla, como si la sesión hubiese desaparecido

    with pytest.raises(VozFallidaError, match="AttributeError") as error:
        audio.flujos()
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    audio.cerrar()


def test_el_atenuador_baja_el_juego_y_no_la_voz(tmp_path: Path) -> None:
    sesiones = [SesionFalsa("juego", 100), SesionFalsa("voz", os.getpid()), SesionFalsa("firefox", 200)]
    audio = cliente(sesiones)
    juego = Juego(frozenset({100}), frozenset({"juego.exe"}))
    atenuador = AtenuadorJuego(
        audio, Seleccion(juego, nivel_juego=0.7), estado=tmp_path / "estado.json", intervalo_s=60
    )

    atenuador.bajar()
    assert [s.amplitud for s in sesiones] == pytest.approx([0.343, 1.0, 1.0])
    atenuador.cerrar()
    assert [s.amplitud for s in sesiones] == pytest.approx([1.0, 1.0, 1.0])
    audio.cerrar()


@pytest.mark.skipif(sys.platform != "win32", reason="Core Audio solo existe en Windows")
def test_sesiones_reales_en_windows() -> None:
    try:
        audio = ClienteCoreAudio()
    except VozFallidaError as error:
        pytest.skip(f"Sin dispositivo de audio: {error}")
    try:
        flujos = audio.flujos()
        assert all(0 <= v <= 1 for f in flujos for v in f.volumen)
    finally:
        audio.cerrar()


def test_adaptador_de_pycaw() -> None:
    volumen = SimpleNamespace(GetMasterVolume=lambda: 0.25)
    sesion = SimpleNamespace(
        InstanceIdentifier="id|1", ProcessId=100, DisplayName=None, SimpleAudioVolume=volumen
    )
    adaptada = _SesionPycaw(sesion)
    assert (adaptada.identificador, adaptada.pid, adaptada.nombre, adaptada.volumen()) == (
        "id|1",
        100,
        "",
        0.25,
    )
    sesion.DisplayName = "@%SystemRoot%\\System32\\AudioSrv.Dll,-202"
    assert adaptada.nombre == ""
    sesion.DisplayName = "Mi juego"
    assert adaptada.nombre == "Mi juego"
