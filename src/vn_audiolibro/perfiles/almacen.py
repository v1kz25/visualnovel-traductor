"""Guardado de los perfiles: un fichero JSON por perfil en la configuración del usuario."""

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, ZonaRelativa
from vn_audiolibro.guion.modelos import OrigenGuion
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.perfiles.modelos import (
    DESTINOS,
    IDIOMAS,
    AjustesGuion,
    AjustesLectura,
    AjustesSubtitulos,
    AjustesVolumen,
    AjustesVoz,
    Color,
    Perfil,
    PerfilInvalidoError,
    PosicionSubtitulos,
    nuevo_id,
)
from vn_audiolibro.rutas import directorio_config
from vn_audiolibro.textos import _
from vn_audiolibro.traduccion.modelos import Glosario, Motor
from vn_audiolibro.voz.modelos import ModoLectura
from vn_audiolibro.voz.piper import Hablante

_registro = logging.getLogger(__name__)

VERSION_FORMATO = 1
"""Versión del formato de los ficheros. Sube si cambia de forma incompatible."""


class PerfilDuplicadoError(ValueError):
    """Ya hay otro perfil con ese nombre."""


def directorio_perfiles() -> Path:
    """Carpeta de los perfiles en la configuración del usuario."""
    return directorio_config() / "perfiles"


def a_dict(perfil: Perfil) -> dict[str, Any]:
    """Perfil como datos JSON."""
    return {
        "version": VERSION_FORMATO,
        "id": perfil.id,
        "nombre": perfil.nombre,
        "ventana": perfil.ventana,
        "idioma": perfil.idioma,
        "destino": perfil.destino,
        "zona": asdict(perfil.zona),
        "color": perfil.color.value,
        "orientacion": perfil.orientacion.value,
        "busqueda": perfil.busqueda.value,
        "glosario": dict(perfil.glosario.terminos),
        "traductor": perfil.traductor.value,
        "voz": {"hablante": perfil.voz.hablante.name.lower(), "velocidad": perfil.voz.velocidad},
        "lectura": {"modo": perfil.lectura.modo.value, "pausa_s": perfil.lectura.pausa_s},
        "volumen": {
            "activo": perfil.volumen.activo,
            "nivel_juego": perfil.volumen.nivel_juego,
            "otras": dict(perfil.volumen.otras),
            "excluir": list(perfil.volumen.excluir),
        },
        "subtitulos": {
            "activo": perfil.subtitulos.activo,
            "posicion": perfil.subtitulos.posicion.value,
            "tamano": perfil.subtitulos.tamano,
            "opacidad": perfil.subtitulos.opacidad,
        },
        "guion": None
        if perfil.guion is None
        else {"carpeta": perfil.guion.carpeta, "origen": perfil.guion.origen.value},
    }


