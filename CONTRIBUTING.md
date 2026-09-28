# Contribuir a vn-audiolibro

Gracias por querer ayudar. Este documento resume cómo está organizado el proyecto y qué se espera
de un cambio.

## Antes de empezar

- Los errores y las propuestas se abren como [issues](../../issues/new/choose), con su plantilla.
- Para un cambio grande, abre antes una issue para hablarlo: así nadie trabaja en algo que no encaja.
- **Nunca subas capturas, textos ni audio de juegos**, ni en el código ni en las issues: tienen
  copyright. Los tests usan imágenes sintéticas generadas con una fuente CJK libre.

## Preparar el entorno

Hace falta [uv](https://docs.astral.sh/uv/) y Python 3.12 (uv lo instala si no lo tienes).

```bash
git clone https://github.com/v1kz25/visualnovel-traductor.git
cd vn-audiolibro
git config core.hooksPath .githooks   # bloquea el push directo a main y develop
uv sync
uv run vn-audiolibro
```

En Linux, los tests de OCR necesitan la fuente Noto Sans CJK (`fonts-noto-cjk`). Los tests que usan
los modelos reales se saltan si no están descargados (se descargan al abrir la app la primera vez).

## Ramas y commits

- `develop` es la rama de integración: los cambios salen de ella en una rama
  `feature/<descripcion-corta>` (minúsculas y guiones) y vuelven por pull request.
- `main` solo tiene versiones publicadas.
- Commits pequeños y con [Conventional Commits](https://www.conventionalcommits.org/es/), en español
  y en imperativo: `feat: añade el japonés vertical`, `fix(ocr): corrige la puntuación`.

## Antes de abrir el pull request

Pasa lo mismo que la CI:

```bash
uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest
```

- `ruff` revisa estilo, errores, reglas de seguridad y complejidad (≤ 10 por función).
- `mypy --strict` revisa los tipos.
- `pytest` exige una cobertura mínima del 80 %.

El pull request va contra `develop`, con un título en el mismo formato que los commits, y explica
qué cambia, por qué y cómo probarlo. Si cierra una issue, añade `Closes #N`.

## Convenciones del código

- Código, comentarios, docstrings, commits y pull requests en español.
- Para el usuario, lo que configura son **juegos** (en el código, `Perfil`).
- Lo que depende del sistema (X11, PulseAudio, Win32) vive en `src/vn_audiolibro/plataforma.py`.
- Cada OCR, traductor o motor de voz entra por su interfaz (`Reconocedor`, `Traductor`…); nada del
  pipeline depende de una implementación concreta.
- El idioma de origen se configura por juego: nada fijo en el código.
- Los modelos no van en el repo: se descargan en el primer arranque y se verifican por SHA-256.

## Licencia

Al contribuir, aceptas que tu código se publique bajo la licencia del proyecto,
[GPL-3.0-or-later](LICENSE).
