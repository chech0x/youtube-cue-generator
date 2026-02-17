import argparse
import json
import os
import sys
from pathlib import Path

from openai import OpenAI


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
    template = '''Te pasaré una transcripción y quiero que me des los tiempos de las **secciones**:
- Bienvenida
- Alabanza
- Avisos (puede ir antes o despues de Testimonios)
- Testimonios (son testimonios de lo que ha hecho Dios en la vida de la gente y le da gracias a Dios)
- Mensaje 
  - tiempos de ideas clave (pon un título a cada idea clave)
- Ministración (tiempo de oración)
- Cumpleaños
- Despedida 

**Formato de salida obligatorio**.
Responde en JSON con estructura `{"cues": ["HH:MM:SS Titulo de CUE", "..."]}`.


"""
<TRANSCRIPCION>
"""
'''
    return template.replace("<TRANSCRIPCION>", transcript_text)


def call_openrouter(model_name: str, api_key: str, prompt: str) -> str:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    cues_schema = {
        "name": "cues_response",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cues": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["cues"],
        },
    }

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={
            "type": "json_schema",
            "json_schema": cues_schema,
        },
    )
    content = response.choices[0].message.content
    return content.strip() if content else "{}"


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

    transcript_path = Path(args.transcript_file)
    if not transcript_path.exists():
        print(f"[ERROR] No existe el archivo: {transcript_path}", file=sys.stderr)
        return 1

    transcript_text = transcript_path.read_text(encoding="utf-8")
    prompt = build_prompt(transcript_text)

    try:
        cues_json = call_openrouter(model_name, api_key, prompt)
        cues_lines = cues_json_to_lines(cues_json)
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
    print(f"\nCUEs guardados en: {output_path}")
    print(f"Respuesta completa guardada en: {response_path}")
    print(f"CUEs por linea guardados en: {lines_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
