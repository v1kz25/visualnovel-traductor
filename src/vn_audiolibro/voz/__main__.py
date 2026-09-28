"""Herramienta de depuración: lee textos en voz alta con Piper.

Uso:
    uv run python -m vn_audiolibro.voz "¿Volvemos juntos a casa?" "Hoy hace mucho frío."
    uv run python -m vn_audiolibro.voz --hombre "¿Volvemos juntos a casa?"
    uv run python -m vn_audiolibro.voz --ingles "Shall we go home together?"
    uv run python -m vn_audiolibro.voz --ventana <título> "Texto largo mientras suena el juego…"
    uv run python -m vn_audiolibro.voz --ventana <título> --nivel 0.7 --app Firefox=0 --app Spotify=0.5 "…"

Lee los textos uno detrás de otro e indica cuánto tarda en estar lista la primera frase de
cada uno. Con `--ventana`, baja el volumen de ese juego mientras habla (a `--nivel`); con
`--app NOMBRE=NIVEL`, también el de otras aplicaciones (0 las silencia), y `--no-bajar` excluye
alguna. Indica a qué nivel va a bajar cada flujo de audio. La primera vez descarga la voz.
"""

import argparse
import sys
import time
from collections.abc import Iterator

from vn_audiolibro.cache.modelos import Clave
from vn_audiolibro.captura.modelos import VentanaNoEncontradaError
from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.plataforma import cliente_audio, gestor_ventanas, juego_de_pid, reproductor
from vn_audiolibro.voz.locutor import Locutor
from vn_audiolibro.voz.modelos import Atenuador, Fragmento, Sintetizador, VozFallidaError
from vn_audiolibro.voz.piper import (
    HABLANTE_POR_DEFECTO,
    Hablante,
    SintetizadorPiper,
    asegurar_voz,
    elegir_voz,
)
from vn_audiolibro.voz.volumen import NIVEL_POR_DEFECTO, AtenuadorJuego, Seleccion


class _Cronometrado:
    """Sintetizador que informa del tiempo hasta la primera frase."""

    def __init__(self, sintetizador: Sintetizador) -> None:
        self._sintetizador = sintetizador

    def sintetizar(self, texto: str) -> Iterator[Fragmento]:
        inicio = time.perf_counter()
        for i, fragmento in enumerate(self._sintetizador.sintetizar(texto)):
            if i == 0:
                print(f"{(time.perf_counter() - inicio) * 1000:.0f} ms  {texto}")
            yield fragmento


def _app(valor: str) -> tuple[str, float]:
    """`NOMBRE=NIVEL` de la opción `--app`."""
    nombre, separador, nivel = valor.rpartition("=")
    try:
        if not separador or not nombre:
            raise ValueError
        return nombre, float(nivel)
    except ValueError:
        raise argparse.ArgumentTypeError(f"se esperaba NOMBRE=NIVEL (p. ej. Firefox=0.5): {valor}") from None


def _atenuador(
    titulo: str | None, nivel_juego: float, otras: dict[str, float], excluir: list[str]
) -> Atenuador:
    """Atenuador del juego de esa ventana y de las aplicaciones elegidas; informa de qué flujos baja."""
    juego = None
    if titulo:
        ventana = gestor_ventanas().buscar(titulo)
        if ventana.pid is None:
            raise VozFallidaError(f"La ventana «{ventana.titulo}» no indica su proceso")
        juego = juego_de_pid(ventana.pid)
        print(f"Juego: «{ventana.titulo}», procesos {sorted(juego.pids)}, nombres {sorted(juego.nombres)}")
    seleccion = Seleccion.de_nombres(juego, nivel_juego, otras, excluir)
    cliente = cliente_audio()
    for flujo in cliente.flujos():
        nivel = seleccion(flujo)
        marca = "     " if nivel is None else f"{nivel:>5.2f}"
        print(f"  [{marca}] #{flujo.indice} {flujo.aplicacion} ({flujo.binario}, PID {flujo.pid})")
    return AtenuadorJuego(cliente, seleccion)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la herramienta."""
    parser = argparse.ArgumentParser(prog="python -m vn_audiolibro.voz", description=__doc__.splitlines()[0])
    parser.add_argument("textos", nargs="+", help="textos en español (o en inglés con --ingles)")
    parser.add_argument("--hombre", action="store_true", help="voz de hombre (por defecto, de mujer)")
    parser.add_argument("--ingles", action="store_true", help="voz inglesa (por defecto, española)")
    parser.add_argument("--ventana", help="título (o parte) de la ventana del juego al que bajar el volumen")
    parser.add_argument(
        "--app",
        action="append",
        default=[],
        type=_app,
        metavar="NOMBRE=NIVEL",
        help="bajar también esta aplicación a ese nivel (0 la silencia)",
    )
    parser.add_argument(
        "--no-bajar", action="append", default=[], metavar="APP", help="no bajar nunca esta aplicación"
    )
    parser.add_argument(
        "--nivel", type=float, default=NIVEL_POR_DEFECTO, help="volumen del juego mientras habla, de 0 a 1"
    )
    args = parser.parse_args(argv)

    destino = "en" if args.ingles else "es"
    voz = elegir_voz(destino, Hablante.HOMBRE if args.hombre else HABLANTE_POR_DEFECTO)
    try:
        modelo = asegurar_voz(voz.voz)
        atenuador = None
        if args.ventana or args.app:
            atenuador = _atenuador(args.ventana, args.nivel, dict(args.app), args.no_bajar)
    except (DescargaFallidaError, VentanaNoEncontradaError, VozFallidaError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    sintetizador = _Cronometrado(SintetizadorPiper(modelo, voz.hablante))
    locutor = Locutor(sintetizador, reproductor(), atenuador=atenuador)
    try:
        for texto in args.textos:
            locutor.decir(Clave("prueba", "es", texto, destino), texto)
            locutor.esperar()
    finally:
        locutor.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
