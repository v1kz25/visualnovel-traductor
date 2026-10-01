"""Tests de la línea de comandos `vn-audiolibro`, con la sesión sustituida por una falsa."""

import contextlib
import io
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from tests.conftest import parece_espanol
from vn_audiolibro import cli, plataforma
from vn_audiolibro.cache.modelos import Clave
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.captura.modelos import VentanaNoEncontradaError
from vn_audiolibro.configuracion import AjustesApp, guardar_ajustes
from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.guion.modelos import GuionNoEncontradoError, OrigenGuion
from vn_audiolibro.ocr.preprocesado import BusquedaTexto
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import AjustesGuion, AjustesLectura, Color, Perfil
from vn_audiolibro.pipeline.orquestador import LineaJuego, Tiempos
from vn_audiolibro.preparacion import Aviso, Componente
from vn_audiolibro.voz.modelos import ModoLectura
from vn_audiolibro.voz.piper import Hablante


@pytest.fixture(autouse=True)
def configuracion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AlmacenPerfiles:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return AlmacenPerfiles()


class OrquestadorFalso:
    def __init__(self) -> None:
        self.pausado = False
        self.silenciado = False
        self.acciones: list[str] = []

    def pausar(self) -> None:
        self.pausado = True
        self.acciones.append("pausar")

    def reanudar(self) -> None:
        self.pausado = False
        self.acciones.append("reanudar")

    def silenciar(self) -> None:
        self.silenciado = True
        self.acciones.append("silenciar")

    def quitar_silencio(self) -> None:
        self.silenciado = False
        self.acciones.append("quitar_silencio")

    def repetir(self) -> None:
        self.acciones.append("repetir")

    def saltar(self) -> None:
        self.acciones.append("saltar")


class SesionFalsa:
    """Sesión que muestra dos líneas al arrancar; `fallo` hace que no arranque."""

    creadas: ClassVar[list["SesionFalsa"]] = []
    fallo: ClassVar[BaseException | None] = None

    def __init__(
        self,
        perfil: Perfil,
        al_linea: Callable[[LineaJuego], None],
        al_error: Callable[[str], None],
        al_estado: Callable[[str], None],
    ) -> None:
        self.perfil = perfil
        self.al_linea = al_linea
        self.al_estado = al_estado
        self.orquestador = OrquestadorFalso()
        self.detenida = False
        SesionFalsa.creadas.append(self)

    def iniciar(self) -> OrquestadorFalso:
        self.al_estado("Arrancando…")
        if SesionFalsa.fallo is not None:
            raise SesionFalsa.fallo
        self.al_linea(LineaJuego("一", "uno", desde_cache=True, leida=True))
        self.al_linea(LineaJuego("二", "dos", desde_cache=False, leida=False))
        return self.orquestador

    def detener(self) -> None:
        self.detenida = True


@pytest.fixture
def sesion_falsa(monkeypatch: pytest.MonkeyPatch) -> type[SesionFalsa]:
    SesionFalsa.creadas = []
    SesionFalsa.fallo = None
    monkeypatch.setattr(cli, "Sesion", SesionFalsa)
    return SesionFalsa


def test_sin_perfiles(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["juegos"]) == 0
    assert "No hay juegos" in capsys.readouterr().out


def test_sin_orden_abre_la_interfaz(monkeypatch: pytest.MonkeyPatch) -> None:
    from vn_audiolibro.ui import app

    monkeypatch.setattr(app, "ejecutar", lambda: 7)
    assert cli.main([]) == 7


def test_crear_y_listar(configuracion: AlmacenPerfiles, capsys: pytest.CaptureFixture[str]) -> None:
    argumentos = ["crear", "Mi juego", "--ventana", "juego", "--zona", "0.1,0.7,0.8,0.25", "--idioma", "ja"]
    opciones = [
        "--oscuro",
        "--vertical",
        "--detector",
        "--hombre",
        "--velocidad",
        "1.2",
        "--nivel",
        "0.5",
        "--destino",
        "en",
    ]
    assert cli.main([*argumentos, *opciones, "--sin-bajar-volumen"]) == 0

    (perfil,) = configuracion.listar()
    assert (perfil.nombre, perfil.ventana, perfil.idioma, perfil.destino) == ("Mi juego", "juego", "ja", "en")
    assert perfil.color == Color.OSCURO
    assert perfil.busqueda is BusquedaTexto.DETECTOR
    assert perfil.zona.y == 0.7
    assert (perfil.voz.hablante, perfil.voz.velocidad) == (Hablante.HOMBRE, 1.2)
    assert (perfil.volumen.activo, perfil.volumen.nivel_juego) == (False, 0.5)
    assert perfil.lectura == AjustesLectura(ModoLectura.COLA, 2.0)

    assert cli.main(["crear", "Otro", "--ventana", "otro", "--saltar-a-la-ultima", "--pausa", "0.5"]) == 0
    otro = configuracion.buscar("Otro")
    assert otro.lectura == AjustesLectura(ModoLectura.ULTIMA, 0.5)
    assert otro.destino == "es"
    assert otro.busqueda is BusquedaTexto.COLOR

    assert cli.main(["juegos"]) == 0
    assert "Mi juego  (ventana «juego», ja → en" in capsys.readouterr().out


