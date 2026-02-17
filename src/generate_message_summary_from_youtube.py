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
from generate_cues_from_transcript import build_prompt as build_cues_prompt
from generate_cues_from_transcript import generate_cues_with_retry
from generate_cues_from_transcript import load_env_file_if_needed
from generate_message_summary import _seconds_to_hms
from generate_message_summary import build_prompt as build_summary_prompt
from generate_message_summary import extract_transcript_range
from generate_message_summary import find_time_range
from generate_message_summary import generate_summary_with_retry
from generate_message_summary import parse_summary_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un resumen en puntos (con emojis) del bloque Mensaje -> antes de "
            "Ministracion, recibiendo URL o ID de YouTube."
        )
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
        "--start-label",
        default="mensaje",
        help="Etiqueta de inicio del bloque (por defecto: mensaje).",
    )
    parser.add_argument(
        "--end-label",
        default="ministracion",
        help="Etiqueta de fin del bloque (por defecto: ministracion).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime la respuesta en JSON en lugar de puntos por linea.",
    )
    parser.add_argument(
        "--save-temp",
        action="store_true",
        help="Guarda transcript, cues y resumen en una carpeta temporal (/tmp).",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=6000,
        help="Maximo de tokens de salida para el resumen (por defecto: 6000).",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="Muestra respuestas crudas del modelo (cues y resumen) por stderr.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file_if_needed()
    cues_json = ""
    summary_json = ""
    cues_used_tokens = 3000
    cues_finish_reason: str | None = None
    cues_retried = False
    cues_used_effort = "low"
    used_tokens = args.max_output_tokens
    finish_reason: str | None = None
    retried = False
    used_effort = "low"

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

        cues_prompt = build_cues_prompt(transcript_ti)
        cues_json, cues_lines, cues_used_tokens, cues_finish_reason, cues_retried, cues_used_effort = (
            generate_cues_with_retry(model_name, api_key, cues_prompt)
        )

        start_time, end_time, range_source = find_time_range(
            cues_lines, args.start_label, args.end_label
        )
        message_segment = extract_transcript_range(transcript_ti, start_time, end_time)

        summary_prompt = build_summary_prompt(message_segment)
        summary_json, summary_lines, used_tokens, finish_reason, retried, used_effort = generate_summary_with_retry(
            model_name,
            api_key,
            summary_prompt,
            max_output_tokens=args.max_output_tokens,
        )

        if args.show_raw:
            print("\n[DEBUG] Raw CUEs response:", file=sys.stderr)
            print(cues_json, file=sys.stderr)
            print("\n[DEBUG] Raw summary response:", file=sys.stderr)
            print(summary_json, file=sys.stderr)

        if args.save_temp:
            temp_dir = Path(tempfile.mkdtemp(prefix="youtube-message-summary-"))
            (temp_dir / "transcript_ti.txt").write_text(transcript_ti + "\n", encoding="utf-8")
            (temp_dir / "cues.json").write_text(cues_json + "\n", encoding="utf-8")
            (temp_dir / "cues.txt").write_text(cues_lines + "\n", encoding="utf-8")
            (temp_dir / "summary.json").write_text(summary_json + "\n", encoding="utf-8")
            (temp_dir / "summary.txt").write_text(summary_lines + "\n", encoding="utf-8")
            print(f"[INFO] Archivos temporales en: {temp_dir}", file=sys.stderr)
    except ValueError as exc:
        if ("summary_points" in str(exc) or "JSON" in str(exc)) and summary_json:
            print("\n[DEBUG] Raw summary response on error:", file=sys.stderr)
            print(summary_json, file=sys.stderr)
        if args.show_raw and cues_json:
            print("\n[DEBUG] Raw CUEs response on error:", file=sys.stderr)
            print(cues_json, file=sys.stderr)
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

    if end_time is None:
        print(
            f"[INFO] Rango usado: {_seconds_to_hms(start_time)} -> FIN TRANSCRIPT",
            file=sys.stderr,
        )
    else:
        print(
            f"[INFO] Rango usado: {_seconds_to_hms(start_time)} -> {_seconds_to_hms(end_time)}",
            file=sys.stderr,
        )
    if range_source == "post_message_label":
        print(
            (
                f"[INFO] No se encontro '{args.end_label}' despues de '{args.start_label}'. "
                "Se uso una seccion posterior detectada por nombre."
            ),
            file=sys.stderr,
        )
    elif range_source == "end_of_transcript":
        print(
            (
                f"[INFO] No se encontro '{args.end_label}' ni una seccion posterior "
                f"despues de '{args.start_label}'. Se uso fin de transcript."
            ),
            file=sys.stderr,
        )
    print(
        (
            f"[INFO] CUEs finish_reason: {cues_finish_reason} "
            f"(max_output_tokens usado: {cues_used_tokens}, reasoning.effort: {cues_used_effort})"
        ),
        file=sys.stderr,
    )
    if cues_retried:
        print("[INFO] CUEs reintentados por salida truncada.", file=sys.stderr)
    print(
        (
            f"[INFO] Resumen finish_reason: {finish_reason} "
            f"(max_output_tokens usado: {used_tokens}, reasoning.effort: {used_effort})"
        ),
        file=sys.stderr,
    )
    if retried:
        print(
            (
                f"[INFO] Se reintento por salida truncada. max_output_tokens usado: {used_tokens} "
                f"(finish_reason final: {finish_reason})."
            ),
            file=sys.stderr,
        )

    if args.json:
        payload = parse_summary_payload(summary_json)
        payload["range"] = {
            "start": _seconds_to_hms(start_time),
            "end": _seconds_to_hms(end_time) if end_time is not None else "END_OF_TRANSCRIPT",
        }
        payload["range_source"] = range_source
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(summary_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
