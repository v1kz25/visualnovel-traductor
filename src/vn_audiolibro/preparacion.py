"""Preparación del equipo: comprobar el sistema y descargar los componentes la primera vez.

Los modelos no van en el repo ni en el AppImage: se descargan una sola vez, verificados por
SHA-256, y a partir de ahí la app funciona sin conexión.
"""

import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass

from vn_audiolibro.descargas import Cancelado, Progreso, asegurar_descarga, directorio_modelos
from vn_audiolibro.ocr.modelos import REC_PPOCRV5_MOBILE
from vn_audiolibro.textos import N_, _
from vn_audiolibro.traduccion.llama import (
    HY_MT2_1_8B_Q4,
    asegurar_llama_server,
    asegurar_modelo_traduccion,
    binario_llama,
    ruta_llama_server,
)
from vn_audiolibro.voz.piper import SHARVARD_MEDIUM, asegurar_voz
from vn_audiolibro.voz.volumen import hay_control_de_volumen

AVISO_COPYRIGHT = N_(
    "vn-audiolibro no incluye ningún juego ni textos de juegos. Las traducciones y el audio que "
    "genera se guardan solo en tu equipo y no se comparten con nadie."
)
"""Se traduce al mostrarlo, con `_()`."""


@dataclass(frozen=True)
class Componente:
    """Algo que la app necesita descargar una vez para funcionar sin conexión."""

    nombre: str
    uso: str
    licencia: str
    tamano: int
    """Bytes aproximados de la descarga."""
    instalado: Callable[[], bool]
    instalar: Callable[[Progreso | None, Cancelado | None], object]


def componentes() -> list[Componente]:
    """Todos los componentes, en el orden en que se descargan (primero los pequeños)."""
    modelos = directorio_modelos()
    return [
        Componente(
            _("Reconocimiento de texto (PP-OCRv5)"),
            _("Lee el texto chino o japonés de la pantalla"),
            "Apache-2.0",
            16_631_306,
            lambda: (modelos / REC_PPOCRV5_MOBILE.fichero).is_file(),
            lambda progreso, cancelado: asegurar_descarga(
                REC_PPOCRV5_MOBILE, progreso=progreso, cancelado=cancelado
            ),
        ),
        Componente(
            _("Servidor de traducción (llama.cpp)"),
            _("Ejecuta el modelo de traducción en tu equipo"),
            "MIT",
            binario_llama().tamano,
            lambda: ruta_llama_server().is_file(),
            lambda progreso, cancelado: asegurar_llama_server(progreso=progreso, cancelado=cancelado),
        ),
        Componente(
            _("Voz en español (Piper, sharvard)"),
            _("Lee las traducciones en voz alta, con voz de mujer u hombre"),
            _("Piper GPL-3.0; voz CC BY 3.0"),
            76_738_518,
            lambda: all(
                (modelos / d.fichero).is_file() for d in (SHARVARD_MEDIUM.modelo, SHARVARD_MEDIUM.config)
            ),
            lambda progreso, cancelado: asegurar_voz(progreso=progreso, cancelado=cancelado),
        ),
        Componente(
            _("Modelo de traducción (Hy-MT2 1.8B, Tencent)"),
            _("Traduce sin conexión"),
            "Apache-2.0",
            1_133_080_448,
            lambda: (modelos / HY_MT2_1_8B_Q4.fichero).is_file(),
            lambda progreso, cancelado: asegurar_modelo_traduccion(progreso=progreso, cancelado=cancelado),
        ),
    ]


def pendientes() -> list[Componente]:
    """Componentes que aún no están en el equipo."""
    return [componente for componente in componentes() if not componente.instalado()]


@dataclass(frozen=True)
class Aviso:
    """Algo del sistema que falta o no es compatible."""

    texto: str
    grave: bool
    """True si impide usar la app; False si solo se pierde alguna función."""


def comprobar_sistema(
    entorno: dict[str, str] | None = None, hay_libpulse: Callable[[], bool] = hay_control_de_volumen
) -> list[Aviso]:
    """Comprueba lo que la app necesita del sistema y que no puede descargar.

    En Windows no hay nada que comprobar: la captura, el audio y el volumen usan lo que trae el
    propio sistema y las bibliotecas que se instalan con la app.
    """
    if sys.platform == "win32":
        return []
    entorno = dict(os.environ) if entorno is None else entorno
    avisos = []
    if entorno.get("XDG_SESSION_TYPE", "").lower() == "wayland" or not entorno.get("DISPLAY"):
        avisos.append(
            Aviso(
                _(
                    "La sesión no es X11: no se podrá capturar la ventana del juego. Entra en una sesión "
                    "«Xorg» o «X11» desde la pantalla de inicio de sesión."
                ),
                grave=True,
            )
        )
    if shutil.which("paplay") is None:
        avisos.append(
            Aviso(
                _("Falta «paplay»: no se oirá la voz. Instálalo con: sudo apt install pulseaudio-utils"), True
            )
        )
    if not hay_libpulse():
        avisos.append(
            Aviso(_("Falta libpulse: no se podrá bajar el volumen del juego mientras habla la voz."), False)
        )
    return avisos
