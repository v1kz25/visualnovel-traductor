"""Ajustes de los atajos de teclado globales: activarlos y elegir la combinación de cada acción."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vn_audiolibro.atajos.modelos import (
    NOMBRES_ACCIONES,
    POR_DEFECTO,
    Accion,
    AtajoNoValidoError,
    leer_atajos,
)
from vn_audiolibro.configuracion import cargar_ajustes, guardar_ajustes
from vn_audiolibro.textos import _


class DialogoAtajos(QDialog):
    """Atajos que funcionan con el juego en primer plano, mientras se juega."""

    def __init__(self, ruta_ajustes: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Atajos de teclado"))
        self._ruta_ajustes = ruta_ajustes
        ajustes = cargar_ajustes(ruta_ajustes)

        explicacion = QLabel(
            _(
                "Mientras juegas, estas combinaciones funcionan aunque el juego esté en primer plano, "
                "y el juego deja de recibirlas. Si alguna choca con las del juego o con otra "
                "aplicación, cámbiala o desactiva los atajos."
            )
        )
        explicacion.setWordWrap(True)
        self.activos = QCheckBox(_("Usar atajos de teclado mientras juegas"))
        self.activos.setChecked(ajustes.atajos_activos)
        self.campos: dict[Accion, QKeySequenceEdit] = {}
        formulario = QFormLayout()
        for accion in Accion:
            campo = QKeySequenceEdit(QKeySequence(ajustes.atajos[accion.value]))
            campo.setMaximumSequenceLength(1)
            campo.setClearButtonEnabled(True)
            self.campos[accion] = campo
            formulario.addRow(_(NOMBRES_ACCIONES[accion]), campo)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c0392b")
        self.boton_defecto = QPushButton(_("Restablecer"))
        self.boton_defecto.clicked.connect(self.restablecer)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.guardar)
        botones.rejected.connect(self.reject)
        self.botones = botones
        fila = QHBoxLayout()
        fila.addWidget(self.boton_defecto)
        fila.addStretch()
        fila.addWidget(botones)

        columna = QVBoxLayout(self)
        columna.addWidget(explicacion)
        columna.addWidget(self.activos)
        columna.addLayout(formulario)
        columna.addWidget(self.error)
        columna.addLayout(fila)
        self.activos.toggled.connect(self._habilitar)
        self._habilitar(self.activos.isChecked())

    def _habilitar(self, activos: bool) -> None:
        for campo in self.campos.values():
            campo.setEnabled(activos)

    def restablecer(self) -> None:
        for accion, campo in self.campos.items():
            campo.setKeySequence(QKeySequence(POR_DEFECTO[accion]))
        self.error.clear()

    def textos(self) -> dict[str, str]:
        """El atajo escrito en cada campo, como lo escribe Qt («Ctrl+Alt+P»)."""
        return {
            accion.value: campo.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            for accion, campo in self.campos.items()
        }

    def guardar(self) -> None:
        """Comprueba los atajos y los guarda; si alguno no vale, lo dice y no cierra."""
        textos = self.textos()
        try:
            leer_atajos(textos)
        except AtajoNoValidoError as error:
            self.error.setText(str(error))
            return
        ajustes = cargar_ajustes(self._ruta_ajustes)
        guardar_ajustes(
            replace(ajustes, atajos_activos=self.activos.isChecked(), atajos=textos), self._ruta_ajustes
        )
        self.accept()
