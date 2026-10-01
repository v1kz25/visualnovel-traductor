"""Ajustes de un juego: voz y lectura, volumen del juego y de otras aplicaciones, glosario y subtítulos."""

import logging
import threading
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import (
    PAUSA_MAX_S,
    TAMANO_MAX,
    TAMANO_MIN,
    VELOCIDAD_MAX,
    VELOCIDAD_MIN,
    AjustesLectura,
    AjustesSubtitulos,
    AjustesVolumen,
    AjustesVoz,
    Perfil,
    PerfilInvalidoError,
    PosicionSubtitulos,
)
from vn_audiolibro.plataforma import cliente_audio, reproductor
from vn_audiolibro.textos import N_, _, decimal
from vn_audiolibro.traduccion.modelos import Glosario
from vn_audiolibro.ui.editor import NOMBRES_DESTINOS
from vn_audiolibro.voz.modelos import ModoLectura
from vn_audiolibro.voz.piper import Hablante, SintetizadorPiper, asegurar_voz, elegir_voz
from vn_audiolibro.voz.reproductor import NOMBRE_CLIENTE

_registro = logging.getLogger(__name__)

FRASES_PRUEBA = {
    "es": "Hola. Así sonará la traducción mientras juegas. ¿Qué te parece?",
    "en": "Hello. This is how the translation will sound while you play. What do you think?",
}
"""Frase de prueba de la voz en cada idioma de destino."""
BAJAR, SILENCIAR, NO_TOCAR = "bajar", "silenciar", "no tocar"
ACCIONES = {BAJAR: N_("Bajar a"), SILENCIAR: N_("Silenciar"), NO_TOCAR: N_("No tocar nunca")}
"""Se traducen al mostrarlas, con `_()`."""

POSICIONES = {
    PosicionSubtitulos.ENCIMA: N_("Encima de la caja de texto"),
    PosicionSubtitulos.DEBAJO: N_("Debajo de la caja de texto"),
    PosicionSubtitulos.TAPAR: N_("Tapando la caja de texto (solo se ve la traducción)"),
}
AYUDA_SUBTITULOS = N_(
    "La traducción aparece sobre el juego mientras es la ventana activa; los clics siguen llegando "
    "al juego. Si no se ve con el juego en pantalla completa, ponlo en modo ventana o ventana sin bordes."
)

AbrirCache = Callable[[], CacheSQLite]
ProbarVoz = Callable[[AjustesVoz, str], None]
ListarAplicaciones = Callable[[], list[str]]


def _veces(velocidad: float) -> str:
    return f"{decimal(velocidad, 2)}×"


def probar_voz(ajustes: AjustesVoz, destino: str) -> None:
    """Lee la frase de prueba en el idioma `destino` con la voz y la velocidad indicadas.

    Bloquea hasta que termina. Si la voz de ese idioma aún no está en el equipo, la descarga.
    """
    voz = elegir_voz(destino, ajustes.hablante)
    sintetizador = SintetizadorPiper(asegurar_voz(voz.voz), voz.hablante, ajustes.velocidad)
    fragmentos = list(sintetizador.sintetizar(FRASES_PRUEBA[destino]))
    salida = reproductor().abrir(fragmentos[0].frecuencia)
    for fragmento in fragmentos:
        salida.escribir(fragmento.pcm)
    salida.terminar()


def listar_aplicaciones() -> list[str]:
    """Aplicaciones que están sonando ahora, sin esta app. Vacía si no hay servidor de sonido."""
    try:
        cliente = cliente_audio()
    except Exception:
        _registro.warning("No se pueden listar las aplicaciones que suenan", exc_info=True)
        return []
    try:
        nombres = {flujo.aplicacion for flujo in cliente.flujos()} - {"", NOMBRE_CLIENTE}
    finally:
        cliente.cerrar()
    return sorted(nombres, key=str.casefold)