def desde_dict(datos: Mapping[str, Any]) -> Perfil:
    """Perfil a partir de datos JSON. Los campos que falten toman su valor por defecto."""
    version = datos.get("version")
    if not isinstance(version, int) or version < 1:
        raise PerfilInvalidoError(_("Versión de formato no válida: {version!r}").format(version=version))
    if version > VERSION_FORMATO:
        raise PerfilInvalidoError(_("Este juego se guardó con una versión más nueva de la app: actualízala"))
    try:
        return Perfil(
            nombre=_texto(datos, "nombre"),
            ventana=_texto(datos, "ventana"),
            idioma=datos.get("idioma", IDIOMAS[0]),
            # Los juegos guardados antes de poder elegirlo se traducían al español.
            destino=datos.get("destino", DESTINOS[0]),
            zona=_zona(datos["zona"]) if "zona" in datos else TODA_LA_VENTANA,
            color=Color(datos.get("color", Color.CLARO)),
            orientacion=Orientacion(datos.get("orientacion", Orientacion.HORIZONTAL.value)),
            busqueda=BusquedaTexto(datos.get("busqueda", BusquedaTexto.COLOR.value)),
            glosario=_glosario(datos.get("glosario", {})),
            traductor=Motor(datos.get("traductor", Motor.LOCAL.value)),
            voz=_voz(datos.get("voz", {})),
            lectura=_lectura(datos.get("lectura", {})),
            volumen=_volumen(datos.get("volumen", {})),
            subtitulos=_subtitulos(datos.get("subtitulos", {})),
            guion=_guion(datos.get("guion")),
            id=datos.get("id") or nuevo_id(),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        if isinstance(error, PerfilInvalidoError):
            raise
        raise PerfilInvalidoError(
            _("Juego guardado con un valor no válido: {error}").format(error=error)
        ) from error


def _texto(datos: Mapping[str, Any], clave: str) -> str:
    valor = datos.get(clave)
    if not isinstance(valor, str):
        raise PerfilInvalidoError(_("Falta «{clave}» o no es un texto").format(clave=clave))
    return valor


def _numero(valor: Any) -> float:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise TypeError(_("se esperaba un número: {valor!r}").format(valor=valor))
    return float(valor)


def _zona(datos: Mapping[str, Any]) -> ZonaRelativa:
    return ZonaRelativa(
        _numero(datos["x"]), _numero(datos["y"]), _numero(datos["ancho"]), _numero(datos["alto"])
    )


def _glosario(datos: Mapping[str, Any]) -> Glosario:
    if not all(isinstance(t, str) and isinstance(d, str) for t, d in datos.items()):
        raise TypeError(_("el glosario tiene que ser de textos"))
    return Glosario.desde_dict(dict(datos))


def _voz(datos: Mapping[str, Any]) -> AjustesVoz:
    return AjustesVoz(
        hablante=Hablante[str(datos.get("hablante", "mujer")).upper()],
        velocidad=_numero(datos.get("velocidad", 1.0)),
    )


def _lectura(datos: Mapping[str, Any]) -> AjustesLectura:
    por_defecto = AjustesLectura()
    return AjustesLectura(
        modo=ModoLectura(datos.get("modo", por_defecto.modo.value)),
        pausa_s=_numero(datos.get("pausa_s", por_defecto.pausa_s)),
    )


def _volumen(datos: Mapping[str, Any]) -> AjustesVolumen:
    por_defecto = AjustesVolumen()
    activo = datos.get("activo", por_defecto.activo)
    if not isinstance(activo, bool):
        raise TypeError(_("«activo» tiene que ser verdadero o falso: {activo!r}").format(activo=activo))
    otras = datos.get("otras", {})
    excluir = datos.get("excluir", [])
    if not all(isinstance(nombre, str) for nombre in [*otras, *excluir]):
        raise TypeError(_("los nombres de las aplicaciones tienen que ser textos"))
    return AjustesVolumen(
        activo=activo,
        nivel_juego=_numero(datos.get("nivel_juego", por_defecto.nivel_juego)),
        otras=tuple((nombre, _numero(nivel)) for nombre, nivel in otras.items()),
        excluir=tuple(excluir),
    )


def _subtitulos(datos: Mapping[str, Any]) -> AjustesSubtitulos:
    por_defecto = AjustesSubtitulos()
    activo = datos.get("activo", por_defecto.activo)
    tamano = datos.get("tamano", por_defecto.tamano)
    if not isinstance(activo, bool) or isinstance(tamano, bool) or not isinstance(tamano, int):
        raise TypeError(_("subtítulos no válidos: {datos!r}").format(datos=dict(datos)))
    return AjustesSubtitulos(
        activo=activo,
        posicion=PosicionSubtitulos(datos.get("posicion", por_defecto.posicion.value)),
        tamano=tamano,
        opacidad=_numero(datos.get("opacidad", por_defecto.opacidad)),
    )


def _guion(datos: Mapping[str, Any] | None) -> AjustesGuion | None:
    if datos is None:
        return None
    return AjustesGuion(
        carpeta=_texto(datos, "carpeta"),
        origen=OrigenGuion(datos.get("origen", OrigenGuion.ORIGINAL.value)),
    )


class AlmacenPerfiles:
    """Perfiles guardados en una carpeta, uno por fichero `<id>.json`."""

    def __init__(self, directorio: Path | None = None) -> None:
        self.directorio = directorio or directorio_perfiles()

    def listar(self) -> list[Perfil]:
        """Perfiles guardados, por nombre. Los ficheros ilegibles se saltan con un aviso."""
        perfiles = []
        for ruta in sorted(self.directorio.glob("*.json")):
            try:
                perfiles.append(self._leer(ruta))
            except PerfilInvalidoError:
                _registro.warning("Juego guardado ilegible, se ignora: %s", ruta, exc_info=True)
        return sorted(perfiles, key=lambda perfil: perfil.nombre.casefold())

    def cargar(self, id_perfil: str) -> Perfil:
        """Perfil con ese identificador."""
        ruta = self._ruta(id_perfil)
        if not ruta.is_file():
            raise KeyError(
                _("No hay ningún juego con el identificador {id_perfil}").format(id_perfil=id_perfil)
            )
        return self._leer(ruta)

    def buscar(self, texto: str) -> Perfil:
        """Perfil por su nombre (sin distinguir mayúsculas) o por su identificador."""
        buscado = texto.casefold().strip()
        for perfil in self.listar():
            if buscado in (perfil.nombre.casefold().strip(), perfil.id):
                return perfil
        raise KeyError(_("No hay ningún juego llamado «{texto}»").format(texto=texto))

    def guardar(self, perfil: Perfil) -> Path:
        """Guarda el perfil, nuevo o modificado. El nombre no puede repetirse con otro perfil."""
        nombre = perfil.nombre.casefold().strip()
        for otro in self.listar():
            if otro.id != perfil.id and otro.nombre.casefold().strip() == nombre:
                raise PerfilDuplicadoError(_("Ya hay un juego llamado «{nombre}»").format(nombre=otro.nombre))
        self.directorio.mkdir(parents=True, exist_ok=True)
        ruta = self._ruta(perfil.id)
        temporal = ruta.with_name(ruta.name + ".parcial")
        temporal.write_text(json.dumps(a_dict(perfil), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporal.replace(ruta)
        return ruta

    def borrar(self, id_perfil: str) -> None:
        """Borra el perfil. Su caché se vacía aparte (`CacheSQLite.invalidar(id)`)."""
        self._ruta(id_perfil).unlink(missing_ok=True)

    def _ruta(self, id_perfil: str) -> Path:
        # El id se valida al crear el perfil; aquí se evita que un id externo salga de la carpeta.
        if not id_perfil.isalnum():
            raise KeyError(_("Identificador de juego no válido: {id_perfil}").format(id_perfil=id_perfil))
        return self.directorio / f"{id_perfil}.json"

    def _leer(self, ruta: Path) -> Perfil:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PerfilInvalidoError(
                _("No se pudo leer {fichero}: {error}").format(fichero=ruta.name, error=error)
            ) from error
        if not isinstance(datos, dict):
            raise PerfilInvalidoError(_("{fichero} no contiene un juego").format(fichero=ruta.name))
        perfil = desde_dict(datos)
        if perfil.id != ruta.stem:
            raise PerfilInvalidoError(
                _("{fichero} contiene el juego {id}").format(fichero=ruta.name, id=perfil.id)
            )
        return perfil
