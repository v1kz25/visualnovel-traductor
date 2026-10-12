"""Ventana principal: elegir un juego, jugar y ver cada línea con su traducción.

En la interfaz los perfiles se llaman «juegos»: es lo que el usuario configura.
"""

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from vn_audiolibro import plataforma, textos
from vn_audiolibro.actualizaciones import Consultar, consultar_github, version_instalada
from vn_audiolibro.atajos.modelos import Accion, AtajoNoValidoError, EscuchaAtajos, leer_atajos
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.configuracion import cargar_ajustes, guardar_ajustes
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego
from vn_audiolibro.textos import N_, _
from vn_audiolibro.ui.ajustes import AjustesJuego
from vn_audiolibro.ui.atajos import DialogoAtajos
from vn_audiolibro.ui.cache import VentanaCache
from vn_audiolibro.ui.editor import EditorJuego
from vn_audiolibro.ui.guion import TraducirGuion
from vn_audiolibro.ui.puente import PuenteSesion
from vn_audiolibro.ui.subtitulos import PantallaSubtitulos, abrir_subtitulos
from vn_audiolibro.ui.versiones import AvisoVersion, BuscadorVersiones, preguntar_si_avisar

_registro = logging.getLogger(__name__)

TITULO = "vn-audiolibro"
MAX_LINEAS = 500
"""Líneas que se conservan en el historial de la partida."""
AVISO_IDIOMA = N_("El idioma cambiará la próxima vez que abras vn-audiolibro.")
"""Se muestra en el idioma recién elegido."""

AbrirCache = Callable[[], CacheSQLite]
AbrirEditor = Callable[[QWidget, AlmacenPerfiles, Perfil | None], EditorJuego]
AbrirAjustes = Callable[[QWidget, AlmacenPerfiles, Perfil], AjustesJuego]
AbrirVentanaCache = Callable[[QWidget, AlmacenPerfiles], VentanaCache]
AbrirTraduccionGuion = Callable[[QWidget, Perfil], QDialog]


def _html(linea: LineaJuego) -> str:
    """Una línea del historial: el original pequeño y en gris, la traducción debajo y más grande."""
    normal = linea.leida or linea.silenciada  # con la voz silenciada, el texto es lo que se lee
    sufijo = "" if normal else f' <span style="color: gray">{escape(_("(no leída)"))}</span>'
    color = "" if normal else " color: gray;"  # las no leídas, apagadas
    traduccion = _lineas_html(linea.traduccion_con_personaje)
    return (
        f'<p style="margin: 8px 0 0 0; color: gray">{_lineas_html(linea.original)}</p>'
        f'<p style="margin: 0; font-size: large;{color}">{traduccion}{sufijo}</p>'
    )


def _lineas_html(texto: str) -> str:
    """El texto escapado, con sus saltos de línea (las opciones de un menú van una por línea)."""
    return escape(texto).replace("\n", "<br>")


