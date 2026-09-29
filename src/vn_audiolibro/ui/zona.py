"""Selector de la zona de texto: una captura de la ventana del juego sobre la que se dibuja un recuadro."""

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from vn_audiolibro.captura.modelos import Imagen, ZonaRelativa
from vn_audiolibro.textos import _

LADO_MIN = 0.01
"""Ancho y alto mínimos de la zona, en proporción de la ventana: evita recuadros de un clic."""


def a_qimage(imagen: Imagen) -> QImage:
    """Imagen RGB de numpy como QImage (copiada: no depende de la memoria de numpy)."""
    alto, ancho = imagen.shape[:2]
    datos = np.ascontiguousarray(imagen[:, :, :3])
    return QImage(datos.data, ancho, alto, 3 * ancho, QImage.Format.Format_RGB888).copy()


class SelectorZona(QWidget):
    """Muestra la captura escalada y deja dibujar la zona con el ratón (pulsar, arrastrar, soltar)."""

    zona_cambiada = Signal(object)
    """La nueva `ZonaRelativa`, o None si se borró."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._imagen: QPixmap | None = None
        self._zona: ZonaRelativa | None = None
        self._inicio: QPointF | None = None
        self._arrastre: QRectF | None = None

    def sizeHint(self) -> QSize:  # noqa: N802 - nombre de Qt
        return QSize(640, 360)

    @property
    def zona(self) -> ZonaRelativa | None:
        return self._zona

    @property
    def hay_imagen(self) -> bool:
        return self._imagen is not None

    def mostrar(self, imagen: Imagen) -> None:
        """Pone una captura nueva de la ventana. La zona se conserva (es proporcional)."""
        self._imagen = QPixmap.fromImage(a_qimage(imagen))
        self.update()

    def poner_zona(self, zona: ZonaRelativa | None) -> None:
        self._zona = zona
        self.update()
        self.zona_cambiada.emit(zona)

    def area_imagen(self) -> QRectF:
        """Dónde se dibuja la captura: centrada y escalada sin deformar."""
        if self._imagen is None or self._imagen.width() == 0:
            return QRectF(self.rect())
        escala = min(self.width() / self._imagen.width(), self.height() / self._imagen.height())
        ancho, alto = self._imagen.width() * escala, self._imagen.height() * escala
        return QRectF((self.width() - ancho) / 2, (self.height() - alto) / 2, ancho, alto)

    def a_proporcion(self, punto: QPointF) -> QPointF:
        """Punto del widget en proporciones de la captura (0 a 1), recortado a sus bordes."""
        area = self.area_imagen()
        x = (punto.x() - area.x()) / area.width()
        y = (punto.y() - area.y()) / area.height()
        return QPointF(min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))

    def zona_entre(self, a: QPointF, b: QPointF) -> ZonaRelativa | None:
        """Zona entre dos puntos del widget, o None si es demasiado pequeña."""
        p, q = self.a_proporcion(a), self.a_proporcion(b)
        x, y = min(p.x(), q.x()), min(p.y(), q.y())
        ancho, alto = abs(p.x() - q.x()), abs(p.y() - q.y())
        if ancho < LADO_MIN or alto < LADO_MIN:
            return None
        return ZonaRelativa(x, y, min(ancho, 1 - x), min(alto, 1 - y))

    # Ratón

    def mousePressEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - nombre de Qt
        if evento.button() == Qt.MouseButton.LeftButton and self._imagen is not None:
            self._inicio = evento.position()
            self._arrastre = QRectF(self._inicio, self._inicio)
            self.update()

    def mouseMoveEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - nombre de Qt
        if self._inicio is not None:
            self._arrastre = QRectF(self._inicio, evento.position()).normalized()
            self.update()

    def mouseReleaseEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - nombre de Qt
        if self._inicio is None or evento.button() != Qt.MouseButton.LeftButton:
            return
        zona = self.zona_entre(self._inicio, evento.position())
        self._inicio = self._arrastre = None
        if zona is not None:
            self.poner_zona(zona)
        self.update()

    # Dibujo

    def paintEvent(self, evento: QPaintEvent) -> None:  # noqa: N802 - nombre de Qt
        pintor = QPainter(self)
        pintor.fillRect(self.rect(), self.palette().window())
        if self._imagen is None:
            pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _("Pulsa «Capturar ventana»"))
            return
        area = self.area_imagen()
        pintor.drawPixmap(area.toRect(), self._imagen)
        recuadro = self._arrastre or self._recuadro_zona(area)
        if recuadro is None:
            return
        # Oscurece lo que queda fuera de la zona y la enmarca.
        fuera, dentro = QPainterPath(), QPainterPath()
        fuera.addRect(area)
        dentro.addRect(recuadro)
        pintor.fillPath(fuera.subtracted(dentro), QColor(0, 0, 0, 120))
        pintor.setPen(QPen(QColor(255, 200, 0), 2))
        pintor.drawRect(recuadro)

    def _recuadro_zona(self, area: QRectF) -> QRectF | None:
        if self._zona is None:
            return None
        z = self._zona
        ancho, alto = area.width(), area.height()
        return QRectF(area.x() + z.x * ancho, area.y() + z.y * alto, z.ancho * ancho, z.alto * alto)
