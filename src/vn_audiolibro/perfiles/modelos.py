"""Perfil de un juego: todo lo que se configura una vez y se reutiliza en cada partida."""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from vn_audiolibro.captura.mascara import TEXTO_CLARO, TEXTO_OSCURO, ColorTexto
from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, ZonaRelativa
from vn_audiolibro.guion.modelos import OrigenGuion
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.textos import _
from vn_audiolibro.traduccion.modelos import Glosario, Motor
from vn_audiolibro.voz.modelos import PAUSA_ENTRE_LINEAS_S, ModoLectura
from vn_audiolibro.voz.piper import HABLANTE_POR_DEFECTO, Hablante
from vn_audiolibro.voz.volumen import NIVEL_POR_DEFECTO, Juego, Seleccion

IDIOMAS = ("zh-Hant", "zh-Hans", "ja", "en")
"""Idiomas de origen admitidos: chino tradicional, chino simplificado, japonés e inglés."""

INGLES = "en"
"""Un juego en inglés solo se traduce al español y su texto va en horizontal."""

DESTINOS = ("es", "en")
"""Idiomas a los que se traduce y en los que se lee: español (por defecto) e inglés."""

LARGO_MAX_NOMBRE = 80
VELOCIDAD_MIN, VELOCIDAD_MAX = 0.5, 2.0


class PerfilInvalidoError(ValueError):
    """El perfil tiene un valor no válido o su fichero no se puede leer."""


class Color(StrEnum):
    """Color del texto del juego respecto al fondo de la caja de texto."""

    CLARO = "claro"
    OSCURO = "oscuro"

    @property
    def color_texto(self) -> ColorTexto:
        """Ajustes de captura y OCR para este color."""
        return TEXTO_CLARO if self is Color.CLARO else TEXTO_OSCURO


def _nivel_valido(nivel: float, que: str) -> None:
    if not 0 <= nivel <= 1:
        raise PerfilInvalidoError(
            _("El nivel de {que} tiene que estar entre 0 y 1: {nivel}").format(que=que, nivel=nivel)
        )


@dataclass(frozen=True)
class AjustesVoz:
    """Voz con la que se lee el juego."""

    hablante: Hablante = HABLANTE_POR_DEFECTO
    velocidad: float = 1.0
    """1 es la velocidad normal; 1,25 lee un 25 % más deprisa."""

    def __post_init__(self) -> None:
        if not VELOCIDAD_MIN <= self.velocidad <= VELOCIDAD_MAX:
            raise PerfilInvalidoError(
                _("La velocidad tiene que estar entre {minima} y {maxima}: {velocidad}").format(
                    minima=VELOCIDAD_MIN, maxima=VELOCIDAD_MAX, velocidad=self.velocidad
                )
            )


PAUSA_MAX_S = 10.0


@dataclass(frozen=True)
class AjustesLectura:
    """Cómo se leen las líneas que llegan mientras suena otra."""

    modo: ModoLectura = ModoLectura.COLA
    pausa_s: float = PAUSA_ENTRE_LINEAS_S
    """Silencio entre líneas en modo cola."""

    def __post_init__(self) -> None:
        if not 0 <= self.pausa_s <= PAUSA_MAX_S:
            raise PerfilInvalidoError(
                _("La pausa entre líneas tiene que estar entre 0 y {maximo} s").format(maximo=PAUSA_MAX_S)
            )


@dataclass(frozen=True)
class AjustesVolumen:
    """Qué se baja mientras habla la voz y a qué nivel (ver `Seleccion`)."""

    activo: bool = True
    nivel_juego: float = NIVEL_POR_DEFECTO
    otras: tuple[tuple[str, float], ...] = ()
    """Otras aplicaciones con su nivel mientras habla la voz; 0 las silencia."""
    excluir: tuple[str, ...] = ()
    """Aplicaciones que no se tocan nunca, aunque parezcan del juego."""

    def __post_init__(self) -> None:
        _nivel_valido(self.nivel_juego, _("juego"))
        for nombre, nivel in self.otras:
            _nivel_valido(nivel, nombre)

    def seleccion(self, juego: Juego | None) -> Seleccion | None:
        """Criterio para el atenuador, o None si no hay que bajar nada."""
        if not self.activo:
            return None
        return Seleccion.de_nombres(juego, self.nivel_juego, dict(self.otras), self.excluir)


class PosicionSubtitulos(StrEnum):
    """Dónde van los subtítulos respecto a la zona de texto del juego."""

    ENCIMA = "encima"
    """Justo encima de la zona de texto, sin taparla."""
    DEBAJO = "debajo"
    """Justo debajo de la zona de texto (encima si no cabe dentro del juego)."""
    TAPAR = "tapar"
    """Sobre la zona de texto, con fondo opaco: se ve la traducción en lugar del original."""


TAMANO_MIN, TAMANO_MAX = 10, 72


