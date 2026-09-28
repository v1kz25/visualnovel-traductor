"""Detección de texto nuevo y estable a partir de capturas sucesivas de la zona de texto."""

from dataclasses import dataclass

import numpy as np

from vn_audiolibro.captura.mascara import TEXTO_CLARO, ColorTexto
from vn_audiolibro.captura.modelos import Imagen, Mascara, ZonaEstable


@dataclass(frozen=True)
class AjustesDetector:
    """Parámetros del detector."""

    estabilidad_s: float = 0.3
    """Tiempo sin cambios necesario para dar el texto por terminado (efecto máquina de escribir)."""
    min_pixeles: int = 20
    """Mínimo de píxeles distintos para considerar que la máscara ha cambiado."""
    proporcion_min: float = 0.0005
    """Mínimo de píxeles distintos, relativo al tamaño de la zona."""
    margen_filas: int = 6
    """Filas extra por encima del texto nuevo, para no cortar los caracteres."""
    proporcion_desaparecida: float = 0.2
    """Parte del texto anterior que tiene que desaparecer para considerar la pantalla nueva.

    Por debajo se atribuye a elementos pequeños que desaparecen al avanzar, como el indicador
    de "siguiente" al final de la línea.
    """


class DetectorTexto:
    """Recibe capturas de la zona de texto y avisa cuando hay texto nuevo y estable.

    Compara máscaras de texto, no píxeles, para ignorar fondos animados. Distingue dos casos:
    - Pantalla nueva (ADV, o NVL tras limpiar): parte del texto anterior desaparece -> zona completa.
    - Filas añadidas (NVL): solo cambia texto nuevo -> se emite desde la primera fila cambiada.
    """

    def __init__(
        self,
        ajustes: AjustesDetector | None = None,
        color: ColorTexto = TEXTO_CLARO,
    ) -> None:
        self._ajustes = ajustes or AjustesDetector()
        self._color = color
        self._anterior: Mascara | None = None
        self._emitida: Mascara | None = None
        self._instante_cambio = 0.0

    def procesar(self, imagen: Imagen, instante: float) -> ZonaEstable | None:
        """Procesa una captura y devuelve el texto nuevo si acaba de estabilizarse."""
        actual = self._color.estricta(imagen)
        if self._anterior is None or self._anterior.shape != actual.shape:
            self._reiniciar(actual, instante)
            return None
        if self._distintas(actual, self._anterior):
            self._anterior = actual
            self._instante_cambio = instante
            return None
        if instante - self._instante_cambio < self._ajustes.estabilidad_s:
            return None
        return self._emitir_si_nuevo(imagen, actual, instante)

    def _reiniciar(self, mascara: Mascara, instante: float) -> None:
        self._anterior = mascara
        self._emitida = np.zeros_like(mascara)
        self._instante_cambio = instante

    def _emitir_si_nuevo(self, imagen: Imagen, actual: Mascara, instante: float) -> ZonaEstable | None:
        emitida = self._emitida if self._emitida is not None else np.zeros_like(actual)
        if not self._distintas(actual, emitida):
            return None
        self._emitida = actual
        if not actual.any():
            return None  # La zona se ha vaciado: no hay nada que leer.
        if self._pantalla_nueva(emitida, actual, self._color.laxa(imagen)):
            return ZonaEstable(imagen=imagen, y_inicio=0, completa=True, instante=instante)
        # Solo cuentan las filas con píxeles añadidos: las que solo pierden algo (el indicador
        # de "siguiente" que desaparece al final de la línea anterior) no son texto nuevo.
        filas_nuevas = np.flatnonzero((actual & ~emitida).any(axis=1))
        if not filas_nuevas.size:
            return None
        y_inicio = max(0, int(filas_nuevas[0]) - self._ajustes.margen_filas)
        return ZonaEstable(
            imagen=imagen[y_inicio:], y_inicio=y_inicio, completa=y_inicio == 0, instante=instante
        )

    def _pantalla_nueva(self, emitida: Mascara, actual: Mascara, presente: Mascara) -> bool:
        """True si el texto anterior ya no está (o apenas queda nada de él).

        `presente` es la máscara laxa: el texto anterior atenuado sigue contando como presente.
        """
        texto_anterior = int(emitida.sum())
        desaparecido = int((emitida & ~presente).sum())
        conservado = texto_anterior - desaparecido
        umbral = max(self._ajustes.min_pixeles, self._ajustes.proporcion_desaparecida * texto_anterior)
        return desaparecido >= umbral or not self._supera_umbral(conservado, actual.size)

    def _distintas(self, a: Mascara, b: Mascara) -> bool:
        return self._supera_umbral(int(np.count_nonzero(a ^ b)), a.size)

    def _supera_umbral(self, pixeles: int, total: int) -> bool:
        return pixeles >= max(self._ajustes.min_pixeles, self._ajustes.proporcion_min * total)