def test_crear_repetido_o_no_valido(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["crear", "Juego", "--ventana", "juego"]) == 0
    assert cli.main(["crear", "juego", "--ventana", "otro"]) == 1
    assert "Ya hay un juego" in capsys.readouterr().err
    assert cli.main(["crear", "Otro", "--ventana", "juego", "--velocidad", "5"]) == 1
    assert "velocidad" in capsys.readouterr().err


def test_crear_con_guion(configuracion: AlmacenPerfiles, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["crear", "Juego", "--ventana", "juego", "--guion", "/juegos/uno", "--desde-ingles"]) == 0
    assert configuracion.buscar("Juego").guion == AjustesGuion("/juegos/uno", OrigenGuion.INGLES)

    assert cli.main(["crear", "Otro", "--ventana", "otro", "--guion", "/juegos/dos"]) == 0
    assert configuracion.buscar("Otro").guion == AjustesGuion("/juegos/dos", OrigenGuion.ORIGINAL)

    assert cli.main(["crear", "Mal", "--ventana", "mal", "--desde-ingles"]) == 1
    assert "--guion" in capsys.readouterr().err


class PreparadorFalso:
    def __init__(self, cortar: bool = False) -> None:
        self._cortar = cortar

    def traducir_todo(self, al_progreso: Callable[[int, int], None]) -> int:
        al_progreso(1, 4)
        if self._cortar:
            raise KeyboardInterrupt
        al_progreso(4, 4)
        return 3


def _traductor_guion(
    monkeypatch: pytest.MonkeyPatch, preparador: PreparadorFalso | None = None, error: Exception | None = None
) -> None:
    @contextlib.contextmanager
    def falso(perfil: Perfil, al_estado: Callable[[str], None]) -> Iterator[PreparadorFalso]:
        al_estado("Arrancando")
        if error is not None:
            raise error
        yield preparador or PreparadorFalso()

    monkeypatch.setattr(cli, "traductor_guion", falso)


