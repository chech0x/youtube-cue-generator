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
