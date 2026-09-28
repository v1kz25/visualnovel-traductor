#!/usr/bin/env bash
# Construye la versión portable para Windows con PyInstaller: una carpeta con los ejecutables y
# sus bibliotecas, comprimida en un zip. Sin modelos: se descargan en el primer arranque.
#
# Uso (en Windows, con Git Bash): empaquetado/construir_windows.sh [carpeta_de_trabajo]
#   (por defecto, build/windows). Necesita uv.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
TRABAJO="${1:-$RAIZ/build/windows}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$RAIZ/pyproject.toml" | head -1)"
PYINSTALLER="pyinstaller==6.22.3 pyinstaller-hooks-contrib==2026.7"

echo "Construyendo vn-audiolibro $VERSION para Windows en $TRABAJO"
rm -rf "$TRABAJO"
mkdir -p "$TRABAJO"
TRABAJO="$(cd "$TRABAJO" && pwd)"

# Entorno aparte con las mismas versiones que en uv.lock, la app y PyInstaller.
uv venv --quiet --python 3.12 "$TRABAJO/venv"
PYTHON="$TRABAJO/venv/Scripts/python.exe"
uv export --project "$RAIZ" --frozen --no-dev --no-hashes --no-emit-project --format requirements-txt \
    > "$TRABAJO/requisitos.txt"
uv build --project "$RAIZ" --wheel --out-dir "$TRABAJO/dist-wheel" >/dev/null
uv pip install --quiet --python "$PYTHON" -r "$TRABAJO/requisitos.txt"
uv pip install --quiet --python "$PYTHON" --no-deps "$TRABAJO"/dist-wheel/*.whl
# shellcheck disable=SC2086
uv pip install --quiet --python "$PYTHON" $PYINSTALLER

QT_QPA_PLATFORM=offscreen "$PYTHON" "$RAIZ/empaquetado/windows/icono.py" "$TRABAJO/icono.png"
VN_ICONO="$TRABAJO/icono.png" "$PYTHON" -m PyInstaller --noconfirm --log-level WARN \
    --distpath "$TRABAJO/dist" --workpath "$TRABAJO/pyinstaller" \
    "$RAIZ/empaquetado/windows/vn-audiolibro.spec"

NOMBRE="vn-audiolibro-$VERSION-windows-x64"
mv "$TRABAJO/dist/vn-audiolibro" "$TRABAJO/$NOMBRE"
"$PYTHON" -c "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], sys.argv[3])" \
    "$TRABAJO/$NOMBRE" "$TRABAJO" "$NOMBRE"
(cd "$TRABAJO" && sha256sum "$NOMBRE.zip" > "$NOMBRE.zip.sha256")
echo "Listo: $TRABAJO/$NOMBRE.zip ($(du -h "$TRABAJO/$NOMBRE.zip" | cut -f1))"