def test_traducir_guion(
    configuracion: AlmacenPerfiles, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configuracion.guardar(Perfil("Juego", "juego", guion=AjustesGuion("/j")))
    _traductor_guion(monkeypatch)

    assert cli.main(["traducir-guion", "Juego"]) == 0

    salida = capsys.readouterr()
    assert "4 de 4 párrafos (100 %)" in salida.out
    assert "3 párrafos traducidos" in salida.out
    assert "Arrancando" in salida.err


def test_traducir_guion_cortado_o_sin_guion(
    configuracion: AlmacenPerfiles, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configuracion.guardar(Perfil("Juego", "juego", guion=AjustesGuion("/j")))
    _traductor_guion(monkeypatch, PreparadorFalso(cortar=True))
    assert cli.main(["traducir-guion", "Juego"]) == 0
    assert "Cortado" in capsys.readouterr().out

    _traductor_guion(monkeypatch, error=GuionNoEncontradoError("sin guion"))
    assert cli.main(["traducir-guion", "Juego"]) == 1
    assert "sin guion" in capsys.readouterr().err


def test_zona_mal_escrita(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["crear", "Juego", "--ventana", "juego", "--zona", "0.1,0.2"])
    assert "zona no válida" in capsys.readouterr().err


def test_jugar_muestra_las_lineas_y_atiende_las_ordenes(
    sesion_falsa: type[SesionFalsa], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["crear", "Juego", "--ventana", "juego"]) == 0

    assert (
        cli.main(
            ["jugar", "juego"], entrada=["p\n", "p\n", "r\n", "s\n", "m\n", "m\n", "\n", "?\n", "q\n", "r\n"]
        )
        == 0
    )

    (sesion,) = sesion_falsa.creadas
    acciones = ["pausar", "reanudar", "repetir", "saltar", "silenciar", "quitar_silencio"]
    assert sesion.orquestador.acciones == acciones  # nada tras «q»
    assert sesion.detenida
    salida = capsys.readouterr()
    assert "一\n→ uno\n" in salida.out
    assert "二\n→ dos (no leída: llegó otra línea)" in salida.out
    assert "⏸ En pausa" in salida.out
    assert "▶ Reanudado" in salida.out
    assert "🔇 Voz silenciada" in salida.out
    assert "🔊 Voz activada" in salida.out
    assert salida.out.count("Controles") == 2  # al empezar y tras la orden desconocida
    assert "! Arrancando…" in salida.err


def test_jugar_hasta_el_final_de_la_entrada(sesion_falsa: type[SesionFalsa]) -> None:
    cli.main(["crear", "Juego", "--ventana", "juego"])
    assert cli.main(["jugar", "Juego"], entrada=[]) == 0
    assert sesion_falsa.creadas[0].detenida


def test_jugar_sin_ventana(sesion_falsa: type[SesionFalsa], capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["crear", "Juego", "--ventana", "juego"])
    sesion_falsa.fallo = VentanaNoEncontradaError("No hay ninguna ventana con «juego» en el título")

    assert cli.main(["jugar", "Juego"], entrada=[]) == 1
    assert "No hay ninguna ventana" in capsys.readouterr().err
    assert sesion_falsa.creadas[0].detenida


def test_jugar_con_ctrl_c(sesion_falsa: type[SesionFalsa]) -> None:
    cli.main(["crear", "Juego", "--ventana", "juego"])
    sesion_falsa.fallo = KeyboardInterrupt()
    assert cli.main(["jugar", "Juego"], entrada=[]) == 0
    assert sesion_falsa.creadas[0].detenida


def test_jugar_perfil_inexistente(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["jugar", "otro"]) == 1
    assert "No hay ningún juego llamado «otro»" in capsys.readouterr().err


def test_jugar_con_tiempos(sesion_falsa: type[SesionFalsa], capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["crear", "Juego", "--ventana", "juego"])

    def con_tiempos(self: SesionFalsa) -> OrquestadorFalso:
        self.al_linea(LineaJuego("一", "uno", False, True, Tiempos(0.1, 1.5, 0.8)))
        self.al_linea(LineaJuego("二", "dos", False, False, Tiempos(0.1, 2.0, None)))
        return self.orquestador

    sesion_falsa.iniciar = con_tiempos  # type: ignore[method-assign]
    assert cli.main(["jugar", "Juego", "--tiempos"], entrada=[]) == 0

    salida = capsys.readouterr().out
    assert "OCR 0.10 s · traducción 1.50 s · hasta la voz 0.80 s" in salida
    assert "hasta la voz no se leyó" in salida


def test_cache_mostrar_vaciar_y_limitar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "datos"))
    cli.main(["crear", "Juego", "--ventana", "juego"])
    perfil = AlmacenPerfiles().buscar("Juego")
    cache = CacheSQLite()
    cache.guardar_traduccion(Clave(perfil.id, "zh-Hant", "一"), "uno", "hy-mt2")
    cache.cerrar()
    capsys.readouterr()

    assert cli.main(["cache"]) == 0
    salida = capsys.readouterr().out
    assert "Juego: 1 línea," in salida
    assert "(máximo 2048 MB)" in salida

    assert cli.main(["cache", "--limite", "500"]) == 0
    assert "(máximo 500 MB)" in capsys.readouterr().out
    assert cli.main(["cache", "--sin-limite"]) == 0
    assert "(sin límite)" in capsys.readouterr().out
    assert cli.main(["cache", "--limite", "5"]) == 1
    assert "al menos 100 MB" in capsys.readouterr().err

    assert cli.main(["cache", "--vaciar", "juego"]) == 0
    assert "Vaciada la caché de «Juego»: 1 línea\n" in capsys.readouterr().out
    assert cli.main(["cache", "--vaciar-todo"]) == 0
    assert "Total: vacía" in capsys.readouterr().out


