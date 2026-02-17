import argparse
import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from cues_schema import CUES_RESPONSE_JSON_SCHEMA
from cues_schema import cues_output_schema_pretty_json

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "cues_prompt.md"


def load_env_file_if_needed(env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        return

    needed = {"MODEL_NAME", "OPENROUTER_API_KEY"}
    missing = [key for key in needed if not os.getenv(key)]
    if not missing:
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in needed and not os.getenv(key):
            os.environ[key] = value


def build_prompt(transcript_text: str) -> str:
    try:
        template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"No se encontro el template de prompt: {PROMPT_TEMPLATE_PATH}") from exc
    return (
        template.replace("<CUES_JSON_SCHEMA>", cues_output_schema_pretty_json())
        .replace("<TRANSCRIPCION>", transcript_text)
    )


def call_openrouter(
    model_name: str,
    api_key: str,
    prompt: str,
    max_output_tokens: int = 3000,
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
            "json_schema": CUES_RESPONSE_JSON_SCHEMA,
        },
    )
    content = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason
    return (content.strip() if content else "{}"), finish_reason


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera CUEs desde una transcripcion -ti usando OpenRouter."
    )
    parser.add_argument(
        "transcript_file",
        help="Ruta al archivo de transcripcion generado con -ti.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ruta de salida para los cues. Por defecto: cues_<archivo>.txt",
    )
    return parser.parse_args()


def default_output_path(transcript_path: Path) -> Path:
    stem = transcript_path.stem
    return transcript_path.with_name(f"cues_{stem}.txt")


def default_response_path(transcript_path: Path) -> Path:
    stem = transcript_path.stem
    return transcript_path.with_name(f"response_{stem}.txt")


def default_lines_path(transcript_path: Path) -> Path:
    stem = transcript_path.stem
    return transcript_path.with_name(f"cues_lines_{stem}.txt")


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


def parse_cues_payload(cues_json: str) -> dict:
    payload = _try_parse_json_text(cues_json)

    if isinstance(payload, list):
        cleaned = [str(item).strip() for item in payload if str(item).strip()]
        if cleaned:
            return {"cues": cleaned}

    if not isinstance(payload, dict):
        raise ValueError("La respuesta no es un objeto JSON valido para cues.")

    cues = payload.get("cues")
    if isinstance(cues, list):
        cleaned = [str(item).strip() for item in cues if str(item).strip()]
        if cleaned:
            return {"cues": cleaned}

    alt_keys = ("points", "resumen", "summary", "bullets", "summary_points")
    for key in alt_keys:
        alt_value = payload.get(key)
        if isinstance(alt_value, list):
            cleaned = [str(item).strip() for item in alt_value if str(item).strip()]
            if cleaned:
                return {"cues": cleaned}

    raise ValueError("La respuesta JSON no contiene una lista en 'cues'.")

def cues_json_to_lines(cues_json: str) -> str:
    payload = parse_cues_payload(cues_json)
    cues = payload["cues"]
    lines = [str(item).strip() for item in cues if str(item).strip()]
    return "\n".join(lines)


def generate_cues_with_retry(
    model_name: str,
    api_key: str,
    prompt: str,
    max_output_tokens: int = 3000,
) -> tuple[str, str, int, str | None, bool, str]:
    attempts: list[tuple[int, str]] = [(max_output_tokens, "low"), (max_output_tokens, "none")]
    retry_tokens = min(max_output_tokens * 2, 6000)
    if retry_tokens > max_output_tokens:
        attempts.append((retry_tokens, "none"))

    last_exc: Exception | None = None
    for idx, (tokens, effort) in enumerate(attempts):
        cues_json, finish_reason = call_openrouter(
            model_name,
            api_key,
            prompt,
            max_output_tokens=tokens,
            reasoning_effort=effort,
        )
        try:
            cues_lines = cues_json_to_lines(cues_json)
            return cues_json, cues_lines, tokens, finish_reason, idx > 0, effort
        except Exception as exc:
            last_exc = exc
            if finish_reason == "length" and idx + 1 < len(attempts):
                continue
            raise

    if last_exc:
        raise last_exc
    raise ValueError("No se pudo generar cues.")


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

    transcript_path = Path(args.transcript_file)
    if not transcript_path.exists():
        print(f"[ERROR] No existe el archivo: {transcript_path}", file=sys.stderr)
        return 1

    transcript_text = transcript_path.read_text(encoding="utf-8")
    prompt = build_prompt(transcript_text)
    used_tokens = 3000
    finish_reason: str | None = None
    retried = False
    used_effort = "low"

    try:
        cues_json, cues_lines, used_tokens, finish_reason, retried, used_effort = generate_cues_with_retry(
            model_name, api_key, prompt
        )
    except Exception as exc:
        print(f"[ERROR] Fallo inesperado: {exc}", file=sys.stderr)
        return 99

    output_path = Path(args.output) if args.output else default_output_path(transcript_path)
    response_path = default_response_path(transcript_path)
    lines_path = default_lines_path(transcript_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(cues_json + "\n", encoding="utf-8")
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(cues_json + "\n", encoding="utf-8")
    lines_path.parent.mkdir(parents=True, exist_ok=True)
    lines_path.write_text(cues_lines + "\n", encoding="utf-8")

    print(cues_json)
    print(
        (
            f"[INFO] CUEs finish_reason: {finish_reason} "
            f"(max_output_tokens usado: {used_tokens}, reasoning.effort: {used_effort})"
        ),
        file=sys.stderr,
    )
    if retried:
        print("[INFO] CUEs reintentados por salida truncada.", file=sys.stderr)
    print(f"\nCUEs guardados en: {output_path}")
    print(f"Respuesta completa guardada en: {response_path}")
    print(f"CUEs por linea guardados en: {lines_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
