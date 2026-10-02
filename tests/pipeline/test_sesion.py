"""Tests del montaje de la sesión, con todas las piezas sustituidas por falsas que apuntan qué pasa."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from vn_audiolibro import claves
from vn_audiolibro.captura.modelos import Rectangulo, Ventana, VentanaNoEncontradaError, ZonaRelativa
from vn_audiolibro.guion.modelos import GuionNoEncontradoError, OrigenGuion
from vn_audiolibro.ocr.preprocesado import BusquedaTexto
from vn_audiolibro.perfiles.almacen import AlmacenPerfiles
from vn_audiolibro.perfiles.modelos import AjustesGuion, AjustesVolumen, AjustesVoz, Perfil
from vn_audiolibro.pipeline import sesion as modulo
from vn_audiolibro.pipeline.orquestador import GuionJuego
from vn_audiolibro.pipeline.sesion import Sesion, ajustes_guion, traductor_guion
from vn_audiolibro.traduccion.gemini import TraductorConRespaldo
from vn_audiolibro.traduccion.modelos import Glosario, Motor
from vn_audiolibro.voz.modelos import VozFallidaError
from vn_audiolibro.voz.piper import Hablante
from vn_audiolibro.voz.volumen import Juego

from ..guion.sinteticos import juego


class Registro:
    """Apunta la creación y el desmontaje de cada pieza, en orden."""

    def __init__(self) -> None:
        self.eventos: list[str] = []
        self.creados: dict[str, tuple[Any, ...]] = {}
        self.opciones: dict[str, dict[str, Any]] = {}

    def pieza(self, nombre: str, parar: str | None = None, fallar_al: str | None = None) -> type:
        registro = self

        class Pieza:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                registro.creados[nombre] = args
                registro.opciones[nombre] = kwargs
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
    monkeypatch.setattr(modulo, "asegurar_descarga", lambda descarga: Path(descarga.fichero))
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


def test_por_color_solo_carga_el_reconocedor(registro: Registro) -> None:
    with sesion():
        pass
    assert registro.creados["reconocedor"] == (Path("ch_PP-OCRv5_rec_mobile.onnx"), None)
    _, ajustes, detector = registro.creados["lector"]
    assert (ajustes.busqueda, detector) == (BusquedaTexto.COLOR, None)


def test_con_detector_lo_descarga_y_se_lo_pasa_al_lector(registro: Registro) -> None:
    with sesion(Perfil("Juego", "juego", idioma="ja", busqueda=BusquedaTexto.DETECTOR)):
        pass
    modelos = (Path("ch_PP-OCRv5_rec_mobile.onnx"), Path("ch_PP-OCRv5_det_mobile.onnx"))
    assert registro.creados["reconocedor"] == modelos
    reconocedor, ajustes, detector = registro.creados["lector"]
    assert ajustes.busqueda is BusquedaTexto.DETECTOR
    assert detector is reconocedor


def test_con_gemini_y_clave_traduce_con_respaldo_local(registro: Registro) -> None:
    claves.guardar("clave-123")
    with sesion(Perfil("Juego", "juego", idioma="ja", traductor=Motor.GEMINI)):
        pass

    traductor = registro.creados["orquestador"][2]
    assert isinstance(traductor, TraductorConRespaldo)
    assert "calentar traductor" in registro.eventos  # el local se calienta igual: es el respaldo


def test_con_gemini_sin_clave_avisa_y_traduce_en_local(registro: Registro) -> None:
    errores: list[str] = []
    with sesion(Perfil("Juego", "juego", idioma="ja", traductor=Motor.GEMINI), errores):
        pass

    assert not isinstance(registro.creados["orquestador"][2], TraductorConRespaldo)
    assert errores == ["Falta la clave de Gemini: se traducirá en local. Añádela en el editor del juego."]


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


# Guion del juego


def test_con_guion_lo_lee_y_se_lo_pasa_al_orquestador(registro: Registro, tmp_path: Path) -> None:
    carpeta = juego(tmp_path)
    perfil = Perfil("Juego", "juego", idioma="ja", guion=AjustesGuion(str(carpeta), OrigenGuion.INGLES))
    estados: list[str] = []
    with Sesion(perfil, lambda _: None, lambda _: None, estados.append):
        pass

    guion = registro.creados["orquestador"][7]
    assert isinstance(guion, GuionJuego)
    assert guion.preparador.ajustes == ajustes_guion(perfil)
    assert guion.preparador.ajustes.origen is OrigenGuion.INGLES
    assert "Leyendo el guion del juego…" in estados


def test_si_no_encuentra_el_guion_avisa_y_juega_con_el_ocr(registro: Registro, tmp_path: Path) -> None:
    errores: list[str] = []
    perfil = Perfil("Juego", "juego", idioma="ja", guion=AjustesGuion(str(tmp_path)))
    with sesion(perfil, errores):
        pass

    assert registro.creados["orquestador"][7] is None
    assert any("No se usará el guion" in error for error in errores)


def test_traductor_guion_arranca_y_para_el_traductor(registro: Registro, tmp_path: Path) -> None:
    perfil = Perfil("Juego", "juego", idioma="ja", guion=AjustesGuion(str(juego(tmp_path))))

    with traductor_guion(perfil) as preparador:
        assert len(preparador.guion.parrafos) == 7
        assert "detener servidor" not in registro.eventos

    assert registro.eventos[-2:] == ["cerrar cache", "detener servidor"]


def test_traductor_guion_sin_guion(registro: Registro) -> None:
    with (
        pytest.raises(GuionNoEncontradoError, match="no tiene configurado"),
        traductor_guion(Perfil("J", "j")),
    ):
        pass
    assert registro.eventos == []


def test_pasa_la_zona_del_nombre_y_si_se_separa_el_personaje(registro: Registro) -> None:
    zona_nombre = ZonaRelativa(0.1, 0.7, 0.2, 0.05)
    perfil = Perfil("Juego", "juego", zona_nombre=zona_nombre, separar_personaje=False)
    with sesion(perfil) as abierta:
        assert registro.opciones["bucle"]["zona_nombre"] == zona_nombre
        assert not registro.creados["orquestador"][0].separar_personaje
        assert registro.opciones["orquestador"]["al_personaje"] == abierta.guardar_personaje


def test_guarda_los_nombres_aprendidos_en_el_glosario_del_juego(tmp_path: Path) -> None:
    almacen = AlmacenPerfiles(tmp_path)
    perfil = Perfil("Juego", "juego", glosario=Glosario.desde_dict({"櫻": "Sakura"}))
    almacen.guardar(perfil)
    # Mientras se juega, el usuario cambia algo del juego: no se pierde.
    almacen.guardar(replace(perfil, glosario=Glosario.desde_dict({"櫻": "Sakura", "林": "Lin"})))
    abierta = Sesion(perfil, lambda _: None, lambda _: None, almacen=almacen)

    abierta.guardar_personaje("小雨", "Xiaoyu")
    abierta.guardar_personaje("林", "Bosque")  # ya tenía traducción: se respeta
    abierta.guardar_personaje("？", "？")  # sin traducción: solo se apunta el personaje

    guardado = almacen.cargar(perfil.id)
    assert dict(guardado.glosario.terminos) == {"櫻": "Sakura", "林": "Lin", "小雨": "Xiaoyu"}
    assert guardado.personajes == (("小雨", None), ("林", None), ("？", None))


def test_no_cambia_la_voz_que_el_usuario_dio_al_personaje(tmp_path: Path) -> None:
    almacen = AlmacenPerfiles(tmp_path)
    perfil = Perfil(
        "Juego", "juego", glosario=Glosario.desde_dict({"林": "Lin"}), personajes=(("林", Hablante.HOMBRE),)
    )
    almacen.guardar(perfil)
    ruta = almacen.directorio / f"{perfil.id}.json"
    antes = ruta.stat().st_mtime_ns

    Sesion(perfil, lambda _: None, lambda _: None, almacen=almacen).guardar_personaje("林", "Lin")

    assert almacen.cargar(perfil.id) == perfil
    assert ruta.stat().st_mtime_ns == antes  # nada que guardar: no se reescribe


def test_si_no_puede_guardar_el_nombre_se_sigue_jugando(tmp_path: Path) -> None:
    perfil = Perfil("Juego", "juego")  # nunca se guardó
    abierta = Sesion(perfil, lambda _: None, lambda _: None, almacen=AlmacenPerfiles(tmp_path))

    abierta.guardar_personaje("小雨", "Xiaoyu")

    assert not list(tmp_path.iterdir())


def test_cada_personaje_con_otra_voz_tiene_su_sintetizador(registro: Registro) -> None:
    personajes = (("小雨", Hablante.HOMBRE), ("林", None), ("櫻", Hablante.MUJER))
    with sesion(Perfil("Juego", "juego", personajes=personajes)):
        voces = registro.opciones["locutor"]["voces"]
        assert set(voces) == {"M"}  # en español, el otro hablante del mismo modelo
        assert registro.creados["orquestador"][0].voces == (("小雨", "M"),)
    assert "con_hablante sintetizador" in registro.eventos


def test_en_ingles_la_otra_voz_es_otro_modelo(registro: Registro, monkeypatch: pytest.MonkeyPatch) -> None:
    descargadas: list[str] = []
    monkeypatch.setattr(
        modulo, "asegurar_voz", lambda voz: descargadas.append(voz.modelo.fichero) or Path(voz.modelo.fichero)
    )
    perfil = Perfil("Juego", "juego", destino="en", personajes=(("小雨", Hablante.HOMBRE),))
    with sesion(perfil):
        assert set(registro.opciones["locutor"]["voces"]) == {"M"}
    assert descargadas == ["en_US-kristin-medium.onnx", "en_US-john-medium.onnx"]
    assert registro.creados["sintetizador"] == (Path("en_US-john-medium.onnx"), None, 1.0)
