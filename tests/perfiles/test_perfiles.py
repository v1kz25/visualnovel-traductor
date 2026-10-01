"""Tests de los perfiles: validación, guardado y carga."""

import json
from pathlib import Path
from typing import Any

import pytest

from vn_audiolibro.captura.mascara import TEXTO_OSCURO
from vn_audiolibro.captura.modelos import TODA_LA_VENTANA, ZonaRelativa
from vn_audiolibro.guion.modelos import OrigenGuion
from vn_audiolibro.ocr.preprocesado import BusquedaTexto, Orientacion
from vn_audiolibro.perfiles.almacen import (
    VERSION_FORMATO,
    AlmacenPerfiles,
    PerfilDuplicadoError,
    a_dict,
    desde_dict,
    directorio_perfiles,
)
from vn_audiolibro.perfiles.modelos import (
    AjustesGuion,
    AjustesLectura,
    AjustesSubtitulos,
    AjustesVolumen,
    AjustesVoz,
    Color,
    Perfil,
    PerfilInvalidoError,
    PosicionSubtitulos,
)
from vn_audiolibro.traduccion.modelos import Glosario, Motor
from vn_audiolibro.voz.modelos import ModoLectura
from vn_audiolibro.voz.piper import Hablante
from vn_audiolibro.voz.volumen import Flujo, Juego

COMPLETO = Perfil(
    nombre="Mi juego «uno»",
    ventana="juego uno",
    idioma="ja",
    destino="en",
    zona=ZonaRelativa(0.1, 0.7, 0.8, 0.25),
    color=Color.OSCURO,
    orientacion=Orientacion.VERTICAL,
    busqueda=BusquedaTexto.DETECTOR,
    glosario=Glosario.desde_dict({"櫻": "Sakura", "先輩": "senpai"}),
    traductor=Motor.GEMINI,
    voz=AjustesVoz(Hablante.HOMBRE, 1.25),
    lectura=AjustesLectura(ModoLectura.ULTIMA, 0.5),
    volumen=AjustesVolumen(activo=False, nivel_juego=0.5, otras=(("Firefox", 0.0),), excluir=("Discord",)),
    subtitulos=AjustesSubtitulos(activo=True, posicion=PosicionSubtitulos.TAPAR, tamano=30, opacidad=0.5),
    guion=AjustesGuion("/juegos/mi juego"),
)


@pytest.fixture
def almacen(tmp_path: Path) -> AlmacenPerfiles:
    return AlmacenPerfiles(tmp_path / "perfiles")


# Modelo


def test_valores_por_defecto() -> None:
    perfil = Perfil("Juego", "juego")
    assert perfil.idioma == "zh-Hant"
    assert perfil.destino == "es"
    assert perfil.zona == TODA_LA_VENTANA
    assert perfil.voz == AjustesVoz(Hablante.MUJER, 1.0)
    assert perfil.lectura == AjustesLectura(ModoLectura.COLA, 2.0)
    assert perfil.volumen.activo
    assert perfil.volumen.nivel_juego == 0.7
    assert len(perfil.id) == 32


def test_cada_perfil_nuevo_tiene_su_id() -> None:
    assert Perfil("A", "a").id != Perfil("A", "a").id


@pytest.mark.parametrize(
    ("campos", "mensaje"),
    [
        ({"nombre": "  "}, "nombre"),
        ({"nombre": "x" * 81}, "80 caracteres"),
        ({"ventana": ""}, "ventana"),
        ({"idioma": "ko"}, "Idioma no admitido"),
        ({"destino": "fr"}, "Idioma de traducción no admitido"),
        ({"idioma": "en", "destino": "en"}, "solo se puede traducir al español"),
        ({"idioma": "en", "orientacion": Orientacion.VERTICAL}, "columnas verticales"),
        ({"id": "../../etc"}, "Identificador"),
    ],
)
def test_perfil_no_valido(campos: dict[str, Any], mensaje: str) -> None:
    datos: dict[str, Any] = {"nombre": "Juego", "ventana": "juego", **campos}
    with pytest.raises(PerfilInvalidoError, match=mensaje):
        Perfil(**datos)


def test_un_juego_en_ingles_se_traduce_al_espanol() -> None:
    perfil = Perfil("Juego", "juego", idioma="en")
    assert (perfil.destino, perfil.orientacion) == ("es", Orientacion.HORIZONTAL)
    assert desde_dict(a_dict(perfil)) == perfil


@pytest.mark.parametrize(
    ("campos", "mensaje"),
    [({"tamano": 5}, "tamaño de los subtítulos"), ({"opacidad": 1.5}, "opacidad")],
)
def test_subtitulos_no_validos(campos: dict[str, Any], mensaje: str) -> None:
    with pytest.raises(PerfilInvalidoError, match=mensaje):
        AjustesSubtitulos(**campos)


