import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from youtube_transcript_api import NoTranscriptFound
from youtube_transcript_api import TranscriptsDisabled
from youtube_transcript_api import VideoUnavailable

from download_youtube_transcript import extract_video_id
from download_youtube_transcript import fetch_transcript
from download_youtube_transcript import format_with_start_time_only
from download_youtube_transcript import parse_languages
from generate_cues_from_transcript import build_prompt
from generate_cues_from_transcript import call_openrouter
from generate_cues_from_transcript import load_env_file_if_needed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera CUEs desde un video de YouTube (URL o ID) y responde por stdout."
    )
    parser.add_argument(
        "video",
        help="Video ID (11 chars) o URL de YouTube.",
    )
    parser.add_argument(
        "-l",
        "--languages",
        default="es,en",
        help='Idiomas en prioridad separados por coma (ej: "es,en").',
    )
    parser.add_argument(
        "--save-temp",
        action="store_true",
        help="Guarda transcript y cues en una carpeta temporal (/tmp).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime la respuesta en JSON en lugar de texto por lineas.",
    )
    return parser.parse_args()


def cues_json_to_lines(cues_json: str) -> str:
    payload = json.loads(cues_json)
    cues = payload.get("cues")
    if not isinstance(cues, list):
        raise ValueError("La respuesta JSON no contiene una lista en 'cues'.")
    lines = [str(item).strip() for item in cues if str(item).strip()]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    load_env_file_if_needed()

    model_name = os.getenv("MODEL_NAME")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not model_name:
        print("[ERROR] Falta MODEL_NAME en el entorno o .env", file=sys.stderr)
        return 1
    if not api_key:
        print("[ERROR] Falta OPENROUTER_API_KEY en el entorno o .env", file=sys.stderr)
        return 1

    try:
        video_id = extract_video_id(args.video)
        languages = parse_languages(args.languages)
        segments = fetch_transcript(video_id, languages)
        transcript_ti = format_with_start_time_only(segments)
        prompt = build_prompt(transcript_ti)
        cues_json = call_openrouter(model_name, api_key, prompt)
        cues_lines = cues_json_to_lines(cues_json)

        if args.save_temp:
            temp_dir = Path(tempfile.mkdtemp(prefix="youtube-cues-"))
            (temp_dir / "transcript_ti.txt").write_text(transcript_ti + "\n", encoding="utf-8")
            (temp_dir / "cues.json").write_text(cues_json + "\n", encoding="utf-8")
            (temp_dir / "cues.txt").write_text(cues_lines + "\n", encoding="utf-8")
            print(f"[INFO] Archivos temporales en: {temp_dir}", file=sys.stderr)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except NoTranscriptFound:
        print(
            "[ERROR] No hay transcripcion en los idiomas pedidos. Prueba con --languages en,es.",
            file=sys.stderr,
        )
        return 3
    except TranscriptsDisabled:
        print("[ERROR] El video tiene subtitulos desactivados.", file=sys.stderr)
        return 4
    except VideoUnavailable:
        print("[ERROR] El video no esta disponible.", file=sys.stderr)
        return 5
    except Exception as exc:
        print(f"[ERROR] Fallo inesperado: {exc}", file=sys.stderr)
        return 99

    if args.json:
        print(cues_json)
    else:
        print(cues_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
