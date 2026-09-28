
## Instalación

### Linux

1. Descarga `vn-audiolibro-X.Y.Z-x86_64.AppImage` y, si quieres, comprueba su huella:
   `sha256sum -c vn-audiolibro-X.Y.Z-x86_64.AppImage.sha256`.
2. Dale permiso de ejecución: `chmod +x vn-audiolibro-*.AppImage`.
3. Ábrelo con doble clic o desde la terminal: `./vn-audiolibro-*.AppImage`.

**Requisitos:** Linux x86_64 con una sesión **X11** (no Wayland), PulseAudio o PipeWire y `paplay`
(paquete `pulseaudio-utils`).

### Windows

1. Descarga `vn-audiolibro-X.Y.Z-windows-x64.zip` y, si quieres, comprueba su huella en PowerShell:
   `Get-FileHash vn-audiolibro-X.Y.Z-windows-x64.zip` (debe coincidir con el `.sha256`).
2. Descomprímelo donde quieras y abre `vn-audiolibro.exe`. No necesita instalación.
3. El ejecutable no está firmado: si Windows SmartScreen avisa, pulsa **Más información** y
   **Ejecutar de todas formas**.

**Requisitos:** Windows 10 u 11 de 64 bits.

### En los dos sistemas

La primera vez descarga los componentes que necesita (unos 1,2 GB: reconocimiento de texto,
traducción y voz). Después funciona sin conexión. 8 GB de RAM recomendados.

Si la versión tiene atestación de origen, puedes verificar cualquier fichero con
`gh attestation verify <fichero> --repo v1kz25/visualnovel-traductor`.
