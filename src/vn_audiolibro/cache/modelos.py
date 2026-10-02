"""Tipos de la caché: la clave de cada línea y lo que se guarda de ella."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_ESPACIOS = re.compile(r"\s+")


def normalizar_para_clave(texto: str) -> str:
    """Forma canónica del texto para calcular la clave.

    NFKC unifica anchos (！ y !, ｱ y ア) y se quitan los espacios: el mismo texto leído dos veces
    por el OCR con pequeñas diferencias de este tipo tiene que acertar en la caché.
    """
    return _ESPACIOS.sub("", unicodedata.normalize("NFKC", texto))


DESTINO_ORIGINAL = "es"
"""Idioma de destino de las claves anteriores a poder elegirlo: no entra en el hash."""


@dataclass(frozen=True)
class Clave:
    """Identifica una línea de un juego: perfil, idioma de origen, texto original e idioma de destino."""

    perfil: str
    idioma: str
    texto: str
    destino: str = DESTINO_ORIGINAL

    @property
    def id(self) -> str:
        """SHA-256 del perfil, el idioma, el texto normalizado y el destino.

        El español no se añade al hash: así las líneas guardadas antes de poder elegir el destino
        siguen valiendo, y cambiar de idioma de destino no mezcla las traducciones.
        """
        partes = [self.perfil, self.idioma, normalizar_para_clave(self.texto)]
        if self.destino != DESTINO_ORIGINAL:
            partes.append(self.destino)
        return hashlib.sha256("\0".join(partes).encode()).hexdigest()


@dataclass(frozen=True)
class Entrada:
    """Lo guardado para una línea."""

    original: str
    traduccion: str
    modelo: str
    """Traductor que generó la traducción (p. ej. `hy-mt2-1.8b-q4_k_m`)."""
    audio: Path | None
    """Fichero Opus con la voz, o None si aún no se ha sintetizado."""
    creada: float
    usada: float
    """Última vez que se consultó, en segundos desde la época (para borrar lo más antiguo)."""
    voz: str | None = None
    """Con qué voz se sintetizó el audio: None si con la del juego, o la de un personaje."""


@dataclass(frozen=True)
class ResumenPerfil:
    """Cuánto ocupa la caché de un juego."""

    perfil: str
    entradas: int
    bytes: int
