"""Trusted checkpoint evidence, never populated from record_intent arguments.

The runner supplies validation output and an explicit continuation-state stamp.
Absence remains absence; a successful validation does not imply task completion.
"""
from __future__ import annotations
from dataclasses import dataclass

CONTINUATION_STATES = ('needs completion', 'already solved, preserve', 'behavior broken')


@dataclass(frozen=True)
class ValidationEvidence:
    command: str
    evidence: str


@dataclass(frozen=True)
class Checkpoint:
    changed_targets: tuple[str, ...]
    non_target_artifacts: tuple[str, ...] = ()
    latest_validation_command: str | None = None
    latest_validation_evidence: str | None = None
    continuation_state: str | None = None

    def __post_init__(self):
        if self.continuation_state is not None and self.continuation_state not in CONTINUATION_STATES:
            raise ValueError('continuation_state must be explicitly stamped from the declared vocabulary')
        if (self.latest_validation_command is None) != (self.latest_validation_evidence is None):
            raise ValueError('validation command and evidence travel together')

    @classmethod
    def observe(cls, effects, *, non_target_artifacts=(), validation=None, continuation_state=None):
        return cls(tuple(sorted({e.node_id() for e in effects})),
                   tuple(non_target_artifacts),
                   validation.command if validation else None,
                   validation.evidence if validation else None,
                   continuation_state)

    @classmethod
    def from_dict(cls, data):
        return cls(tuple(data['changed_targets']), tuple(data.get('non_target_artifacts', ())),
                   data.get('latest_validation_command'), data.get('latest_validation_evidence'),
                   data.get('continuation_state'))
