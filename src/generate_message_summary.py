import argparse
import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

from generate_cues_from_transcript import load_env_file_if_needed
from message_summary_schema import SUMMARY_RESPONSE_JSON_SCHEMA
from message_summary_schema import summary_output_schema_pretty_json

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "message_summary_prompt.md"
TIMED_LINE_REGEX = re.compile(r"^(\d{2}:\d{2}:\d{2})\|(.*)$")
CUE_LINE_REGEX = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+(.+?)\s*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera resumen en puntos (con emojis) del bloque entre 'Mensaje' y antes de "
            "'Ministracion' usando transcript -ti y cues por linea."
        )
    )
    parser.add_argument(
        "transcript_file",
        help="Ruta al transcript en formato -ti (HH:MM:SS|texto).",
    )
    parser.add_argument(
        "cues_file",
        help="Ruta a cues_lines_*.txt (formato: HH:MM:SS Titulo).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ruta de salida para el resumen. Por defecto: summary_<archivo_transcript>.txt",
    )
    parser.add_argument(
        "--start-label",
        default="mensaje",
        help="Etiqueta que marca inicio del bloque (por defecto: mensaje).",
    )
    parser.add_argument(
        "--end-label",
        default="ministracion",
        help="Etiqueta que marca fin del bloque (por defecto: ministracion).",
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
        help="Muestra la respuesta cruda del modelo por stderr.",
    )
    return parser.parse_args()


def _normalize(text: str) -> str:
    lowered = text.strip().lower()
    replacements = str.maketrans(
        {
            "á": "a",
            "é": "e",
            "í": "i",
            "ó": "o",
            "ú": "u",
            "ü": "u",
            "ñ": "n",
        }
    )
    return lowered.translate(replacements)


def _hms_to_seconds(hms: str) -> int:
    hh, mm, ss = hms.split(":")
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def _seconds_to_hms(seconds: int) -> str:
    hh = seconds // 3600
    mm = (seconds % 3600) // 60
    ss = seconds % 60
    return f"{hh:02}:{mm:02}:{ss:02}"


def _parse_cues(cues_text: str) -> list[tuple[int, str]]:
    cues: list[tuple[int, str]] = []
    for line in cues_text.splitlines():
        match = CUE_LINE_REGEX.match(line.strip())
        if not match:
            continue
        hms, title = match.groups()
        cues.append((_hms_to_seconds(hms), title))
    return cues


def find_time_range(cues_text: str, start_label: str, end_label: str) -> tuple[int, int | None, str]:
    start_key = _normalize(start_label)
    end_key = _normalize(end_label)
    cues = _parse_cues(cues_text)
    if not cues:
        raise ValueError("No pude parsear cues validos (formato esperado: HH:MM:SS Titulo).")

    start_index: int | None = None
    for idx, (_, title) in enumerate(cues):
        if start_key in _normalize(title):
            start_index = idx
            break

    if start_index is None:
        raise ValueError(f"No encontre un cue de inicio con etiqueta: '{start_label}'.")
    start_time = cues[start_index][0]

    for seconds, title in cues[start_index + 1 :]:
        if end_key in _normalize(title) and seconds > start_time:
            return start_time, seconds, "end_label"

    # Fallback 1: buscar secciones tipicas posteriores al mensaje.
    post_message_labels = (
        "ministracion",
        "ministración",
        "oracion",
        "oración",
        "cumpleanos",
        "cumpleaños",
        "despedida",
        "cierre",
        "bendicion",
        "bendición",
    )
    for seconds, title in cues[start_index + 1 :]:
        normalized_title = _normalize(title)
        if any(_normalize(label) in normalized_title for label in post_message_labels):
            return start_time, seconds, "post_message_label"

    # Fallback 2: resumir hasta fin de transcript.
    return start_time, None, "end_of_transcript"


def extract_transcript_range(transcript_text: str, start_time: int, end_time: int | None) -> str:
    lines_in_range: list[str] = []
    for line in transcript_text.splitlines():
        match = TIMED_LINE_REGEX.match(line.strip())
        if not match:
            continue
        hms, text = match.groups()
        seconds = _hms_to_seconds(hms)
        in_range = start_time <= seconds if end_time is None else start_time <= seconds < end_time
        if in_range:
            cleaned = text.strip()
            if cleaned:
                lines_in_range.append(f"{hms}|{cleaned}")

    if not lines_in_range:
        raise ValueError(
            "No se encontraron lineas del transcript dentro del rango de tiempo detectado."
        )
    return "\n".join(lines_in_range)


def build_prompt(segment_text: str) -> str:
    try:
        template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"No se encontro el template de prompt: {PROMPT_TEMPLATE_PATH}") from exc
    return (
        template.replace("<SUMMARY_JSON_SCHEMA>", summary_output_schema_pretty_json())
        .replace("<TRANSCRIPCION_MENSAJE>", segment_text)
    )


def call_openrouter(
    model_name: str,
    api_key: str,
    prompt: str,
    max_output_tokens: int = 6000,
    reasoning_effort: str = "low",
) -> tuple[str, str | None]:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=max_output_tokens,
        extra_body={
            "reasoning": {
                "effort": reasoning_effort,
            }
        },
        response_format={
            "type": "json_schema",
            "json_schema": SUMMARY_RESPONSE_JSON_SCHEMA,
        },
    )
    content = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason
    return (content.strip() if content else "{}"), finish_reason


