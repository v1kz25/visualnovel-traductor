"""Tests del puente entre la sesión de juego y la interfaz."""

import threading

from pytestqt.qtbot import QtBot

from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego
from vn_audiolibro.ui.puente import PuenteSesion

from .conftest import ESPERA_MS, Fabrica

PERFIL = Perfil("Juego", "juego")


def test_arranca_en_segundo_plano_y_reenvia_los_avisos(qtbot: QtBot) -> None:
    puente = PuenteSesion(Fabrica())
    estados: list[str] = []
    lineas: list[LineaJuego] = []
    puente.estado.connect(estados.append)
    puente.linea.connect(lineas.append)

    with qtbot.waitSignal(puente.iniciada, timeout=ESPERA_MS):
        puente.iniciar(PERFIL)

    assert puente.jugando
    assert estados == ["Arrancando el traductor…"]
    assert [linea.traduccion for linea in lineas] == ["uno"]


def test_iniciar_dos_veces_no_crea_otra_sesion(qtbot: QtBot) -> None:
    fabrica = Fabrica()
    puente = PuenteSesion(fabrica)
    with qtbot.waitSignal(puente.iniciada, timeout=ESPERA_MS):
        puente.iniciar(PERFIL)
    puente.iniciar(PERFIL)
    assert len(fabrica.sesiones) == 1


def test_si_no_arranca_avisa_del_error_y_termina(qtbot: QtBot) -> None:
    puente = PuenteSesion(Fabrica(fallo="No hay ninguna ventana"))
    errores: list[str] = []
    puente.error.connect(errores.append)

    with qtbot.waitSignal(puente.terminada, timeout=ESPERA_MS):
        puente.iniciar(PERFIL)

    assert errores == ["No hay ninguna ventana"]
    assert not puente.jugando


def test_controles_y_parada(qtbot: QtBot) -> None:
    fabrica = Fabrica()
    puente = PuenteSesion(fabrica)
    puente.alternar_pausa()  # sin partida: no hace nada
    puente.repetir()
    puente.saltar()
    with qtbot.waitSignal(puente.iniciada, timeout=ESPERA_MS):
        puente.iniciar(PERFIL)

    puente.alternar_pausa()
    assert puente.pausado
    puente.alternar_pausa()
    puente.repetir()
    puente.saltar()
    with qtbot.waitSignal(puente.terminada, timeout=ESPERA_MS):
        puente.detener()

    sesion = fabrica.sesiones[0]
    assert sesion.control.acciones == ["pausar", "reanudar", "repetir", "saltar"]
    assert sesion.detenida.is_set()
    assert not puente.jugando
    assert not puente.pausado
    puente.detener()  # ya parada: no hace nada


def test_el_silencio_se_aplica_a_la_partida_y_a_las_siguientes(qtbot: QtBot) -> None:
    fabrica = Fabrica()
    puente = PuenteSesion(fabrica)
    puente.silenciar(True)  # sin partida: se recuerda
    assert puente.silenciado

    with qtbot.waitSignal(puente.iniciada, timeout=ESPERA_MS):
        puente.iniciar(PERFIL)
    puente.silenciar(False)
    puente.silenciar(True)
    with qtbot.waitSignal(puente.terminada, timeout=ESPERA_MS):
        puente.detener()
    with qtbot.waitSignal(puente.iniciada, timeout=ESPERA_MS):
        puente.iniciar(PERFIL)

    primera, segunda = fabrica.sesiones
    assert primera.control.acciones == ["silenciar", "quitar_silencio", "silenciar"]
    assert segunda.control.acciones == ["silenciar"]


def test_detener_mientras_arranca_no_bloquea_y_la_para_al_terminar(qtbot: QtBot) -> None:
    puerta = threading.Event()
    fabrica = Fabrica(puerta=puerta)
    puente = PuenteSesion(fabrica)
    iniciadas: list[bool] = []
    puente.iniciada.connect(lambda: iniciadas.append(True))

    puente.iniciar(PERFIL)
    sesion = fabrica.sesiones[0]
    assert sesion.arrancando.wait(ESPERA_MS / 1000)
    puente.detener()  # vuelve en el acto aunque siga arrancando
    assert not puente.jugando
    with qtbot.waitSignal(puente.terminada, timeout=ESPERA_MS):
        puerta.set()

    assert sesion.detenida.is_set()
    assert iniciadas == []


def test_un_error_al_parar_se_avisa(qtbot: QtBot) -> None:
    puente = PuenteSesion(Fabrica(fallo_al_parar="llama-server no responde"))
    errores: list[str] = []
    puente.error.connect(errores.append)
    with qtbot.waitSignal(puente.iniciada, timeout=ESPERA_MS):
        puente.iniciar(PERFIL)
    with qtbot.waitSignal(puente.terminada, timeout=ESPERA_MS):
        puente.detener()
    assert errores == ["Error al parar: llama-server no responde"]
