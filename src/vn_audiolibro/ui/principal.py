"""Ventana principal: elegir un juego, jugar y ver cada línea con su traducción.

En la interfaz los perfiles se llaman «juegos»: es lo que el usuario configura.
"""

from collections import deque
from collections.abc import Callable
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego
from vn_audiolibro.ui.ajustes import AjustesJuego
from vn_audiolibro.ui.cache import VentanaCache
from vn_audiolibro.ui.editor import EditorJuego
from vn_audiolibro.ui.puente import PuenteSesion

TITULO = "vn-audiolibro"
MAX_LINEAS = 500
"""Líneas que se conservan en el historial de la partida."""

AbrirCache = Callable[[], CacheSQLite]
AbrirEditor = Callable[[QWidget, AlmacenPerfiles, Perfil | None], EditorJuego]
AbrirAjustes = Callable[[QWidget, AlmacenPerfiles, Perfil], AjustesJuego]
AbrirVentanaCache = Callable[[QWidget, AlmacenPerfiles], VentanaCache]


def _html(linea: LineaJuego) -> str:
    """Una línea del historial: el original pequeño y en gris, la traducción debajo y más grande."""
    sufijo = "" if linea.leida else ' <span style="color: gray">(no leída)</span>'
    color = "" if linea.leida else " color: gray;"  # las no leídas, apagadas
    return (
        f'<p style="margin: 8px 0 0 0; color: gray">{escape(linea.original)}</p>'
        f'<p style="margin: 0; font-size: large;{color}">{escape(linea.traduccion)}{sufijo}</p>'
    )


