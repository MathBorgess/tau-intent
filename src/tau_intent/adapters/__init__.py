"""Static, lazy adapter registry: no discovery, network or runtime dependency."""
from __future__ import annotations
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol


class Adapter(Protocol):
    name: str
    version: str
    size_unit: str
    edge_types: tuple[str, ...]

    def effects(self, workspace: Any, supplied: Any = None) -> list: ...
    def collect(self, events: list, effects: list, workspace: Any) -> dict: ...
    def identities(self, effects: list, workspace: Any) -> set[str]: ...
    def anchor(self, pending: Any, workspace: Any) -> Any: ...
    def neighbourhood(self, workspace: Any) -> Any: ...
    def oracle(self, check: Any) -> bool: ...
    def classification(self, effect: Any) -> str: ...


@dataclass(frozen=True)
class Registration:
    module: str
    factory: str
    anchor_format: str


REGISTRY = {
    "code": Registration("tau_intent.adapters.code", "CodeAdapter",
                         r"[\w./\\%-]+::[\w.%-]+"),
}


def get_adapter(name: str, **kwargs: Any) -> Adapter:
    if name not in REGISTRY:
        raise ValueError(f"adaptador indisponível: {name}; efeito não verificável, modo degradado")
    entry = REGISTRY[name]
    return getattr(import_module(entry.module), entry.factory)(**kwargs)
