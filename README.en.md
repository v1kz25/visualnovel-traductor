<p align="center">
  <img src=".github/assets/banner.png" alt="vn-audiolibro: Chinese and Japanese visual novels, read aloud while you play" width="100%">
</p>

# vn-audiolibro

[Español](README.md) · **English**

A real-time audiobook for Chinese and Japanese visual novels.

While you play, the app reads the text in the game window, translates it into Spanish or English
(chosen per game) and reads it aloud. Everything runs on your computer: no accounts, no cost and no
connection (except to download the models the first time).

The app itself is available in Spanish and English: it follows your system language, and you can
change it under **App language** in the main window.

## How it works

1. Pick the game window and draw a box over the text area (once per game).
2. The app notices new text, recognizes it with OCR and translates it with a local model.
3. You hear the translation with a synthetic voice and see it in the app window. Anything already
   translated is cached.

## Requirements

- **Linux** x86_64 with an **X11** session (not Wayland) and PulseAudio or PipeWire, with `paplay`
  (package `pulseaudio-utils`).
- **Windows** 10 or 11, 64-bit.
- About 2 GB of free disk space for the components downloaded the first time.
- 8 GB of RAM recommended.

## Installation

- **Linux**: download the AppImage from the latest [release](../../releases), make it executable
  (`chmod +x vn-audiolibro-*.AppImage`) and run it.
- **Windows**: download `vn-audiolibro-X.Y.Z-windows-x64.zip` from the latest
  [release](../../releases), unzip it anywhere and open `vn-audiolibro.exe`. The executable is not
  signed, so SmartScreen may warn you the first time: choose **More info** and then **Run anyway**.

The first time, the app downloads the components it needs (about 1.2 GB), showing their licenses
and progress. After that it works offline.

## Usage

1. **Add game**: choose the game window, capture it and draw a box over the text box. This is also
   where you choose the language of the translation and the voice.
2. **Play**: the app reads each new line, translates it and says it aloud while you play.
3. **Settings**: voice (female or male) and speed, what to do when you advance quickly, the volume
   of the game and other applications, and a glossary of names.

From the terminal: `vn-audiolibro --help` (`vn-audiolibro-consola.exe --help` on Windows).

## Translating the app

The interface texts are written in Spanish in the code and each language has a catalog in
`src/vn_audiolibro/textos/`. To add a language, create its catalog and fill in the empty `msgstr`
entries:

```bash
uv run python -m vn_audiolibro.textos fr
```

## Contributing

Bugs and suggestions go in [issues](../../issues/new/choose). Before sending a change, read
[`CONTRIBUTING.md`](CONTRIBUTING.md) (in Spanish).

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