class VentanaPrincipal(QMainWindow):
    """Lista de juegos a la izquierda; la partida en curso a la derecha."""

    atajo = Signal(str)
    """Acción de un atajo global; se emite desde el hilo de los atajos y se atiende en el de Qt."""

    def __init__(
        self,
        almacen: AlmacenPerfiles,
        puente: PuenteSesion | None = None,
        abrir_cache: AbrirCache = CacheSQLite,
        abrir_editor: AbrirEditor | None = None,
        abrir_ajustes: AbrirAjustes | None = None,
        abrir_ventana_cache: AbrirVentanaCache | None = None,
        ruta_ajustes: Path | None = None,
        subtitulos: Callable[[Perfil], PantallaSubtitulos | None] = abrir_subtitulos,
        consultar_version: Consultar = consultar_github,
        abrir_traduccion_guion: AbrirTraduccionGuion | None = None,
        escucha_atajos: Callable[[], EscuchaAtajos] | None = None,
    ) -> None:
        super().__init__()
        self._crear_escucha = escucha_atajos or (lambda: plataforma.escucha_atajos())
        self._escucha: EscuchaAtajos | None = None
        self._minimizada_al_jugar = False
        self._abrir_traduccion_guion = abrir_traduccion_guion or (
            lambda padre, perfil: TraducirGuion(perfil, parent=padre)
        )
        self.buscador_versiones = BuscadorVersiones(
            version_instalada(), consultar_version, ruta_ajustes, parent=self
        )
        self._crear_subtitulos = subtitulos
        self._subtitulos: PantallaSubtitulos | None = None
        self._ruta_ajustes = ruta_ajustes
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
        self.boton_jugar = QPushButton(_("Jugar"))
        self.boton_anadir = QPushButton(_("Añadir juego"))
        self.boton_editar = QPushButton(_("Editar"))
        self.boton_ajustes = QPushButton(_("Ajustes"))
        self.boton_borrar = QPushButton(_("Borrar"))
        self.boton_cache = QPushButton(_("Caché…"))
        self.boton_atajos = QPushButton(_("Atajos de teclado…"))
        self.boton_guion = QPushButton(_("Traducir el guion…"))
        self.boton_guion.setToolTip(
            _("Traduce entero el guion del juego antes de jugar (solo en los juegos con guion).")
        )

        izquierda = QWidget()
        columna = QVBoxLayout(izquierda)
        columna.addWidget(QLabel(f"<b>{_('Juegos')}</b>"))
        columna.addWidget(self.lista_perfiles)
        columna.addWidget(self.boton_jugar)
        fila = QHBoxLayout()
        for boton in (self.boton_anadir, self.boton_editar, self.boton_ajustes, self.boton_borrar):
            fila.addWidget(boton)
        columna.addLayout(fila)
        columna.addWidget(self.boton_guion)
        fila = QHBoxLayout()
        fila.addWidget(self.boton_cache)
        fila.addWidget(self.boton_atajos)
        columna.addLayout(fila)
        self.idioma = QComboBox()
        self.idioma.addItem(_("El del sistema"), None)
        for codigo in textos.disponibles():
            self.idioma.addItem(textos.nombre_idioma(codigo), codigo)
        self.idioma.setCurrentIndex(max(self.idioma.findData(cargar_ajustes(self._ruta_ajustes).idioma), 0))
        fila = QHBoxLayout()
        fila.addWidget(QLabel(_("Idioma de la app")))
        fila.addWidget(self.idioma, 1)
        columna.addLayout(fila)
        self.avisar_versiones = QCheckBox(_("Avisar de versiones nuevas"))
        self.avisar_versiones.setToolTip(
            _("Al abrir la app, consulta en GitHub como mucho una vez al día si hay una versión nueva.")
        )
        self.avisar_versiones.setChecked(cargar_ajustes(self._ruta_ajustes).avisar_versiones is True)
        columna.addWidget(self.avisar_versiones)

        self.estado = QLabel(_("Elige un juego y pulsa Jugar."))
        self.estado.setWordWrap(True)
        self.historial = QTextBrowser()
        self._lineas: deque[LineaJuego] = deque(maxlen=MAX_LINEAS)
        self._seguir_final = True
        """Si el historial baja solo al crecer; deja de hacerlo si el usuario sube a releer."""
        self.boton_pausa = QPushButton(_("Pausa (P)"))
        self.boton_repetir = QPushButton(_("Repetir (R)"))
        self.boton_saltar = QPushButton(_("Saltar (S)"))
        self.boton_detener = QPushButton(_("Detener"))
        self.silenciar = QCheckBox(_("Silenciar voz (M)"))
        self.silenciar.setToolTip(_("Sigue traduciendo y mostrando cada línea, pero sin leerla."))
        self.siempre_encima = QCheckBox(_("Mantener encima del juego"))
        self.solo_subtitulos = QCheckBox(_("Solo subtítulos: minimizar la app al jugar"))
        self.solo_subtitulos.setToolTip(
            _(
                "Al jugar, la app se minimiza y sobre el juego solo quedan los subtítulos. Controla "
                "la partida con los atajos de teclado y, al terminar, la app vuelve."
            )
        )
        self.solo_subtitulos.setChecked(cargar_ajustes(self._ruta_ajustes).solo_subtitulos)

        derecha = QWidget()
        columna = QVBoxLayout(derecha)
        columna.addWidget(self.estado)
        columna.addWidget(self.historial)
        fila = QHBoxLayout()
        for boton in (self.boton_pausa, self.boton_repetir, self.boton_saltar, self.boton_detener):
            fila.addWidget(boton)
        columna.addLayout(fila)
        columna.addWidget(self.silenciar)
        columna.addWidget(self.siempre_encima)
        columna.addWidget(self.solo_subtitulos)

        divisor = QSplitter()
        divisor.addWidget(izquierda)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(1, 3)
        self.aviso_version = AvisoVersion()
        central = QWidget()
        columna = QVBoxLayout(central)
        columna.addWidget(self.aviso_version)
        columna.addWidget(divisor, 1)
        self.setCentralWidget(central)

    def _conectar(self) -> None:
        self.boton_jugar.clicked.connect(self.jugar)
        self.lista_perfiles.itemDoubleClicked.connect(lambda _: self.jugar())
        self.lista_perfiles.currentRowChanged.connect(lambda _: self._actualizar_botones())
        self.boton_borrar.clicked.connect(self.borrar)
        self.boton_anadir.clicked.connect(lambda: self.editar(None))
        self.boton_editar.clicked.connect(lambda: self.editar(self.perfil_elegido()))
        self.boton_ajustes.clicked.connect(self.ajustar)
        self.boton_cache.clicked.connect(self.ver_cache)
        self.boton_guion.clicked.connect(self.traducir_guion)
        self.boton_atajos.clicked.connect(self.configurar_atajos)
        self.solo_subtitulos.toggled.connect(self._al_cambiar_solo_subtitulos)
        self.atajo.connect(self._al_atajo)
        self.boton_pausa.clicked.connect(self._alternar_pausa)
        self.boton_repetir.clicked.connect(self.puente.repetir)
        self.boton_saltar.clicked.connect(self.puente.saltar)
        self.boton_detener.clicked.connect(self.detener)
        self.silenciar.toggled.connect(self.puente.silenciar)
        self.siempre_encima.toggled.connect(self._mantener_encima)
        self.idioma.activated.connect(lambda _indice: self.cambiar_idioma(self.idioma.currentData()))
        self.avisar_versiones.toggled.connect(self._al_cambiar_avisos)
        self.buscador_versiones.encontrada.connect(self.aviso_version.mostrar)
        atajos = {
            "P": self._alternar_pausa,
            "R": self.puente.repetir,
            "S": self.puente.saltar,
            "M": self.silenciar.toggle,
        }
        for tecla, accion in atajos.items():
            QShortcut(QKeySequence(tecla), self, accion)

        self.puente.estado.connect(self.estado.setText)
        self.puente.linea.connect(self._mostrar_linea)
        self.puente.subtitulo.connect(self._mostrar_subtitulo)
        barra = self.historial.verticalScrollBar()
        barra.rangeChanged.connect(lambda _minimo, _maximo: self._bajar_historial())
        barra.valueChanged.connect(self._al_mover_historial)
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
            ayuda = _("Ventana «{ventana}» · {idioma} → {destino}")
            elemento.setToolTip(
                ayuda.format(ventana=perfil.ventana, idioma=perfil.idioma, destino=perfil.destino)
            )
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

    def traducir_guion(self) -> None:
        """Abre la traducción del guion entero. Es modal: mientras dura no se puede jugar."""
        perfil = self.perfil_elegido()
        if perfil is None or perfil.guion is None or self.puente.jugando:
            return
        self._abrir_traduccion_guion(self, perfil).exec()

    def borrar(self) -> None:
        perfil = self.perfil_elegido()
        if perfil is None or self.puente.jugando:
            return
        respuesta = QMessageBox.question(
            self,
            _("Borrar juego"),
            _(
                "¿Borrar «{nombre}» de la lista?\n\n"
                "Sus traducciones y su audio guardados también se borrarán."
            ).format(nombre=perfil.nombre),
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

    def cambiar_idioma(self, idioma: str | None) -> None:
        """Guarda el idioma de la app (None: el del sistema). Se aplica al volver a abrirla."""
        ajustes = cargar_ajustes(self._ruta_ajustes)
        if idioma == ajustes.idioma:
            return
        guardar_ajustes(replace(ajustes, idioma=idioma), self._ruta_ajustes)
        nuevo = textos.catalogo(textos.elegir(idioma, plataforma.idiomas_sistema()))
        QMessageBox.information(self, TITULO, nuevo.gettext(AVISO_IDIOMA))

    def buscar_version_nueva(self) -> None:
        """La primera vez pregunta si avisar de versiones nuevas; si está activado, busca si hay una."""
        preguntar_si_avisar(self, self._ruta_ajustes)
        self.avisar_versiones.setChecked(cargar_ajustes(self._ruta_ajustes).avisar_versiones is True)
        self.buscador_versiones.iniciar()

    def _al_cambiar_avisos(self, activo: bool) -> None:
        ajustes = cargar_ajustes(self._ruta_ajustes)
        if ajustes.avisar_versiones != activo:
            guardar_ajustes(replace(ajustes, avisar_versiones=activo), self._ruta_ajustes)

    # Partida

    def jugar(self) -> None:
        perfil = self.perfil_elegido()
        if perfil is None or self.puente.jugando:
            return
        self._perfil_en_juego = perfil
        self._hubo_error = False
        self._lineas.clear()
        self.historial.clear()
        self.estado.setText(_("Preparando «{nombre}»…").format(nombre=perfil.nombre))
        # Antes de arrancar: la primera línea puede llegar en cuanto empieza la captura.
        self._subtitulos = self._crear_subtitulos(perfil)
        if self._subtitulos is not None:
            # Los botones que salen al pasar el ratón por los subtítulos hacen lo mismo que los atajos.
            self._subtitulos.conectar(lambda accion: self._al_atajo(accion.value))
        self.puente.iniciar(perfil)
        self._actualizar_botones()

    def detener(self) -> None:
        self.estado.setText(_("Parando…"))
        self.puente.detener()
        self._actualizar_botones()

    def _alternar_pausa(self) -> None:
        self.puente.alternar_pausa()
        self._actualizar_botones()

    def _al_iniciar(self) -> None:
        if self._perfil_en_juego is not None:
            texto = _("Leyendo «{nombre}». Juega con normalidad.")
            self.estado.setText(texto.format(nombre=self._perfil_en_juego.nombre))
        self._iniciar_atajos()
        if self.solo_subtitulos.isChecked() and self._subtitulos is not None and not self.isMinimized():
            self._minimizada_al_jugar = True
            self.showMinimized()
        self._actualizar_botones()

    # Atajos globales y modo «solo subtítulos»

    def configurar_atajos(self) -> None:
        """Abre los atajos de teclado (no mientras se juega: ya están en uso)."""
        if not self.puente.jugando:
            DialogoAtajos(self._ruta_ajustes, parent=self).exec()

    def _iniciar_atajos(self) -> None:
        ajustes = cargar_ajustes(self._ruta_ajustes)
        if not ajustes.atajos_activos:
            return
        try:
            atajos = leer_atajos(ajustes.atajos)
            self._escucha = self._crear_escucha()
            fallidos = self._escucha.iniciar(atajos, lambda accion: self.atajo.emit(accion.value))
        except AtajoNoValidoError as error:
            self._avisar(str(error))
            return
        except Exception:
            # Sin atajos se puede jugar igual, con los botones de la app.
            _registro.warning("No se pueden usar los atajos de teclado globales", exc_info=True)
            self._avisar(_("No se pueden usar los atajos de teclado en este sistema."))
            return
        if fallidos:
            ocupados = ", ".join(str(atajos[accion]) for accion in fallidos)
            self._avisar(
                _("Estos atajos ya los usa otra aplicación y no funcionarán: {atajos}").format(
                    atajos=ocupados
                )
            )

    def _detener_atajos(self) -> None:
        if self._escucha is not None:
            self._escucha.detener()
            self._escucha = None

    def _al_atajo(self, accion: str) -> None:
        if not self.puente.jugando:
            return
        acciones = {
            Accion.PAUSA: self._alternar_pausa,
            Accion.REPETIR: self.puente.repetir,
            Accion.SALTAR: self.puente.saltar,
            Accion.SUBTITULOS: self._alternar_subtitulos,
        }
        acciones[Accion(accion)]()

    def _alternar_subtitulos(self) -> None:
        if self._subtitulos is not None:
            self._subtitulos.alternar()

    def _al_cambiar_solo_subtitulos(self, activo: bool) -> None:
        ajustes = cargar_ajustes(self._ruta_ajustes)
        if ajustes.solo_subtitulos != activo:
            guardar_ajustes(replace(ajustes, solo_subtitulos=activo), self._ruta_ajustes)

    def _al_terminar(self) -> None:
        if self._perfil_en_juego is not None:
            # La partida puede haber añadido nombres de personajes al glosario del juego.
            self.recargar_perfiles(elegir=self._perfil_en_juego.id)
        self._perfil_en_juego = None
        self._detener_atajos()
        if self._minimizada_al_jugar:
            self._minimizada_al_jugar = False
            self.showNormal()
        if self._subtitulos is not None:
            self._subtitulos.cerrar()
            self._subtitulos = None
        if not self.puente.jugando and not self._hubo_error:
            self.estado.setText(_("Partida terminada. Elige un juego y pulsa Jugar."))
        self._actualizar_botones()

    def _mostrar_linea(self, linea: LineaJuego) -> None:
        self._lineas.append(linea)
        self.historial.setHtml("".join(_html(linea) for linea in self._lineas))
        # El documento se maqueta después y su altura cambia también al redimensionar la ventana:
        # la barra se baja cada vez que cambia su rango (`_bajar_historial`), no solo aquí.
        self._seguir_final = True
        self._bajar_historial()

    def _mostrar_subtitulo(self, texto: str) -> None:
        if self._subtitulos is not None:
            self._subtitulos.mostrar(texto)

    def _bajar_historial(self) -> None:
        if self._seguir_final:
            barra = self.historial.verticalScrollBar()
            barra.setValue(barra.maximum())

    def _al_mover_historial(self, valor: int) -> None:
        # Al crecer el documento el valor no cambia; solo cambia si se mueve la barra o se recorta al final.
        self._seguir_final = valor >= self.historial.verticalScrollBar().maximum()

    def _avisar(self, mensaje: str) -> None:
        """Un aviso que no impide jugar: no cuenta como error de la partida."""
        self.estado.setText(f"⚠ {mensaje}")

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
        perfil = self.perfil_elegido()
        self.boton_guion.setEnabled(perfil is not None and perfil.guion is not None and not jugando)
        self.boton_anadir.setEnabled(not jugando)
        self.boton_cache.setEnabled(not jugando)
        self.boton_atajos.setEnabled(not jugando)
        self.lista_perfiles.setEnabled(not jugando)
        for boton in (self.boton_pausa, self.boton_repetir, self.boton_saltar, self.boton_detener):
            boton.setEnabled(jugando)
        self.boton_pausa.setText(_("Seguir (P)") if self.puente.pausado else _("Pausa (P)"))

    def closeEvent(self, evento: QCloseEvent) -> None:  # noqa: N802 - nombre de Qt
        """Al cerrar, para la partida y espera: devuelve el volumen del juego y para el traductor."""
        if self.puente.jugando:
            self.puente.detener()
        self.puente.esperar(timeout_s=15)
        self._detener_atajos()
        if self._subtitulos is not None:
            self._subtitulos.cerrar()  # no tiene padre: si no, la app seguiría abierta
            self._subtitulos = None
        evento.accept()
