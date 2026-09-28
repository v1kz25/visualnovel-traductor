"""Bajada del volumen del juego mientras habla la voz, con PulseAudio o PipeWire (pipewire-pulse).

El juego se reconoce por el PID de su ventana y sus procesos hijos y, si no, por el nombre del
ejecutable: con Wine, el flujo de audio lo abre el mismo proceso que la ventana (`Juego.exe`).

PulseAudio recuerda el volumen de cada aplicación, así que si la app se cerrase con el juego
bajado, el juego seguiría bajado en la siguiente partida. Para evitarlo, el volumen original se
apunta en un fichero de estado mientras el juego está bajado y se recupera al volver a arrancar.
"""

import atexit
import json
import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

try:
    import pulsectl
except (ImportError, OSError):  # falta libpulse: la app funciona igual, pero sin bajar el volumen
    pulsectl = None

from vn_audiolibro.procesos import descendientes, listar_procesos
from vn_audiolibro.rutas import directorio_estado
from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.reproductor import NOMBRE_CLIENTE

_registro = logging.getLogger(__name__)

NIVEL_POR_DEFECTO = 0.7
"""Volumen que se deja al juego mientras habla la voz, como fracción del suyo.

Va en la escala de PulseAudio, que es cúbica: 0,7 son unos -9 dB (se oyen el juego y la voz) y
0,3 serían -31 dB (el juego casi no se oye). 0 silencia.
"""

LARGO_COMM = 15
"""Linux recorta el nombre de los procesos (`/proc/<pid>/comm`) a 15 caracteres."""

NOMBRES_GENERICOS = frozenset(
    {"wine", "wine64", "wine-preloader", "wine64-preloader", "wineserver", "python3", "sh", "bash"}
)
"""Nombres que no identifican a un juego: compararlos bajaría otras aplicaciones."""

Volumen = tuple[float, ...]
"""Volumen de cada canal, de 0 a 1 (puede pasar de 1 si se ha amplificado)."""


@dataclass(frozen=True)
class Flujo:
    """Flujo de audio de una aplicación (sink input)."""

    indice: int
    aplicacion: str
    binario: str
    pid: int | None
    volumen: Volumen

    @property
    def identidad(self) -> str:
        """Identifica la aplicación entre ejecuciones (el índice y el PID cambian)."""
        return f"{self.binario}|{self.aplicacion}"


class ClienteAudio(Protocol):
    """Lo que el atenuador necesita del servidor de sonido: listar los flujos y cambiar su volumen."""

    def flujos(self) -> list[Flujo]: ...

    def poner_volumen(self, indice: int, volumen: Volumen) -> None:
        """Cambia el volumen de un flujo. Si el flujo ya no existe, no hace nada."""
        ...

    def cerrar(self) -> None:
        """Libera la conexión con el servidor de sonido."""
        ...


class ClientePulse:
    """Cliente de PulseAudio (vale también para PipeWire con pipewire-pulse)."""

    def __init__(self) -> None:
        if pulsectl is None:
            raise VozFallidaError("Falta libpulse: no se puede controlar el volumen")
        try:
            self._pulse = pulsectl.Pulse(f"{NOMBRE_CLIENTE}-volumen")
        except pulsectl.PulseError as error:
            raise VozFallidaError(f"No se pudo conectar con el servidor de sonido: {error}") from error
        self._cerrojo = threading.Lock()

    def flujos(self) -> list[Flujo]:
        with self._cerrojo:
            entradas = self._pulse.sink_input_list()
        return [_flujo(entrada) for entrada in entradas]

    def poner_volumen(self, indice: int, volumen: Volumen) -> None:
        try:
            with self._cerrojo:
                self._pulse.sink_input_volume_set(indice, pulsectl.PulseVolumeInfo(list(volumen)))
        except pulsectl.PulseOperationFailed:
            _registro.debug("El flujo %d ya no existe", indice)

    def cerrar(self) -> None:
        with self._cerrojo:
            self._pulse.close()