class AjustesJuego(QDialog):
    """Cambia la voz, la lectura, el volumen y el glosario de un juego."""

    prueba_terminada = Signal(str)
    """Mensaje de error de la voz de prueba, o vacío si ha sonado bien."""

    def __init__(
        self,
        almacen: AlmacenPerfiles,
        perfil: Perfil,
        abrir_cache: AbrirCache = CacheSQLite,
        probar: ProbarVoz = probar_voz,
        aplicaciones: ListarAplicaciones = listar_aplicaciones,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Ajustes de «{nombre}»").format(nombre=perfil.nombre))
        self.resize(620, 520)
        self._almacen = almacen
        self._perfil = perfil
        self._abrir_cache = abrir_cache
        self._probar = probar
        self._aplicaciones = aplicaciones
        self.guardado: Perfil | None = None

        pestanas = QTabWidget()
        pestanas.addTab(self._pestana_voz(), _("Voz y lectura"))
        pestanas.addTab(self._pestana_volumen(), _("Volumen"))
        pestanas.addTab(self._pestana_glosario(), _("Glosario"))
        pestanas.addTab(self._pestana_subtitulos(), _("Subtítulos"))
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        self.error.setWordWrap(True)
        botones = QDialogButtonBox.StandardButton
        self.botones = QDialogButtonBox(botones.Save | botones.Cancel)
        self.botones.accepted.connect(self.guardar)
        self.botones.rejected.connect(self.reject)
        columna = QVBoxLayout(self)
        columna.addWidget(pestanas)
        columna.addWidget(self.error)
        columna.addWidget(self.botones)
        self._rellenar(perfil)

    # Voz y lectura

    def _pestana_voz(self) -> QWidget:
        self.hablante = QComboBox()
        self.hablante.addItem(_("Mujer"), Hablante.MUJER.value)
        self.hablante.addItem(_("Hombre"), Hablante.HOMBRE.value)
        self.velocidad = QSlider(Qt.Orientation.Horizontal)
        self.velocidad.setRange(round(VELOCIDAD_MIN * 100), round(VELOCIDAD_MAX * 100))
        self.velocidad.setSingleStep(5)
        self.texto_velocidad = QLabel()
        self.velocidad.valueChanged.connect(lambda v: self.texto_velocidad.setText(_veces(v / 100)))
        self.boton_probar = QPushButton(_("Escuchar"))
        self.boton_probar.clicked.connect(self.probar)
        self.prueba_terminada.connect(self._al_terminar_prueba)
        self.modo = QComboBox()
        self.modo.addItem(_("En cola: leer todas las líneas en orden"), ModoLectura.COLA.value)
        self.modo.addItem(_("Saltar a la última: cortar al avanzar"), ModoLectura.ULTIMA.value)
        self.pausa = QDoubleSpinBox()
        self.pausa.setRange(0, PAUSA_MAX_S)
        self.pausa.setSingleStep(0.5)
        self.pausa.setSuffix(" s")
        self.modo.currentIndexChanged.connect(lambda _: self._actualizar_pausa())

        fila_velocidad = QHBoxLayout()
        fila_velocidad.addWidget(self.velocidad, 1)
        fila_velocidad.addWidget(self.texto_velocidad)
        fila_voz = QHBoxLayout()
        fila_voz.addWidget(self.hablante, 1)
        fila_voz.addWidget(self.boton_probar)
        pestana = QWidget()
        formulario = QFormLayout(pestana)
        formulario.addRow(_("Voz"), fila_voz)
        formulario.addRow(_("Velocidad"), fila_velocidad)
        formulario.addRow(_("Al avanzar deprisa"), self.modo)
        formulario.addRow(_("Pausa entre líneas"), self.pausa)
        return pestana

    # Subtítulos

    def _pestana_subtitulos(self) -> QWidget:
        self.subtitulos = QCheckBox(_("Mostrar la traducción encima del juego"))
        self.posicion = QComboBox()
        for posicion, texto in POSICIONES.items():
            self.posicion.addItem(_(texto), posicion.value)
        self.tamano = QSpinBox()
        self.tamano.setRange(TAMANO_MIN, TAMANO_MAX)
        self.tamano.setSuffix(" pt")
        self.opacidad = QSlider(Qt.Orientation.Horizontal)
        self.opacidad.setRange(0, 100)
        self.texto_opacidad = QLabel()
        self.opacidad.valueChanged.connect(lambda v: self.texto_opacidad.setText(f"{v} %"))
        self.subtitulos.toggled.connect(lambda _: self._actualizar_subtitulos())
        self.posicion.currentIndexChanged.connect(lambda _: self._actualizar_subtitulos())
        ayuda = QLabel(_(AYUDA_SUBTITULOS))
        ayuda.setWordWrap(True)

        fila_opacidad = QHBoxLayout()
        fila_opacidad.addWidget(self.opacidad, 1)
        fila_opacidad.addWidget(self.texto_opacidad)
        pestana = QWidget()
        formulario = QFormLayout(pestana)
        formulario.addRow(self.subtitulos)
        formulario.addRow(_("Posición"), self.posicion)
        formulario.addRow(_("Tamaño de la letra"), self.tamano)
        formulario.addRow(_("Opacidad del fondo"), fila_opacidad)
        formulario.addRow(ayuda)
        return pestana

    def _actualizar_subtitulos(self) -> None:
        activo = self.subtitulos.isChecked()
        for control in (self.posicion, self.tamano):
            control.setEnabled(activo)
        tapar = self.posicion.currentData() == PosicionSubtitulos.TAPAR.value
        self.opacidad.setEnabled(activo and not tapar)  # al tapar, el fondo es opaco

    def _subtitulos(self) -> AjustesSubtitulos:
        return AjustesSubtitulos(
            activo=self.subtitulos.isChecked(),
            posicion=PosicionSubtitulos(self.posicion.currentData()),
            tamano=self.tamano.value(),
            opacidad=self.opacidad.value() / 100,
        )

    def probar(self) -> None:
        """Lee la frase de prueba en segundo plano con la voz y la velocidad elegidas."""
        ajustes, destino = self._voz(), self._perfil.destino
        self.boton_probar.setEnabled(False)

        def sonar() -> None:
            try:
                self._probar(ajustes, destino)
                self.prueba_terminada.emit("")
            except Exception as error:
                _registro.exception("No se pudo probar la voz")
                self.prueba_terminada.emit(_("No se pudo probar la voz: {error}").format(error=error))

        threading.Thread(target=sonar, name="voz-prueba", daemon=True).start()

    def _al_terminar_prueba(self, error: str) -> None:
        self.boton_probar.setEnabled(True)
        self.error.setText(error)

    def _actualizar_pausa(self) -> None:
        self.pausa.setEnabled(self.modo.currentData() == ModoLectura.COLA.value)

    def _voz(self) -> AjustesVoz:
        return AjustesVoz(Hablante(self.hablante.currentData()), self.velocidad.value() / 100)

    # Volumen

    def _pestana_volumen(self) -> QWidget:
        self.bajar = QCheckBox(_("Bajar el volumen del juego mientras habla la voz"))
        self.nivel = QSlider(Qt.Orientation.Horizontal)
        self.nivel.setRange(0, 100)
        self.texto_nivel = QLabel()
        self.nivel.valueChanged.connect(lambda v: self.texto_nivel.setText(f"{v} %"))
        self.bajar.toggled.connect(self.nivel.setEnabled)
        self.tabla_apps = QTableWidget(0, 3)
        self.tabla_apps.setHorizontalHeaderLabels([_("Aplicación"), _("Qué hacer"), _("Nivel")])
        cabecera = self.tabla_apps.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for indice in (1, 2):
            cabecera.setSectionResizeMode(indice, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla_apps.verticalHeader().setVisible(False)
        self.nueva_app = QComboBox()
        self.nueva_app.setEditable(True)
        if (editor := self.nueva_app.lineEdit()) is not None:
            editor.setPlaceholderText(_("Nombre de la aplicación (p. ej. Firefox)"))
        boton_buscar = QPushButton(_("Ver las que suenan"))
        boton_buscar.clicked.connect(self.buscar_aplicaciones)
        boton_anadir = QPushButton(_("Añadir"))
        boton_anadir.clicked.connect(lambda: self.anadir_aplicacion(self.nueva_app.currentText()))
        boton_quitar = QPushButton(_("Quitar la elegida"))
        boton_quitar.clicked.connect(lambda: self._quitar_fila(self.tabla_apps))

        fila_nivel = QHBoxLayout()
        fila_nivel.addWidget(QLabel(_("Volumen del juego")))
        fila_nivel.addWidget(self.nivel, 1)
        fila_nivel.addWidget(self.texto_nivel)
        fila_nueva = QHBoxLayout()
        fila_nueva.addWidget(self.nueva_app, 1)
        fila_nueva.addWidget(boton_buscar)
        fila_nueva.addWidget(boton_anadir)
        pestana = QWidget()
        columna = QVBoxLayout(pestana)
        columna.addWidget(self.bajar)
        columna.addLayout(fila_nivel)
        columna.addWidget(QLabel(_("<b>Otras aplicaciones</b> (un vídeo, música…)")))
        columna.addWidget(self.tabla_apps, 1)
        columna.addLayout(fila_nueva)
        columna.addWidget(boton_quitar, 0, Qt.AlignmentFlag.AlignLeft)
        return pestana

    def buscar_aplicaciones(self) -> None:
        """Rellena el desplegable con las aplicaciones que están sonando."""
        texto = self.nueva_app.currentText()
        self.nueva_app.clear()
        self.nueva_app.addItems(self._aplicaciones())
        self.nueva_app.setEditText(texto)
        self.nueva_app.showPopup()

    def anadir_aplicacion(self, nombre: str, accion: str = BAJAR, nivel: float = 0.3) -> None:
        """Añade una fila a la tabla de aplicaciones (si no está ya)."""
        nombre = nombre.strip()
        if not nombre or nombre.casefold() in {n.casefold() for n, _, _ in self.aplicaciones()}:
            return
        fila = self.tabla_apps.rowCount()
        self.tabla_apps.insertRow(fila)
        elemento = QTableWidgetItem(nombre)
        elemento.setFlags(elemento.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.tabla_apps.setItem(fila, 0, elemento)
        acciones = QComboBox()
        for clave, texto in ACCIONES.items():
            acciones.addItem(_(texto), clave)
        acciones.setCurrentIndex(acciones.findData(accion))
        porcentaje = QSpinBox()
        porcentaje.setRange(0, 100)
        porcentaje.setSuffix(" %")
        porcentaje.setValue(round(nivel * 100))
        porcentaje.setEnabled(accion == BAJAR)
        acciones.currentIndexChanged.connect(lambda _: porcentaje.setEnabled(acciones.currentData() == BAJAR))
        self.tabla_apps.setCellWidget(fila, 1, acciones)
        self.tabla_apps.setCellWidget(fila, 2, porcentaje)
        self.nueva_app.setEditText("")

    def aplicaciones(self) -> list[tuple[str, str, float]]:
        """Filas de la tabla: nombre, acción y nivel (0 a 1)."""
        filas = []
        for fila in range(self.tabla_apps.rowCount()):
            elemento = self.tabla_apps.item(fila, 0)
            acciones = self.tabla_apps.cellWidget(fila, 1)
            porcentaje = self.tabla_apps.cellWidget(fila, 2)
            if elemento and isinstance(acciones, QComboBox) and isinstance(porcentaje, QSpinBox):
                filas.append((elemento.text(), str(acciones.currentData()), porcentaje.value() / 100))
        return filas

    def _volumen(self) -> AjustesVolumen:
        filas = self.aplicaciones()
        return AjustesVolumen(
            activo=self.bajar.isChecked(),
            nivel_juego=self.nivel.value() / 100,
            otras=tuple((n, 0.0 if a == SILENCIAR else nivel) for n, a, nivel in filas if a != NO_TOCAR),
            excluir=tuple(n for n, a, _ in filas if a == NO_TOCAR),
        )

    # Glosario

    def _pestana_glosario(self) -> QWidget:
        self.tabla_glosario = QTableWidget(0, 2)
        self.tabla_glosario.setHorizontalHeaderLabels([_("Término en el juego"), _("Traducción")])
        self.tabla_glosario.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_glosario.verticalHeader().setVisible(False)
        boton_anadir = QPushButton(_("Añadir término"))
        boton_anadir.clicked.connect(lambda: self.anadir_termino("", ""))
        boton_quitar = QPushButton(_("Quitar el elegido"))
        boton_quitar.clicked.connect(lambda: self._quitar_fila(self.tabla_glosario))
        ayuda = QLabel(
            _(
                "Nombres propios y términos que siempre se traducen igual, p. ej. 櫻 → Sakura. "
                "Escribe la traducción en el idioma al que se traduce el juego ({idioma})."
            ).format(idioma=_(NOMBRES_DESTINOS[self._perfil.destino]))
        )
        ayuda.setWordWrap(True)
        fila = QHBoxLayout()
        fila.addWidget(boton_anadir)
        fila.addWidget(boton_quitar)
        fila.addStretch()
        pestana = QWidget()
        columna = QVBoxLayout(pestana)
        columna.addWidget(ayuda)
        columna.addWidget(self.tabla_glosario, 1)
        columna.addLayout(fila)
        return pestana

    def anadir_termino(self, termino: str, traduccion: str) -> None:
        fila = self.tabla_glosario.rowCount()
        self.tabla_glosario.insertRow(fila)
        elemento = QTableWidgetItem(termino)
        self.tabla_glosario.setItem(fila, 0, elemento)
        self.tabla_glosario.setItem(fila, 1, QTableWidgetItem(traduccion))
        if not termino:
            self.tabla_glosario.editItem(elemento)

    def _glosario(self) -> Glosario:
        terminos = []
        for fila in range(self.tabla_glosario.rowCount()):
            termino, traduccion = (self.tabla_glosario.item(fila, c) for c in (0, 1))
            if termino and traduccion and termino.text().strip() and traduccion.text().strip():
                terminos.append((termino.text().strip(), traduccion.text().strip()))
        return Glosario(tuple(terminos))

    @staticmethod
    def _quitar_fila(tabla: QTableWidget) -> None:
        if tabla.currentRow() >= 0:
            tabla.removeRow(tabla.currentRow())

    # Carga y guardado

    def _rellenar(self, perfil: Perfil) -> None:
        self.hablante.setCurrentIndex(self.hablante.findData(perfil.voz.hablante.value))
        self.velocidad.setValue(round(perfil.voz.velocidad * 100))
        self.texto_velocidad.setText(_veces(perfil.voz.velocidad))
        self.modo.setCurrentIndex(self.modo.findData(perfil.lectura.modo.value))
        self.pausa.setValue(perfil.lectura.pausa_s)
        self._actualizar_pausa()
        self.bajar.setChecked(perfil.volumen.activo)
        self.nivel.setEnabled(perfil.volumen.activo)
        self.nivel.setValue(round(perfil.volumen.nivel_juego * 100))
        self.texto_nivel.setText(f"{self.nivel.value()} %")
        for nombre, nivel in perfil.volumen.otras:
            self.anadir_aplicacion(nombre, SILENCIAR if nivel == 0 else BAJAR, nivel)
        for nombre in perfil.volumen.excluir:
            self.anadir_aplicacion(nombre, NO_TOCAR)
        for termino, traduccion in perfil.glosario.terminos:
            self.anadir_termino(termino, traduccion)
        self.subtitulos.setChecked(perfil.subtitulos.activo)
        self.posicion.setCurrentIndex(self.posicion.findData(perfil.subtitulos.posicion.value))
        self.tamano.setValue(perfil.subtitulos.tamano)
        self.opacidad.setValue(round(perfil.subtitulos.opacidad * 100))
        self.texto_opacidad.setText(f"{self.opacidad.value()} %")
        self._actualizar_subtitulos()

    def guardar(self) -> None:
        """Guarda los ajustes y limpia de la caché lo que ya no vale con ellos."""
        try:
            lectura = AjustesLectura(ModoLectura(self.modo.currentData()), self.pausa.value())
            nuevo = replace(
                self._perfil,
                voz=self._voz(),
                lectura=lectura,
                volumen=self._volumen(),
                glosario=self._glosario(),
                subtitulos=self._subtitulos(),
            )
            self._almacen.guardar(nuevo)
        except (PerfilInvalidoError, ValueError) as error:
            self.error.setText(str(error))
            return
        self._limpiar_cache(nuevo)
        self.guardado = nuevo
        self.accept()

    def _limpiar_cache(self, nuevo: Perfil) -> None:
        voz_cambiada = nuevo.voz != self._perfil.voz
        glosario_cambiado = nuevo.glosario != self._perfil.glosario
        retraducir = glosario_cambiado and self._preguntar_retraducir()
        if not (voz_cambiada or retraducir):
            return
        cache = self._abrir_cache()
        try:
            if retraducir:
                cache.invalidar(nuevo.id)  # borra traducciones y audio
            else:
                cache.borrar_audio(nuevo.id)  # el audio guardado es de la voz anterior
        finally:
            cache.cerrar()

    def _preguntar_retraducir(self) -> bool:
        respuesta = QMessageBox.question(
            self,
            _("Glosario cambiado"),
            _(
                "Las líneas ya traducidas no usan el glosario nuevo.\n\n"
                "¿Borrar sus traducciones guardadas para que se vuelvan a traducir al jugar?"
            ),
        )
        return respuesta == QMessageBox.StandardButton.Yes
