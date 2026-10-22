# Scraper y análisis de perfiles públicos de TikTok

Proyecto de la asignatura de Dispositivos Móviles. A partir del `@usuario` de un perfil **público** de TikTok, el programa obtiene:

- Número de **seguidores** y **seguidos**.
- Los **últimos videos**, con vistas, likes, **comentarios** y **compartidos**.
- Los **primeros 5 comentarios** de cada video (cuando TikTok los deja ver).
- Un **análisis de texto** con modelos de Hugging Face: transcripción del audio, sentimiento, emociones y una estimación exploratoria del Big Five.

> **Aviso:** TikTok prohíbe el scraping automatizado en sus términos de uso. Este proyecto es solo con fines académicos, con pocas peticiones y sobre datos públicos. No lo uses de forma masiva ni para tomar decisiones sobre personas.

---

## Estructura del proyecto

| Archivo | Descripción |
|---|---|
| `tiktok_scraper.py` | Versión con **solo Playwright**. |
| `tiktok_scraper_hibrido.py` | Versión **híbrida**: Playwright carga la página y **BeautifulSoup** analiza el HTML. Además captura los primeros 5 comentarios de cada video. |
| `tiktok_scraper_requests.py` | Versión con `requests` + BeautifulSoup. **TikTok la bloquea** (no ejecuta JavaScript); se conserva como comparación. |
| `analisis.py` | Analiza el JSON generado por el scraper: transcribe, calcula sentimiento, emociones y Big Five. |
| `requirements.txt` | Dependencias de Python. |

---

## Cómo funciona

### 1. Scraping (Playwright)
1. Abre el perfil con **Google Chrome real** (`channel="chrome"`), porque el Chromium de pruebas de Playwright es detectado más fácilmente por TikTok.
2. Lee los datos del perfil desde el bloque JSON que TikTok incrusta en la página (`__UNIVERSAL_DATA_FOR_REHYDRATION__`). Se reintenta hasta que el JSON llega completo.
3. **Escucha las respuestas de red** (`page.on("response")`): cuando el perfil pide su lista de videos, el programa guarda las estadísticas de cada uno. Así no se entra video por video con la URL directa, que TikTok responde con error 403.
4. En la versión híbrida, hace **clic** en cada video desde el perfil y captura la respuesta de comentarios.
5. Ordena los videos por fecha (los más recientes primero, ignorando los fijados) y guarda los resultados.

### 2. Cookies
El programa **no maneja cookies manualmente**. Usa un perfil persistente de navegador:

```python
launch_persistent_context(user_data_dir="perfil_navegador", ...)
```

Chrome guarda las cookies de TikTok en la carpeta `perfil_navegador/` y las reenvía en cada ejecución, igual que un navegador normal. Por eso un captcha resuelto una vez suele recordarse. También cuentan tu actividad como visitante: pasados un par de videos, TikTok puede pedir iniciar sesión (afecta solo a los comentarios). Borrar la carpeta equivale a empezar como visitante nuevo. **Nunca se sube a Git.**

### 3. Análisis (`analisis.py`)
Por cada video:

1. `yt-dlp` descarga el audio.
2. **Whisper** (`openai/whisper-small`) lo transcribe en español.
3. Se junta la descripción con la transcripción (texto del creador).
4. **Sentimiento y emociones** en español: `pysentimiento/robertuito`.
5. Traducción al inglés (`Helsinki-NLP/opus-mt-es-en`) y **Big Five** con `Minej/bert-base-personality`.

---

## Requisitos

- Windows, macOS o Linux con **Python 3.11** o similar.
- **Google Chrome** instalado.
- **ffmpeg** (solo para `analisis.py`).
- Conexión a internet. La primera ejecución de `analisis.py` descarga unos 3 GB de modelos.
- No necesitas tarjeta gráfica: todo corre en CPU (más lento).

---

## Instalación

```powershell
# 1. Clonar el repositorio
git clone https://github.com/TU_USUARIO/TU_REPOSITORIO.git
cd TU_REPOSITORIO

# 2. Crear y activar el entorno virtual
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 3. Instalar dependencias
pip install -r requirements.txt
```

Si el `requirements.txt` no incluye todo lo necesario, instala a mano:

```powershell
pip install playwright beautifulsoup4 requests
pip install yt-dlp transformers torch sentencepiece sacremoses pysentimiento
pip install -U "yt-dlp[default,curl-cffi]"
```

**ffmpeg** (necesario para el análisis de audio):

```powershell
winget install Gyan.FFmpeg
```

Después **cierra y vuelve a abrir VS Code** y comprueba con `ffmpeg -version`.

---

## Uso

> En PowerShell, el símbolo `@` tiene un significado especial. Escribe el usuario **sin arroba** o entre comillas: `calla.nomas` o `"@calla.nomas"`.

### Paso 1: obtener los datos del perfil

```powershell
python tiktok_scraper_hibrido.py calla.nomas 10
```

