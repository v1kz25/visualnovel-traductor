"""Tests de la herramienta `python -m vn_audiolibro.voz`, con la voz y el audio falsos."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vn_audiolibro.captura.modelos import Rectangulo, Ventana
from vn_audiolibro.descargas import DescargaFallidaError
from vn_audiolibro.voz import __main__ as cli
from vn_audiolibro.voz.piper import Hablante
from vn_audiolibro.voz.volumen import Flujo, Juego

from .falsos import AtenuadorFalso, ReproductorFalso, SintetizadorFalso


def test_lee_cada_texto_e_informa_del_tiempo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reproductor = ReproductorFalso()
    monkeypatch.setattr(cli, "asegurar_voz", lambda voz: Path(voz.modelo.fichero))
    voces: list[tuple[str, Hablante | None]] = []

    def sintetizador(modelo: Path, hablante: Hablante | None) -> SintetizadorFalso:
        voces.append((modelo.name, hablante))
        return SintetizadorFalso()

    monkeypatch.setattr(cli, "SintetizadorPiper", sintetizador)
    monkeypatch.setattr(cli, "reproductor", lambda: reproductor)

    assert cli.main(["hola", "adiós"]) == 0

    salida = capsys.readouterr().out.splitlines()
    assert [linea.split("  ", 1)[1] for linea in salida] == ["hola", "adiós"]
    assert all(" ms  " in linea for linea in salida)
    assert [s.valores for s in reproductor.salidas] == [[4], [5]]
    assert voces == [("es_ES-sharvard-medium.onnx", Hablante.MUJER)]

    assert cli.main(["--hombre", "hola"]) == 0
    assert voces[-1] == ("es_ES-sharvard-medium.onnx", Hablante.HOMBRE)

    assert cli.main(["--ingles", "--hombre", "hello"]) == 0
    assert voces[-1] == ("en_US-john-medium.onnx", None)


def test_sin_voz(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def falla(_: object) -> Path:
        raise DescargaFallidaError("sin conexión")

    monkeypatch.setattr(cli, "asegurar_voz", falla)
    assert cli.main(["hola"]) == 1
    assert "sin conexión" in capsys.readouterr().err


def test_con_ventana_baja_el_juego_e_informa_de_sus_flujos(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    creados: list[tuple[float | None, float | None]] = []

    class GestorFalso:
        def buscar(self, titulo: str) -> Ventana:
            return Ventana(1, f"{titulo} ver. 1.0", 100, Rectangulo(0, 0, 800, 600))

    class ClienteFalso:
        def flujos(self) -> list[Flujo]:
            return [
                Flujo(7, "Juego.exe", "wine64-preloader", 100, (1.0,)),
                Flujo(8, "Firefox", "firefox", 5, (1.0,)),
            ]

    def atenuador(cliente: object, criterio: Callable[[Flujo], float | None]) -> AtenuadorFalso:
        juego = Flujo(7, "Juego.exe", "wine64-preloader", 100, (1.0,))
        creados.append((criterio(juego), criterio(Flujo(8, "Firefox", "", 5, (1.0,)))))
        return AtenuadorFalso()

    monkeypatch.setattr(cli, "asegurar_voz", lambda voz: Path(voz.modelo.fichero))
    monkeypatch.setattr(cli, "SintetizadorPiper", lambda *_: SintetizadorFalso())
    monkeypatch.setattr(cli, "reproductor", ReproductorFalso)
    monkeypatch.setattr(cli, "gestor_ventanas", GestorFalso)
    monkeypatch.setattr(cli, "cliente_audio", ClienteFalso)
    monkeypatch.setattr(cli, "juego_de_pid", lambda pid: Juego(frozenset({pid}), frozenset()))
    monkeypatch.setattr(cli, "AtenuadorJuego", atenuador)

    assert cli.main(["--ventana", "Juego", "--nivel", "0.6", "--app", "Firefox=0", "hola"]) == 0

    salida = capsys.readouterr().out
    assert "[ 0.60] #7 Juego.exe" in salida
    assert "[ 0.00] #8 Firefox" in salida
    assert creados == [(0.6, 0)]


def test_ventana_sin_pid(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class GestorFalso:
        def buscar(self, titulo: str) -> Ventana:
            return Ventana(1, titulo, None, Rectangulo(0, 0, 800, 600))

    monkeypatch.setattr(cli, "asegurar_voz", lambda voz: Path(voz.modelo.fichero))
    monkeypatch.setattr(cli, "gestor_ventanas", GestorFalso)

    assert cli.main(["--ventana", "Juego", "hola"]) == 1
    assert "no indica su proceso" in capsys.readouterr().err


def test_bajar_otras_aplicaciones_sin_juego(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class ClienteFalso:
        def flujos(self) -> list[Flujo]:
            return [Flujo(8, "Firefox", "firefox", 5, (1.0,)), Flujo(9, "Spotify", "spotify", 6, (1.0,))]

    monkeypatch.setattr(cli, "asegurar_voz", lambda voz: Path(voz.modelo.fichero))
    monkeypatch.setattr(cli, "SintetizadorPiper", lambda *_: SintetizadorFalso())
    monkeypatch.setattr(cli, "reproductor", ReproductorFalso)
    monkeypatch.setattr(cli, "cliente_audio", ClienteFalso)
    monkeypatch.setattr(cli, "AtenuadorJuego", lambda *_: AtenuadorFalso())

    assert cli.main(["--app", "spotify=0.5", "hola"]) == 0

    salida = capsys.readouterr().out
    assert "[ 0.50] #9 Spotify" in salida
    assert "[     ] #8 Firefox" in salida


@pytest.mark.parametrize("valor", ["Firefox", "=0.5", "Firefox=alto"])
def test_app_mal_escrita(valor: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--app", valor, "hola"])
    assert "NOMBRE=NIVEL" in capsys.readouterr().err


def test_nivel_fuera_de_rango(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "asegurar_voz", lambda voz: Path(voz.modelo.fichero))
    assert cli.main(["--app", "Firefox=2", "hola"]) == 1
    assert "entre 0 y 1" in capsys.readouterr().err
