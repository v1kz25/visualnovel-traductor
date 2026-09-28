"""Punto de entrada: sin argumentos abre la interfaz gráfica; con una orden, trabaja en la terminal.

    uv run vn-audiolibro
    uv run vn-audiolibro preparar
    uv run vn-audiolibro juegos
    uv run vn-audiolibro crear "Mi juego" --ventana "mi juego" --zona 0.1,0.7,0.8,0.25 --idioma ja
    uv run vn-audiolibro jugar "Mi juego"
    uv run vn-audiolibro cache [--vaciar "Mi juego" | --vaciar-todo | --limite MB | --sin-limite]
    uv run vn-audiolibro instalar-acceso

Mientras se juega, se controla escribiendo en la terminal y pulsando Intro:
`p` pausa o reanuda, `r` repite la última línea, `s` la calla y `q` sale.
"""

import argparse
import io
import logging
import sys
from collections.abc import Callable, Iterable
from dataclasses import replace
from importlib.metadata import version

from vn_audiolibro import plataforma, preparacion
from vn_audiolibro.cache.sqlite import CacheSQLite
from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, VentanaNoEncontradaError, ZonaRelativa
from vn_audiolibro.configuracion import AjustesApp, cargar_ajustes, formato_tamano, guardar_ajustes
from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.ocr.preprocesado import Orientacion
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles, PerfilDuplicadoError
from vn_audiolibro.perfiles.modelos import (
    DESTINOS,
    IDIOMAS,
    AjustesLectura,
    AjustesVolumen,
    AjustesVoz,
    Color,
    Perfil,
    PerfilInvalidoError,
)
from vn_audiolibro.pipeline.orquestador import LineaJuego, Orquestador
from vn_audiolibro.pipeline.sesion import Sesion
from vn_audiolibro.traduccion.modelos import TraduccionFallidaError
from vn_audiolibro.voz.modelos import ModoLectura, VozFallidaError
from vn_audiolibro.voz.piper import Hablante

AYUDA_CONTROLES = "Controles (escribe y pulsa Intro): p pausa/reanuda · r repite · s calla · q sale"


def _zona(texto: str) -> ZonaRelativa:
    try:
        x, y, ancho, alto = (float(v) for v in texto.split(","))
        return ZonaRelativa(x=x, y=y, ancho=ancho, alto=alto)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"zona no válida (x,y,ancho,alto entre 0 y 1): {texto}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=nombre_orden(), description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('vn-audiolibro')}")
    # Oculta: la usa la CI para comprobar el ejecutable empaquetado.
    parser.add_argument("--autocomprobacion", action="store_true", help=argparse.SUPPRESS)
    ordenes = parser.add_subparsers(dest="orden")
    ordenes.add_parser("preparar", help="comprueba el sistema y descarga lo que falte para usar la app")
    ordenes.add_parser("juegos", help="lista los juegos configurados")

    crear = ordenes.add_parser("crear", help="configura un juego nuevo")
    crear.add_argument("nombre")
    crear.add_argument("--ventana", required=True, help="texto del título de la ventana del juego")
    crear.add_argument("--zona", type=_zona, default=TODA_LA_VENTANA, help="x,y,ancho,alto entre 0 y 1")
    crear.add_argument("--idioma", choices=IDIOMAS, default=IDIOMAS[0], help="idioma del juego")
    crear.add_argument(
        "--destino", choices=DESTINOS, default=DESTINOS[0], help="idioma de la traducción y de la voz"
    )
    crear.add_argument("--oscuro", action="store_true", help="el texto es oscuro sobre fondo claro")
    crear.add_argument("--vertical", action="store_true", help="el texto va en columnas verticales")
    crear.add_argument("--hombre", action="store_true", help="voz de hombre (por defecto, de mujer)")
    crear.add_argument("--velocidad", type=float, default=1.0, help="velocidad de la voz (1 = normal)")
    crear.add_argument("--nivel", type=float, default=AjustesVolumen().nivel_juego, help="volumen del juego")
    crear.add_argument("--sin-bajar-volumen", action="store_true", help="no bajar el juego mientras habla")
    crear.add_argument(
        "--saltar-a-la-ultima",
        action="store_true",
        help="al avanzar deprisa, cortar la línea que suena y leer solo la última (por defecto, en cola)",
    )
    crear.add_argument(
        "--pausa", type=float, default=AjustesLectura().pausa_s, help="segundos de silencio entre líneas"
    )

    cache = ordenes.add_parser("cache", help="muestra lo que ocupa la caché; permite vaciarla o limitarla")
    accion = cache.add_mutually_exclusive_group()
    accion.add_argument("--vaciar", metavar="JUEGO", help="vacía la caché de un juego")
    accion.add_argument("--vaciar-todo", action="store_true", help="vacía la caché de todos los juegos")
    accion.add_argument("--limite", type=int, metavar="MB", help="tamaño máximo de la caché")
    accion.add_argument("--sin-limite", action="store_true", help="no limitar el tamaño de la caché")

    ordenes.add_parser(
        "instalar-acceso", help="añade vn-audiolibro al menú de aplicaciones (en Windows, al menú Inicio)"
    )

    jugar = ordenes.add_parser("jugar", help="juega con un juego configurado")
    jugar.add_argument("juego", help="nombre del juego")
    jugar.add_argument("--tiempos", action="store_true", help="muestra cuánto tarda cada etapa de cada línea")
    return parser


