"""Crea o pone al día el catálogo de un idioma con los textos del código.

    uv run python -m vn_audiolibro.textos en     # actualiza en.po
    uv run python -m vn_audiolibro.textos fr     # crea fr.po, con todos los textos por traducir

Después solo queda rellenar los `msgstr` vacíos del fichero.
"""

import argparse

from vn_audiolibro.textos.extraer import CARPETA, actualizar, textos_del_paquete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("idioma", help="código del idioma (en, fr, pt…)")
    idioma = parser.parse_args().idioma
    ruta = CARPETA / f"{idioma}.po"
    anterior = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
    textos = textos_del_paquete()
    ruta.write_text(actualizar(idioma, textos, anterior), encoding="utf-8")
    print(f"{ruta}: {len(textos)} textos")


main()
