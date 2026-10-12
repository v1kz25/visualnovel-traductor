"""Tests de la interfaz: Qt sin pantalla y una sesión de juego falsa."""

import os
import threading
from collections.abc import Callable, Mapping

# Antes de que pytest-qt cree la aplicación: sin ventanas reales, también en la CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from vn_audiolibro import plataforma
from vn_audiolibro.atajos.modelos import Accion, Atajo
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego

ESPERA_MS = 5000


class ControlFalso:
    def __init__(self) -> None:
        self.pausado = False
        self.silenciado = False
        self.acciones: list[str] = []

    def pausar(self) -> None:
        self.pausado = True
        self.acciones.append("pausar")

    def reanudar(self) -> None:
        self.pausado = False
        self.acciones.append("reanudar")

    def silenciar(self) -> None:
        self.silenciado = True
        self.acciones.append("silenciar")

    def quitar_silencio(self) -> None:
        self.silenciado = False
        self.acciones.append("quitar_silencio")

    def repetir(self) -> None:
        self.acciones.append("repetir")

    def saltar(self) -> None:
        self.acciones.append("saltar")


class SesionFalsa:
    """Al arrancar avisa de su estado, del subtítulo y de una línea.

    Se puede retener, hacer fallar o fallar al parar.
    """

    def __init__(
        self,
        perfil: Perfil,
        al_linea: Callable[[LineaJuego], None],
        al_error: Callable[[str], None],
        al_estado: Callable[[str], None],
        al_subtitulo: Callable[[str], None],
        puerta: threading.Event | None = None,
        fallo: str | None = None,
        fallo_al_parar: str | None = None,
    ) -> None:
        self.perfil = perfil
        self._al_linea = al_linea
        self._al_estado = al_estado
        self._al_subtitulo = al_subtitulo
        self._puerta = puerta
        self._fallo = fallo
        self._fallo_al_parar = fallo_al_parar
        self.control = ControlFalso()
        self.arrancando = threading.Event()
        self.detenida = threading.Event()

    def iniciar(self) -> ControlFalso:
        self.arrancando.set()
        self._al_estado("Arrancando el traductor…")
        if self._puerta is not None:
            assert self._puerta.wait(ESPERA_MS / 1000)
        if self._fallo:
            raise RuntimeError(self._fallo)
        self._al_subtitulo("uno")
        self._al_linea(LineaJuego("一", "uno", desde_cache=False, leida=True))
        return self.control

    def detener(self) -> None:
        self.detenida.set()
        if self._fallo_al_parar:
            raise RuntimeError(self._fallo_al_parar)


class Fabrica:
    """Crea sesiones falsas con las opciones indicadas y recuerda la última."""

    def __init__(self, **opciones: object) -> None:
        self.opciones = opciones
        self.sesiones: list[SesionFalsa] = []

    def __call__(
        self,
        perfil: Perfil,
        al_linea: Callable[[LineaJuego], None],
        al_error: Callable[[str], None],
        al_estado: Callable[[str], None],
        al_subtitulo: Callable[[str], None],
    ) -> SesionFalsa:
        sesion = SesionFalsa(perfil, al_linea, al_error, al_estado, al_subtitulo, **self.opciones)  # type: ignore[arg-type]
        self.sesiones.append(sesion)
        return sesion


class EscuchaFalsa:
    """Atajos globales de pega: apunta lo que se registra y deja simular pulsaciones."""

    def __init__(self, fallidos: list[Accion] | None = None, fallo: Exception | None = None) -> None:
        self.fallidos = fallidos or []
        self.fallo = fallo
        self.atajos: dict[Accion, Atajo] | None = None
        self.al_pulsar: Callable[[Accion], None] | None = None
        self.detenida = False

    def iniciar(self, atajos: Mapping[Accion, Atajo], al_pulsar: Callable[[Accion], None]) -> list[Accion]:
        if self.fallo is not None:
            raise self.fallo
        self.atajos, self.al_pulsar, self.detenida = dict(atajos), al_pulsar, False
        return self.fallidos

    def pulsar(self, accion: Accion) -> None:
        """Como el hilo de los atajos: llama desde otro hilo."""
        assert self.al_pulsar is not None
        hilo = threading.Thread(target=self.al_pulsar, args=(accion,))
        hilo.start()
        hilo.join()

    def detener(self) -> None:
        self.detenida = True


@pytest.fixture(autouse=True)
def escucha(monkeypatch: pytest.MonkeyPatch) -> EscuchaFalsa:
    """Ningún test de la interfaz coge atajos de teclado reales del escritorio."""
    falsa = EscuchaFalsa()
    monkeypatch.setattr(plataforma, "escucha_atajos", lambda: falsa)
    return falsa
