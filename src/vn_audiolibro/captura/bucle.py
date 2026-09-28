"""Bucle que captura la zona de texto de una ventana y avisa del texto nuevo."""

import contextlib
import threading
import time
from collections.abc import Callable

from vn_audiolibro.captura.capturador import Capturador, FuenteGeometria
from vn_audiolibro.captura.detector import DetectorTexto
from vn_audiolibro.captura.modelos import VentanaMinimizadaError, ZonaEstable, ZonaRelativa


class BucleCaptura:
    """Captura periódicamente la zona de texto y entrega cada `ZonaEstable` a un callback.

    Se ejecuta en un hilo propio. El tamaño de la ventana se relee en cada vuelta: la zona es
    proporcional, así que sigue valiendo si el usuario la mueve o la redimensiona.
    """

    def __init__(
        self,
        id_ventana: int,
        zona: ZonaRelativa,
        al_detectar: Callable[[ZonaEstable], None],
        ventanas: FuenteGeometria,
        capturador: Capturador,
        detector: DetectorTexto | None = None,
        intervalo_s: float = 0.1,
    ) -> None:
        self._id_ventana = id_ventana
        self._zona = zona
        self._al_detectar = al_detectar
        self._ventanas = ventanas
        self._capturador = capturador
        self._detector = detector or DetectorTexto()
        self._intervalo_s = intervalo_s
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    def paso(self, instante: float | None = None) -> ZonaEstable | None:
        """Hace una captura y la pasa por el detector. Útil para tests y depuración."""
        ventana = self._ventanas.geometria(self._id_ventana)
        zona = self._zona.en_pixeles(ventana.ancho, ventana.alto)
        imagen = self._capturador.capturar(self._id_ventana, zona)
        evento = self._detector.procesar(imagen, time.monotonic() if instante is None else instante)
        if evento is not None:
            self._al_detectar(evento)
        return evento

    def iniciar(self) -> None:
        """Arranca el hilo de captura."""
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._ejecutar, name="captura", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        """Para el hilo y espera a que termine."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2)

    def _ejecutar(self) -> None:
        while not self._parar.is_set():
            inicio = time.monotonic()
            # Minimizada: se sigue cuando la restauren, con el detector como estaba.
            with contextlib.suppress(VentanaMinimizadaError):
                self.paso(inicio)
            self._parar.wait(max(0.0, self._intervalo_s - (time.monotonic() - inicio)))
