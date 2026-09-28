"""Ventanas y captura en X11: listado y geometría (EWMH) y contenido de la ventana (XComposite)."""

import numpy as np
from Xlib import X, display
from Xlib.error import XError
from Xlib.ext import composite
from Xlib.xobject.drawable import Window

from vn_audiolibro.captura.capturador import Capturador
from vn_audiolibro.captura.modelos import (
    Imagen,
    Rectangulo,
    Ventana,
    VentanaNoEncontradaError,
    buscar_por_titulo,
)
from vn_audiolibro.procesos import pids_propios


class GestorVentanasX11:
    """Consulta las ventanas de nivel superior a través del gestor de ventanas (EWMH)."""

    def __init__(self, pantalla: display.Display | None = None) -> None:
        self._pantalla = pantalla or display.Display()
        self._raiz = self._pantalla.screen().root
        self._atomo = self._pantalla.intern_atom

    def listar(self) -> list[Ventana]:
        """Devuelve las ventanas visibles con título, en el orden del gestor de ventanas."""
        ids = self._propiedad(self._raiz, "_NET_CLIENT_LIST") or []
        ventanas = []
        for id_ventana in ids:
            try:
                ventana = self._leer(int(id_ventana))
            except (XError, VentanaNoEncontradaError):
                continue  # la ventana se ha cerrado mientras la leíamos
            if ventana.titulo:
                ventanas.append(ventana)
        return ventanas

    def buscar(self, texto: str, excluir_pids: frozenset[int] | None = None) -> Ventana:
        """Primera ventana cuyo título contiene `texto`; sin contar las de esta app ni su terminal."""
        excluidos = pids_propios() if excluir_pids is None else excluir_pids
        return buscar_por_titulo(self.listar(), texto, excluidos)

    def geometria(self, id_ventana: int) -> Rectangulo:
        """Posición absoluta y tamaño actuales del contenido de la ventana."""
        try:
            ventana = self._pantalla.create_resource_object("window", id_ventana)
            tamano = ventana.get_geometry()
            origen = ventana.translate_coords(self._raiz, 0, 0)
        except XError as error:
            raise VentanaNoEncontradaError(f"La ventana {id_ventana:#x} ya no existe") from error
        return Rectangulo(x=-origen.x, y=-origen.y, ancho=tamano.width, alto=tamano.height)

    def _leer(self, id_ventana: int) -> Ventana:
        ventana = self._pantalla.create_resource_object("window", id_ventana)
        titulo = self._propiedad(ventana, "_NET_WM_NAME", self._atomo("UTF8_STRING"))
        if titulo is None:
            titulo = self._propiedad(ventana, "WM_NAME", X.AnyPropertyType)
        pid = self._propiedad(ventana, "_NET_WM_PID")
        return Ventana(
            id=id_ventana,
            titulo=_texto(titulo),
            pid=int(pid[0]) if pid else None,
            geometria=self.geometria(id_ventana),
        )

    def _propiedad(
        self, ventana: Window, nombre: str, tipo: int = X.AnyPropertyType
    ) -> list[int] | bytes | None:
        respuesta = ventana.get_full_property(self._atomo(nombre), tipo)
        if respuesta is None:
            return None
        valor = respuesta.value
        if isinstance(valor, str):
            return valor.encode()
        if isinstance(valor, bytes):
            return valor
        return [int(v) for v in valor]


def _texto(valor: list[int] | bytes | None) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace")
    return bytes(valor).decode("utf-8", errors="replace")


class CapturadorVentanaX11:
    """Captura el contenido de la propia ventana con XComposite, aunque tenga otras encima.

    Necesita un compositor (GNOME, KDE… en X11). Si la ventana no está redirigida (por ejemplo,
    algunos juegos a pantalla completa), usa el capturador alternativo.
    """

    def __init__(
        self, alternativo: Capturador | None = None, pantalla: display.Display | None = None
    ) -> None:
        self._pantalla = pantalla or display.Display()
        if not self._pantalla.has_extension("Composite"):
            raise RuntimeError("El servidor X no tiene la extensión Composite")
        self._alternativo = alternativo
        self._redirigidas: set[int] = set()

    def capturar(self, id_ventana: int, zona: Rectangulo) -> Imagen:
        """Captura la zona desde el pixmap de la ventana."""
        ventana = self._pantalla.create_resource_object("window", id_ventana)
        try:
            if id_ventana not in self._redirigidas:
                # Redirección automática: sin compositor el servidor mantiene el contenido de la
                # ventana en un pixmap y la sigue pintando en pantalla igual que antes.
                # El stub de typeshed tipa `update` como callable, pero es el modo (un entero).
                composite.redirect_window(ventana, composite.RedirectAutomatic)  # type: ignore[arg-type]
                self._redirigidas.add(id_ventana)
            pixmap = composite.name_window_pixmap(ventana)
            try:
                datos = pixmap.get_image(zona.x, zona.y, zona.ancho, zona.alto, X.ZPixmap, 0xFFFFFFFF).data
            finally:
                pixmap.free()
        except XError:
            if self._alternativo is None:
                raise
            return self._alternativo.capturar(id_ventana, zona)
        bgrx = np.frombuffer(datos, dtype=np.uint8).reshape(zona.alto, zona.ancho, 4)
        rgb: Imagen = np.ascontiguousarray(bgrx[:, :, 2::-1])
        return rgb
