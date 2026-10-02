"""Voz en español o en inglés con Piper (GPL-3.0), en CPU."""

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

HABLANTE_POR_DEFECTO = Hablante.MUJER


@dataclass(frozen=True)
class VozElegida:
    """Voz de Piper que lee un idioma con un hablante, y el hablante dentro de ella."""

    voz: VozPiper
    hablante: Hablante | None
    """Hablante de una voz con varios, o None si la voz solo tiene uno."""


VOCES: dict[str, dict[Hablante, VozElegida]] = {
    "es": {h: VozElegida(SHARVARD_MEDIUM, h) for h in Hablante},
    "en": {
        Hablante.MUJER: VozElegida(KRISTIN_MEDIUM, None),
        Hablante.HOMBRE: VozElegida(JOHN_MEDIUM, None),
    },
}
"""Voz de cada idioma de destino y hablante. Las inglesas son dos voces de un solo hablante."""


def elegir_voz(destino: str, hablante: Hablante = HABLANTE_POR_DEFECTO) -> VozElegida:
    """Voz con la que se lee el idioma `destino` (`es` o `en`) con ese hablante."""
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
        self, modelo: Path, hablante: Hablante | None = HABLANTE_POR_DEFECTO, velocidad: float = 1.0
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

    def con_hablante(self, hablante: Hablante | None) -> "SintetizadorPiper":
        """El mismo modelo, ya cargado en memoria, con otro hablante y la misma velocidad."""
        otro = copy.copy(self)
        otro._ajustes = SynthesisConfig(
            speaker_id=self._id_hablante(hablante), length_scale=self._ajustes.length_scale
        )
        return otro

    def _id_hablante(self, hablante: Hablante | None) -> int | None:
        hablantes = self._voz.config.speaker_id_map or {}
        if hablante is None:
            return None
        if hablante not in hablantes:
            raise VozFallidaError(
                _("La voz {voz} no tiene el hablante {hablante}").format(
                    voz=self._modelo.stem, hablante=hablante.name.lower()
                )
            )
        return hablantes[hablante]

    def sintetizar(self, texto: str) -> Iterator[Fragmento]:
        for trozo in self._voz.synthesize(texto, self._ajustes):
            yield Fragmento(trozo.audio_int16_array, trozo.sample_rate)
