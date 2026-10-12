"""Voz de Piper (GPL-3.0) en cada idioma de destino, en CPU."""

import copy
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

from vn_audiolibro.descargas import Cancelado, Descarga, Progreso, asegurar_descarga
from vn_audiolibro.textos import _
from vn_audiolibro.voz.modelos import Fragmento, VozFallidaError

_VOCES = "https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117"


class Hablante(StrEnum):
    """Hablante de una voz con varios, con el nombre que usa su configuración."""

    MUJER = "F"
    HOMBRE = "M"


@dataclass(frozen=True)
class VozPiper:
    """Voz de Piper: el modelo ONNX y su configuración, que se descargan juntos."""

    modelo: Descarga
    config: Descarga


SHARVARD_MEDIUM = VozPiper(
    modelo=Descarga(
        fichero="es_ES-sharvard-medium.onnx",
        url=f"{_VOCES}/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx",
        sha256="40febfb1679c69a4505ff311dc136e121e3419a13a290ef264fdf43ddedd0fb1",
    ),
    config=Descarga(
        fichero="es_ES-sharvard-medium.onnx.json",
        url=f"{_VOCES}/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx.json",
        sha256="7438c9b699c72b0c3388dae1b68d3f364dc66a2150fe554a1c11f03372957b2c",
    ),
)
"""Voz de España con dos hablantes, mujer y hombre; calidad media, 22,05 kHz. ~77 MB.

Dataset SHaRVARD (CC BY 3.0), afinada a partir de la voz inglesa lessac. La app no la
redistribuye: se descarga del repositorio oficial de voces de Piper.
"""

KRISTIN_MEDIUM = VozPiper(
    modelo=Descarga(
        fichero="en_US-kristin-medium.onnx",
        url=f"{_VOCES}/en/en_US/kristin/medium/en_US-kristin-medium.onnx",
        sha256="5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4",
    ),
    config=Descarga(
        fichero="en_US-kristin-medium.onnx.json",
        url=f"{_VOCES}/en/en_US/kristin/medium/en_US-kristin-medium.onnx.json",
        sha256="5681426d4aead22195de70531eeeeddb46493cfaffc5764b2ea3db73428b651c",
    ),
)
"""Voz inglesa (EE. UU.) de mujer; calidad media, 22,05 kHz. ~64 MB.

Entrenada desde cero con grabaciones de LibriVox (dominio público).
"""

JOHN_MEDIUM = VozPiper(
    modelo=Descarga(
        fichero="en_US-john-medium.onnx",
        url=f"{_VOCES}/en/en_US/john/medium/en_US-john-medium.onnx",
        sha256="789c6c875726e627ddee93d51d8727859abe9c091c3d141591f4b83c2072e988",
    ),
    config=Descarga(
        fichero="en_US-john-medium.onnx.json",
        url=f"{_VOCES}/en/en_US/john/medium/en_US-john-medium.onnx.json",
        sha256="af60f177b6b550f3d7a302720c0fb89e7f94a82b5dca464775ef63b1c69ba09a",
    ),
)
"""Voz inglesa (EE. UU.) de hombre; calidad media, 22,05 kHz. ~64 MB.

Afinada a partir de kristin con grabaciones de LibriVox (dominio público).
"""

UPMC_MEDIUM = VozPiper(
    modelo=Descarga(
        fichero="fr_FR-upmc-medium.onnx",
        url=f"{_VOCES}/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx",
        sha256="9abb3800c199148897a9ed64e100d224f3de83579f100044174ad19418f1786f",
    ),
    config=Descarga(
        fichero="fr_FR-upmc-medium.onnx.json",
        url=f"{_VOCES}/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json",
        sha256="e8636ec15dfd5d72db37a02cb5320a20f2b8d339f2a0e4337da64c58a33a5868",
    ),
)
"""Voz francesa (Francia) con dos hablantes, jessica (mujer) y pierre (hombre); calidad media,
22,05 kHz. ~77 MB.

Dataset UPMC de MaryTTS (CC BY-SA 4.0), afinada a partir de la voz inglesa lessac.
"""

KERSTIN_LOW = VozPiper(
    modelo=Descarga(
        fichero="de_DE-kerstin-low.onnx",
        url=f"{_VOCES}/de/de_DE/kerstin/low/de_DE-kerstin-low.onnx",
        sha256="d352a7641892cebf2903859af94e9ba81a141110215fe3943bcda7f7da401b7a",
    ),
    config=Descarga(
        fichero="de_DE-kerstin-low.onnx.json",
        url=f"{_VOCES}/de/de_DE/kerstin/low/de_DE-kerstin-low.onnx.json",
        sha256="56e708556b7b9b7a53c4f8957e021421e69f11a600962bba554cffbe72cf2d47",
    ),
)
"""Voz alemana de mujer; calidad baja, 16 kHz. ~63 MB.

Dataset de Rhasspy y Nabu Casa (CC0). Es la única voz alemana de mujer con licencia libre clara.
"""

THORSTEN_MEDIUM = VozPiper(
    modelo=Descarga(
        fichero="de_DE-thorsten-medium.onnx",
        url=f"{_VOCES}/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx",
        sha256="7e64762d8e5118bb578f2eea6207e1a35a8e0c30595010b666f983fc87bb7819",
    ),
    config=Descarga(
        fichero="de_DE-thorsten-medium.onnx.json",
        url=f"{_VOCES}/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json",
        sha256="974adee790533adb273a1ac88f49027d2a1b8f0f2cf4905954a4791e79264e85",
    ),
)
"""Voz alemana de hombre; calidad media, 22,05 kHz. ~63 MB.

Dataset Thorsten-Voice (CC0), afinada a partir de la voz inglesa lessac.
"""