def test_subtitulos_guardados_con_tipos_erroneos() -> None:
    base = {"version": 1, "nombre": "J", "ventana": "j"}
    with pytest.raises(PerfilInvalidoError, match="subtítulos"):
        desde_dict({**base, "subtitulos": {"activo": "sí"}})


def test_guion_no_valido() -> None:
    with pytest.raises(PerfilInvalidoError, match="carpeta"):
        AjustesGuion(" ")
    with pytest.raises(PerfilInvalidoError, match="inglés"):
        Perfil("Juego", "juego", destino="en", guion=AjustesGuion("/j", OrigenGuion.INGLES))
    assert Perfil("Juego", "juego", guion=AjustesGuion("/j", OrigenGuion.INGLES)).guion is not None


def test_velocidad_y_niveles_fuera_de_rango() -> None:
    with pytest.raises(PerfilInvalidoError, match="velocidad"):
        AjustesVoz(velocidad=3)
    with pytest.raises(PerfilInvalidoError, match="juego"):
        AjustesVolumen(nivel_juego=1.2)
    with pytest.raises(PerfilInvalidoError, match="Firefox"):
        AjustesVolumen(otras=(("Firefox", -1),))


def test_color_da_los_ajustes_de_captura() -> None:
    assert Color.OSCURO.color_texto is TEXTO_OSCURO


def test_volumen_da_la_seleccion_del_atenuador() -> None:
    juego = Juego(frozenset({100}), frozenset())
    ajustes = AjustesVolumen(nivel_juego=0.5, otras=(("Firefox", 0.0),), excluir=("Discord",))
    seleccion = ajustes.seleccion(juego)

    assert seleccion is not None
    assert seleccion(Flujo(1, "Juego.exe", "wine", 100, (1.0,))) == 0.5
    assert seleccion(Flujo(2, "Firefox", "firefox", 5, (1.0,))) == 0.0
    assert seleccion(Flujo(3, "Discord", "discord", 100, (1.0,))) is None
    assert AjustesVolumen(activo=False).seleccion(juego) is None


# Formato


def test_ida_y_vuelta_por_json() -> None:
    datos = json.loads(json.dumps(a_dict(COMPLETO)))
    assert desde_dict(datos) == COMPLETO
    assert datos["version"] == VERSION_FORMATO
    assert datos["voz"] == {"hablante": "hombre", "velocidad": 1.25}
    assert datos["lectura"] == {"modo": "ultima", "pausa_s": 0.5}
    assert datos["destino"] == "en"
    assert datos["busqueda"] == "detector"
    assert datos["traductor"] == "gemini"
    assert datos["subtitulos"] == {"activo": True, "posicion": "tapar", "tamano": 30, "opacidad": 0.5}
    assert "clave" not in json.dumps(datos).lower()  # la clave nunca va en el fichero del juego
    assert datos["guion"] == {"carpeta": "/juegos/mi juego", "origen": "original"}
    sin_guion = a_dict(Perfil("J", "j"))
    assert sin_guion["guion"] is None
    assert desde_dict(sin_guion).guion is None


def test_los_campos_que_faltan_toman_su_valor_por_defecto() -> None:
    perfil = desde_dict({"version": 1, "nombre": "Juego", "ventana": "juego"})
    assert perfil.destino == "es"  # los juegos de antes se traducían al español
    assert perfil.color == Color.CLARO
    assert perfil.busqueda is BusquedaTexto.COLOR  # los juegos de antes buscaban por color
    assert perfil.traductor is Motor.LOCAL
    assert perfil.subtitulos == AjustesSubtitulos()  # desactivados
    assert perfil.glosario == Glosario()
    assert perfil.volumen == AjustesVolumen()
    assert perfil.guion is None
    con_guion = desde_dict({"version": 1, "nombre": "J", "ventana": "j", "guion": {"carpeta": "/j"}})
    assert con_guion.guion == AjustesGuion("/j", OrigenGuion.ORIGINAL)


def test_ajustes_parciales() -> None:
    base = {"version": 1, "nombre": "J", "ventana": "j"}
    perfil = desde_dict({**base, "voz": {"velocidad": 1.5}, "volumen": {"nivel_juego": 0.4}})
    assert perfil.voz == AjustesVoz(Hablante.MUJER, 1.5)
    assert perfil.volumen == AjustesVolumen(nivel_juego=0.4)


def test_version_mas_nueva() -> None:
    with pytest.raises(PerfilInvalidoError, match="versión más nueva"):
        desde_dict({"version": VERSION_FORMATO + 1, "nombre": "J", "ventana": "j"})