def nombre_orden() -> str:
    """Cómo se llama la orden de la terminal: en la versión de Windows, el ejecutable de consola."""
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        return "vn-audiolibro-consola"
    return "vn-audiolibro"


def salida_utf8() -> None:
    """En Windows, escribe en UTF-8 también cuando la salida va a un fichero o a otro programa.

    Python solo usa UTF-8 al escribir en la consola; si la salida se redirige, usa la página de
    códigos del sistema (cp1252), que no tiene los caracteres chinos ni japoneses y falla con los
    nombres de los juegos. Sin consola (la interfaz gráfica empaquetada) no hay nada que cambiar.
    """
    if sys.platform != "win32":
        return
    for flujo in (sys.stdout, sys.stderr):
        if isinstance(flujo, io.TextIOWrapper):
            flujo.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None, entrada: Iterable[str] = sys.stdin) -> int:
    """Punto de entrada de la terminal."""
    salida_utf8()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = _parser().parse_args(argv)
    if args.autocomprobacion:
        from vn_audiolibro.autocomprobacion import autocomprobar

        return autocomprobar()
    almacen = AlmacenPerfiles()
    try:
        if args.orden == "crear":
            return _crear(almacen, args)
        if args.orden == "jugar":
            return _jugar(almacen.buscar(args.juego), entrada, args.tiempos)
        if args.orden == "preparar":
            return _preparar()
        if args.orden == "juegos":
            return _perfiles(almacen)
        if args.orden == "cache":
            return _cache(almacen, args)
        if args.orden == "instalar-acceso":
            return _instalar_acceso()
    except (KeyError, ValueError, PerfilInvalidoError, PerfilDuplicadoError) as error:
        print(error.args[0] if error.args else error, file=sys.stderr)
        return 1
    from vn_audiolibro.ui.app import ejecutar  # Qt solo se carga si se abre la interfaz

    return ejecutar()


def _perfiles(almacen: AlmacenPerfiles) -> int:
    perfiles = almacen.listar()
    if not perfiles:
        print(f'No hay juegos. Configura uno con: {nombre_orden()} crear "Mi juego" --ventana "título"')
    for perfil in perfiles:
        idiomas = f"{perfil.idioma} → {perfil.destino}"
        print(f"{perfil.nombre}  (ventana «{perfil.ventana}», {idiomas}, id {perfil.id})")
    return 0


