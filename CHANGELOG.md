# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones con [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Añadido
- **Controles al pasar el ratón por los subtítulos:** botones para pausar o seguir, repetir, saltar y ocultar los subtítulos, sin salir del juego y sin depender de los atajos de teclado. Los clics no le quitan el foco al juego.
- Al ocultar los subtítulos queda una marca pequeña de «Subtítulos ocultos» sobre el juego, para que no parezca que han desaparecido; al pasar el ratón por ella vuelven los controles.

## [0.3.0] - 2026-10-12

Subtítulos sobre el juego, controles sin salir de él, más idiomas, el guion del juego como fuente del texto y Gemini como traductor opcional.

### Añadido
- **Subtítulos encima del juego** (opcionales, en los ajustes del juego): la traducción aparece encima o debajo de la caja de texto, o tapándola, con el tamaño de letra y la opacidad que elijas. Los clics siguen llegando al juego y solo se ven mientras el juego es la ventana activa. Aparecen con la primera frase de la traducción, a la vez que la voz, y crecen con cada parte.
- **Inglés como idioma de origen:** se pueden jugar juegos en inglés y oírlos traducidos.
- **Menús de opciones:** cuando el juego muestra una elección, cada opción se traduce por separado y la voz las lee numeradas («Opción 1: …»). Funciona con la búsqueda del texto «Con el detector».
- **Interfaz en inglés:** la app, sus mensajes y la ayuda de la terminal salen en inglés si el sistema está en inglés (o en cualquier idioma que no sea el español). Se puede cambiar en «Idioma de la app», en la ventana principal. Las órdenes y opciones de la terminal no cambian.
- Resumen del README en inglés (`README.en.md`).
- **Guion del juego como fuente del texto:** en los juegos que guardan su guion en ficheros de texto (por ahora, los de Unity con órdenes `OutputLine` en `StreamingAssets/Scripts`), el texto sale exacto del guion y el OCR solo sirve para saber por dónde vas, así que funciona aunque el OCR falle bastante. Cada frase de diálogo se lee entera al aparecer su primera parte, y los párrafos siguientes se traducen por adelantado mientras suena el actual. Se elige en el editor del juego («Guion del juego»), que lo encuentra solo al elegir la ventana; se puede traducir desde el texto original o desde la traducción oficial al inglés que traen algunos guiones. `vn-audiolibro traducir-guion "Juego"` lo traduce entero antes de jugar, y se puede cortar y seguir otro día. Los ficheros del juego no se modifican.
- **El nombre del personaje que habla no se lee:** se reconoce al principio de la línea (`Nombre：texto`, `【Nombre】texto`, `Nombre「texto」` o `Name: text`) o en una zona propia que se dibuja en el editor del juego («Zona del nombre»), y se muestra delante de la traducción en el historial, los subtítulos y la terminal. Cada nombre se traduce una sola vez y se añade al glosario del juego, para que salga siempre igual y se pueda corregir. Si un juego no usa ese formato, se puede desactivar con «No leer el nombre de quien habla» (`--con-nombre` en la terminal).
- **Voz de cada personaje:** en los ajustes del juego, la pestaña «Personajes» lista los que ya han hablado (se apuntan solos al jugar) y deja elegir para cada uno voz de mujer, de hombre o la del juego. En español es la misma voz con otro hablante; en inglés, la otra voz se descarga la primera vez. El audio guardado recuerda con qué voz se sintetizó, así que cambiar la de un personaje no obliga a borrar la caché.
- **Francés, portugués, alemán e italiano como idiomas de destino:** cada juego se puede traducir y leer en cualquiera de ellos, también los juegos en inglés. Cada idioma tiene voz de mujer y de hombre (en portugués e italiano, una sola voz para los dos, porque no hay otra con licencia libre), que se descarga la primera vez que se usa. Las voces y sus licencias están en el README.
- **Controles sin salir del juego:** atajos de teclado globales que funcionan con el juego en primer plano: Ctrl+Alt+P (pausar o seguir), Ctrl+Alt+R (repetir), Ctrl+Alt+S (saltar) y Ctrl+Alt+H (mostrar u ocultar los subtítulos). Se pueden cambiar o desactivar en «Atajos de teclado…», y la app avisa si alguno ya lo usa otra aplicación. En Linux funcionan con X11.
- **Modo «solo subtítulos»:** al jugar, la app se minimiza y sobre el juego solo quedan los subtítulos; al terminar, vuelve.
- **Gemini como traductor opcional:** en el editor de cada juego se puede elegir Gemini Flash-Lite, de Google, con la clave gratuita de cada usuario, guardada en el llavero del sistema. Si falla o se agota el límite, la línea se traduce en local y se avisa. Al traducir el guion entero, Gemini traduce 40 líneas por petición, para que un guion largo quepa en el límite diario del plan gratuito. La cuenta de peticiones se guarda entre ejecuciones: si se agota, se sigue otro día por donde se quedó.
- **Traducir el guion desde la interfaz:** en los juegos con guion, el botón «Traducir el guion…» de la ventana principal lo traduce entero antes de jugar, con el progreso, el tiempo que lleva y una estimación del que falta. Se puede parar y seguir otro día; mientras traduce no se puede jugar.
- **Aviso de versión nueva:** si hay una versión más nueva publicada, la ventana principal lo dice en una franja discreta, con sus novedades y el enlace para descargarla, una sola vez por versión. La app pregunta la primera vez si quieres el aviso, porque para saberlo consulta GitHub (como mucho una vez al día); se puede cambiar en «Avisar de versiones nuevas». Nunca descarga ni instala nada sola.
- **Silenciar la voz** sin dejar de traducir: con «Silenciar voz» (tecla M) o la orden `m` en la terminal, cada línea se sigue traduciendo y mostrando, pero no se lee ni se baja el volumen del juego.

### Cambiado
- **Buscar el texto con el detector:** en los juegos que escriben el texto directamente sobre la imagen, el ajuste «Buscar el texto → Con el detector» encuentra las líneas con el detector de PP-OCRv5 (se descarga la primera vez que se usa). Los juegos ya configurados siguen buscando por color.
- Banco de pruebas de la traducción (`python -m vn_audiolibro.traduccion`) para medir la velocidad, la calidad y el uso de CPU y memoria.

### Corregido
- El historial de la ventana principal a veces no mostraba la última línea traducida, sobre todo al cambiar el tamaño de la ventana.

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