El segundo argumento es la cantidad de videos (por defecto 5). Si no pasas el usuario, el programa te lo pregunta.

- Se abrirá una ventana de Chrome. **No la cierres ni la uses mientras el programa trabaja.**
- Si TikTok muestra un **captcha**, resuélvelo en esa ventana y presiona **Enter** en la terminal para continuar.

**Archivos generados:**

| Archivo | Contenido |
|---|---|
| `usuario_hibrido.json` | Perfil, videos y primeros comentarios. |
| `usuario_hibrido.csv` | Una fila por video (con los comentarios unidos por ` \| `). |
| `usuario_hibrido_comentarios.csv` | Una fila por comentario. |

Por privacidad, los nombres de usuario de quienes comentan **no se guardan** (`INCLUIR_AUTOR = False` en el código).

La versión de solo Playwright se usa igual: `python tiktok_scraper.py calla.nomas 10` (genera `usuario.json` y `usuario.csv`, sin comentarios).

### Paso 2: analizar los videos

```powershell
python analisis.py calla.nomas_hibrido.json
```

Genera `analisis_calla.nomas.csv` con una fila por video y una fila `PROMEDIO`, además de `transcripciones.json` (caché de las transcripciones, para no repetirlas).

**Cómo leer el CSV de análisis:**

| Columnas | Significado |
|---|---|
| `fuente` | `descripcion+audio` si se transcribió el audio; `solo descripcion` si no. |
| `sent_NEG`, `sent_NEU`, `sent_POS` | Probabilidades de sentimiento negativo, neutro y positivo (suman 1). |
| `emo_*` | Probabilidad de cada emoción (alegría, tristeza, ira, sorpresa, asco, miedo, otras). Suman 1. |
| `Extroversion` ... `Openness` | Salida cruda del modelo de Big Five. **No son porcentajes**; sirven para comparar entre videos. |

### Si no se puede descargar el audio
TikTok a veces bloquea a `yt-dlp`. En ese caso:

1. Graba o descarga el video manualmente.
2. Cópialo a la carpeta `audios/` con el **id del video** como nombre (el número al final del enlace), por ejemplo `7697656336556854546.mp4`.
3. Vuelve a ejecutar `analisis.py`: usará esos archivos en lugar de descargarlos.

---

## Problemas frecuentes

| Problema | Posible causa y solución |
|---|---|
| Aparece un captcha | Resuélvelo en la ventana de Chrome y presiona Enter en la terminal. |
| Error 403 o `Videos obtenidos: 0` | TikTok marcó la sesión. Borra `perfil_navegador/`, cambia de red o espera unas horas. Ejecutar muchas veces seguidas empeora el bloqueo. |
| `JSONDecodeError` al leer el perfil | El JSON llegó incompleto. Las versiones actuales reintentan automáticamente. |
| Piden iniciar sesión al abrir videos | Límite de TikTok para visitantes. Se pierden comentarios, pero las estadísticas se siguen obteniendo. |
| `ffmpeg` no se reconoce | No está en el PATH. Reinstálalo y reinicia VS Code por completo. |
| `yt-dlp` falla con TikTok | Instala `yt-dlp[default,curl-cffi]` o usa el método manual de la carpeta `audios/`. |
| `The task translation has been removed` | Estás usando una versión vieja de `analisis.py`; usa la actual, compatible con `transformers` 5. |

---

## Limitaciones

- **TikTok cambia su estructura con frecuencia.** Las rutas de red y los nombres de los campos pueden dejar de funcionar.
- Sin sesión iniciada, TikTok limita el acceso a los comentarios a partir del segundo video aproximadamente.
- El **Big Five es una estimación exploratoria**, no una evaluación psicológica: los modelos se entrenaron con ensayos en inglés y largos, y aquí se aplican a textos cortos en español traducidos automáticamente. Con pocas palabras por video, los resultados no permiten sacar conclusiones sobre la personalidad de nadie.
- Los comentarios los escriben otras personas: sirven para medir la reacción de la audiencia, no para describir al creador.

---

## Privacidad y buenas prácticas

- Usa perfiles propios o de personas que sepan y estén de acuerdo con el análisis.
- No publiques análisis de personalidad de personas reales identificables.
- No subas a Git la carpeta `perfil_navegador/` (contiene cookies), ni el entorno `venv/`, ni audios o videos (`audios/`, `*.wav`, `*.mp4`, `*.mp3`), ni `transcripciones.json`.

Ejemplo de `.gitignore`:

```
venv/
perfil_navegador/
__pycache__/
*.pyc
debug.html
.vscode/
audios/
*.wav
*.mp4
*.mp3
transcripciones.json
```

---

## Tecnologías

Python · Playwright · BeautifulSoup · requests · yt-dlp · ffmpeg · Hugging Face Transformers (Whisper, Marian, BERT, RoBERTuito) · pysentimiento