"""Tests del montaje de la sesión, con todas las piezas sustituidas por falsas que apuntan qué pasa."""

from pathlib import Path
from typing import Any

import pytest

from vn_audiolibro.captura.modelos import Rectangulo, Ventana, VentanaNoEncontradaError
from vn_audiolibro.perfiles.modelos import AjustesVolumen, AjustesVoz, Perfil
from vn_audiolibro.pipeline import sesion as modulo
from vn_audiolibro.pipeline.sesion import Sesion
from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.piper import Hablante
from vn_audiolibro.voz.volumen import Juego


class Registro:
    """Apunta la creación y el desmontaje de cada pieza, en orden."""

    def __init__(self) -> None:
        self.eventos: list[str] = []
        self.creados: dict[str, tuple[Any, ...]] = {}

    def pieza(self, nombre: str, parar: str | None = None, fallar_al: str | None = None) -> type:
        registro = self

        class Pieza:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                registro.creados[nombre] = args
                registro.eventos.append(f"crear {nombre}")
                if fallar_al == "crear":
                    raise VozFallidaError(f"{nombre} no disponible")

            def __getattr__(self, metodo: str) -> Any:
                def llamada(*args: Any, **kwargs: Any) -> Any:
                    registro.eventos.append(f"{metodo} {nombre}")
                    if metodo == fallar_al:
                        raise VozFallidaError(f"{nombre} falla en {metodo}")
                    return f"cliente de {nombre}" if metodo == "iniciar" else None

                return llamada

        return Pieza


class GestorFalso:
    def buscar(self, texto: str) -> Ventana:
        if texto == "no está":
            raise VentanaNoEncontradaError("No hay ninguna ventana")
        return Ventana(0x42, f"{texto} (juego)", 100, Rectangulo(0, 0, 800, 600))


@pytest.fixture
def registro(monkeypatch: pytest.MonkeyPatch) -> Registro:
    registro = Registro()
    monkeypatch.setattr(modulo, "gestor_ventanas", GestorFalso)
    monkeypatch.setattr(modulo, "asegurar_descarga", lambda descarga: Path("ocr.onnx"))
    monkeypatch.setattr(modulo, "asegurar_voz", lambda voz: Path(voz.modelo.fichero))
    monkeypatch.setattr(modulo, "asegurar_llama_server", lambda: Path("llama-server"))
    monkeypatch.setattr(modulo, "asegurar_modelo_traduccion", lambda: Path("hy-mt2.gguf"))
    monkeypatch.setattr(modulo, "juego_de_pid", lambda pid: Juego(frozenset({pid}), frozenset()))
    for nombre, clase in [
        ("servidor", "ServidorLlama"),
        ("cache", "CacheSQLite"),
        ("sintetizador", "SintetizadorPiper"),
        ("reproductor", "reproductor"),
        ("pulse", "cliente_audio"),
        ("atenuador", "AtenuadorJuego"),
        ("locutor", "Locutor"),
        ("reconocedor", "ReconocedorRapidOCR"),
        ("lector", "LectorOCR"),
        ("traductor", "TraductorLocal"),
        ("orquestador", "Orquestador"),
        ("capturador", "capturador"),
        ("bucle", "BucleCaptura"),
    ]:
        monkeypatch.setattr(modulo, clase, registro.pieza(nombre))
    return registro


def sesion(perfil: Perfil | None = None, errores: list[str] | None = None) -> Sesion:
    perfil = perfil or Perfil("Juego", "juego", idioma="ja")
    return Sesion(perfil, lambda _: None, (errores if errores is not None else []).append)


def test_monta_todo_y_desmonta_en_orden_inverso(registro: Registro) -> None:
    estados: list[str] = []
    perfil = Perfil("Juego", "juego", idioma="ja")
    with Sesion(perfil, lambda _: None, lambda _: None, estados.append) as abierta:
        assert abierta.orquestador is not None

    paradas = [e for e in registro.eventos if not e.startswith("crear") and e != "iniciar servidor"]
    assert paradas == [
        "calentar traductor",
        "iniciar bucle",
        "detener bucle",
        "cerrar orquestador",
        "cerrar locutor",
        "cerrar atenuador",
        "cerrar cache",
        "detener servidor",
    ]
    assert estados[-1] == "Leyendo «juego (juego)»."
    assert registro.creados["traductor"] == ("cliente de servidor",)
    ajustes = registro.creados["orquestador"][0]
    assert (ajustes.perfil, ajustes.idioma, ajustes.destino) == (perfil.id, "ja", "es")
    voz = Path("es_ES-sharvard-medium.onnx")
    assert registro.creados["sintetizador"] == (voz, perfil.voz.hablante, 1.0)


@pytest.mark.parametrize(
    ("hablante", "modelo"),
    [(Hablante.MUJER, "en_US-kristin-medium.onnx"), (Hablante.HOMBRE, "en_US-john-medium.onnx")],
)
def test_un_juego_en_ingles_traduce_y_lee_en_ingles(
    registro: Registro, hablante: Hablante, modelo: str
) -> None:
    perfil = Perfil("Juego", "juego", destino="en", voz=AjustesVoz(hablante, 1.25))
    with sesion(perfil):
        pass
    assert registro.creados["orquestador"][0].destino == "en"
    # Las voces inglesas tienen un solo hablante: se elige el modelo, no el hablante.
    assert registro.creados["sintetizador"] == (Path(modelo), None, 1.25)


def test_sin_ventana_no_arranca_nada(registro: Registro) -> None:
    with pytest.raises(VentanaNoEncontradaError):
        sesion(Perfil("Juego", "no está")).iniciar()
    assert registro.eventos == []


def test_si_falla_al_arrancar_desmonta_lo_que_habia(
    registro: Registro, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modulo, "BucleCaptura", registro.pieza("bucle", fallar_al="iniciar"))
    abierta = sesion()

    with pytest.raises(VozFallidaError, match="bucle falla"):
        abierta.iniciar()

    assert registro.eventos[-5:] == [
        "cerrar orquestador",
        "cerrar locutor",
        "cerrar atenuador",
        "cerrar cache",
        "detener servidor",
    ]
    assert abierta.orquestador is None


def test_volumen_desactivado_no_crea_atenuador(registro: Registro) -> None:
    perfil = Perfil("Juego", "juego", volumen=AjustesVolumen(activo=False))
    with sesion(perfil):
        pass
    assert "crear atenuador" not in registro.eventos
    assert registro.creados["locutor"][3] is None


def test_sin_servidor_de_sonido_se_juega_sin_bajar_el_volumen(
    registro: Registro, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modulo, "cliente_audio", registro.pieza("pulse", fallar_al="crear"))
    errores: list[str] = []
    with sesion(errores=errores):
        pass
    assert errores == ["No se podrá bajar el volumen del juego: pulse no disponible"]
    assert registro.creados["locutor"][3] is None
