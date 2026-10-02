# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones con [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Añadido
- **Interfaz en inglés:** la app, sus mensajes y la ayuda de la terminal salen en inglés si el sistema está en inglés (o en cualquier idioma que no sea el español). Se puede cambiar en «Idioma de la app», en la ventana principal. Las órdenes y opciones de la terminal no cambian.
- Resumen del README en inglés (`README.en.md`).
- **Guion del juego como fuente del texto:** en los juegos que guardan su guion en ficheros de texto (por ahora, los de Unity con órdenes `OutputLine` en `StreamingAssets/Scripts`), el texto sale exacto del guion y el OCR solo sirve para saber por dónde vas, así que funciona aunque el OCR falle bastante. Cada frase de diálogo se lee entera al aparecer su primera parte, y los párrafos siguientes se traducen por adelantado mientras suena el actual. Se elige en el editor del juego («Guion del juego»), que lo encuentra solo al elegir la ventana; se puede traducir desde el texto original o desde la traducción oficial al inglés que traen algunos guiones. `vn-audiolibro traducir-guion "Juego"` lo traduce entero antes de jugar, y se puede cortar y seguir otro día. Los ficheros del juego no se modifican.
- **El nombre del personaje que habla no se lee:** se reconoce al principio de la línea (`Nombre：texto`, `【Nombre】texto`, `Nombre「texto」` o `Name: text`) o en una zona propia que se dibuja en el editor del juego («Zona del nombre»), y se muestra delante de la traducción en el historial, los subtítulos y la terminal. Cada nombre se traduce una sola vez y se añade al glosario del juego, para que salga siempre igual y se pueda corregir. Si un juego no usa ese formato, se puede desactivar con «No leer el nombre de quien habla» (`--con-nombre` en la terminal).
- **Silenciar la voz** sin dejar de traducir: con «Silenciar voz» (tecla M) o la orden `m` en la terminal, cada línea se sigue traduciendo y mostrando, pero no se lee ni se baja el volumen del juego.

## [0.2.0] - 2026-09-28

Versión para Windows y opción de oír la traducción en inglés.

### Añadido
- **Versión para Windows 10 y 11** (64 bits): zip portable, sin instalación, con `vn-audiolibro.exe` (la interfaz) y `vn-audiolibro-consola.exe` (las órdenes de terminal). Captura la ventana del juego con Win32, reproduce la voz con PortAudio, baja el volumen del juego con Core Audio y arranca el traductor sin abrir una consola. No está firmado, así que Windows SmartScreen puede avisar la primera vez.
- **Acceso directo:** en Windows, el primer arranque ofrece añadir la app al menú Inicio. En Linux, `vn-audiolibro instalar-acceso` la añade al menú de aplicaciones, con su icono.
- **Inglés como idioma de destino:** cada juego se puede traducir y leer en inglés, con voz de mujer (*kristin*) o de hombre (*john*). La voz inglesa (~64 MB) se descarga la primera vez que se usa. Los juegos ya configurados siguen en español.
- **Icono** en la ventana de la app.

### Cambiado
- La CI prueba también en Windows y comprueba los dos paquetes (AppImage y zip) cargando todo lo nativo y los datos.

### Corregido
- El botón «Reintentar» del primer arranque a veces no hacía nada si se pulsaba justo al terminar una descarga fallida.
- En Windows, la terminal fallaba al escribir texto chino o japonés con la salida redirigida.

## [0.1.0] - 2026-09-27

Primera versión: juega una novela visual en chino o japonés y óyela traducida al español, en tu equipo y sin conexión.

### Añadido
- **Lectura de la pantalla:** captura de la zona de texto de la ventana del juego (también con otras ventanas encima), detección de texto nuevo y estable (efecto máquina de escribir, pantallas ADV y NVL) y OCR con PP-OCRv5 para chino tradicional, chino simplificado y japonés.
- **Traducción local** con Hy-MT2 1.8B (Tencent) servido por `llama-server`: contexto de las líneas anteriores, glosario por juego y honoríficos japoneses. La voz empieza con la primera frase mientras se traduce el resto (~1,5 s de mediana).
- **Voz en español** con Piper, de mujer o de hombre, con velocidad ajustable. Lee las líneas en cola, con una pausa entre ellas, o salta a la última al avanzar deprisa.
- **Volumen:** baja el juego mientras habla la voz y, si se quiere, baja o silencia otras aplicaciones (un vídeo, música…). Se recupera aunque la app se cierre de golpe.
- **Caché** de traducciones y audio: la segunda vez cada línea suena al instante. Se puede ver lo que ocupa cada juego, vaciarla y limitar su tamaño.
- **Interfaz gráfica:** añadir y editar juegos dibujando la zona de texto sobre una captura y probando el OCR; jugar con pausa, repetir y saltar; ajustes de voz, lectura, volumen y glosario.
- **Primer arranque:** comprueba el sistema y descarga los componentes (~1,2 GB) mostrando su licencia y el progreso, con posibilidad de cancelar y reintentar.
- **Terminal:** `vn-audiolibro juegos | crear | jugar | cache | preparar`.
- **AppImage** para Linux x86_64 con checksum y atestación de origen.
