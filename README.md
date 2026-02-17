# youtube-cue-generator

![youtube-cue-generator banner](https://raw.githubusercontent.com/chech0x/youtube-cue-generator/main/images/banner.png)

Scripts para:
- descargar transcripciones de YouTube
- exportarlas con distintos formatos de tiempo
- generar CUEs por secciones usando OpenRouter (JSON schema)

## Requisitos

- Python 3.12+
- `uv`

## Instalación

```bash
uv sync
```

## Variables de entorno

Copia el ejemplo y completa tu API key:

```bash
cp .env.example .env
```

Variables:
- `MODEL_NAME`
- `OPENROUTER_API_KEY`

## 1) Descargar transcript

Formato simple:

```bash
uv run src/download_youtube_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Formato por segmento `[inicio --> fin] texto`:

```bash
uv run src/download_youtube_transcript.py "VIDEO_ID" -t -o transcript_timed.txt
```

Formato compacto `inicio|fin|texto`:

```bash
uv run src/download_youtube_transcript.py "VIDEO_ID" -tc -o transcript_tc.txt
```

Formato inicial `HH:MM:SS|texto` (recomendado para CUEs):

```bash
uv run src/download_youtube_transcript.py "VIDEO_ID" -ti -o transcript_ti.txt
```

Tambien soporta URLs tipo live:

```bash
uv run src/download_youtube_transcript.py "https://www.youtube.com/live/VIDEO_ID"
```

## 2) Generar CUEs con OpenRouter

```bash
uv run src/generate_cues_from_transcript.py transcript_ti.txt
```

Salida:
- `cues_<archivo>.txt` (JSON con `{"cues":[...]}`)
- `response_<archivo>.txt` (respuesta JSON completa)
- `cues_lines_<archivo>.txt` (un cue por línea)

## Notas

- El script de CUEs fuerza respuesta estructurada vía `response_format` + `json_schema`.
- Si el video no tiene subtítulos disponibles, la descarga de transcript fallará.

## Prompt configurable

El prompt de extracción de CUEs está en:

- `prompts/cues_prompt.md`

El script reemplaza el placeholder `<TRANSCRIPCION>` por el contenido real de la transcripción.

Si quieres ajustar categorías, estilo de títulos o reglas, edita ese archivo sin tocar el código Python.

## 3) Comando unificado (YouTube -> CUEs)

Genera CUEs directamente desde URL o `video_id` sin archivos intermedios por defecto.

Salida por defecto: texto por líneas (`HH:MM:SS Titulo`).

```bash
uv run src/generate_cues_from_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Con `video_id`:

```bash
uv run src/generate_cues_from_youtube.py "VIDEO_ID"
```

Con URL live:

```bash
uv run src/generate_cues_from_youtube.py "https://www.youtube.com/live/VIDEO_ID"
```

Con idiomas:

```bash
uv run src/generate_cues_from_youtube.py "VIDEO_ID" -l "es,en"
```

Salida JSON:

```bash
uv run src/generate_cues_from_youtube.py "VIDEO_ID" --json
```

Guardar artefactos en carpeta temporal (`/tmp`):

```bash
uv run src/generate_cues_from_youtube.py "VIDEO_ID" --save-temp
```

Debug raw (respuesta cruda del modelo):

```bash
uv run src/generate_message_summary_from_youtube.py "VIDEO_ID" --show-raw
```

## 4) Resumen del Mensaje (con emojis)

Toma el bloque entre `Mensaje` y antes de `Ministración` usando tiempos detectados en `cues_lines_*.txt`, y arma un resumen en puntos con emojis.
Al modelo de resumen se le pasa el **texto completo del rango** (no solo los tiempos).
Si no aparece un cue explícito de `Ministración`, el script usa fallback automático:
1) la primera sección posterior detectada (`Oración`, `Cumpleaños`, `Despedida`, etc.), o
2) fin del transcript si no hay una sección posterior clara.

Directo con URL o `video_id`:

```bash
uv run src/generate_message_summary_from_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

o:

```bash
uv run src/generate_message_summary_from_youtube.py "VIDEO_ID"
```

Tambien soporta URL live:

```bash
uv run src/generate_message_summary_from_youtube.py "https://www.youtube.com/live/VIDEO_ID"
```

Con idiomas:

```bash
uv run src/generate_message_summary_from_youtube.py "VIDEO_ID" -l "es,en"
```

Salida JSON:

```bash
uv run src/generate_message_summary_from_youtube.py "VIDEO_ID" --json
```

Resumen con mas tokens (default ya es 6000, puedes subirlo si hace falta):

```bash
uv run src/generate_message_summary_from_youtube.py "VIDEO_ID" --max-output-tokens 8000
```

Guardar artefactos temporales (`/tmp`):

```bash
uv run src/generate_message_summary_from_youtube.py "VIDEO_ID" --save-temp
```

Ver respuesta cruda del modelo (cues + resumen):

```bash
uv run src/generate_message_summary_from_youtube.py "VIDEO_ID" --show-raw
```

Tambien puedes correrlo desde archivos ya generados:

```bash
uv run src/generate_message_summary.py transcript_ti.txt cues_lines_transcript_ti.txt
```

Salida:
- `summary_<archivo>.txt` (puntos del mensaje, uno por línea)
- `summary_response_<archivo>.txt` (respuesta JSON completa)

Logs utiles en stderr:
- `finish_reason` de CUEs y de Resumen.
- `reasoning.effort` usado en cada etapa.
- aviso de reintento automatico cuando hay salida truncada (`length`).

Opcional: cambiar etiquetas de inicio/fin:

```bash
uv run src/generate_message_summary.py transcript_ti.txt cues_lines_transcript_ti.txt --start-label mensaje --end-label ministracion
```