@pytest.mark.parametrize(
    "cambio",
    [
        {"version": "1"},
        {"version": 0},
        {"nombre": 3},
        {"zona": {"x": 0.5, "y": 0.5, "ancho": 0.9, "alto": 0.1}},
        {"zona": {"x": "0", "y": 0, "ancho": 1, "alto": 1}},
        {"zona": {"x": True, "y": 0, "ancho": 1, "alto": 1}},
        {"zona": {"x": 0}},
        {"color": "verde"},
        {"orientacion": "diagonal"},
        {"glosario": {"櫻": 3}},
        {"glosario": ["櫻"]},
        {"voz": {"hablante": "niño"}},
        {"voz": {"velocidad": 10}},
        {"volumen": {"activo": "sí"}},
        {"lectura": {"modo": "aleatorio"}},
        {"lectura": {"pausa_s": 60}},
        {"lectura": {"pausa_s": "2"}},
        {"volumen": {"otras": {"Firefox": "alto"}}},
        {"volumen": {"excluir": [1]}},
        {"id": 5},
        {"guion": {"carpeta": 3}},
        {"guion": {"carpeta": "/j", "origen": "klingon"}},
        {"guion": "/j"},
    ],
)
def test_datos_no_validos(cambio: dict[str, Any]) -> None:
    datos = {"version": 1, "nombre": "J", "ventana": "j", **cambio}
    with pytest.raises(PerfilInvalidoError):
        desde_dict(datos)


# Almacén


def test_guardar_y_cargar(almacen: AlmacenPerfiles) -> None:
    ruta = almacen.guardar(COMPLETO)

    assert ruta == almacen.directorio / f"{COMPLETO.id}.json"
    assert almacen.cargar(COMPLETO.id) == COMPLETO
    assert "Mi juego «uno»" in ruta.read_text(encoding="utf-8")  # legible a mano, sin escapes
    assert not list(almacen.directorio.glob("*.parcial"))


def test_listar_por_nombre_y_saltar_ilegibles(
    almacen: AlmacenPerfiles, caplog: pytest.LogCaptureFixture
) -> None:
    almacen.guardar(Perfil("zeta", "z"))
    almacen.guardar(Perfil("Alfa", "a"))
    (almacen.directorio / "roto.json").write_text("{no es json")
    (almacen.directorio / "lista.json").write_text("[]")

    assert [p.nombre for p in almacen.listar()] == ["Alfa", "zeta"]
    assert "roto.json" in caplog.text
    assert "lista.json" in caplog.text


def test_listar_sin_carpeta(almacen: AlmacenPerfiles) -> None:
    assert almacen.listar() == []


def test_fichero_con_otro_perfil_dentro(almacen: AlmacenPerfiles) -> None:
    ruta = almacen.guardar(COMPLETO)
    ruta.rename(almacen.directorio / f"{'0' * 32}.json")
    with pytest.raises(PerfilInvalidoError, match="contiene el juego"):
        almacen.cargar("0" * 32)


def test_renombrar_conserva_el_id(almacen: AlmacenPerfiles) -> None:
    almacen.guardar(COMPLETO)
    renombrado = Perfil("Otro nombre", COMPLETO.ventana, id=COMPLETO.id)
    almacen.guardar(renombrado)

    assert [p.nombre for p in almacen.listar()] == ["Otro nombre"]


def test_nombre_repetido(almacen: AlmacenPerfiles) -> None:
    almacen.guardar(Perfil("Juego", "juego"))
    with pytest.raises(PerfilDuplicadoError, match="Juego"):
        almacen.guardar(Perfil(" JUEGO ", "otro"))


def test_buscar_por_nombre_o_id(almacen: AlmacenPerfiles) -> None:
    almacen.guardar(COMPLETO)
    assert almacen.buscar("mi juego «UNO»") == COMPLETO
    assert almacen.buscar(COMPLETO.id) == COMPLETO
    with pytest.raises(KeyError, match="otro"):
        almacen.buscar("otro")


def test_cargar_inexistente_o_id_peligroso(almacen: AlmacenPerfiles) -> None:
    with pytest.raises(KeyError, match="identificador"):
        almacen.cargar("0" * 32)
    with pytest.raises(KeyError, match="no válido"):
        almacen.cargar("../fuera")


def test_borrar(almacen: AlmacenPerfiles) -> None:
    almacen.guardar(COMPLETO)
    almacen.borrar(COMPLETO.id)
    almacen.borrar(COMPLETO.id)  # ya no existe: no falla
    assert almacen.listar() == []


def test_directorio_en_la_configuracion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert directorio_perfiles() == tmp_path / "vn-audiolibro" / "perfiles"
    assert AlmacenPerfiles().directorio == directorio_perfiles()
