"""Tooling records and tool schemas for intent capture."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IntentRecord:
    file: str
    symbol: str
    why: str
    property: str
    domain: str


def record_intent(
    file: str, symbol: str, why: str, property: str, domain: str
) -> dict[str, str]:
    return asdict(IntentRecord(file=file, symbol=symbol, why=why, property=property, domain=domain))


READ_TOOL_SCHEMA = {
    "name": "read",
    "description": "Read file contents. Fixture copied under MIT from tau. ORIGIN_SHA=<ORIGIN_SHA>.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    },
}

WRITE_TOOL_SCHEMA = {
    "name": "write",
    "description": "Write file contents. Fixture copied under MIT from tau. ORIGIN_SHA=<ORIGIN_SHA>.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
}

EDIT_TOOL_SCHEMA = {
    "name": "edit",
    "description": "Edit file contents via text replacements. Fixture copied under MIT from tau. ORIGIN_SHA=<ORIGIN_SHA>.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "oldText": {"type": "string"},
                        "newText": {"type": "string"},
                    },
                    "required": ["oldText", "newText"],
                },
            },
        },
        "required": ["path", "edits"],
    },
}

BASH_TOOL_SCHEMA = {
    "name": "bash",
    "description": "Run shell commands (may write files). Fixture copied under MIT from tau. ORIGIN_SHA=<ORIGIN_SHA>.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
        "required": ["command"],
    },
}
