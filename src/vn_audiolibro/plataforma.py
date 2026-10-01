"""Lo que depende del sistema operativo: ventanas, captura, audio y procesos.

El resto de la app pide aquí lo que necesita y nunca importa X11, PulseAudio ni Win32
directamente. Cada implementación se importa solo al pedirla, porque sus bibliotecas no existen
en el otro sistema.
"""

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from vn_audiolibro.captura.capturador import Capturador, CapturadorMss, Ventanas
from vn_audiolibro.textos import _
from vn_audiolibro.voz.modelos import Reproductor
from vn_audiolibro.voz.volumen import ClienteAudio, Juego


class PlataformaNoCompatibleError(RuntimeError):
    """Lo pedido todavía no está disponible en este sistema operativo."""


def es_linux() -> bool:
    return sys.platform == "linux"


def _exigir_linux(que: str) -> None:
    if not es_linux():
        raise PlataformaNoCompatibleError(
            _("{que} todavía no está disponible en este sistema ({sistema})").format(
                que=que, sistema=sys.platform
            )
        )


def es_windows() -> bool:
    return sys.platform == "win32"


def sin_ventana() -> int:
    """`creationflags` de un proceso hijo para que en Windows no abra una consola."""
    if sys.platform == "win32":  # así, mypy sabe que la constante existe
        return subprocess.CREATE_NO_WINDOW
    return 0


def idiomas_sistema(entorno: Mapping[str, str] | None = None) -> list[str]:
    """Idiomas del usuario según el sistema, por orden de preferencia (`es_ES.UTF-8`, `en`…).

    En Linux salen de las variables de entorno de siempre (`LANGUAGE`, `LC_ALL`, `LC_MESSAGES` y
    `LANG`); en Windows, del idioma de la interfaz de Windows. Si no se puede saber, vacía.
    """
    if sys.platform == "win32" and entorno is None:  # así, mypy sabe que existe `windll`
        import ctypes
        import locale

        try:
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        except (AttributeError, OSError):
            return []
        return [idioma] if (idioma := locale.windows_locale.get(lcid)) else []
    entorno = os.environ if entorno is None else entorno
    idiomas = [*entorno.get("LANGUAGE", "").split(":")]
    idiomas += [entorno.get(variable, "") for variable in ("LC_ALL", "LC_MESSAGES", "LANG")]
    return [idioma for idioma in idiomas if idioma and idioma not in {"C", "POSIX"}]


def gestor_ventanas() -> Ventanas:
    """Las ventanas del escritorio: X11 en Linux y Win32 en Windows."""
    if es_windows():
        from vn_audiolibro.captura.win32 import GestorVentanasWin32

        return GestorVentanasWin32()
    _exigir_linux(_("El listado de ventanas"))
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
    _exigir_linux(_("La captura de ventanas"))
    from vn_audiolibro.captura.x11 import CapturadorVentanaX11

    return CapturadorVentanaX11(alternativo=alternativo)


def reproductor() -> Reproductor:
    """Salida de audio para la voz: `paplay` en Linux, que pone el nombre de la app en el
    mezclador, y PortAudio en Windows."""
    if es_windows():
        from vn_audiolibro.voz.portaudio import ReproductorPortAudio

        return ReproductorPortAudio()
    _exigir_linux(_("La reproducción de audio"))
    from vn_audiolibro.voz.reproductor import ReproductorProceso

    return ReproductorProceso()


def instalar_acceso() -> Path:
    """Crea el acceso directo de la app en el menú: el de aplicaciones en Linux y el Inicio en Windows.

    Devuelve la ruta del acceso. Lanza `AccesoNoDisponibleError` si no se puede crear.
    """
    if es_windows():
        from vn_audiolibro.ui.acceso import instalar_acceso_windows

        return instalar_acceso_windows()
    _exigir_linux(_("El acceso directo en el menú"))
    from vn_audiolibro.ui.acceso import instalar_acceso as instalar_acceso_linux

    return instalar_acceso_linux()


def cliente_audio() -> ClienteAudio:
    """Conexión con el sistema de sonido, para bajar el volumen de otras aplicaciones:
    PulseAudio (o PipeWire) en Linux y las sesiones de audio de Core Audio en Windows."""
    if es_windows():
        from vn_audiolibro.voz.coreaudio import ClienteCoreAudio

        return ClienteCoreAudio()
    _exigir_linux(_("El control del volumen"))
    from vn_audiolibro.voz.volumen import ClientePulse

    return ClientePulse()


def carpeta_de_proceso(pid: int) -> Path | None:
    """Carpeta donde está el juego, a partir del proceso de su ventana; None si no se sabe.

    En Linux es su carpeta de trabajo, que con Proton es la del juego; en Windows, la de su
    ejecutable.
    """
    if sys.platform == "win32":  # así, mypy sabe que existe `windll`
        import ctypes

        acceso_limitado = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        proceso = ctypes.windll.kernel32.OpenProcess(acceso_limitado, False, pid)
        if not proceso:
            return None
        try:
            largo = ctypes.c_ulong(32768)
            ruta = ctypes.create_unicode_buffer(largo.value)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(proceso, 0, ruta, ctypes.byref(largo)):
                return None
            return Path(ruta.value).parent
        finally:
            ctypes.windll.kernel32.CloseHandle(proceso)
    try:
        return Path(f"/proc/{pid}/cwd").readlink()
    except OSError:
        return None


def juego_de_pid(pid: int) -> Juego:
    """Procesos del juego a partir del de su ventana, para reconocer su audio."""
    from vn_audiolibro.voz.volumen import juego_de_pid as juego

    return juego(pid)
