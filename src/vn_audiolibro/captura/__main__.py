"""Herramienta de depuración: captura la zona de texto de un juego y guarda cada texto nuevo.

Uso:
    uv run python -m vn_audiolibro.captura --listar
    uv run python -m vn_audiolibro.captura --ventana <título> --zona 0.14,0.01,0.66,0.75 --salida /tmp/zonas

La zona va en proporciones de la ventana (x, y, ancho, alto entre 0 y 1), así que vale con
cualquier tamaño de ventana.

Las imágenes guardadas son capturas del juego: no se suben al repo.
"""

import argparse
import sys
import time
from pathlib import Path

from vn_audiolibro.captura.bucle import BucleCaptura
from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, VentanaNoEncontradaError, ZonaEstable, ZonaRelativa
from vn_audiolibro.plataforma import capturador, gestor_ventanas


def _zona(texto: str) -> ZonaRelativa:
    x, y, ancho, alto = (float(v) for v in texto.split(","))
    return ZonaRelativa(x=x, y=y, ancho=ancho, alto=alto)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la herramienta."""
    parser = argparse.ArgumentParser(
        prog="python -m vn_audiolibro.captura", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--listar", action="store_true", help="lista las ventanas y sale")
    parser.add_argument("--ventana", help="texto contenido en el título de la ventana del juego")
    parser.add_argument(
        "--zona", type=_zona, help="x,y,ancho,alto en proporciones de la ventana (por defecto, toda)"
    )
    parser.add_argument(
        "--pantalla",
        action="store_true",
        help="captura lo que se ve en pantalla en vez del contenido de la ventana",
    )
    parser.add_argument("--salida", type=Path, help="carpeta donde guardar cada zona detectada en PNG")
    args = parser.parse_args(argv)

    ventanas = gestor_ventanas()
    if args.listar or not args.ventana:
        for v in ventanas.listar():
            g = v.geometria
            print(f"{v.id:#x}  pid={v.pid}  {g.ancho}x{g.alto}+{g.x}+{g.y}  {v.titulo}")
        return 0

    try:
        ventana = ventanas.buscar(args.ventana)
    except VentanaNoEncontradaError as error:
        print(error, file=sys.stderr)
        return 1
    zona = args.zona or TODA_LA_VENTANA
    if args.salida:
        args.salida.mkdir(parents=True, exist_ok=True)
    print(f"Capturando «{ventana.titulo}» (pid {ventana.pid}), zona {zona}. Ctrl+C para salir.")

    contador = 0

    def al_detectar(evento: ZonaEstable) -> None:
        nonlocal contador
        contador += 1
        tipo = "pantalla nueva" if evento.completa else f"filas nuevas desde y={evento.y_inicio}"
        alto, ancho = evento.imagen.shape[:2]
        print(f"[{contador:03d}] {time.strftime('%H:%M:%S')} {tipo} ({ancho}x{alto})")
        if args.salida:
            from PIL import Image  # opcional: solo para guardar las zonas

            Image.fromarray(evento.imagen).save(args.salida / f"zona-{contador:03d}.png")

    bucle = BucleCaptura(ventana.id, zona, al_detectar, ventanas, capturador(ventanas, args.pantalla))
    bucle.iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bucle.detener()
    return 0


if __name__ == "__main__":
    sys.exit(main())
