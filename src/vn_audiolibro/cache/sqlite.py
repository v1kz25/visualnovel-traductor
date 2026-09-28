"""Caché persistente de traducciones y audio en SQLite.

La base de datos guarda el texto original, la traducción y el nombre del fichero de audio; el
audio va aparte, en una carpeta junto a la base de datos, para no inflarla. La caché gestiona
ambos: al invalidar, vaciar o recortar por tamaño se borran también los ficheros.

Se usa desde varios hilos del pipeline (captura, traducción, voz), así que todas las
operaciones pasan por un cerrojo.
"""

import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from vn_audiolibro.cache.modelos import Clave, Entrada, ResumenPerfil
from vn_audiolibro.rutas import directorio_datos

VERSION_ESQUEMA = 1

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS entradas (
    id TEXT PRIMARY KEY,
    perfil TEXT NOT NULL,
    idioma TEXT NOT NULL,
    original TEXT NOT NULL,
    traduccion TEXT NOT NULL,
    modelo TEXT NOT NULL,
    audio TEXT,
    bytes INTEGER NOT NULL,
    creada REAL NOT NULL,
    usada REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS entradas_perfil ON entradas (perfil);
CREATE INDEX IF NOT EXISTS entradas_usada ON entradas (usada);
"""

_Fila = tuple[str, str, str, str | None, float, float]


def directorio_cache() -> Path:
    """Directorio de la caché en los datos del usuario: persiste entre partidas."""
    return directorio_datos() / "cache"


def _bytes_texto(*textos: str) -> int:
    return sum(len(texto.encode()) for texto in textos)


class CacheSQLite:
    """Caché de líneas traducidas y su audio.

    `limite_bytes` fija el tamaño máximo (texto más audio). Al superarlo se borran primero las
    entradas usadas hace más tiempo.
    """

    def __init__(
        self,
        directorio: Path | None = None,
        limite_bytes: int | None = None,
        reloj: Callable[[], float] = time.time,
    ) -> None:
        self.directorio = directorio or directorio_cache()
        self.directorio_audio = self.directorio / "audio"
        self.directorio_audio.mkdir(parents=True, exist_ok=True)
        self.limite_bytes = limite_bytes
        self._reloj = reloj
        self._cerrojo = threading.Lock()
        self._conexion = sqlite3.connect(self.directorio / "cache.sqlite3", check_same_thread=False)
        with self._transaccion() as cursor:
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.executescript(_ESQUEMA)
            cursor.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")

    def cerrar(self) -> None:
        """Cierra la base de datos."""
        with self._cerrojo:
            self._conexion.close()

    @contextmanager
    def _transaccion(self) -> Iterator[sqlite3.Cursor]:
        with self._cerrojo, self._conexion:
            yield self._conexion.cursor()

    def consultar(self, clave: Clave) -> Entrada | None:
        """Entrada guardada para la línea, o None. Marca la entrada como usada ahora."""
        ahora = self._reloj()
        with self._transaccion() as cursor:
            fila: _Fila | None = cursor.execute(
                "SELECT original, traduccion, modelo, audio, creada, usada FROM entradas WHERE id = ?",
                (clave.id,),
            ).fetchone()
            if fila is None:
                return None
            original, traduccion, modelo, audio, creada, _ = fila
            ruta = self.directorio_audio / audio if audio else None
            if ruta is not None and not ruta.is_file():
                # El fichero ha desaparecido (borrado a mano): se volverá a sintetizar.
                ruta = None
                cursor.execute(
                    "UPDATE entradas SET audio = NULL, bytes = ? WHERE id = ?",
                    (_bytes_texto(original, traduccion), clave.id),
                )
            cursor.execute("UPDATE entradas SET usada = ? WHERE id = ?", (ahora, clave.id))
        return Entrada(original, traduccion, modelo, ruta, creada, ahora)

    def guardar_traduccion(self, clave: Clave, traduccion: str, modelo: str) -> None:
        """Guarda o sustituye la traducción de una línea.

        Si cambia la traducción, el audio anterior deja de valer y se borra.
        """
        ahora = self._reloj()
        with self._transaccion() as cursor:
            anterior = cursor.execute(
                "SELECT traduccion, audio FROM entradas WHERE id = ?", (clave.id,)
            ).fetchone()
            if anterior is not None and anterior[0] != traduccion and anterior[1]:
                self._borrar_audio(anterior[1])
            cursor.execute(
                """
                INSERT INTO entradas (id, perfil, idioma, original, traduccion, modelo, audio, bytes,
                                      creada, usada)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    traduccion = excluded.traduccion,
                    modelo = excluded.modelo,
                    audio = CASE WHEN traduccion = excluded.traduccion THEN audio END,
                    bytes = CASE WHEN traduccion = excluded.traduccion THEN bytes ELSE excluded.bytes END,
                    usada = excluded.usada
                """,
                (
                    clave.id,
                    clave.perfil,
                    clave.idioma,
                    clave.texto,
                    traduccion,
                    modelo,
                    _bytes_texto(clave.texto, traduccion),
                    ahora,
                    ahora,
                ),
            )
        self._aplicar_limite(proteger=clave.id)

    def guardar_audio(self, clave: Clave, datos: bytes) -> Path:
        """Guarda el audio Opus de una línea ya traducida y devuelve su ruta."""
        nombre = f"{clave.id}.opus"
        ruta = self.directorio_audio / nombre
        with self._transaccion() as cursor:
            fila = cursor.execute(
                "SELECT original, traduccion FROM entradas WHERE id = ?", (clave.id,)
            ).fetchone()
            if fila is None:
                raise KeyError(f"No hay traducción guardada para «{clave.texto}»")
            temporal = ruta.with_name(nombre + ".parcial")
            temporal.write_bytes(datos)
            temporal.replace(ruta)
            cursor.execute(
                "UPDATE entradas SET audio = ?, bytes = ?, usada = ? WHERE id = ?",
                (nombre, _bytes_texto(*fila) + len(datos), self._reloj(), clave.id),
            )
        self._aplicar_limite(proteger=clave.id)
        return ruta

    def invalidar(self, perfil: str) -> int:
        """Borra todo lo guardado de un juego (p. ej. al cambiar su glosario). Devuelve cuántas líneas."""
        return self._borrar("WHERE perfil = ?", (perfil,))

    def vaciar(self) -> int:
        """Borra toda la caché. Devuelve cuántas líneas."""
        return self._borrar("", ())

    def resumen(self) -> list[ResumenPerfil]:
        """Líneas y bytes (texto más audio) de cada juego, de mayor a menor tamaño."""
        with self._transaccion() as cursor:
            filas = cursor.execute(
                "SELECT perfil, COUNT(*), SUM(bytes) FROM entradas GROUP BY perfil ORDER BY 3 DESC, 1"
            ).fetchall()
        return [ResumenPerfil(perfil, entradas, total) for perfil, entradas, total in filas]

    def tamano(self) -> int:
        """Bytes totales de la caché (texto más audio)."""
        return sum(resumen.bytes for resumen in self.resumen())

    def recortar(self) -> None:
        """Aplica el límite ya: tras bajarlo, borra lo usado hace más tiempo hasta caber."""
        self._aplicar_limite(proteger="")

    def borrar_audio(self, perfil: str) -> int:
        """Borra el audio de un juego y conserva sus traducciones (p. ej. al cambiar de voz).

        Devuelve cuántas líneas tenían audio. Se volverá a sintetizar la próxima vez.
        """
        with self._transaccion() as cursor:
            filas = cursor.execute(
                "SELECT id, original, traduccion, audio FROM entradas WHERE perfil = ? AND audio IS NOT NULL",
                (perfil,),
            ).fetchall()
            cursor.executemany(
                "UPDATE entradas SET audio = NULL, bytes = ? WHERE id = ?",
                [(_bytes_texto(original, traduccion), id_) for id_, original, traduccion, _ in filas],
            )
        for *_, audio in filas:
            self._borrar_audio(audio)
        return len(filas)

    def _borrar(self, filtro: str, parametros: tuple[str, ...]) -> int:
        with self._transaccion() as cursor:
            audios = cursor.execute(
                # El filtro es fijo (invalidar o vaciar), nunca viene del usuario.
                f"SELECT audio FROM entradas {filtro}",  # noqa: S608
                parametros,
            ).fetchall()
            cursor.execute(f"DELETE FROM entradas {filtro}", parametros)  # noqa: S608
        for (audio,) in audios:
            if audio:
                self._borrar_audio(audio)
        return len(audios)

    def _borrar_audio(self, nombre: str) -> None:
        (self.directorio_audio / nombre).unlink(missing_ok=True)

    def _aplicar_limite(self, proteger: str) -> None:
        """Borra las entradas usadas hace más tiempo hasta quedar por debajo del límite.

        La entrada `proteger` (la que se acaba de guardar) no se borra aunque el límite no alcance
        para ella: quien la guardó va a usarla enseguida.
        """
        if self.limite_bytes is None:
            return
        with self._transaccion() as cursor:
            total = cursor.execute("SELECT COALESCE(SUM(bytes), 0) FROM entradas").fetchone()[0]
            sobrantes: list[tuple[str, str | None]] = []
            if total > self.limite_bytes:
                for id_, audio, bytes_ in cursor.execute(
                    "SELECT id, audio, bytes FROM entradas WHERE id != ? ORDER BY usada", (proteger,)
                ).fetchall():
                    if total <= self.limite_bytes:
                        break
                    sobrantes.append((id_, audio))
                    total -= bytes_
                cursor.executemany("DELETE FROM entradas WHERE id = ?", [(id_,) for id_, _ in sobrantes])
        for _, audio in sobrantes:
            if audio:
                self._borrar_audio(audio)