PAOLA_MEDIUM = VozPiper(
    modelo=Descarga(
        fichero="it_IT-paola-medium.onnx",
        url=f"{_VOCES}/it/it_IT/paola/medium/it_IT-paola-medium.onnx",
        sha256="6fc918b5a0ea6137382833dddfa567bffbe6a5060c02043c87192ee59c04210c",
    ),
    config=Descarga(
        fichero="it_IT-paola-medium.onnx.json",
        url=f"{_VOCES}/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json",
        sha256="aea19c0a7fce29fbc359b93f10e7902854401e4c95ae2ea328ae516b15d296cf",
    ),
)
"""Voz italiana de mujer; calidad media, 22,05 kHz. ~64 MB.

Dataset de Nabu Casa (CC0). No hay voz italiana de hombre de calidad con licencia libre clara,
así que lee también a los personajes masculinos.
"""

FABER_MEDIUM = VozPiper(
    modelo=Descarga(
        fichero="pt_BR-faber-medium.onnx",
        url=f"{_VOCES}/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        sha256="858555e3a064209c57088fe6bd70c4c3dc54d03eaa00c45d5ecaf43a33f95aa7",
    ),
    config=Descarga(
        fichero="pt_BR-faber-medium.onnx.json",
        url=f"{_VOCES}/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json",
        sha256="7e694de195ae3fc36dd732c445eb04fb49b649854893cb5506b978f0d50a1d6f",
    ),
)
"""Voz portuguesa (Brasil) de hombre; calidad media, 22,05 kHz. ~63 MB.

Dataset de Nabu Casa (CC0). No hay voz portuguesa de mujer con licencia libre, así que lee también
a los personajes femeninos.
"""

HABLANTE_POR_DEFECTO = Hablante.MUJER


@dataclass(frozen=True)
class VozElegida:
    """Voz de Piper que lee un idioma con un hablante, y el hablante dentro de ella."""

    voz: VozPiper
    hablante: str | None
    """Nombre del hablante en una voz con varios (el de su `speaker_id_map`), o None si solo tiene uno."""


VOCES: dict[str, dict[Hablante, VozElegida]] = {
    "es": {h: VozElegida(SHARVARD_MEDIUM, h) for h in Hablante},
    "en": {
        Hablante.MUJER: VozElegida(KRISTIN_MEDIUM, None),
        Hablante.HOMBRE: VozElegida(JOHN_MEDIUM, None),
    },
    "fr": {
        Hablante.MUJER: VozElegida(UPMC_MEDIUM, "jessica"),
        Hablante.HOMBRE: VozElegida(UPMC_MEDIUM, "pierre"),
    },
    "pt": {h: VozElegida(FABER_MEDIUM, None) for h in Hablante},
    "de": {
        Hablante.MUJER: VozElegida(KERSTIN_LOW, None),
        Hablante.HOMBRE: VozElegida(THORSTEN_MEDIUM, None),
    },
    "it": {h: VozElegida(PAOLA_MEDIUM, None) for h in Hablante},
}
"""Voz de cada idioma de destino y hablante. Si un idioma solo tiene una voz, lee a los dos."""


def elegir_voz(destino: str, hablante: Hablante = HABLANTE_POR_DEFECTO) -> VozElegida:
    """Voz con la que se lee el idioma `destino` con ese hablante."""
    return VOCES[destino][hablante]


def asegurar_voz(
    voz: VozPiper = SHARVARD_MEDIUM,
    directorio: Path | None = None,
    progreso: Progreso | None = None,
    cancelado: Cancelado | None = None,
) -> Path:
    """Ruta del modelo de la voz; la descarga antes si hace falta. La config queda a su lado."""
    asegurar_descarga(voz.config, directorio, cancelado=cancelado)
    return asegurar_descarga(voz.modelo, directorio, progreso=progreso, cancelado=cancelado)


class SintetizadorPiper:
    """Sintetiza con una voz de Piper, frase a frase."""

    def __init__(
        self, modelo: Path, hablante: str | None = HABLANTE_POR_DEFECTO, velocidad: float = 1.0
    ) -> None:
        """`velocidad` 1 es la de la voz; 1,25 lee un 25 % más deprisa."""
        if velocidad <= 0:
            raise VozFallidaError(_("Velocidad no válida: {velocidad}").format(velocidad=velocidad))
        self._modelo = modelo
        self._voz = PiperVoice.load(modelo)
        self._ajustes = SynthesisConfig(
            speaker_id=self._id_hablante(hablante),
            # Piper alarga los fonemas con `length_scale`: más velocidad, menos duración.
            length_scale=self._voz.config.length_scale / velocidad,
        )

    def con_hablante(self, hablante: str | None) -> "SintetizadorPiper":
        """El mismo modelo, ya cargado en memoria, con otro hablante y la misma velocidad."""
        otro = copy.copy(self)
        otro._ajustes = SynthesisConfig(
            speaker_id=self._id_hablante(hablante), length_scale=self._ajustes.length_scale
        )
        return otro

    def _id_hablante(self, hablante: str | None) -> int | None:
        hablantes = self._voz.config.speaker_id_map or {}
        if hablante is None:
            return None
        if hablante not in hablantes:
            raise VozFallidaError(
                _("La voz {voz} no tiene el hablante {hablante}").format(
                    voz=self._modelo.stem, hablante=hablante
                )
            )
        return hablantes[hablante]

    def sintetizar(self, texto: str) -> Iterator[Fragmento]:
        for trozo in self._voz.synthesize(texto, self._ajustes):
            yield Fragmento(trozo.audio_int16_array, trozo.sample_rate)
