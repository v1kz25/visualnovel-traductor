"""Editor de un juego: ventana, zona de texto dibujada sobre una captura, idiomas y aspecto del texto."""

import logging
import threading
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, Imagen, Rectangulo, Ventana
from vn_audiolibro.descargas import asegurar_descarga
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR
from vn_audiolibro.ocr.modelos import REC_PPOCRV5_MOBILE
from vn_audiolibro.ocr.preprocesado import Orientacion
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles, PerfilDuplicadoError
from vn_audiolibro.perfiles.modelos import DESTINOS, IDIOMAS, Color, Perfil, PerfilInvalidoError
from vn_audiolibro.plataforma import capturador, gestor_ventanas
from vn_audiolibro.procesos import pids_propios
from vn_audiolibro.ui.zona import SelectorZona

_registro = logging.getLogger(__name__)

NOMBRES_IDIOMAS = {"zh-Hant": "Chino tradicional", "zh-Hans": "Chino simplificado", "ja": "Japonés"}
NOMBRES_DESTINOS = {"es": "español", "en": "inglés"}
NOMBRES_COLORES = {Color.CLARO: "Claro sobre fondo oscuro", Color.OSCURO: "Oscuro sobre fondo claro"}
NOMBRES_ORIENTACIONES = {Orientacion.HORIZONTAL: "Horizontal", Orientacion.VERTICAL: "Vertical (columnas)"}

AYUDA_ZONA = "Captura la ventana y dibuja con el ratón un recuadro sobre la caja de texto."

ListarVentanas = Callable[[], list[Ventana]]
CapturarVentana = Callable[[Ventana], Imagen]
LeerZona = Callable[[Imagen, AjustesLector], str]


def listar_ventanas() -> list[Ventana]:
    """Ventanas abiertas, sin las de esta app ni la terminal desde la que se lanzó."""
    propios = pids_propios()
    return [ventana for ventana in gestor_ventanas().listar() if ventana.pid not in propios]


def capturar_ventana(ventana: Ventana) -> Imagen:
    """Captura completa de la ventana, aunque tenga otras encima (si hay compositor)."""
    gestor = gestor_ventanas()
    geometria = gestor.geometria(ventana.id)
    return capturador(gestor).capturar(ventana.id, Rectangulo(0, 0, geometria.ancho, geometria.alto))


class LectorBajoDemanda:
    """OCR que carga el modelo la primera vez que se usa (tarda un poco) y lo reutiliza."""

    def __init__(self) -> None:
        self._reconocedor: ReconocedorRapidOCR | None = None
        self._cerrojo = threading.Lock()

    def __call__(self, imagen: Imagen, ajustes: AjustesLector) -> str:
        with self._cerrojo:
            if self._reconocedor is None:
                self._reconocedor = ReconocedorRapidOCR(asegurar_descarga(REC_PPOCRV5_MOBILE))
            return LectorOCR(self._reconocedor, ajustes).leer(imagen).texto