class VentanaPrincipal(QMainWindow):
    """Lista de juegos a la izquierda; la partida en curso a la derecha."""

    def __init__(
        self,
        almacen: AlmacenPerfiles,
        puente: PuenteSesion | None = None,
        abrir_cache: AbrirCache = CacheSQLite,
        abrir_editor: AbrirEditor | None = None,
        abrir_ajustes: AbrirAjustes | None = None,
        abrir_ventana_cache: AbrirVentanaCache | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(TITULO)
        self.resize(900, 560)
        self._almacen = almacen
        self._abrir_cache = abrir_cache
        self._abrir_editor = abrir_editor or (
            lambda padre, almacen, perfil: EditorJuego(almacen, perfil, parent=padre)
        )
        self._abrir_ventana_cache = abrir_ventana_cache or (
            lambda padre, almacen: VentanaCache(almacen, abrir_cache, parent=padre)
        )
        self._abrir_ajustes = abrir_ajustes or (
            lambda padre, almacen, perfil: AjustesJuego(almacen, perfil, abrir_cache, parent=padre)
        )
        self.puente = puente or PuenteSesion(parent=self)
        self._perfil_en_juego: Perfil | None = None
        self._hubo_error = False
        self._crear_widgets()
        self._conectar()
        self.recargar_perfiles()
        self._actualizar_botones()

    # Construcción

    def _crear_widgets(self) -> None:
        self.lista_perfiles = QListWidget()
        self.boton_jugar = QPushButton("Jugar")
        self.boton_anadir = QPushButton("Añadir juego")
        self.boton_editar = QPushButton("Editar")
        self.boton_ajustes = QPushButton("Ajustes")
        self.boton_borrar = QPushButton("Borrar")
        self.boton_cache = QPushButton("Caché…")

        izquierda = QWidget()
        columna = QVBoxLayout(izquierda)
        columna.addWidget(QLabel("<b>Juegos</b>"))
        columna.addWidget(self.lista_perfiles)
        columna.addWidget(self.boton_jugar)
        fila = QHBoxLayout()
        for boton in (self.boton_anadir, self.boton_editar, self.boton_ajustes, self.boton_borrar):
            fila.addWidget(boton)
        columna.addLayout(fila)
        columna.addWidget(self.boton_cache)

        self.estado = QLabel("Elige un juego y pulsa Jugar.")
        self.estado.setWordWrap(True)
        self.historial = QTextBrowser()
        self._lineas: deque[LineaJuego] = deque(maxlen=MAX_LINEAS)
        self.boton_pausa = QPushButton("Pausa (P)")
        self.boton_repetir = QPushButton("Repetir (R)")
        self.boton_saltar = QPushButton("Saltar (S)")
        self.boton_detener = QPushButton("Detener")
        self.siempre_encima = QCheckBox("Mantener encima del juego")

        derecha = QWidget()
        columna = QVBoxLayout(derecha)
        columna.addWidget(self.estado)
        columna.addWidget(self.historial)
        fila = QHBoxLayout()
        for boton in (self.boton_pausa, self.boton_repetir, self.boton_saltar, self.boton_detener):
            fila.addWidget(boton)
        columna.addLayout(fila)
        columna.addWidget(self.siempre_encima)

        divisor = QSplitter()
        divisor.addWidget(izquierda)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(1, 3)
        self.setCentralWidget(divisor)

    def _conectar(self) -> None:
        self.boton_jugar.clicked.connect(self.jugar)
        self.lista_perfiles.itemDoubleClicked.connect(lambda _: self.jugar())
        self.lista_perfiles.currentRowChanged.connect(lambda _: self._actualizar_botones())
        self.boton_borrar.clicked.connect(self.borrar)
        self.boton_anadir.clicked.connect(lambda: self.editar(None))
        self.boton_editar.clicked.connect(lambda: self.editar(self.perfil_elegido()))
        self.boton_ajustes.clicked.connect(self.ajustar)
        self.boton_cache.clicked.connect(self.ver_cache)
        self.boton_pausa.clicked.connect(self._alternar_pausa)
        self.boton_repetir.clicked.connect(self.puente.repetir)
        self.boton_saltar.clicked.connect(self.puente.saltar)
        self.boton_detener.clicked.connect(self.detener)
        self.siempre_encima.toggled.connect(self._mantener_encima)
        atajos = {"P": self._alternar_pausa, "R": self.puente.repetir, "S": self.puente.saltar}
        for tecla, accion in atajos.items():
            QShortcut(QKeySequence(tecla), self, accion)

        self.puente.estado.connect(self.estado.setText)
        self.puente.linea.connect(self._mostrar_linea)
        self.puente.error.connect(self._mostrar_error)
        self.puente.iniciada.connect(self._al_iniciar)
        self.puente.terminada.connect(self._al_terminar)

    # Perfiles

    def recargar_perfiles(self, elegir: str | None = None) -> None:
        """Vuelve a leer los juegos; deja elegido el de id `elegir` si se indica."""
        self.lista_perfiles.clear()
        for perfil in self._almacen.listar():
            elemento = QListWidgetItem(perfil.nombre)
            elemento.setData(Qt.ItemDataRole.UserRole, perfil)
            elemento.setToolTip(f"Ventana «{perfil.ventana}» · {perfil.idioma} → {perfil.destino}")
            self.lista_perfiles.addItem(elemento)
            if perfil.id == elegir:
                self.lista_perfiles.setCurrentItem(elemento)
        if self.lista_perfiles.count() and self.lista_perfiles.currentRow() < 0:
            self.lista_perfiles.setCurrentRow(0)

    def perfil_elegido(self) -> Perfil | None:
        elemento = self.lista_perfiles.currentItem()
        perfil = None if elemento is None else elemento.data(Qt.ItemDataRole.UserRole)
        return perfil if isinstance(perfil, Perfil) else None

    def editar(self, perfil: Perfil | None) -> None:
        """Abre el editor para añadir un juego (None) o cambiar uno existente."""
        if self.puente.jugando:
            return
        editor = self._abrir_editor(self, self._almacen, perfil)
        if editor.exec() == QDialog.DialogCode.Accepted and editor.guardado is not None:
            self.recargar_perfiles(elegir=editor.guardado.id)
        self._actualizar_botones()

    def ajustar(self) -> None:
        """Abre los ajustes de voz, lectura, volumen y glosario del juego elegido."""
        perfil = self.perfil_elegido()
        if perfil is None or self.puente.jugando:
            return
        ajustes = self._abrir_ajustes(self, self._almacen, perfil)
        if ajustes.exec() == QDialog.DialogCode.Accepted and ajustes.guardado is not None:
            self.recargar_perfiles(elegir=ajustes.guardado.id)
        self._actualizar_botones()

    def ver_cache(self) -> None:
        """Abre la ventana de la caché (no mientras se juega: la partida la está usando)."""
        if not self.puente.jugando:
            self._abrir_ventana_cache(self, self._almacen).exec()

    def borrar(self) -> None:
        perfil = self.perfil_elegido()
        if perfil is None or self.puente.jugando:
            return
        respuesta = QMessageBox.question(
            self,
            "Borrar juego",
            f"¿Borrar «{perfil.nombre}» de la lista?\n\n"
            "Sus traducciones y su audio guardados también se borrarán.",
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        self._almacen.borrar(perfil.id)
        cache = self._abrir_cache()
        try:
            cache.invalidar(perfil.id)
        finally:
            cache.cerrar()
        self.recargar_perfiles()
        self._actualizar_botones()

    # Partida

    def jugar(self) -> None:
        perfil = self.perfil_elegido()
        if perfil is None or self.puente.jugando:
            return
        self._perfil_en_juego = perfil
        self._hubo_error = False
        self._lineas.clear()
        self.historial.clear()
        self.estado.setText(f"Preparando «{perfil.nombre}»…")
        self.puente.iniciar(perfil)
        self._actualizar_botones()

    def detener(self) -> None:
        self.estado.setText("Parando…")
        self.puente.detener()
        self._actualizar_botones()

    def _alternar_pausa(self) -> None:
        self.puente.alternar_pausa()
        self._actualizar_botones()

    def _al_iniciar(self) -> None:
        if self._perfil_en_juego is not None:
            self.estado.setText(f"Leyendo «{self._perfil_en_juego.nombre}». Juega con normalidad.")
        self._actualizar_botones()

    def _al_terminar(self) -> None:
        self._perfil_en_juego = None
        if not self.puente.jugando and not self._hubo_error:
            self.estado.setText("Partida terminada. Elige un juego y pulsa Jugar.")
        self._actualizar_botones()

    def _mostrar_linea(self, linea: LineaJuego) -> None:
        self._lineas.append(linea)
        self.historial.setHtml("".join(_html(linea) for linea in self._lineas))
        barra = self.historial.verticalScrollBar()
        barra.setValue(barra.maximum())

    def _mostrar_error(self, mensaje: str) -> None:
        self._hubo_error = True  # que no lo tape el «Partida terminada» que llega después
        self.estado.setText(f"⚠ {mensaje}")

    def _mantener_encima(self, activo: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, activo)
        self.show()  # cambiar las banderas oculta la ventana

    def _actualizar_botones(self) -> None:
        jugando = self.puente.jugando
        hay_perfil = self.perfil_elegido() is not None
        self.boton_jugar.setEnabled(hay_perfil and not jugando)
        self.boton_borrar.setEnabled(hay_perfil and not jugando)
        self.boton_editar.setEnabled(hay_perfil and not jugando)
        self.boton_ajustes.setEnabled(hay_perfil and not jugando)
        self.boton_anadir.setEnabled(not jugando)
        self.boton_cache.setEnabled(not jugando)
        self.lista_perfiles.setEnabled(not jugando)
        for boton in (self.boton_pausa, self.boton_repetir, self.boton_saltar, self.boton_detener):
            boton.setEnabled(jugando)
        self.boton_pausa.setText("Seguir (P)" if self.puente.pausado else "Pausa (P)")

    def closeEvent(self, evento: QCloseEvent) -> None:  # noqa: N802 - nombre de Qt
        """Al cerrar, para la partida y espera: devuelve el volumen del juego y para el traductor."""
        if self.puente.jugando:
            self.puente.detener()
        self.puente.esperar(timeout_s=15)
        evento.accept()
