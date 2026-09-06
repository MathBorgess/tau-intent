"""One binary, four flags. Arms A/B/C are combinations, not branches."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from tau_intent.supervisor import Flags, run_task

# Owner sets temperature=0 on the provider they expose. This binary does not
# send seed. If a future HTTP transport is used, stamp and test the body.


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tau-intent",
        description=(
            "Intent-history mechanism around tau. "
            "A: --no-capture --no-gate --no-project --no-serve; "
            "B: --capture --gate --project --serve --no-llm-rescue; "
            "C: --capture --gate --project --serve --llm-rescue. "
            "Owner sets temperature 0 on the provider they expose."
        ),
    )
    parser.add_argument("--capture", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--gate", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--project", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--serve", action=argparse.BooleanOptionalAction, default=False)
    # The four mechanism flags above are the ones AGENTS.md pins. --llm-rescue
    # is not a fifth mechanism stage: it is arm C's single knob (H16/H17),
    # read here and passed through to the projection config.
    parser.add_argument(
        "--llm-rescue",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Arm C only: summarise the selected block after the budget cut.",
    )
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--prompt", default="implement the task")
    parser.add_argument("--task-id", default="task")
    parser.add_argument("--modelo-produtor")
    parser.add_argument("--modelo-consumidor")
    parser.add_argument("--manifest", type=Path, help="Write the execution manifest as JSON")
    parser.add_argument("--max-productive-turns", type=int, default=8)
    parser.add_argument(
        "--fake-provider",
        action="store_true",
        help="Run the canned fake-provider demo (no API key, no network).",
    )
    parser.add_argument(
        "--arm",
        choices=("A", "B", "C"),
        default=None,
        help="Convenience alias that only reads flags; not used elsewhere.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def flags_from_args(args: argparse.Namespace | list[str] | None = None) -> Flags:
    if not isinstance(args, argparse.Namespace):
        args = parse_args(args)
    capture, gate, project, serve = args.capture, args.gate, args.project, args.serve
    rescue = getattr(args, "llm_rescue", None)
    # H16: B and C both project. C is B plus llm_rescue, and that is the whole
    # difference between them. The pre-H16 mapping (B served the entire current
    # store with no budget) measured a design that was revoked (D1).
    if args.arm == "A":
        capture, gate, project, serve = False, False, False, False
        rescue = False if rescue is None else rescue
    elif args.arm == "B":
        capture, gate, project, serve = True, True, True, True
        rescue = False if rescue is None else rescue
    elif args.arm == "C":
        capture, gate, project, serve = True, True, True, True
        rescue = True if rescue is None else rescue
    return Flags(
        capture=capture,
        gate=gate,
        project=project,
        serve=serve,
        llm_rescue=bool(rescue),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    flags = flags_from_args(args)
    harness = None
    diff: str | None = None
    symbols: set[str] | None = None
    summarizer = None
    if flags.llm_rescue and args.fake_provider:
        from tau_intent.rescue import sumarizador_falso

        summarizer = sumarizador_falso()
    if args.fake_provider:
        from tau_intent.fake_provider import FakeHarness, passing_script

        harness = FakeHarness(passing_script(), max_turns=None)
        diff = (
            "diff --git a/src/mod.py b/src/mod.py\n"
            "--- a/src/mod.py\n"
            "+++ b/src/mod.py\n"
            "@@ -1,0 +1,2 @@\n"
            "+def f():\n"
            "+    return 1\n"
        )
        symbols = {"f", "int"}
    result = asyncio.run(
        run_task(
            args.workspace,
            flags,
            prompt=args.prompt,
            task_id=args.task_id,
            max_productive_turns=args.max_productive_turns,
            harness=harness,
            diff=diff,
            symbols=symbols,
            summarizer_fn=summarizer,
            modelo_produtor=args.modelo_produtor,
            modelo_consumidor=args.modelo_consumidor,
        )
    )
    if args.manifest is not None:
        import json
        args.manifest.write_text(json.dumps(result.manifest, ensure_ascii=False, indent=2) + "\n")
    print(
        f"verdict={result.verdict} productive={result.productive_turns} "
        f"blocks={result.block_turns} capture={flags.capture} gate={flags.gate} "
        f"project={flags.project} serve={flags.serve}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
