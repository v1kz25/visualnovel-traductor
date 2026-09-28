"""Troceo de la traducción que llega en streaming, para empezar a leerla antes de que termine."""

FIN_FRASE = ".!?…"
PAUSAS = ",;:—"
CIERRES = "»”\"')」』"
MIN_FRASE = 8
"""Caracteres mínimos de un trozo que acaba en fin de frase: evita trozos como «Sí.» sueltos."""
MIN_PAUSA = 30
"""Caracteres mínimos para cortar en una coma o similar: más corto, la voz sonaría entrecortada."""


class Segmentador:
    """Junta el texto que llega a trozos y lo devuelve en partes que ya se pueden leer.

    Corta tras un fin de frase seguido de espacio o, si la parte es larga, tras una coma, punto
    y coma, dos puntos o raya. Así la voz empieza con la primera frase mientras llega el resto.
    """

    def __init__(self) -> None:
        self._pendiente = ""

    def anadir(self, trozo: str) -> list[str]:
        """Añade texto y devuelve las partes que ya están completas."""
        self._pendiente += trozo
        partes = []
        while (corte := self._corte()) is not None:
            parte, self._pendiente = self._pendiente[:corte].strip(), self._pendiente[corte:]
            if parte:
                partes.append(parte)
        return partes

    def terminar(self) -> str:
        """Lo que queda cuando el texto ha llegado entero."""
        resto, self._pendiente = self._pendiente.strip(), ""
        return resto

    def _corte(self) -> int | None:
        texto = self._pendiente
        for i, caracter in enumerate(texto):
            if caracter not in FIN_FRASE + PAUSAS:
                continue
            fin = i + 1
            while fin < len(texto) and texto[fin] in FIN_FRASE + PAUSAS + CIERRES:
                fin += 1  # «...», «?!» o la comilla que cierra van con la frase
            minimo = MIN_FRASE if caracter in FIN_FRASE else MIN_PAUSA
            if fin < len(texto) and texto[fin].isspace() and len(texto[:fin].strip()) >= minimo:
                return fin
        return None
