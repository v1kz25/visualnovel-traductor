"""Lo que depende del sistema operativo: ventanas, captura, audio y procesos.

El resto de la app pide aquí lo que necesita y nunca importa X11, PulseAudio ni Win32
directamente. Cada implementación se importa solo al pedirla, porque sus bibliotecas no existen
en el otro sistema.
"""

import subprocess
import sys
from pathlib import Path

from vn_audiolibro.captura.capturador import Capturador, CapturadorMss, Ventanas
from vn_audiolibro.voz.modelos import Reproductor
from vn_audiolibro.voz.volumen import ClienteAudio, Juego


class PlataformaNoCompatibleError(RuntimeError):
    """Lo pedido todavía no está disponible en este sistema operativo."""


def es_linux() -> bool:
    return sys.platform == "linux"


def _exigir_linux(que: str) -> None:
    if not es_linux():
        raise PlataformaNoCompatibleError(
            f"{que} todavía no está disponible en este sistema ({sys.platform})"
        )


def es_windows() -> bool:
    return sys.platform == "win32"


def sin_ventana() -> int:
    """`creationflags` de un proceso hijo para que en Windows no abra una consola."""
    if sys.platform == "win32":  # así, mypy sabe que la constante existe
        return subprocess.CREATE_NO_WINDOW
    return 0


def gestor_ventanas() -> Ventanas:
    """Las ventanas del escritorio: X11 en Linux y Win32 en Windows."""
    if es_windows():
        from vn_audiolibro.captura.win32 import GestorVentanasWin32

        return GestorVentanasWin32()
    _exigir_linux("El listado de ventanas")
    from vn_audiolibro.captura.x11 import GestorVentanasX11

    return GestorVentanasX11()


def capturador(ventanas: Ventanas, solo_pantalla: bool = False) -> Capturador:
    """Captura del contenido de la ventana aunque tenga otras encima.

    Con `solo_pantalla`, o si el sistema no permite leer la ventana, captura lo que se ve en
    pantalla en su posición.
    """
    alternativo = CapturadorMss(ventanas)
    if solo_pantalla:
        return alternativo
    if es_windows():
        from vn_audiolibro.captura.win32 import CapturadorVentanaWin32

        return CapturadorVentanaWin32(alternativo=alternativo)
    _exigir_linux("La captura de ventanas")
    from vn_audiolibro.captura.x11 import CapturadorVentanaX11

    return CapturadorVentanaX11(alternativo=alternativo)


def reproductor() -> Reproductor:
    """Salida de audio para la voz: `paplay` en Linux, que pone el nombre de la app en el
    mezclador, y PortAudio en Windows."""
    if es_windows():
        from vn_audiolibro.voz.portaudio import ReproductorPortAudio

        return ReproductorPortAudio()
    _exigir_linux("La reproducción de audio")
    from vn_audiolibro.voz.reproductor import ReproductorProceso

    return ReproductorProceso()


def instalar_acceso() -> Path:
    """Crea el acceso directo de la app en el menú: el de aplicaciones en Linux y el Inicio en Windows.

    Devuelve la ruta del acceso. Lanza `AccesoNoDisponibleError` si no se puede crear.
    """
    if es_windows():
        from vn_audiolibro.ui.acceso import instalar_acceso_windows

        return instalar_acceso_windows()
    _exigir_linux("El acceso directo en el menú")
    from vn_audiolibro.ui.acceso import instalar_acceso as instalar_acceso_linux

    return instalar_acceso_linux()


def cliente_audio() -> ClienteAudio:
    """Conexión con el sistema de sonido, para bajar el volumen de otras aplicaciones:
    PulseAudio (o PipeWire) en Linux y las sesiones de audio de Core Audio en Windows."""
    if es_windows():
        from vn_audiolibro.voz.coreaudio import ClienteCoreAudio

        return ClienteCoreAudio()
    _exigir_linux("El control del volumen")
    from vn_audiolibro.voz.volumen import ClientePulse

    return ClientePulse()


def juego_de_pid(pid: int) -> Juego:
    """Procesos del juego a partir del de su ventana, para reconocer su audio."""
    from vn_audiolibro.voz.volumen import juego_de_pid as juego

    return juego(pid)
