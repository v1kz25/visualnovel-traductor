"""Prompts de Hy-MT2 a partir de las plantillas oficiales de su ficha de Hugging Face.

Las plantillas en inglés van mejor con destino español que las chinas. Hy-MT2 no tiene prompt
de sistema: todo va en el mensaje del usuario.
"""

from collections.abc import Sequence

DESTINOS = {"es": "Spanish", "en": "English"}
"""Nombre en inglés de cada idioma de destino, como lo espera la plantilla."""

POR_DEFECTO = (
    "{terminos}Translate the following text into {destino}. Note that you should only output the translated "
    "result without any additional explanation:\n\n{texto}"
)

CON_CONTEXTO = (
    "[Background Information]\n{contexto}\n\n"
    "{terminos}Please translate the following text into {destino}, taking the provided background "
    "information into consideration. Only output the translated result without any additional "
    "explanation.\n\n[Source Text]\n{texto}"
)

TERMINOS = "Reference the following translations:\n{terminos}\n\n"
"""Bloque de la plantilla oficial de terminología; va justo antes de la instrucción."""


def construir(
    texto: str,
    contexto: Sequence[str] = (),
    terminos: Sequence[tuple[str, str]] = (),
    destino: str = "es",
) -> str:
    """Prompt para traducir `texto` al idioma `destino`, con las líneas anteriores y el glosario.

    El contexto y la terminología son dos plantillas oficiales distintas; combinadas (contexto,
    términos, instrucción) funcionan bien con el modelo real.
    """
    idioma = DESTINOS[destino]
    glosario = ""
    if terminos:
        lineas = "\n".join(f"{termino} translates to {traduccion}" for termino, traduccion in terminos)
        glosario = TERMINOS.format(terminos=lineas)
    if contexto:
        return CON_CONTEXTO.format(
            contexto="\n".join(contexto), terminos=glosario, destino=idioma, texto=texto
        )
    return POR_DEFECTO.format(terminos=glosario, destino=idioma, texto=texto)
