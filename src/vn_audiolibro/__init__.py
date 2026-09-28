"""vn-audiolibro: audiolibro en español, en tiempo real, para novelas visuales en chino y japonés."""

import sys


def main() -> None:
    """Punto de entrada de la aplicación."""
    # Se importa aquí para no cargar los modelos y Qt al importar el paquete.
    from vn_audiolibro.cli import main as principal

    sys.exit(principal())