class EditorJuego(QDialog):
    """Añade un juego nuevo o edita uno existente.

    Al editar, solo cambia lo que se ve aquí: la voz, el volumen, el glosario y la lectura se
    conservan, y también el identificador (y con él la caché del juego).
    """

    texto_leido = Signal(str)

    def __init__(
        self,
        almacen: AlmacenPerfiles,
        perfil: Perfil | None = None,
        listar: ListarVentanas = listar_ventanas,
        capturar: CapturarVentana = capturar_ventana,
        leer: LeerZona | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar juego" if perfil else "Añadir juego")
        self.resize(760, 640)
        self._almacen = almacen
        self._original = perfil
        self._listar = listar
        self._capturar = capturar
        self._leer = leer or LectorBajoDemanda()
        self._captura: Imagen | None = None
        self.guardado: Perfil | None = None
        self._crear_widgets()
        self._conectar()
        self.actualizar_ventanas()
        if perfil is not None:
            self._rellenar(perfil)
        self._actualizar_botones()

    # Construcción

    def _crear_widgets(self) -> None:
        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Cómo lo verás en la lista")
        self.ventanas = QComboBox()
        self.boton_actualizar = QPushButton("Actualizar")
        self.titulo = QLineEdit()
        self.titulo.setPlaceholderText("Parte del título de la ventana que la identifica")
        self.idioma = QComboBox()
        for codigo in IDIOMAS:
            self.idioma.addItem(NOMBRES_IDIOMAS.get(codigo, codigo), codigo)
        self.destino = QComboBox()
        for codigo in DESTINOS:
            self.destino.addItem(NOMBRES_DESTINOS.get(codigo, codigo).capitalize(), codigo)
        self.color = QComboBox()
        # Qt convierte los enum de texto en `str`: se guarda el valor y se convierte al leerlo.
        for color, texto in NOMBRES_COLORES.items():
            self.color.addItem(texto, color.value)
        self.orientacion = QComboBox()
        for orientacion, texto in NOMBRES_ORIENTACIONES.items():
            self.orientacion.addItem(texto, orientacion.value)

        fila_ventana = QHBoxLayout()
        fila_ventana.addWidget(self.ventanas, 1)
        fila_ventana.addWidget(self.boton_actualizar)
        formulario = QFormLayout()
        formulario.addRow("Nombre", self.nombre)
        formulario.addRow("Ventana del juego", fila_ventana)
        formulario.addRow("Buscar por el título", self.titulo)
        formulario.addRow("Idioma del juego", self.idioma)
        formulario.addRow("Traducir y leer en", self.destino)
        formulario.addRow("Texto", self.color)
        formulario.addRow("Orientación", self.orientacion)

        self.boton_capturar = QPushButton("Capturar ventana")
        self.boton_probar = QPushButton("Probar OCR")
        self.boton_toda = QPushButton("Toda la ventana")
        self.selector = SelectorZona()
        self.resultado = QLabel(AYUDA_ZONA)
        self.resultado.setWordWrap(True)
        self.resultado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        self.error.setWordWrap(True)
        botones = QDialogButtonBox.StandardButton
        self.botones = QDialogButtonBox(botones.Save | botones.Cancel)

        fila_zona = QHBoxLayout()
        for boton in (self.boton_capturar, self.boton_probar, self.boton_toda):
            fila_zona.addWidget(boton)
        fila_zona.addStretch()
        columna = QVBoxLayout(self)
        columna.addLayout(formulario)
        columna.addWidget(QLabel("<b>Zona de texto</b>"))
        columna.addLayout(fila_zona)
        columna.addWidget(self.selector, 1)
        columna.addWidget(self.resultado)
        columna.addWidget(self.error)
        columna.addWidget(self.botones)

    def _conectar(self) -> None:
        self.boton_actualizar.clicked.connect(self.actualizar_ventanas)
        self.ventanas.activated.connect(lambda _: self._al_elegir_ventana())
        self.titulo.textChanged.connect(lambda _: self._actualizar_botones())
        self.nombre.textChanged.connect(lambda _: self._actualizar_botones())
        self.boton_capturar.clicked.connect(self.capturar)
        self.boton_probar.clicked.connect(self.probar_ocr)
        self.boton_toda.clicked.connect(lambda: self.selector.poner_zona(TODA_LA_VENTANA))
        self.selector.zona_cambiada.connect(lambda _: self._actualizar_botones())
        self.texto_leido.connect(self._mostrar_texto)
        self.botones.accepted.connect(self.guardar)
        self.botones.rejected.connect(self.reject)

    def _rellenar(self, perfil: Perfil) -> None:
        self.nombre.setText(perfil.nombre)
        self.titulo.setText(perfil.ventana)
        self._elegir(self.idioma, perfil.idioma)
        self._elegir(self.destino, perfil.destino)
        self._elegir(self.color, perfil.color.value)
        self._elegir(self.orientacion, perfil.orientacion.value)
        self.selector.poner_zona(perfil.zona)
        buscado = perfil.ventana.casefold()
        for i in range(self.ventanas.count()):
            ventana = self.ventanas.itemData(i)
            if isinstance(ventana, Ventana) and buscado in ventana.titulo.casefold():
                self.ventanas.setCurrentIndex(i)
                break

    @staticmethod
    def _elegir(combo: QComboBox, valor: object) -> None:
        indice = combo.findData(valor)
        if indice >= 0:
            combo.setCurrentIndex(indice)

    # Ventana y zona

    def actualizar_ventanas(self) -> None:
        """Vuelve a listar las ventanas abiertas, conservando la elegida si sigue abierta."""
        anterior = self.ventana_elegida()
        self.ventanas.clear()
        try:
            ventanas = self._listar()
        except Exception as error:
            _registro.exception("No se pudieron listar las ventanas")
            self.error.setText(f"No se pudieron listar las ventanas: {error}")
            ventanas = []
        for ventana in ventanas:
            self.ventanas.addItem(f"{ventana.titulo}  (proceso {ventana.pid})", ventana)
            if anterior is not None and ventana.id == anterior.id:
                self.ventanas.setCurrentIndex(self.ventanas.count() - 1)
        self._actualizar_botones()

    def ventana_elegida(self) -> Ventana | None:
        ventana = self.ventanas.currentData()
        return ventana if isinstance(ventana, Ventana) else None

    def _al_elegir_ventana(self) -> None:
        ventana = self.ventana_elegida()
        if ventana is not None:
            self.titulo.setText(ventana.titulo)
            if not self.nombre.text().strip():
                self.nombre.setText(ventana.titulo)
        self._actualizar_botones()

    def capturar(self) -> None:
        ventana = self.ventana_elegida()
        if ventana is None:
            return
        try:
            self._captura = self._capturar(ventana)
        except Exception as error:
            _registro.exception("No se pudo capturar la ventana")
            self.error.setText(f"No se pudo capturar la ventana: {error}")
            return
        self.error.clear()
        self.selector.mostrar(self._captura)
        self._actualizar_botones()

    def probar_ocr(self) -> None:
        """Lee el texto de la zona en segundo plano (la primera vez carga el modelo)."""
        recorte = self._recorte()
        if recorte is None:
            return
        ajustes = AjustesLector(self.idioma.currentData(), self._color().color_texto, self._orientacion())
        self.boton_probar.setEnabled(False)
        self.resultado.setText("Leyendo…")

        def leer() -> None:
            try:
                texto = self._leer(recorte, ajustes) or "(no se ha reconocido texto en la zona)"
            except Exception as error:
                _registro.exception("Falló el OCR de prueba")
                texto = f"No se pudo leer: {error}"
            self.texto_leido.emit(texto)

        threading.Thread(target=leer, name="ocr-prueba", daemon=True).start()

    def _mostrar_texto(self, texto: str) -> None:
        self.resultado.setText(f"Texto leído: {texto}")
        self._actualizar_botones()

    def _recorte(self) -> Imagen | None:
        if self._captura is None:
            return None
        zona = self.selector.zona or TODA_LA_VENTANA
        alto, ancho = self._captura.shape[:2]
        r = zona.en_pixeles(ancho, alto)
        return self._captura[r.y : r.y + r.alto, r.x : r.x + r.ancho]

    def _color(self) -> Color:
        return Color(self.color.currentData())

    def _orientacion(self) -> Orientacion:
        return Orientacion(self.orientacion.currentData())

    # Guardado

    def guardar(self) -> None:
        """Guarda el juego y cierra; si algo no vale, lo indica y deja seguir editando."""
        nombre, ventana = self.nombre.text().strip(), self.titulo.text().strip()
        try:
            perfil = replace(
                self._original or Perfil(nombre, ventana),
                nombre=nombre,
                ventana=ventana,
                idioma=self.idioma.currentData(),
                destino=self.destino.currentData(),
                zona=self.selector.zona or TODA_LA_VENTANA,
                color=self._color(),
                orientacion=self._orientacion(),
            )
            self._almacen.guardar(perfil)
        except (PerfilInvalidoError, PerfilDuplicadoError) as error:
            self.error.setText(str(error))
            return
        self.guardado = perfil
        self.accept()

    def _actualizar_botones(self) -> None:
        self.boton_capturar.setEnabled(self.ventana_elegida() is not None)
        self.boton_probar.setEnabled(self._captura is not None)
        self.boton_toda.setEnabled(self.selector.hay_imagen)
        guardar = self.botones.button(QDialogButtonBox.StandardButton.Save)
        guardar.setEnabled(bool(self.nombre.text().strip() and self.titulo.text().strip()))
