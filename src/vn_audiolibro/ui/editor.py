"""Editor de un juego: ventana, zona de texto dibujada sobre una captura, idiomas y aspecto del texto."""

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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
from vn_audiolibro.guion.modelos import GuionNoEncontradoError, OrigenGuion
from vn_audiolibro.guion.outputline import carpeta_scripts, leer_guion
from vn_audiolibro.ocr.lector import AjustesLector, LectorOCR
from vn_audiolibro.ocr.modelos import DET_PPOCRV5_MOBILE, REC_PPOCRV5_MOBILE
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.ocr.reconocedor import ReconocedorRapidOCR
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles, PerfilDuplicadoError
from vn_audiolibro.perfiles.modelos import (
    DESTINOS,
    IDIOMAS,
    INGLES,
    AjustesGuion,
    Color,
    Perfil,
    PerfilInvalidoError,
)
from vn_audiolibro.plataforma import capturador, carpeta_de_proceso, gestor_ventanas
from vn_audiolibro.procesos import pids_propios
from vn_audiolibro.textos import N_, _, ngettext
from vn_audiolibro.ui.zona import SelectorZona

_registro = logging.getLogger(__name__)

# Se traducen al mostrarlos, con `_()`.
NOMBRES_IDIOMAS = {
    "zh-Hant": N_("Chino tradicional"),
    "zh-Hans": N_("Chino simplificado"),
    "ja": N_("Japonés"),
    "en": N_("Inglés"),
}
NOMBRES_DESTINOS = {"es": N_("Español"), "en": N_("Inglés")}
NOMBRES_COLORES = {Color.CLARO: N_("Claro sobre fondo oscuro"), Color.OSCURO: N_("Oscuro sobre fondo claro")}
NOMBRES_ORIENTACIONES = {
    Orientacion.HORIZONTAL: N_("Horizontal"),
    Orientacion.VERTICAL: N_("Vertical (columnas)"),
}
NOMBRES_BUSQUEDAS = {
    BusquedaTexto.COLOR: N_("Por color (caja de texto lisa)"),
    BusquedaTexto.DETECTOR: N_("Con el detector (texto sobre la imagen)"),
}

NOMBRES_ORIGENES = {
    OrigenGuion.ORIGINAL: N_("El texto del juego"),
    OrigenGuion.INGLES: N_("La traducción oficial al inglés del guion"),
}
AYUDA_GUION = N_(
    "Opcional. Si el juego guarda su guion en ficheros legibles, elige su carpeta: el texto sale "
    "exacto del guion, se traduce por adelantado y el OCR solo sirve para saber por dónde vas."
)
STEAM = Path.home() / ".local" / "share" / "Steam" / "steamapps" / "common"

AYUDA_BUSQUEDA = N_(
    "Por color va bien con una caja de texto lisa. Si el juego escribe el texto directamente sobre "
    "la imagen y el OCR lee mal o nada, usa el detector: es más lento y la primera vez descarga "
    "un modelo de 5 MB."
)

AYUDA_ZONA = N_("Captura la ventana y dibuja con el ratón un recuadro sobre la caja de texto.")

ListarVentanas = Callable[[], list[Ventana]]
CapturarVentana = Callable[[Ventana], Imagen]
LeerZona = Callable[[Imagen, AjustesLector], str]
CarpetaJuego = Callable[[int], Path | None]
"""Carpeta del juego a partir del proceso de su ventana."""
ElegirCarpeta = Callable[[QWidget, str], str]
"""Pide una carpeta al usuario partiendo de la indicada; cadena vacía si cancela."""


