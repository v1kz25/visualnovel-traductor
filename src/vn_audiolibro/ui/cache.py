"""Ventana de la caché: cuánto ocupa cada juego, vaciarla y su tamaño máximo."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.configuracion import (
    LIMITE_CACHE_MB,
    LIMITE_MIN_MB,
    AjustesApp,
    cargar_ajustes,
    formato_tamano,
    guardar_ajustes,
)
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles

AbrirCache = Callable[[], CacheSQLite]
JUEGO_BORRADO = "(juego borrado)"


class VentanaCache(QDialog):
    """Muestra la caché por juego y permite vaciarla o limitar su tamaño."""

    def __init__(
        self,
        almacen: AlmacenPerfiles,
        abrir_cache: AbrirCache = CacheSQLite,
        ruta_ajustes: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Caché de traducciones y audio")
        self.resize(560, 420)
        self._almacen = almacen
        self._abrir_cache = abrir_cache
        self._ruta_ajustes = ruta_ajustes
        self._ajustes = cargar_ajustes(ruta_ajustes)

        explicacion = QLabel(
            "Cada línea traducida se guarda con su audio: la segunda vez suena al instante y sin "
            "traducir. Vaciarla solo hace que se vuelva a traducir."
        )
        explicacion.setWordWrap(True)
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Juego", "Líneas", "Tamaño"])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.total = QLabel()
        self.boton_vaciar = QPushButton("Vaciar el elegido")
        self.boton_vaciar_todo = QPushButton("Vaciar todo")
        self.limitar = QCheckBox("Tamaño máximo")
        self.limite = QSpinBox()
        self.limite.setRange(LIMITE_MIN_MB, 1024 * 1024)
        self.limite.setSingleStep(256)
        self.limite.setSuffix(" MB")
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)

        fila_vaciar = QHBoxLayout()
        fila_vaciar.addWidget(self.boton_vaciar)
        fila_vaciar.addWidget(self.boton_vaciar_todo)
        fila_vaciar.addStretch()
        fila_limite = QHBoxLayout()
        fila_limite.addWidget(self.limitar)
        fila_limite.addWidget(self.limite)
        fila_limite.addStretch()
        columna = QVBoxLayout(self)
        columna.addWidget(explicacion)
        columna.addWidget(self.tabla, 1)
        columna.addWidget(self.total)
        columna.addLayout(fila_vaciar)
        columna.addLayout(fila_limite)
        columna.addWidget(
            QLabel("Al llegar al máximo se borra primero lo que se usó hace más tiempo."),
        )
        columna.addWidget(botones)

        self.boton_vaciar.clicked.connect(self.vaciar_elegido)
        self.boton_vaciar_todo.clicked.connect(self.vaciar_todo)
        self.limitar.toggled.connect(self.limite.setEnabled)
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        botones.rejected.connect(self.reject)

        limite = self._ajustes.limite_cache_mb
        self.limitar.setChecked(limite is not None)
        self.limite.setEnabled(limite is not None)
        self.limite.setValue(limite or LIMITE_CACHE_MB)
        self.recargar()

    def recargar(self) -> None:
        nombres = {perfil.id: perfil.nombre for perfil in self._almacen.listar()}
        cache = self._abrir_cache()
        try:
            resumen = cache.resumen()
        finally:
            cache.cerrar()
        self.tabla.setRowCount(0)
        for fila, juego in enumerate(resumen):
            self.tabla.insertRow(fila)
            nombre = QTableWidgetItem(nombres.get(juego.perfil, JUEGO_BORRADO))
            nombre.setData(Qt.ItemDataRole.UserRole, juego.perfil)
            self.tabla.setItem(fila, 0, nombre)
            self.tabla.setItem(fila, 1, QTableWidgetItem(str(juego.entradas)))
            self.tabla.setItem(fila, 2, QTableWidgetItem(formato_tamano(juego.bytes)))
        total = sum(juego.bytes for juego in resumen)
        self.total.setText(f"Total: {formato_tamano(total)}" if resumen else "La caché está vacía.")
        self._actualizar_botones()

    def perfil_elegido(self) -> tuple[str, str] | None:
        """Identificador y nombre del juego elegido en la tabla."""
        fila = self.tabla.currentRow()
        elemento = self.tabla.item(fila, 0) if fila >= 0 else None
        if elemento is None:
            return None
        return str(elemento.data(Qt.ItemDataRole.UserRole)), elemento.text()

    def vaciar_elegido(self) -> None:
        elegido = self.perfil_elegido()
        if elegido is None or not self._confirmar(f"¿Vaciar la caché de «{elegido[1]}»?"):
            return
        self._con_cache(lambda cache: cache.invalidar(elegido[0]))

    def vaciar_todo(self) -> None:
        if self._confirmar("¿Vaciar la caché de todos los juegos?"):
            self._con_cache(lambda cache: cache.vaciar())

    def guardar_limite(self) -> None:
        """Guarda el tamaño máximo si ha cambiado y recorta la caché si ya se pasa."""
        limite = self.limite.value() if self.limitar.isChecked() else None
        if limite == self._ajustes.limite_cache_mb:
            return
        self._ajustes = AjustesApp(limite_cache_mb=limite)
        guardar_ajustes(self._ajustes, self._ruta_ajustes)
        if limite is not None:
            limite_bytes = self._ajustes.limite_cache_bytes

            def recortar(cache: CacheSQLite) -> None:
                cache.limite_bytes = limite_bytes
                cache.recortar()

            self._con_cache(recortar)

    def done(self, resultado: int) -> None:
        """Al cerrar, de cualquier forma, se guarda el límite."""
        self.guardar_limite()
        super().done(resultado)

    def _con_cache(self, accion: Callable[[CacheSQLite], object]) -> None:
        cache = self._abrir_cache()
        try:
            accion(cache)
        finally:
            cache.cerrar()
        self.recargar()

    def _confirmar(self, pregunta: str) -> bool:
        texto = f"{pregunta}\n\nSe volverá a traducir al jugar."
        respuesta = QMessageBox.question(self, "Vaciar caché", texto)
        return respuesta == QMessageBox.StandardButton.Yes

    def _actualizar_botones(self) -> None:
        self.boton_vaciar.setEnabled(self.perfil_elegido() is not None)
        self.boton_vaciar_todo.setEnabled(self.tabla.rowCount() > 0)
