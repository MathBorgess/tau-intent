"""tau-intent CLI with independent capture/gate/project/serve flags."""

from __future__ import annotations

import argparse
from pathlib import Path

from .supervisor import Flags, run_supervisor


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="tau-intent")
    parser.add_argument("--capture", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--gate", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--project", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--serve", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--repo", default=str(Path.cwd()))
    parser.add_argument("--intents", default="intents.jsonl")
    parser.add_argument("--max-productive-turns", type=int, default=1)
    return parser.parse_args(argv)


def run_with_provider(provider, argv=None):
    args = parse_args(argv)
    return run_supervisor(
        provider=provider,
        flags=Flags(capture=args.capture, gate=args.gate, project=args.project, serve=args.serve),
        repo_path=args.repo,
        intents_path=args.intents,
        max_productive_turns=args.max_productive_turns,
    )


def main(argv=None):
    parse_args(argv)
    raise SystemExit(
        "No default provider wired in v1. Use tau_intent.cli.run_with_provider(...). "
        "Owner configures provider temperature=0."
    )