def elegir_carpeta(padre: QWidget, desde: str) -> str:
    """Diálogo del sistema para elegir la carpeta del juego."""
    inicio = desde or (str(STEAM) if STEAM.is_dir() else str(Path.home()))
    return QFileDialog.getExistingDirectory(padre, _("Carpeta del juego"), inicio)


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
    """OCR que carga el modelo la primera vez que se usa (tarda un poco) y lo reutiliza.

    El detector solo se descarga y se carga cuando se prueba un juego que lo usa.
    """

    def __init__(self) -> None:
        self._reconocedor: ReconocedorRapidOCR | None = None
        self._cerrojo = threading.Lock()

    def __call__(self, imagen: Imagen, ajustes: AjustesLector) -> str:
        with self._cerrojo:
            con_detector = ajustes.busqueda is BusquedaTexto.DETECTOR
            if self._reconocedor is None or (con_detector and not self._reconocedor.con_detector):
                detector = asegurar_descarga(DET_PPOCRV5_MOBILE) if con_detector else None
                self._reconocedor = ReconocedorRapidOCR(asegurar_descarga(REC_PPOCRV5_MOBILE), detector)
            reconocedor = self._reconocedor
            return LectorOCR(reconocedor, ajustes, reconocedor if con_detector else None).leer(imagen).texto


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
        pedir_carpeta: ElegirCarpeta = elegir_carpeta,
        carpeta_juego: CarpetaJuego = carpeta_de_proceso,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Editar juego") if perfil else _("Añadir juego"))
        self.resize(760, 720)
        self._almacen = almacen
        self._original = perfil
        self._listar = listar
        self._capturar = capturar
        self._leer = leer or LectorBajoDemanda()
        self._pedir_carpeta = pedir_carpeta
        self._carpeta_juego = carpeta_juego
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
        self.nombre.setPlaceholderText(_("Cómo lo verás en la lista"))
        self.ventanas = QComboBox()
        self.boton_actualizar = QPushButton(_("Actualizar"))
        self.titulo = QLineEdit()
        self.titulo.setPlaceholderText(_("Parte del título de la ventana que la identifica"))
        self.idioma = QComboBox()
        for codigo in IDIOMAS:
            self.idioma.addItem(_(NOMBRES_IDIOMAS.get(codigo, codigo)), codigo)
        self.destino = QComboBox()
        for codigo in DESTINOS:
            self.destino.addItem(_(NOMBRES_DESTINOS.get(codigo, codigo)), codigo)
        self.color = QComboBox()
        # Qt convierte los enum de texto en `str`: se guarda el valor y se convierte al leerlo.
        for color, texto in NOMBRES_COLORES.items():
            self.color.addItem(_(texto), color.value)
        self.orientacion = QComboBox()
        for orientacion, texto in NOMBRES_ORIENTACIONES.items():
            self.orientacion.addItem(_(texto), orientacion.value)
        self.busqueda = QComboBox()
        for busqueda, texto in NOMBRES_BUSQUEDAS.items():
            self.busqueda.addItem(_(texto), busqueda.value)
        self.busqueda.setToolTip(_(AYUDA_BUSQUEDA))
        self.carpeta_guion = QLineEdit()
        self.carpeta_guion.setPlaceholderText(_("Ninguno: solo OCR"))
        self.boton_guion = QPushButton(_("Elegir…"))
        self.origen_guion = QComboBox()
        for origen, texto in NOMBRES_ORIGENES.items():
            self.origen_guion.addItem(_(texto), origen.value)
        self.estado_guion = QLabel(_(AYUDA_GUION))
        self.estado_guion.setWordWrap(True)

        fila_guion = QHBoxLayout()
        fila_guion.addWidget(self.carpeta_guion, 1)
        fila_guion.addWidget(self.boton_guion)
        fila_ventana = QHBoxLayout()
        fila_ventana.addWidget(self.ventanas, 1)
        fila_ventana.addWidget(self.boton_actualizar)
        formulario = QFormLayout()
        formulario.addRow(_("Nombre"), self.nombre)
        formulario.addRow(_("Ventana del juego"), fila_ventana)
        formulario.addRow(_("Buscar por el título"), self.titulo)
        formulario.addRow(_("Idioma del juego"), self.idioma)
        formulario.addRow(_("Traducir y leer en"), self.destino)
        formulario.addRow(_("Texto"), self.color)
        formulario.addRow(_("Orientación"), self.orientacion)
        formulario.addRow(_("Buscar el texto"), self.busqueda)
        formulario.addRow(_("Guion del juego"), fila_guion)
        formulario.addRow(_("Traducir desde"), self.origen_guion)
        formulario.addRow("", self.estado_guion)

        self.boton_capturar = QPushButton(_("Capturar ventana"))
        self.boton_probar = QPushButton(_("Probar OCR"))
        self.boton_toda = QPushButton(_("Toda la ventana"))
        self.selector = SelectorZona()
        self.resultado = QLabel(_(AYUDA_ZONA))
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
        columna.addWidget(QLabel(f"<b>{_('Zona de texto')}</b>"))
        columna.addLayout(fila_zona)
        columna.addWidget(self.selector, 1)
        columna.addWidget(self.resultado)
        columna.addWidget(self.error)
        columna.addWidget(self.botones)

    def _conectar(self) -> None:
        self.boton_actualizar.clicked.connect(self.actualizar_ventanas)
        self.idioma.currentIndexChanged.connect(lambda _: self._al_cambiar_idioma())
        self.ventanas.activated.connect(lambda _: self._al_elegir_ventana())
        self.titulo.textChanged.connect(lambda _: self._actualizar_botones())
        self.nombre.textChanged.connect(lambda _: self._actualizar_botones())
        self.boton_capturar.clicked.connect(self.capturar)
        self.boton_probar.clicked.connect(self.probar_ocr)
        self.boton_toda.clicked.connect(lambda: self.selector.poner_zona(TODA_LA_VENTANA))
        self.selector.zona_cambiada.connect(lambda _: self._actualizar_botones())
        self.texto_leido.connect(self._mostrar_texto)
        self.boton_guion.clicked.connect(self.elegir_guion)
        self.carpeta_guion.editingFinished.connect(self.comprobar_guion)
        self.botones.accepted.connect(self.guardar)
        self.botones.rejected.connect(self.reject)

    def _rellenar(self, perfil: Perfil) -> None:
        self.nombre.setText(perfil.nombre)
        self.titulo.setText(perfil.ventana)
        self._elegir(self.idioma, perfil.idioma)
        self._elegir(self.destino, perfil.destino)
        self._elegir(self.color, perfil.color.value)
        self._elegir(self.orientacion, perfil.orientacion.value)
        self._elegir(self.busqueda, perfil.busqueda.value)
        self.selector.poner_zona(perfil.zona)
        if perfil.guion is not None:
            self.carpeta_guion.setText(perfil.guion.carpeta)
            self._elegir(self.origen_guion, perfil.guion.origen.value)
            self.comprobar_guion()
        buscado = perfil.ventana.casefold()
        for i in range(self.ventanas.count()):
            ventana = self.ventanas.itemData(i)
            if isinstance(ventana, Ventana) and buscado in ventana.titulo.casefold():
                self.ventanas.setCurrentIndex(i)
                self._buscar_guion(ventana)
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
            self.error.setText(_("No se pudieron listar las ventanas: {error}").format(error=error))
            ventanas = []
        for ventana in ventanas:
            self.ventanas.addItem(
                _("{titulo}  (proceso {pid})").format(titulo=ventana.titulo, pid=ventana.pid), ventana
            )
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
            self._buscar_guion(ventana)
        self._actualizar_botones()

    def _buscar_guion(self, ventana: Ventana) -> None:
        """Si aún no hay guion elegido y la carpeta del juego tiene uno, lo propone."""
        if self.carpeta_guion.text().strip() or ventana.pid is None:
            return
        carpeta = self._carpeta_juego(ventana.pid)
        if carpeta is not None and carpeta_scripts(carpeta) is not None:
            self.carpeta_guion.setText(str(carpeta))
            self.comprobar_guion()

    def capturar(self) -> None:
        ventana = self.ventana_elegida()
        if ventana is None:
            return
        try:
            self._captura = self._capturar(ventana)
        except Exception as error:
            _registro.exception("No se pudo capturar la ventana")
            self.error.setText(_("No se pudo capturar la ventana: {error}").format(error=error))
            return
        self.error.clear()
        self.selector.mostrar(self._captura)
        self._actualizar_botones()

    def probar_ocr(self) -> None:
        """Lee el texto de la zona en segundo plano (la primera vez carga el modelo)."""
        recorte = self._recorte()
        if recorte is None:
            return
        ajustes = AjustesLector(
            self.idioma.currentData(), self._color().color_texto, self._orientacion(), self._busqueda()
        )
        self.boton_probar.setEnabled(False)
        self.resultado.setText(_("Leyendo…"))

        def leer() -> None:
            try:
                texto = self._leer(recorte, ajustes) or _("(no se ha reconocido texto en la zona)")
            except Exception as error:
                _registro.exception("Falló el OCR de prueba")
                texto = _("No se pudo leer: {error}").format(error=error)
            self.texto_leido.emit(texto)

        threading.Thread(target=leer, name="ocr-prueba", daemon=True).start()

    def _mostrar_texto(self, texto: str) -> None:
        self.resultado.setText(_("Texto leído: {texto}").format(texto=texto))
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

    def _busqueda(self) -> BusquedaTexto:
        return BusquedaTexto(self.busqueda.currentData())

    # Guion

    def elegir_guion(self) -> None:
        carpeta = self._pedir_carpeta(self, self.carpeta_guion.text().strip())
        if carpeta:
            self.carpeta_guion.setText(carpeta)
            self.comprobar_guion()

    def comprobar_guion(self) -> None:
        """Lee el guion de la carpeta elegida y dice si se ha encontrado y cuánto texto tiene."""
        carpeta = self.carpeta_guion.text().strip()
        self.origen_guion.setEnabled(bool(carpeta))
        if not carpeta:
            self.estado_guion.setText(_(AYUDA_GUION))
            return
        try:
            guion = leer_guion(Path(carpeta))
        except GuionNoEncontradoError as error:
            self.estado_guion.setText(str(error))
            return
        n = len(guion.parrafos)
        if guion.tiene_ingles:
            texto = ngettext(
                "Guion encontrado: {n} párrafo, con la traducción oficial al inglés.",
                "Guion encontrado: {n} párrafos, con la traducción oficial al inglés.",
                n,
            )
        else:
            texto = ngettext("Guion encontrado: {n} párrafo.", "Guion encontrado: {n} párrafos.", n)
        self.estado_guion.setText(texto.format(n=n))

    def _guion(self) -> AjustesGuion | None:
        carpeta = self.carpeta_guion.text().strip()
        if not carpeta:
            return None
        return AjustesGuion(carpeta, OrigenGuion(self.origen_guion.currentData()))

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
                busqueda=self._busqueda(),
                guion=self._guion(),
            )
            self._almacen.guardar(perfil)
        except (PerfilInvalidoError, PerfilDuplicadoError) as error:
            self.error.setText(str(error))
            return
        self.guardado = perfil
        self.accept()

    def _al_cambiar_idioma(self) -> None:
        """Un juego en inglés solo se traduce al español y en horizontal: se fijan y se bloquean."""
        ingles = self.idioma.currentData() == INGLES
        if ingles:
            self._elegir(self.destino, DESTINOS[0])
            self._elegir(self.orientacion, Orientacion.HORIZONTAL.value)
        self.destino.setEnabled(not ingles)
        self.orientacion.setEnabled(not ingles)

    def _actualizar_botones(self) -> None:
        self.origen_guion.setEnabled(bool(self.carpeta_guion.text().strip()))
        self.boton_capturar.setEnabled(self.ventana_elegida() is not None)
        self.boton_probar.setEnabled(self._captura is not None)
        self.boton_toda.setEnabled(self.selector.hay_imagen)
        guardar = self.botones.button(QDialogButtonBox.StandardButton.Save)
        guardar.setEnabled(bool(self.nombre.text().strip() and self.titulo.text().strip()))
