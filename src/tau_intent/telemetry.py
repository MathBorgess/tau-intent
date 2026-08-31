"""v1 local telemetry accounting."""

from __future__ import annotations


def _count_whitespace_tokens(text: str) -> int:
    return len(text.split()) if text else 0


def build_telemetry(*, total_turns: int, productive_turns: int, gate_block_turns: int, prompt_text: str = "", completion_text: str = "") -> dict[str, object]:
    """Build v1 telemetry with local whitespace token accounting."""
    cobertura_efetiva = 0.0
    if total_turns > 0:
        cobertura_efetiva = productive_turns / total_turns

    input_tokens_local = _count_whitespace_tokens(prompt_text)
    output_tokens_local = _count_whitespace_tokens(completion_text)

    return {
        "cobertura_efetiva": cobertura_efetiva,
        "gate_block_turns": gate_block_turns,
        "tokenizer": "whitespace-v1",
        "input_tokens_local": input_tokens_local,
        "output_tokens_local": output_tokens_local,
        "total_tokens_local": input_tokens_local + output_tokens_local,
    }
