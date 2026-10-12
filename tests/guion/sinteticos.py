"""Guiones inventados con el formato `OutputLine`, para no usar texto de ningún juego."""

from pathlib import Path

from vn_audiolibro.guion.modelos import Guion, agrupar

PAGINAS = [
    [
        [
            (
                "　朝の光が窓から差し込んで、部屋の中を静かに照らしていた。",
                "Morning light came in through the window.",
            )
        ],
        [
            ("「おはよう、今日は早いんだね。", '"Good morning, you are early today.'),
            ("朝ごはんはもう食べたの？」", ' Did you already eat breakfast?"'),
        ],
        [("　僕は首を横に振って、台所のほうを指差した。", "I shook my head and pointed at the kitchen.")],
    ],
    [
        [("「それなら一緒に駅前の喫茶店へ行こうよ。」", '"Then let\'s go to the cafe by the station."')],
        [("　彼女はそう言うと、鞄を持って玄関へ向かった。", "She said that and walked to the door.")],
    ],
    [
        [("　外は思ったよりも寒くて、白い息が空に消えていった。", "It was colder than I thought outside.")],
        [("「手袋を持ってくればよかったな。」", '"I should have brought my gloves."')],
    ],
]
"""Páginas, cada una con sus párrafos, y cada párrafo con sus fragmentos (original, inglés)."""


def orden_linea(original: str, ingles: str, fin: str = "Line_WaitForInput") -> str:
    ingles = ingles.replace('"', '\\"')
    return f'\tOutputLine(NULL, "{original}",\n\t\t   NULL, "{ingles}", {fin});\n'


def script(paginas: list[list[list[tuple[str, str]]]] = PAGINAS) -> str:
    """Fichero de guion con las páginas: saltos de línea entre párrafos y borrado entre páginas."""
    partes = ['#include\t"Include\\bss.h"\n', "void main()\n{\n", '\tPlayBGM( 0, "yoru", 120, 0 );\n']
    for pagina in paginas:
        for parrafo in pagina:
            for original, ingles in parrafo:
                partes.append(orden_linea(original, ingles))
            partes.append('\tOutputLineAll(NULL, "\\n", Line_ContinueAfterTyping);\n')
        partes.append("\tClearMessage();\n")
    partes.append("}\n")
    return "".join(partes)


def juego(carpeta: Path, ficheros: dict[str, str] | None = None) -> Path:
    """Carpeta de un juego con el guion donde lo guarda Unity; devuelve la del juego."""
    scripts = carpeta / "Juego_Data" / "StreamingAssets" / "Scripts"
    scripts.mkdir(parents=True)
    for nombre, texto in (ficheros or {"_cap_001.txt": script()}).items():
        (scripts / nombre).write_bytes(("\ufeff" + texto).replace("\n", "\r\n").encode("utf-8"))
    return carpeta


def guion(paginas: list[list[list[tuple[str, str]]]] = PAGINAS) -> Guion:
    """Guion con las páginas, sin pasar por ficheros."""
    fragmentos = []
    for pagina in paginas:
        for n, parrafo in enumerate(pagina, 1):
            for m, (original, ingles) in enumerate(parrafo, 1):
                fin_parrafo = m == len(parrafo)
                fragmentos.append(
                    (original.strip("\u3000"), ingles, fin_parrafo, fin_parrafo and n == len(pagina))
                )
    return agrupar(fragmentos)


def pantalla(guion: Guion, hasta: int) -> str:
    """Lo que se ve en una VN tipo NVL con el fragmento `hasta` recién mostrado: toda su página."""
    pagina = guion.fragmentos[hasta].pagina
    return "".join(f.original for f in guion.fragmentos[: hasta + 1] if f.pagina == pagina)