@dataclass(frozen=True)
class AjustesSubtitulos:
    """Subtítulos con la traducción encima del juego (desactivados por defecto)."""

    activo: bool = False
    posicion: PosicionSubtitulos = PosicionSubtitulos.ENCIMA
    tamano: int = 22
    """Tamaño de la letra en puntos."""
    opacidad: float = 0.75
    """Opacidad del fondo (0, transparente; 1, opaco). Al tapar el texto, el fondo es opaco."""

    def __post_init__(self) -> None:
        if not TAMANO_MIN <= self.tamano <= TAMANO_MAX:
            raise PerfilInvalidoError(
                _("El tamaño de los subtítulos tiene que estar entre {minimo} y {maximo}").format(
                    minimo=TAMANO_MIN, maximo=TAMANO_MAX
                )
            )
        _nivel_valido(self.opacidad, _("opacidad"))


@dataclass(frozen=True)
class AjustesGuion:
    """Guion del juego como fuente del texto (ver `vn_audiolibro.guion`)."""

    carpeta: str
    """Carpeta del juego (o la de los ficheros del guion)."""
    origen: OrigenGuion = OrigenGuion.ORIGINAL

    def __post_init__(self) -> None:
        if not self.carpeta.strip():
            raise PerfilInvalidoError(_("Falta la carpeta del juego para leer su guion"))


def nuevo_id() -> str:
    """Identificador de un perfil nuevo."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Perfil:
    """Configuración de un juego.

    `id` no cambia nunca: es el nombre del fichero y la clave de la caché del juego, así que el
    `nombre` se puede cambiar sin perder las traducciones ni el audio guardados.
    """

    nombre: str
    ventana: str
    """Texto que aparece en el título de la ventana del juego (sin distinguir mayúsculas)."""
    idioma: str = IDIOMAS[0]
    destino: str = DESTINOS[0]
    """Idioma de la traducción y de la voz. El glosario del juego va en este idioma."""
    zona: ZonaRelativa = TODA_LA_VENTANA
    zona_nombre: ZonaRelativa | None = None
    """Zona donde el juego escribe quién habla, si la tiene: ese texto no se lee en voz alta."""
    separar_personaje: bool = True
    """Sin zona del nombre, si se quita el de quien habla del principio de la línea (`Nombre：texto`)."""
    color: Color = Color.CLARO
    orientacion: Orientacion = Orientacion.HORIZONTAL
    busqueda: BusquedaTexto = BusquedaTexto.COLOR
    """Cómo se busca el texto en la zona: por color (caja de texto lisa) o con el detector."""
    glosario: Glosario = field(default_factory=Glosario)
    traductor: Motor = Motor.LOCAL
    """Traductor del juego: el local (por defecto) o Gemini, con la clave del usuario."""
    voz: AjustesVoz = field(default_factory=AjustesVoz)
    lectura: AjustesLectura = field(default_factory=AjustesLectura)
    volumen: AjustesVolumen = field(default_factory=AjustesVolumen)
    subtitulos: AjustesSubtitulos = field(default_factory=AjustesSubtitulos)
    guion: AjustesGuion | None = None
    """Si está, el texto sale del guion del juego y el OCR solo sirve para saber por dónde va."""
    id: str = field(default_factory=nuevo_id)

    def __post_init__(self) -> None:
        if not self.nombre.strip():
            raise PerfilInvalidoError(_("El juego necesita un nombre"))
        if len(self.nombre) > LARGO_MAX_NOMBRE:
            raise PerfilInvalidoError(
                _("El nombre no puede pasar de {maximo} caracteres").format(maximo=LARGO_MAX_NOMBRE)
            )
        if not self.ventana.strip():
            raise PerfilInvalidoError(_("Falta el título de la ventana del juego"))
        if self.idioma not in IDIOMAS:
            raise PerfilInvalidoError(
                _("Idioma no admitido: {idioma} (admitidos: {admitidos})").format(
                    idioma=self.idioma, admitidos=", ".join(IDIOMAS)
                )
            )
        if self.destino not in DESTINOS:
            raise PerfilInvalidoError(
                _("Idioma de traducción no admitido: {destino} (admitidos: {admitidos})").format(
                    destino=self.destino, admitidos=", ".join(DESTINOS)
                )
            )
        if self.idioma == INGLES and self.destino == INGLES:
            raise PerfilInvalidoError(_("Un juego en inglés solo se puede traducir al español"))
        if self.idioma == INGLES and self.orientacion is Orientacion.VERTICAL:
            raise PerfilInvalidoError(_("El texto en inglés no puede ir en columnas verticales"))
        if self.guion is not None and self.guion.origen is OrigenGuion.INGLES and self.destino == "en":
            raise PerfilInvalidoError(
                _("Si se traduce desde el inglés del guion, no se puede traducir al inglés")
            )
        if len(self.id) != 32 or any(c not in "0123456789abcdef" for c in self.id):
            raise PerfilInvalidoError(_("Identificador de juego no válido: {id}").format(id=self.id))