def _instalar_acceso() -> int:
    from vn_audiolibro.ui.acceso import AccesoNoDisponibleError

    try:
        ruta = plataforma.instalar_acceso()
    except (AccesoNoDisponibleError, plataforma.PlataformaNoCompatibleError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Acceso directo creado en {ruta}")
    return 0


def _preparar() -> int:
    for aviso in preparacion.comprobar_sistema():
        print(("⚠ " if aviso.grave else "Aviso: ") + aviso.texto)
    faltan = preparacion.pendientes()
    if not faltan:
        print("Todos los componentes están descargados.")
        return 0
    print(preparacion.AVISO_COPYRIGHT)
    for componente in faltan:
        print(
            f"Descargando {componente.nombre} ({formato_tamano(componente.tamano)}, {componente.licencia})…"
        )
        try:
            componente.instalar(_progreso_terminal, None)
        except DescargaFallidaError as error:
            print(f"\n{error}", file=sys.stderr)
            return 1
        print()
    print("Todo listo.")
    return 0


def _progreso_terminal(hecho: int, total: int | None) -> None:
    porcentaje = f" ({100 * hecho // total} %)" if total else ""
    print(f"\r  {formato_tamano(hecho)}{porcentaje}", end="", flush=True)


def _cache(almacen: AlmacenPerfiles, args: argparse.Namespace) -> int:
    ajustes = cargar_ajustes()
    if args.limite is not None or args.sin_limite:
        ajustes = AjustesApp(limite_cache_mb=None if args.sin_limite else args.limite)
        guardar_ajustes(ajustes)
    cache = CacheSQLite(limite_bytes=ajustes.limite_cache_bytes)
    try:
        if args.vaciar:
            perfil = almacen.buscar(args.vaciar)
            print(f"Vaciada la caché de «{perfil.nombre}»: {cache.invalidar(perfil.id)} líneas")
        elif args.vaciar_todo:
            print(f"Vaciada la caché: {cache.vaciar()} líneas")
        cache.recortar()
        _mostrar_cache(almacen, cache, ajustes)
    finally:
        cache.cerrar()
    return 0


def _mostrar_cache(almacen: AlmacenPerfiles, cache: CacheSQLite, ajustes: AjustesApp) -> None:
    nombres = {perfil.id: perfil.nombre for perfil in almacen.listar()}
    resumen = cache.resumen()
    for juego in resumen:
        nombre = nombres.get(juego.perfil, "(juego borrado)")
        print(f"{nombre}: {juego.entradas} líneas, {formato_tamano(juego.bytes)}")
    total = formato_tamano(sum(juego.bytes for juego in resumen)) if resumen else "vacía"
    limite = "sin límite" if ajustes.limite_cache_mb is None else f"máximo {ajustes.limite_cache_mb} MB"
    print(f"Total: {total} ({limite})")


def _crear(almacen: AlmacenPerfiles, args: argparse.Namespace) -> int:
    perfil = Perfil(
        nombre=args.nombre,
        ventana=args.ventana,
        idioma=args.idioma,
        destino=args.destino,
        zona=args.zona,
        color=Color.OSCURO if args.oscuro else Color.CLARO,
        orientacion=Orientacion.VERTICAL if args.vertical else Orientacion.HORIZONTAL,
        voz=AjustesVoz(Hablante.HOMBRE if args.hombre else Hablante.MUJER, args.velocidad),
        lectura=AjustesLectura(
            ModoLectura.ULTIMA if args.saltar_a_la_ultima else ModoLectura.COLA, args.pausa
        ),
        volumen=replace(AjustesVolumen(), activo=not args.sin_bajar_volumen, nivel_juego=args.nivel),
    )
    ruta = almacen.guardar(perfil)
    print(f"Juego «{perfil.nombre}» guardado en {ruta}")
    return 0


def _mostrar(linea: LineaJuego, tiempos: bool = False) -> None:
    marcas = "" if linea.leida else " (no leída: llegó otra línea)"
    print(f"\n{linea.original}\n→ {linea.traduccion}{marcas}", flush=True)
    if tiempos and linea.tiempos is not None:
        t = linea.tiempos
        voz = "no se leyó" if t.hasta_voz_s is None else f"{t.hasta_voz_s:.2f} s"
        print(f"  OCR {t.ocr_s:.2f} s · traducción {t.traduccion_s:.2f} s · hasta la voz {voz}", flush=True)


def _avisar(mensaje: str) -> None:
    print(f"! {mensaje}", file=sys.stderr, flush=True)


def _jugar(perfil: Perfil, entrada: Iterable[str], tiempos: bool = False) -> int:
    sesion = Sesion(perfil, lambda linea: _mostrar(linea, tiempos), _avisar, al_estado=_avisar)
    try:
        orquestador = sesion.iniciar()
        print(AYUDA_CONTROLES, flush=True)
        _controlar(orquestador, entrada)
    except (VentanaNoEncontradaError, DescargaFallidaError, TraduccionFallidaError, VozFallidaError) as error:
        print(error, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        sesion.detener()
    return 0


def _controlar(orquestador: Orquestador, entrada: Iterable[str]) -> None:
    """Atiende las órdenes escritas en la terminal hasta `q` o el final de la entrada."""
    acciones: dict[str, Callable[[], None]] = {
        "p": lambda: _pausar_o_reanudar(orquestador),
        "r": orquestador.repetir,
        "s": orquestador.saltar,
    }
    for linea in entrada:
        orden = linea.strip().lower()[:1]
        if orden == "q":
            return
        accion = acciones.get(orden)
        if accion is not None:
            accion()
        elif orden:
            print(AYUDA_CONTROLES, flush=True)


def _pausar_o_reanudar(orquestador: Orquestador) -> None:
    if orquestador.pausado:
        orquestador.reanudar()
        print("▶ Reanudado", flush=True)
    else:
        orquestador.pausar()
        print("⏸ En pausa (p para seguir)", flush=True)
