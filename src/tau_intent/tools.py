"""Tool catalog around tau. Schemas copied from huggingface/tau at ORIGIN_SHA (MIT).

Do not depend on tau_coding. Descriptions are experimental fixtures.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

# huggingface/tau @ 0a67734 (tau-ai 0.4.1). Copy of read/write/edit/bash schemas only.
ORIGIN_SHA = "0a67734fe4c89821c652c02fe74c1e0434fd36f6"

READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file to read"},
        "offset": {"type": "integer", "description": "Line number to start reading from"},
        "limit": {"type": "integer", "description": "Maximum number of lines to read"},
    },
    "required": ["path"],
}

WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file to write"},
        "content": {"type": "string", "description": "Content to write to the file"},
    },
    "required": ["path", "content"],
}

EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the file to edit"},
        "edits": {
            "type": "array",
            "description": "One or more targeted replacements.",
            "items": {
                "type": "object",
                "properties": {
                    "oldText": {"type": "string"},
                    "newText": {"type": "string"},
                },
                "required": ["oldText", "newText"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["path", "edits"],
    "additionalProperties": False,
}

BASH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Bash command to execute"},
        "description": {
            "type": "string",
            "description": (
                "Brief present-participle summary of the command's purpose, such as "
                "'Running tests' or 'Validating and committing changes'"
            ),
        },
        "timeout": {
            "type": "number",
            "description": "Timeout in seconds (optional, no default timeout)",
        },
    },
    "required": ["command", "description"],
}

RECORD_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "description": "Path of the file this intent anchors to."},
        "files": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "All files this increment spans. Use when one decision crosses "
                "files (AtomicCommitBench: 59.5% of commits). file still works "
                "for the single-file case; either file or files is required."
            ),
        },
        "symbol": {
            "type": "string",
            "description": (
                "Optional scope: name of the def/class this call claims, exactly "
                "as written in the file, resolved against the AST. When set, only "
                "hunks of that symbol receive this why (accidental-claim guard). "
                "Omit it so one why covers every hunk of the listed files — "
                "several defs, one subject. Labels such as fix/refactor live in "
                "why, not here."
            ),
        },
        "why": {
            "type": "string",
            "description": (
                "Why this code exists this way. The subject of the increment, "
                "including any label (fix, refactor, feat) that distinguishes "
                "this decision from another in the same file."
            ),
        },
        "property": {
            "type": "string", "description": "Pre/post-condition this increment assumes or establishes.",
        },
        "domain": {
            "type": "string",
            "description": "Domain concept this increment embodies. Required in practice.",
        },
    },
    "required": ["why"],
}


def _origin_doc(name: str, body: str) -> str:
    return f"{body}\n\nORIGIN_SHA={ORIGIN_SHA} (MIT, huggingface/tau {name} schema)."


READ_DESCRIPTION = _origin_doc(
    "read",
    "Read the contents of a file. Supports text files and images "
    "(jpg, png, gif, webp, bmp). Use offset/limit for large files.",
)
WRITE_DESCRIPTION = _origin_doc(
    "write",
    "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
    "Automatically creates parent directories. Argument name is path, not file_path.",
)
EDIT_DESCRIPTION = _origin_doc(
    "edit",
    "Edit a single file using exact text replacement. Every edits[].oldText must match "
    "a unique, non-overlapping region of the original file. Argument name is path, not file_path.",
)
BASH_DESCRIPTION = _origin_doc(
    "bash",
    "Execute a bash command in the current working directory. Returns stdout and stderr. "
    "Bash can write files; those regions still need intent.",
)


RECORD_INTENT_DESCRIPTION = (
    "Registra a intenção deste incremento. Chame antes de encerrar o turno. "
    "why é o assunto (fix/refactor/feat distinguem decisões). "
    "symbol, se preenchido, restringe a chamada àquele def — omita para "
    "cobrir vários defs do mesmo arquivo com o mesmo why. "
    "domain é o conceito de domínio. "
    "Se a decisão atravessa arquivos, passe files: [..]."
)


async def record_intent(
    file: str = "",
    symbol: str = "",
    why: str = "",
    property: str = "",
    domain: str = "",
    files: list[str] | None = None,
) -> dict[str, Any]:
    """Registra a intenção deste incremento. Chame antes de encerrar o turno.

    why:      assunto deste incremento; um rótulo (fix/refactor/feat) distingue decisões
    property: pré/pós-condição — why iguais com property diferentes são duas entradas
    domain:   que conceito do domínio ele encarna
    files:    arquivos que a decisão atravessa; file continua válido sozinho
    symbol:   escopo opcional; omitido, o why cobre todos os hunks listados
    """
    ancoras = list(files or [])
    if file and file not in ancoras:
        ancoras.insert(0, file)
    primaria = ancoras[0] if ancoras else file
    return {"ok": True, "anchor": f"{primaria}::{symbol}" if symbol else primaria or ",".join(ancoras)}


def _stub_execute(name: str) -> Callable[..., Any]:
    async def execute(
        tool_call_id: str,
        arguments: Mapping[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> dict[str, Any]:
        del tool_call_id, signal, on_update
        return {"ok": True, "tool": name, "args": dict(arguments)}

    execute.__name__ = f"execute_{name}"
    execute.__doc__ = _origin_doc(name, f"Stub executor for {name}.")
    return execute


def _record_intent_execute():
    async def execute(
        tool_call_id: str,
        arguments: Mapping[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> dict[str, Any]:
        del tool_call_id, signal, on_update
        return await record_intent(
            file=str(arguments.get("file") or ""),
            symbol=str(arguments.get("symbol") or ""),
            why=str(arguments.get("why") or ""),
            property=str(arguments.get("property") or ""),
            domain=str(arguments.get("domain") or ""),
            files=list(arguments["files"]) if isinstance(arguments.get("files"), list) else None,
        )

    return execute


def tool_specs(*, capture: bool) -> list[dict[str, Any]]:
    """Return the v1 catalog. B/C (capture=True) include record_intent; A does not."""
    specs = [
        {
            "name": "read",
            "description": READ_DESCRIPTION,
            "parameters": READ_SCHEMA,
            "execute_fn": _stub_execute("read"),
        },
        {
            "name": "write",
            "description": WRITE_DESCRIPTION,
            "parameters": WRITE_SCHEMA,
            "execute_fn": _stub_execute("write"),
        },
        {
            "name": "edit",
            "description": EDIT_DESCRIPTION,
            "parameters": EDIT_SCHEMA,
            "execute_fn": _stub_execute("edit"),
        },
        {
            "name": "bash",
            "description": BASH_DESCRIPTION,
            "parameters": BASH_SCHEMA,
            "execute_fn": _stub_execute("bash"),
        },
    ]
    if capture:
        specs.append(
            {
                "name": "record_intent",
                "description": RECORD_INTENT_DESCRIPTION,
                "parameters": RECORD_INTENT_SCHEMA,
                "execute_fn": _record_intent_execute(),
            }
        )
    return specs


WRITE_TOOL_SCHEMA = {
    "name": "write",
    "description": WRITE_DESCRIPTION,
    "parameters": WRITE_SCHEMA,
}
READ_TOOL_SCHEMA = {
    "name": "read",
    "description": READ_DESCRIPTION,
    "parameters": READ_SCHEMA,
}
EDIT_TOOL_SCHEMA = {
    "name": "edit",
    "description": EDIT_DESCRIPTION,
    "parameters": EDIT_SCHEMA,
}
BASH_TOOL_SCHEMA = {
    "name": "bash",
    "description": BASH_DESCRIPTION,
    "parameters": BASH_SCHEMA,
}
CATALOG = {
    "read": type("Schema", (), {"parameters": READ_SCHEMA})(),
    "write": type("Schema", (), {"parameters": WRITE_SCHEMA})(),
    "edit": type("Schema", (), {"parameters": EDIT_SCHEMA})(),
    "bash": type("Schema", (), {"parameters": BASH_SCHEMA})(),
}


def catalog(*, capture: bool) -> list[Any]:
    """AgentTool list when tau_agent is importable, else plain spec dicts."""
    specs = tool_specs(capture=capture)
    try:
        from tau_agent.tools import AgentTool
    except ImportError:
        return specs
    return [
        AgentTool(
            name=spec["name"],
            label=spec["name"],
            description=spec["description"],
            parameters=spec["parameters"],
            execute_fn=spec["execute_fn"],
        )
        for spec in specs
    ]