def _flujo(entrada: "pulsectl.PulseSinkInputInfo") -> Flujo:  # entre comillas: pulsectl puede faltar
    propiedades: dict[str, str] = entrada.proplist
    pid = propiedades.get("application.process.id", "")
    return Flujo(
        indice=int(entrada.index),
        aplicacion=propiedades.get("application.name", ""),
        binario=propiedades.get("application.process.binary", ""),
        pid=int(pid) if pid.isdigit() else None,
        volumen=tuple(float(v) for v in entrada.volume.values),
    )


def _clave_nombre(nombre: str) -> str:
    return nombre[:LARGO_COMM].casefold()


@dataclass(frozen=True)
class Juego:
    """Procesos del juego, para reconocer sus flujos de audio."""

    pids: frozenset[int]
    nombres: frozenset[str]
    """Nombres de los procesos, recortados como en `/proc` y en minúsculas."""

    def es_suyo(self, flujo: Flujo) -> bool:
        """Si el flujo es del juego. Los de esta app nunca lo son."""
        if flujo.aplicacion == NOMBRE_CLIENTE:
            return False
        if flujo.pid is not None and flujo.pid in self.pids:
            return True
        candidatos = {_clave_nombre(flujo.binario), _clave_nombre(flujo.aplicacion)} - {""}
        return bool(candidatos & self.nombres)


Criterio = Callable[[Flujo], float | None]
"""Nivel al que se baja cada flujo mientras habla la voz, o None para no tocarlo."""


def _comprobar_nivel(nivel: float) -> None:
    if not 0 <= nivel <= 1:
        raise ValueError(f"El nivel tiene que estar entre 0 y 1: {nivel}")


@dataclass(frozen=True)
class Seleccion:
    """Qué flujos se bajan mientras habla la voz y hasta qué nivel.

    El juego se baja a `nivel_juego`. Las demás aplicaciones solo se tocan si tienen su propio
    nivel en `otras` (0 las silencia mientras habla la voz), y las de `excluir` nunca, aunque
    sean del juego. Las aplicaciones se nombran como las anuncia el servidor de sonido
    (`Firefox`, `Spotify`…) o por su ejecutable (`firefox`), sin distinguir mayúsculas.
    """

    juego: Juego | None = None
    nivel_juego: float = NIVEL_POR_DEFECTO
    otras: tuple[tuple[str, float], ...] = ()
    excluir: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for nivel in (self.nivel_juego, *(nivel for _, nivel in self.otras)):
            _comprobar_nivel(nivel)

    @classmethod
    def de_nombres(
        cls,
        juego: Juego | None = None,
        nivel_juego: float = NIVEL_POR_DEFECTO,
        otras: Mapping[str, float] | None = None,
        excluir: Iterable[str] = (),
    ) -> "Seleccion":
        """Selección con los nombres normalizados."""
        normalizadas = tuple((nombre.casefold(), nivel) for nombre, nivel in (otras or {}).items())
        return cls(juego, nivel_juego, normalizadas, frozenset(n.casefold() for n in excluir))

    def __call__(self, flujo: Flujo) -> float | None:
        if flujo.aplicacion == NOMBRE_CLIENTE:
            return None
        nombres = {flujo.aplicacion.casefold(), flujo.binario.casefold()} - {""}
        if nombres & self.excluir:
            return None
        for nombre, nivel in self.otras:
            if nombre in nombres:
                return nivel
        if self.juego is not None and self.juego.es_suyo(flujo):
            return self.nivel_juego
        return None


def juego_de_pid(pid: int, proc: Path = Path("/proc")) -> Juego:
    """El proceso de la ventana del juego y todos sus descendientes."""
    procesos = listar_procesos(proc)
    pids = descendientes(pid, procesos)
    propios = {_clave_nombre(procesos[p].nombre) for p in pids if p in procesos}
    genericos = {_clave_nombre(nombre) for nombre in NOMBRES_GENERICOS}
    return Juego(pids, frozenset(propios - genericos))


def hay_control_de_volumen() -> bool:
    """Si está libpulse, que hace falta para bajar el volumen del juego."""
    return pulsectl is not None


def fichero_estado() -> Path:
    """Donde se apunta el volumen original del juego mientras está bajado."""
    return directorio_estado() / "volumen-juego.json"


