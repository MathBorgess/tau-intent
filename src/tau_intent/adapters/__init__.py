"""Static, lazy adapter registry: no discovery, network or runtime dependency."""
from __future__ import annotations
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol


class Effect(Protocol):
    resolver: str | None
    size_unit: str
    size: int

    def key(self) -> tuple: ...
    def node_id(self) -> str: ...


class AnchoredIdentity(Protocol):
    def node_id(self) -> str: ...
    def overlaps(self, other: Any) -> bool: ...


class Adapter(Protocol):
    name: str
    version: str
    size_unit: str
    edge_types: tuple[str, ...]

    def effects(self, workspace: Any, supplied: Any = None) -> list[Effect]: ...
    def collect(self, events: list, effects: list, workspace: Any) -> dict: ...
    def identities(self, effects: list, workspace: Any) -> set[str]: ...
    def anchor(self, pending: Any, workspace: Any) -> AnchoredIdentity: ...
    def neighbourhood(self, workspace: Any) -> Any: ...
    def oracle(self, check: Any) -> bool: ...
    def classification(self, effect: Any) -> str: ...


@dataclass(frozen=True)
class Registration:
    module: str
    factory: str
    anchor_format: str


REGISTRY = {
    "state": Registration("tau_intent.adapters.state", "StateAdapter",
                          r"state://[\w.%-]+::[\w.%-]+"),
    "code": Registration("tau_intent.adapters.code", "CodeAdapter",
                         r"[\w./\\%-]+::[\w.%-]+"),
}


def get_adapter(name: str, **kwargs: Any) -> Adapter:
    if name not in REGISTRY:
        return UnavailableSubstrate(name)
    entry = REGISTRY[name]
    return getattr(import_module(entry.module), entry.factory)(**kwargs)


def anchor_from_dict(data):
    if set(data) == {"namespace", "chave", "value_hash"}:
        from tau_intent.adapters.state import StateAnchor
        return StateAnchor(**data)
    from tau_intent.model import Anchor
    return Anchor(**data)


class UnavailableSubstrate:
    """Declared degraded mode, deliberately absent from the adapter registry.

    No independently observable effects means no captured evidence, no oracle
    and no measurable gate verdict. Self-report is never promoted to a witness.
    """
    version = 'unavailable'
    size_unit = 'unknown'
    edge_types = ()
    observable = False

    def __init__(self, name):
        self.name = name

    def effects(self, workspace, supplied=None):
        return []

    def collect(self, events, effects, workspace):
        return {}

    def identities(self, effects, workspace):
        return set()

    def anchor(self, pending, workspace):
        raise ValueError('no independent anchor witness')

    def neighbourhood(self, workspace):
        from tau_intent.neighbourhood import Graph
        return Graph()

    def oracle(self, check):
        raise ValueError('no independent oracle')

    def classification(self, effect):
        return 'unknown'
