import argparse
import re
import sys
from pathlib import Path

from youtube_transcript_api import NoTranscriptFound
from youtube_transcript_api import TranscriptsDisabled
from youtube_transcript_api import VideoUnavailable
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter


VIDEO_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def extract_video_id(value: str) -> str:
    """Return a YouTube video id from a raw id or common YouTube URL formats."""
    value = value.strip()
    if VIDEO_ID_REGEX.fullmatch(value):
        return value

    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com/live/)([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)

    raise ValueError(
        "No pude extraer un video_id valido. Pasa un ID de 11 caracteres o una URL de YouTube."
    )


def parse_languages(raw_languages: str) -> list[str]:
    languages = [lang.strip() for lang in raw_languages.split(",") if lang.strip()]
    return languages or ["es", "en"]


def fetch_transcript(video_id: str, languages: list[str]):
    api = YouTubeTranscriptApi()
    if hasattr(api, "fetch"):
        segments = api.fetch(video_id, languages=languages)
    else:
        segments = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    return segments


def _fmt_seconds(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hh = milliseconds // 3_600_000
    mm = (milliseconds % 3_600_000) // 60_000
    ss = (milliseconds % 60_000) // 1000
    ms = milliseconds % 1000
    return f"{hh:02}:{mm:02}:{ss:02}.{ms:03}"


def _fmt_hms(seconds: float) -> str:
    total_seconds = int(seconds)
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return f"{hh:02}:{mm:02}:{ss:02}"


def format_plain_text(segments) -> str:
    return TextFormatter().format_transcript(segments)


def to_raw_segments(segments):
    if hasattr(segments, "to_raw_data"):
        return segments.to_raw_data()
    return segments


def format_with_timestamps(segments) -> str:
    raw_segments = to_raw_segments(segments)

    lines: list[str] = []
    for segment in raw_segments:
        start = float(segment["start"])
        duration = float(segment.get("duration", 0.0))
        end = start + duration
        text = str(segment["text"]).strip()
        lines.append(f"[{_fmt_seconds(start)} --> {_fmt_seconds(end)}] {text}")
    return "\n".join(lines)


def _fmt_compact_seconds(seconds: float) -> str:
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def format_with_timestamps_compact(segments) -> str:
    raw_segments = to_raw_segments(segments)

    lines: list[str] = []
    for segment in raw_segments:
        start = float(segment["start"])
        duration = float(segment.get("duration", 0.0))
        end = start + duration
        text = str(segment["text"]).replace("\n", " ").strip()
        lines.append(
            f"{_fmt_compact_seconds(start)}|{_fmt_compact_seconds(end)}|{text}"
        )
    return "\n".join(lines)


def format_with_start_time_only(segments) -> str:
    raw_segments = to_raw_segments(segments)

    lines: list[str] = []
    for segment in raw_segments:
        start = float(segment["start"])
        text = str(segment["text"]).replace("\n", " ").strip()
        lines.append(f"{_fmt_hms(start)}|{text}")
    return "\n".join(lines)


def build_output_path(video_id: str, output: str | None) -> Path:
    if output:
        return Path(output)
    return Path(f"transcript_{video_id}.txt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga la transcripcion de un video de YouTube usando captions disponibles."
    )
    parser.add_argument(
        "video",
        help="Video ID (11 chars) o URL de YouTube",
    )
    parser.add_argument(
        "-l",
        "--languages",
        default="es,en",
        help='Idiomas en prioridad separados por coma (ej: "es,en").',
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ruta de salida. Por defecto: transcript_<video_id>.txt",
    )
    parser.add_argument(
        "-t",
        "--with-timestamps",
        action="store_true",
        help="Guarda cada segmento con rango de tiempo [HH:MM:SS.mmm --> HH:MM:SS.mmm].",
    )
    parser.add_argument(
        "-tc",
        "--timestamps-compact",
        action="store_true",
        help='Guarda cada segmento como "start|end|text" en segundos.',
    )
    parser.add_argument(
        "-ti",
        "--timestamps-initial",
        action="store_true",
        help='Guarda cada segmento como "HH:MM:SS|text" usando solo el tiempo inicial.',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        video_id = extract_video_id(args.video)
        languages = parse_languages(args.languages)
        segments = fetch_transcript(video_id, languages)
        if args.timestamps_initial:
            transcript_text = format_with_start_time_only(segments)
        elif args.timestamps_compact:
            transcript_text = format_with_timestamps_compact(segments)
        elif args.with_timestamps:
            transcript_text = format_with_timestamps(segments)
        else:
            transcript_text = format_plain_text(segments)
        output_path = build_output_path(video_id, args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(transcript_text, encoding="utf-8")
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except NoTranscriptFound:
        print(
            "[ERROR] No hay transcripcion en los idiomas pedidos. Prueba con --languages en,es.",
            file=sys.stderr,
        )
        return 2
    except TranscriptsDisabled:
        print("[ERROR] El video tiene subtitulos desactivados.", file=sys.stderr)
        return 3
    except VideoUnavailable:
        print("[ERROR] El video no esta disponible.", file=sys.stderr)
        return 4
    except Exception as exc:
        print(f"[ERROR] Fallo inesperado: {exc}", file=sys.stderr)
        return 99

    print(f"Transcripcion guardada en: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