def _try_parse_json_text(raw_text: str):
    text = raw_text.strip()
    if not text:
        raise ValueError("Respuesta vacia del modelo.")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            fenced = "\n".join(lines[1:-1]).strip()
            if fenced:
                try:
                    return json.loads(fenced)
                except json.JSONDecodeError:
                    pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise ValueError("No pude parsear JSON valido desde la respuesta del modelo.")


def parse_summary_payload(summary_json: str) -> dict:
    payload = _try_parse_json_text(summary_json)

    if isinstance(payload, list):
        points = [str(item).strip() for item in payload if str(item).strip()]
        if points:
            return {"summary_points": points}

    if not isinstance(payload, dict):
        raise ValueError("La respuesta no es un objeto JSON valido para resumen.")

    points = payload.get("summary_points")
    if isinstance(points, list):
        cleaned = [str(item).strip() for item in points if str(item).strip()]
        if cleaned:
            return {"summary_points": cleaned}

    alt_keys = ("points", "resumen", "summary", "bullets", "cues")
    for key in alt_keys:
        alt_value = payload.get(key)
        if isinstance(alt_value, list):
            cleaned = [str(item).strip() for item in alt_value if str(item).strip()]
            if cleaned:
                return {"summary_points": cleaned}

    raise ValueError("La respuesta JSON no contiene una lista en 'summary_points'.")


def summary_json_to_lines(summary_json: str) -> str:
    payload = parse_summary_payload(summary_json)
    return "\n".join(payload["summary_points"])


def generate_summary_with_retry(
    model_name: str,
    api_key: str,
    prompt: str,
    max_output_tokens: int,
) -> tuple[str, str, int, str | None, bool, str]:
    attempts: list[tuple[int, str]] = [(max_output_tokens, "low"), (max_output_tokens, "none")]
    retry_tokens = min(max_output_tokens * 2, 6000)
    if retry_tokens > max_output_tokens:
        attempts.append((retry_tokens, "none"))

    last_exc: Exception | None = None
    for idx, (tokens, effort) in enumerate(attempts):
        summary_json, finish_reason = call_openrouter(
            model_name,
            api_key,
            prompt,
            max_output_tokens=tokens,
            reasoning_effort=effort,
        )
        try:
            summary_lines = summary_json_to_lines(summary_json)
            return summary_json, summary_lines, tokens, finish_reason, idx > 0, effort
        except Exception as exc:
            last_exc = exc
            if finish_reason == "length" and idx + 1 < len(attempts):
                continue
            raise

    if last_exc:
        raise last_exc
    raise ValueError("No se pudo generar el resumen.")


def default_output_path(transcript_path: Path) -> Path:
    stem = transcript_path.stem
    return transcript_path.with_name(f"summary_{stem}.txt")


def default_response_path(transcript_path: Path) -> Path:
    stem = transcript_path.stem
    return transcript_path.with_name(f"summary_response_{stem}.txt")


def main() -> int:
    args = parse_args()
    load_env_file_if_needed()
    summary_json = ""
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

    transcript_path = Path(args.transcript_file)
    cues_path = Path(args.cues_file)
    if not transcript_path.exists():
        print(f"[ERROR] No existe el archivo: {transcript_path}", file=sys.stderr)
        return 2
    if not cues_path.exists():
        print(f"[ERROR] No existe el archivo: {cues_path}", file=sys.stderr)
        return 3

    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
        cues_text = cues_path.read_text(encoding="utf-8")
        start_time, end_time, range_source = find_time_range(
            cues_text, args.start_label, args.end_label
        )
        message_segment = extract_transcript_range(transcript_text, start_time, end_time)
        prompt = build_prompt(message_segment)
        summary_json, summary_lines, used_tokens, finish_reason, retried, used_effort = generate_summary_with_retry(
            model_name,
            api_key,
            prompt,
            max_output_tokens=args.max_output_tokens,
        )
        if args.show_raw:
            print("\n[DEBUG] Raw summary response:", file=sys.stderr)
            print(summary_json, file=sys.stderr)
    except Exception as exc:
        if ("summary_points" in str(exc) or "JSON" in str(exc)) and summary_json:
            print("\n[DEBUG] Raw summary response on error:", file=sys.stderr)
            print(summary_json, file=sys.stderr)
        print(f"[ERROR] Fallo inesperado: {exc}", file=sys.stderr)
        return 99

    output_path = Path(args.output) if args.output else default_output_path(transcript_path)
    response_path = default_response_path(transcript_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary_lines + "\n", encoding="utf-8")
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(summary_json + "\n", encoding="utf-8")

    print(summary_lines)
    if end_time is None:
        print(
            f"\n[INFO] Rango usado: {_seconds_to_hms(start_time)} -> FIN TRANSCRIPT",
            file=sys.stderr,
        )
    else:
        print(
            f"\n[INFO] Rango usado: {_seconds_to_hms(start_time)} -> {_seconds_to_hms(end_time)}",
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
    print(f"[INFO] Resumen guardado en: {output_path}", file=sys.stderr)
    print(f"[INFO] Respuesta JSON guardada en: {response_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
