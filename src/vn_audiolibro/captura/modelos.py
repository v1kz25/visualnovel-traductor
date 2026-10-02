"""Tipos básicos de la captura: ventanas, zonas y eventos."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from vn_audiolibro.textos import _

Imagen = npt.NDArray[np.uint8]
"""Imagen RGB con forma (alto, ancho, 3)."""

Gris = npt.NDArray[np.uint8]
"""Imagen en escala de grises con forma (alto, ancho)."""

Mascara = npt.NDArray[np.bool_]
"""Máscara booleana con forma (alto, ancho): True donde hay texto."""


@dataclass(frozen=True)
class Rectangulo:
    """Rectángulo en píxeles."""

    x: int
    y: int
    ancho: int
    alto: int

    def __post_init__(self) -> None:
        if self.ancho <= 0 or self.alto <= 0:
            raise ValueError(f"Rectángulo vacío: {self.ancho}x{self.alto}")


@dataclass(frozen=True)
class ZonaRelativa:
    """Zona de texto en proporciones de la ventana (0 a 1), para que valga con cualquier tamaño."""

    x: float
    y: float
    ancho: float
    alto: float

    def __post_init__(self) -> None:
        dentro = 0 <= self.x < 1 and 0 <= self.y < 1 and 0 < self.ancho <= 1 and 0 < self.alto <= 1
        if not dentro or self.x + self.ancho > 1 + 1e-9 or self.y + self.alto > 1 + 1e-9:
            raise ValueError(f"Zona fuera de la ventana: {self}")

    @classmethod
    def desde_pixeles(cls, zona: Rectangulo, ancho_ventana: int, alto_ventana: int) -> "ZonaRelativa":
        """Convierte una zona en píxeles de una ventana de tamaño conocido."""
        x = min(max(zona.x, 0), ancho_ventana - 1)
        y = min(max(zona.y, 0), alto_ventana - 1)
        ancho = min(zona.ancho, ancho_ventana - x)
        alto = min(zona.alto, alto_ventana - y)
        return cls(x / ancho_ventana, y / alto_ventana, ancho / ancho_ventana, alto / alto_ventana)

    def en_pixeles(self, ancho_ventana: int, alto_ventana: int) -> Rectangulo:
        """Zona en píxeles relativos a una ventana del tamaño indicado."""
        x = min(round(self.x * ancho_ventana), ancho_ventana - 1)
        y = min(round(self.y * alto_ventana), alto_ventana - 1)
        ancho = max(1, min(round(self.ancho * ancho_ventana), ancho_ventana - x))
        alto = max(1, min(round(self.alto * alto_ventana), alto_ventana - y))
        return Rectangulo(x=x, y=y, ancho=ancho, alto=alto)


TODA_LA_VENTANA = ZonaRelativa(0.0, 0.0, 1.0, 1.0)


class VentanaNoEncontradaError(LookupError):
    """La ventana ya no existe o no se encuentra."""


class VentanaMinimizadaError(Exception):
    """La ventana está minimizada: no tiene contenido que capturar hasta que se restaure."""


def buscar_por_titulo(ventanas: list["Ventana"], texto: str, excluir_pids: frozenset[int]) -> "Ventana":
    """Primera ventana cuyo título contiene `texto` (sin distinguir mayúsculas).

    Ignora las ventanas de los procesos de `excluir_pids`: la terminal desde la que se lanza la
    app suele llevar el comando (y por tanto el texto buscado) en el título.
    """
    buscado = texto.casefold()
    for ventana in ventanas:
        if ventana.pid not in excluir_pids and buscado in ventana.titulo.casefold():
            return ventana
    raise VentanaNoEncontradaError(_("No hay ninguna ventana con «{texto}» en el título").format(texto=texto))


@dataclass(frozen=True)
class Ventana:
    """Ventana de nivel superior del escritorio."""

    id: int
    titulo: str
    pid: int | None
    geometria: Rectangulo
    """Posición absoluta en pantalla y tamaño del área de contenido."""


@dataclass(frozen=True)
class ZonaEstable:
    """Texto nuevo que ya ha terminado de dibujarse y está listo para el OCR."""

    imagen: Imagen
    """Recorte de la zona de texto desde `y_inicio` hasta el final."""
    y_inicio: int
    """Primera fila de la zona con texto nuevo (0 si la zona es completamente nueva)."""
    completa: bool
    """True si el texto anterior desapareció (pantalla nueva); False si se añadieron filas (NVL)."""
    instante: float
    """Momento de la captura, en segundos monotónicos."""
    nombre: Imagen | None = None
    """Recorte de la zona del nombre del personaje en ese mismo momento, si el juego la tiene."""
