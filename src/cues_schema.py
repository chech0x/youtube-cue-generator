import json

CUES_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cues": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["cues"],
}

CUES_RESPONSE_JSON_SCHEMA = {
    "name": "cues_response",
    "strict": True,
    "schema": CUES_OUTPUT_SCHEMA,
}


def cues_output_schema_pretty_json() -> str:
    return json.dumps(CUES_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
