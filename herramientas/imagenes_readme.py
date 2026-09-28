"""Genera las imágenes de la portada del repo: banner, captura de la app y previsualización social.

La escena del juego es sintética (dibujada aquí, con un texto escrito para la ocasión): nunca se usa
material de juegos con copyright. La ventana de la app es la real, con líneas de ejemplo.

    uv run python herramientas/imagenes_readme.py [carpeta]   # por defecto .github/assets
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego
from vn_audiolibro.ui.acceso import icono_svg
from vn_audiolibro.ui.principal import VentanaPrincipal

AZUL = QColor("#1f3a5f")
AZUL_OSCURO = QColor("#152a45")
CREMA = QColor("#f4f1ea")
NARANJA = QColor("#f2a93b")
LEMA = "Novelas visuales en chino y japonés, leídas en español mientras juegas"
DETALLE = "OCR · traducción local · voz · sin conexión · Linux y Windows"
CJK = "Noto Sans CJK TC"

# Texto escrito para estas imágenes (no sale de ningún juego).
LINEAS = [
    ("窗外又下起雨了。", "Afuera ha vuelto a llover."),
    ("小雨：你今天也忘了帶傘嗎？", "Xiaoyu: ¿Hoy también te has olvidado el paraguas?"),
    ("小雨：那我們一起回家吧。", "Xiaoyu: Entonces, volvamos juntos a casa."),
]


def _fuente(tamano: int, negrita: bool = False, familia: str = "Noto Sans") -> QFont:
    fuente = QFont(familia)
    fuente.setPixelSize(tamano)
    fuente.setBold(negrita)
    return fuente


def _icono(pintor: QPainter, rect: QRectF) -> None:
    QSvgRenderer(QByteArray(icono_svg())).render(pintor, rect)


def _fondo_marca(pintor: QPainter, ancho: int, alto: int) -> None:
    degradado = QLinearGradient(0, 0, ancho, alto)
    degradado.setColorAt(0, AZUL)
    degradado.setColorAt(1, AZUL_OSCURO)
    pintor.fillRect(0, 0, ancho, alto, degradado)


def _textos_marca(pintor: QPainter, x: float, y: float, escala: float) -> None:
    """Nombre, lema y detalle, alineados a la izquierda desde (x, y)."""
    pintor.setPen(CREMA)
    pintor.setFont(_fuente(int(64 * escala), negrita=True))
    pintor.drawText(QPointF(x, y), "vn-audiolibro")
    pintor.setFont(_fuente(int(25 * escala)))
    pintor.drawText(QPointF(x, y + 50 * escala), LEMA)
    pintor.setPen(NARANJA)
    pintor.setFont(_fuente(int(20 * escala)))
    pintor.drawText(QPointF(x, y + 90 * escala), DETALLE)


def banner() -> QImage:
    imagen = QImage(1280, 300, QImage.Format.Format_ARGB32)
    imagen.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    recorte = QPainterPath()
    recorte.addRoundedRect(QRectF(0, 0, 1280, 300), 24, 24)
    pintor.setClipPath(recorte)
    _fondo_marca(pintor, 1280, 300)
    _icono(pintor, QRectF(60, 50, 200, 200))
    _textos_marca(pintor, 310, 135, 1.0)
    pintor.end()
    return imagen


def previsualizacion(captura: QImage) -> QImage:
    """1280×640 para la previsualización social de GitHub: marca arriba y la captura debajo."""
    imagen = QImage(1280, 640, QImage.Format.Format_RGB32)
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    _fondo_marca(pintor, 1280, 640)
    _icono(pintor, QRectF(70, 48, 150, 150))
    _textos_marca(pintor, 250, 110, 0.85)
    reducida = captura.scaledToHeight(390, Qt.TransformationMode.SmoothTransformation)
    pintor.drawImage(QPointF((1280 - reducida.width()) / 2, 225), reducida)
    pintor.end()
    return imagen


def _escena_juego(ancho: int, alto: int) -> QImage:
    """Una escena de novela visual inventada: calle de noche con lluvia y la caja de texto."""
    imagen = QImage(ancho, alto, QImage.Format.Format_RGB32)
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    cielo = QLinearGradient(0, 0, 0, alto)
    cielo.setColorAt(0, QColor("#2b3d63"))
    cielo.setColorAt(1, QColor("#7a6f93"))
    pintor.fillRect(0, 0, ancho, alto, cielo)
    # Edificios con ventanas encendidas
    pintor.setPen(Qt.PenStyle.NoPen)
    for i, (x, w, h) in enumerate(
        [
            (0, 150, 300),
            (140, 120, 380),
            (250, 170, 250),
            (410, 130, 420),
            (530, 180, 290),
            (700, 140, 360),
            (830, 150, 270),
        ]
    ):
        pintor.setBrush(QColor("#1d2540") if i % 2 else QColor("#252f50"))
        pintor.drawRect(QRectF(x, alto - h, w, h))
        pintor.setBrush(QColor("#f5d38a"))
        for fila in range(1, h // 38):
            for col in range(1, w // 34):
                if (fila * 7 + col * 3 + i) % 5 == 0:
                    pintor.drawRect(QRectF(x + col * 34 - 10, alto - h + fila * 38 - 10, 12, 16))
    # Lluvia
    pintor.setPen(QPen(QColor(220, 230, 255, 90), 2))
    for n in range(160):
        x, y = (n * 97) % ancho, (n * 61) % alto
        pintor.drawLine(QPointF(x, y), QPointF(x - 6, y + 22))
    # Caja de texto con el nombre del personaje
    caja = QRectF(40, alto - 190, ancho - 80, 150)
    pintor.setPen(QPen(QColor(255, 255, 255, 160), 2))
    pintor.setBrush(QColor(10, 14, 30, 200))
    pintor.drawRoundedRect(caja, 14, 14)
    pintor.setBrush(QColor("#c0587e"))
    pintor.drawRoundedRect(QRectF(60, alto - 215, 130, 44), 10, 10)
    pintor.setPen(Qt.GlobalColor.white)
    pintor.setFont(_fuente(26, negrita=True, familia=CJK))
    pintor.drawText(QRectF(60, alto - 215, 130, 44), Qt.AlignmentFlag.AlignCenter, "小雨")
    pintor.setFont(_fuente(34, familia=CJK))
    pintor.drawText(caja.adjusted(40, 45, -40, -20), "那我們一起回家吧。")
    # Recuadro de la zona calibrada, como lo dibuja el usuario al configurar el juego
    pintor.setPen(QPen(NARANJA, 3, Qt.PenStyle.DashLine))
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.drawRect(caja.adjusted(20, 25, -20, -25))
    pintor.end()
    return imagen


def _ventana_app(almacen: AlmacenPerfiles) -> QImage:
    ventana = VentanaPrincipal(almacen)
    ventana.resize(760, 560)
    ventana.estado.setText("Leyendo «Lluvia de verano». Juega con normalidad.")
    for original, traduccion in LINEAS:
        ventana._mostrar_linea(LineaJuego(original, traduccion, desde_cache=False, leida=True))
    ventana.recargar_perfiles(elegir=almacen.buscar("Lluvia de verano").id)
    for boton in (ventana.boton_pausa, ventana.boton_repetir, ventana.boton_saltar, ventana.boton_detener):
        boton.setEnabled(True)
    ventana.boton_jugar.setEnabled(False)
    ventana.show()
    QApplication.processEvents()
    return ventana.grab().toImage()


def _con_marco(pintor: QPainter, destino: QRectF, titulo: str, contenido: QImage) -> None:
    """Dibuja una ventana con barra de título sencilla y sombra."""
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor(0, 0, 0, 70))
    pintor.drawRoundedRect(destino.translated(6, 10), 12, 12)
    pintor.setBrush(QColor("#2d2f36"))
    pintor.drawRoundedRect(destino, 12, 12)
    pintor.setPen(QColor("#e8e8ea"))
    pintor.setFont(_fuente(16))
    pintor.drawText(
        QRectF(destino.x(), destino.y(), destino.width(), 36), Qt.AlignmentFlag.AlignCenter, titulo
    )
    for i, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(color))
        pintor.drawEllipse(QPointF(destino.x() + 22 + i * 22, destino.y() + 18), 6, 6)
    interior = QRectF(destino.x(), destino.y() + 36, destino.width(), destino.height() - 36)
    pintor.drawImage(interior, contenido)


def captura(almacen: AlmacenPerfiles) -> QImage:
    """El juego (sintético) a la izquierda y la app leyéndolo a la derecha."""
    juego = _escena_juego(960, 560)
    app = _ventana_app(almacen)
    imagen = QImage(1800, 700, QImage.Format.Format_RGB32)
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    fondo = QLinearGradient(0, 0, 1800, 700)
    fondo.setColorAt(0, QColor("#dfe6f0"))
    fondo.setColorAt(1, QColor("#c9d3e2"))
    pintor.fillRect(0, 0, 1800, 700, QBrush(fondo))
    _con_marco(pintor, QRectF(40, 60, 960, 596), "Lluvia de verano", juego)
    _con_marco(pintor, QRectF(1020, 60, app.width(), app.height() + 36), "vn-audiolibro", app)
    pintor.end()
    return imagen


def main() -> None:
    salida = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/assets")
    salida.mkdir(parents=True, exist_ok=True)
    aplicacion = QApplication([])
    aplicacion.setStyle("Fusion")
    QApplication.setWindowIcon(QPixmap.fromImage(QImage.fromData(icono_svg())))
    with tempfile.TemporaryDirectory() as temporal:
        almacen = AlmacenPerfiles(Path(temporal))
        almacen.guardar(Perfil("Lluvia de verano", "Lluvia de verano", idioma="zh-Hant"))
        almacen.guardar(Perfil("Estrellas de papel", "Estrellas de papel", idioma="ja"))
        imagen_app = captura(almacen)
    banner().save(str(salida / "banner.png"))
    imagen_app.save(str(salida / "captura.png"))
    previsualizacion(imagen_app).save(str(salida / "previsualizacion.png"))
    print(f"Imágenes en {salida}")


if __name__ == "__main__":
    main()
