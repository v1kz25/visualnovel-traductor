#!/usr/bin/env bash
# Construye el AppImage de vn-audiolibro: Python portable, la app y sus dependencias, sin modelos
# (se descargan en el primer arranque). Todo lo que se descarga va fijado y verificado por SHA-256.
#
# Uso: empaquetado/construir_appimage.sh [carpeta_de_trabajo]   (por defecto, build/appimage)
# Necesita: uv, curl, sha256sum y libxcb-cursor0 instalada en el equipo que construye.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
TRABAJO="$(realpath -m "${1:-$RAIZ/build/appimage}")"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$RAIZ/pyproject.toml" | head -1)"

PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260924/cpython-3.12.14%2B20260924-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PYTHON_SHA="269b2c99e4db15b242bf01832f4fea1e8f1a664f273cff519393f296e9820b41"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
LIBXCB_CURSOR="/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0"

descargar() {  # url, destino, sha256
    if [[ ! -f "$2" ]] || ! echo "$3  $2" | sha256sum -c --quiet - 2>/dev/null; then
        curl -fsSL --retry 3 -o "$2" "$1"
        echo "$3  $2" | sha256sum -c --quiet -
    fi
}

echo "Construyendo vn-audiolibro $VERSION en $TRABAJO"
mkdir -p "$TRABAJO/descargas"
APPDIR="$TRABAJO/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"

descargar "$PYTHON_URL" "$TRABAJO/descargas/python.tar.gz" "$PYTHON_SHA"
descargar "$APPIMAGETOOL_URL" "$TRABAJO/descargas/appimagetool" "$APPIMAGETOOL_SHA"
descargar "$RUNTIME_URL" "$TRABAJO/descargas/runtime-x86_64" "$RUNTIME_SHA"
chmod +x "$TRABAJO/descargas/appimagetool"

tar -xzf "$TRABAJO/descargas/python.tar.gz" -C "$APPDIR/usr"  # crea usr/python
PYTHON="$APPDIR/usr/python/bin/python3"

# Las mismas versiones que en uv.lock, y después la app sin volver a resolver dependencias.
uv export --project "$RAIZ" --frozen --no-dev --no-hashes --no-emit-project --format requirements-txt \
    > "$TRABAJO/requisitos.txt"
uv build --project "$RAIZ" --wheel --out-dir "$TRABAJO/dist" >/dev/null
"$PYTHON" -m pip install --quiet --no-cache-dir --no-warn-script-location -r "$TRABAJO/requisitos.txt"
"$PYTHON" -m pip install --quiet --no-cache-dir --no-deps --no-warn-script-location "$TRABAJO"/dist/*.whl

# Qt 6 necesita libxcb-cursor, que no viene en todas las distribuciones (p. ej. Ubuntu 22.04).
cp -L "$LIBXCB_CURSOR" "$APPDIR/usr/lib/"
cp "$RAIZ/empaquetado/AppRun" "$RAIZ/empaquetado/vn-audiolibro.desktop" "$APPDIR/"
# El icono es el mismo que usa la ventana: está en los recursos del paquete.
cp "$RAIZ/src/vn_audiolibro/ui/icono.svg" "$APPDIR/vn-audiolibro.svg"
ln -sf vn-audiolibro.svg "$APPDIR/.DirIcon"
find "$APPDIR/usr/python" -name "__pycache__" -type d -prune -exec rm -rf {} +

SALIDA="$TRABAJO/vn-audiolibro-$VERSION-x86_64.AppImage"
if ! ARCH=x86_64 "$TRABAJO/descargas/appimagetool" --appimage-extract-and-run --no-appstream \
    --runtime-file "$TRABAJO/descargas/runtime-x86_64" "$APPDIR" "$SALIDA" >"$TRABAJO/appimagetool.log" 2>&1; then
    cat "$TRABAJO/appimagetool.log" >&2
    exit 1
fi
(cd "$TRABAJO" && sha256sum "$(basename "$SALIDA")" > "$(basename "$SALIDA").sha256")
echo "Listo: $SALIDA ($(du -h "$SALIDA" | cut -f1))"
