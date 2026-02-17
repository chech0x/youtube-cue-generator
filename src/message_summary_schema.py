import json

SUMMARY_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary_points": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["summary_points"],
}

SUMMARY_RESPONSE_JSON_SCHEMA = {
    "name": "message_summary_response",
    "strict": True,
    "schema": SUMMARY_OUTPUT_SCHEMA,
}


def summary_output_schema_pretty_json() -> str:
    return json.dumps(SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