def test_preparar_descarga_lo_que_falta(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    instalados: list[str] = []

    def componente(nombre: str, falla: bool = False) -> Componente:
        def instalar(progreso: object, cancelado: object) -> None:
            assert callable(progreso)
            progreso(512, 1024)
            progreso(1024, None)
            if falla:
                raise DescargaFallidaError("sin conexión")
            instalados.append(nombre)

        return Componente(nombre, "uso", "MIT", 1024, lambda: False, instalar)

    monkeypatch.setattr(
        cli.preparacion,
        "comprobar_sistema",
        lambda: [Aviso("Falta paplay", True), Aviso("Sin libpulse", False)],
    )
    monkeypatch.setattr(cli.preparacion, "pendientes", lambda: [componente("OCR"), componente("Voz")])
    assert cli.main(["preparar"]) == 0
    salida = capsys.readouterr().out
    assert "⚠ Falta paplay" in salida
    assert "Aviso: Sin libpulse" in salida
    assert "Descargando OCR (1 KB, MIT)…" in salida
    assert "(50 %)" in salida
    assert "Todo listo." in salida
    assert instalados == ["OCR", "Voz"]

    monkeypatch.setattr(cli.preparacion, "pendientes", lambda: [componente("Traductor", falla=True)])
    assert cli.main(["preparar"]) == 1
    assert "sin conexión" in capsys.readouterr().err

    monkeypatch.setattr(cli.preparacion, "comprobar_sistema", lambda: [])
    monkeypatch.setattr(cli.preparacion, "pendientes", lambda: [])
    assert cli.main(["preparar"]) == 0
    assert "Todos los componentes están descargados." in capsys.readouterr().out


def test_instalar_acceso(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")

    assert cli.main(["instalar-acceso"]) == 0

    assert (tmp_path / "applications" / "vn-audiolibro.desktop").exists()
    assert "Acceso directo creado" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("plataforma", "mensaje"),
    [("win32", "solo se puede crear desde la versión empaquetada"), ("darwin", "no está disponible")],
)
def test_instalar_acceso_cuando_no_se_puede(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    plataforma: str,
    mensaje: str,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "platform", plataforma)
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert cli.main(["instalar-acceso"]) == 1

    assert list(tmp_path.iterdir()) == []
    assert mensaje in capsys.readouterr().err


@pytest.mark.parametrize(
    ("plataforma", "empaquetada", "nombre"),
    [
        ("win32", True, "vn-audiolibro-consola"),
        ("win32", False, "vn-audiolibro"),
        ("linux", True, "vn-audiolibro"),
    ],
)
def test_nombre_de_la_orden(
    monkeypatch: pytest.MonkeyPatch, plataforma: str, empaquetada: bool, nombre: str
) -> None:
    monkeypatch.setattr(sys, "platform", plataforma)
    monkeypatch.setattr(sys, "frozen", empaquetada, raising=False)
    assert cli.nombre_orden() == nombre


@pytest.mark.parametrize(("plataforma", "codificacion"), [("win32", "utf-8"), ("linux", "cp1252")])
def test_en_windows_la_salida_es_utf8(
    monkeypatch: pytest.MonkeyPatch, plataforma: str, codificacion: str
) -> None:
    salida = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "platform", plataforma)
    monkeypatch.setattr(sys, "stdout", salida)
    monkeypatch.setattr(sys, "stderr", None)  # la interfaz empaquetada no tiene consola
    cli.salida_utf8()
    assert salida.encoding == codificacion


@pytest.mark.parametrize("orden", [[], ["crear"], ["jugar"], ["cache"]])
def test_ayuda_en_ingles_con_el_sistema_en_ingles(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], orden: list[str]
) -> None:
    monkeypatch.setattr(plataforma, "idiomas_sistema", lambda: ["en_US.UTF-8"])
    with pytest.raises(SystemExit):
        cli.main([*orden, "--help"])
    ayuda = capsys.readouterr().out
    # Sin el uso, que repite las opciones: ni las órdenes ni las opciones se traducen.
    cuerpo = ayuda.split("\n\n", 1)[1]
    sin_nombres = re.sub(
        r"--?[\w-]+|\{[^}]*\}|\b(crear|jugar|juegos|preparar|cache|instalar-acceso)\b", "", cuerpo
    )
    assert not parece_espanol(sin_nombres), sin_nombres


def test_idioma_elegido_en_la_app_manda_sobre_el_del_sistema(capsys: pytest.CaptureFixture[str]) -> None:
    guardar_ajustes(AjustesApp(idioma="en"))
    assert cli.main(["juegos"]) == 0
    assert "No games yet" in capsys.readouterr().out