class AtenuadorJuego:
    """Baja los flujos que indica el criterio mientras habla la voz y luego los devuelve a su volumen.

    El criterio da el nivel de cada flujo (normalmente una `Seleccion`). Mientras está bajado,
    revisa los flujos cada `intervalo_s`: muchos juegos abren un flujo nuevo para cada voz o
    efecto, y también hay que bajarlos.
    """

    def __init__(
        self,
        cliente: ClienteAudio,
        criterio: Criterio,
        estado: Path | None = None,
        intervalo_s: float = 0.25,
    ) -> None:
        self._cliente = cliente
        self._criterio = criterio
        self._estado = estado or fichero_estado()
        self._cerrojo = threading.RLock()
        self._bajado = False
        self._originales: dict[int, Flujo] = {}
        self._pendientes = self._leer_estado()
        self._cerrado = threading.Event()
        with self._cerrojo:
            self._recuperar()
        self._hilo = threading.Thread(target=self._vigilar, args=(intervalo_s,), name="volumen", daemon=True)
        self._hilo.start()
        atexit.register(self.cerrar)

    def bajar(self) -> None:
        with self._cerrojo:
            self._bajado = True
            self._atenuar()

    def restaurar(self) -> None:
        with self._cerrojo:
            self._bajado = False
            if not self._originales:
                return
            for indice, flujo in self._originales.items():
                self._cliente.poner_volumen(indice, flujo.volumen)
            self._originales.clear()
            self._guardar_estado()

    def revisar(self) -> None:
        """Baja los flujos nuevos del juego si la voz está hablando."""
        with self._cerrojo:
            if self._bajado:
                self._atenuar()

    def cerrar(self) -> None:
        """Devuelve el volumen y para la vigilancia."""
        self._cerrado.set()
        self.restaurar()
        atexit.unregister(self.cerrar)

    def _vigilar(self, intervalo_s: float) -> None:
        while not self._cerrado.wait(intervalo_s):
            try:
                self.revisar()
            except Exception:
                _registro.exception("No se pudo revisar el volumen del juego")

    def _atenuar(self) -> None:
        nuevos = False
        for flujo in self._cliente.flujos():
            if flujo.indice in self._originales:
                continue
            nivel = self._criterio(flujo)
            if nivel is None:
                continue
            # Si quedó bajado de una ejecución anterior, su volumen original es el apuntado.
            original = self._pendientes.pop(flujo.identidad, flujo.volumen)
            self._originales[flujo.indice] = Flujo(
                flujo.indice, flujo.aplicacion, flujo.binario, flujo.pid, original
            )
            self._cliente.poner_volumen(flujo.indice, tuple(v * nivel for v in original))
            nuevos = True
        if nuevos:
            self._guardar_estado()

    def _recuperar(self) -> None:
        """Devuelve su volumen a los flujos que quedaron bajados si la app se cerró de golpe."""
        if not self._pendientes:
            return
        for flujo in self._cliente.flujos():
            original = self._pendientes.pop(flujo.identidad, None)
            if original is not None:
                _registro.info("Se recupera el volumen de %s, que quedó bajado", flujo.aplicacion)
                self._cliente.poner_volumen(flujo.indice, original)
        self._guardar_estado()

    def _leer_estado(self) -> dict[str, Volumen]:
        try:
            datos = json.loads(self._estado.read_text(encoding="utf-8"))
            return {str(identidad): tuple(float(v) for v in volumen) for identidad, volumen in datos.items()}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError, AttributeError):
            _registro.warning("Fichero de estado del volumen ilegible: se ignora", exc_info=True)
            return {}

    def _guardar_estado(self) -> None:
        """Apunta los volúmenes originales pendientes de devolver; sin ninguno, borra el fichero."""
        apuntados = dict(self._pendientes)
        apuntados.update({f.identidad: f.volumen for f in self._originales.values()})
        try:
            if not apuntados:
                self._estado.unlink(missing_ok=True)
                return
            self._estado.parent.mkdir(parents=True, exist_ok=True)
            temporal = self._estado.with_name(self._estado.name + ".parcial")
            temporal.write_text(json.dumps(apuntados), encoding="utf-8")
            temporal.replace(self._estado)
        except OSError:
            _registro.warning("No se pudo guardar el estado del volumen", exc_info=True)
