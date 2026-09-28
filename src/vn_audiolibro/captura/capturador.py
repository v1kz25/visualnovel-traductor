"""Captura de una zona de la ventana del juego."""

from typing import Protocol

import mss
import numpy as np

from vn_audiolibro.captura.modelos import Imagen, Rectangulo, Ventana


class FuenteGeometria(Protocol):
    """Devuelve la geometría actual de una ventana (para seguirla si se mueve)."""

    def geometria(self, id_ventana: int) -> Rectangulo:
        """Posición absoluta y tamaño de la ventana."""
        ...


class Ventanas(FuenteGeometria, Protocol):
    """Las ventanas del escritorio. Cada sistema (X11, Windows) lo implementa."""

    def listar(self) -> list[Ventana]:
        """Ventanas visibles con título."""
        ...

    def buscar(self, texto: str) -> Ventana:
        """Primera ventana cuyo título contiene `texto`, sin contar las de esta app.

        Lanza `VentanaNoEncontradaError` si no hay ninguna.
        """
        ...


class Capturador(Protocol):
    """Algo que devuelve la imagen actual de una zona de una ventana."""

    def capturar(self, id_ventana: int, zona: Rectangulo) -> Imagen:
        """Devuelve la zona (en píxeles relativos a la ventana) en RGB con forma (alto, ancho, 3)."""
        ...


class CapturadorMss:
    """Captura lo que se ve en pantalla en la posición de la ventana.

    Si hay otra ventana encima, se captura esa otra: sirve como alternativa cuando no hay
    compositor.
    """

    def __init__(self, ventanas: FuenteGeometria) -> None:
        self._ventanas = ventanas
        self._sct = mss.MSS()

    def capturar(self, id_ventana: int, zona: Rectangulo) -> Imagen:
        """Captura la zona de la ventana tal como se ve en pantalla."""
        ventana = self._ventanas.geometria(id_ventana)
        region = {
            "left": ventana.x + zona.x,
            "top": ventana.y + zona.y,
            "width": zona.ancho,
            "height": zona.alto,
        }
        bgra = np.asarray(self._sct.grab(region), dtype=np.uint8)
        rgb: Imagen = np.ascontiguousarray(bgra[:, :, 2::-1])
        return rgb

    def cerrar(self) -> None:
        """Libera la conexión con el servidor gráfico."""
        self._sct.close()
