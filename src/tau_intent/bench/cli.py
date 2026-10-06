"""``tau-intent bench``: argument parsing and wiring (contract §2).

  tau-intent bench --server ws://<arena-ip>:3000/ws --pin <PIN> \\
      --participant-id <id> --nickname <name> \\
      --provider-url http://localhost:11434/v1 --model <model-id> \\
      --taskset <path> --out <dir>
  tau-intent bench --offline --arms A,B,C --seed 7 ...        # no server: E0 rehearsal

V0.2 (the event): the runner runs on the arena owner's machine, one process per
participant backend, and calls the participant's Ollama over the LAN:

  tau-intent bench --server ws://127.0.0.1:3000/ws --pin <PIN> \\
      --participant-id <backend_id> --nickname <name> --backend-id <backend_id> \\
      --provider-url http://<lan-ip>:11434/v1 --model <model-id> --runner-kind ollama \\
      --hardware-source declared [--chip ... --ram-gb ... --accel ...] \\
      --taskset <path> --out <dir-of-this-backend>

Frontier strand (offline only): the same cell over a vendor's native protocol, through
a local subscription proxy (mathai-harness ``frontier`` runs these for you):

  tau-intent bench --offline --arms A,B,C --seed 7 \\
      --provider-api anthropic-messages --provider-url http://127.0.0.1:8801 \\
      --model claude-opus-5-5 --sampling provider-default --reasoning-effort high \\
      --infra-retries 8 --taskset <path>/taskset-large --out <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets
import sys
import time
from pathlib import Path
from typing import Sequence

from tau_intent import provider_api as api_mod
from tau_intent.bench import environment
from tau_intent.bench.cell import CellError, CellSettings, validate_assign
from tau_intent.bench.client import OnlineConfig, run_offline, run_online
from tau_intent.bench.oracle import OracleError, check_runner
from tau_intent.bench.taskset import TasksetError, load_taskset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tau-intent bench",
        description="Run the real tau agent against your local model for the Gambiarra Arena bench "
                    "(arms A/B/C), or rehearse it offline.")
    arena = parser.add_argument_group("arena (online)")
    arena.add_argument("--server", help="ws://<arena-ip>:3000/ws")
    arena.add_argument("--pin", help="session PIN shown by the arena")
    arena.add_argument("--participant-id")
    arena.add_argument("--nickname")
    arena.add_argument("--once", action="store_true", help="exit after the first cell completes")
    arena.add_argument("--http-url", help="arena HTTP base for the bundle upload "
                                          "(default: the --server host and port over http)")
    model = parser.add_argument_group("model (your machine)")
    model.add_argument("--provider-url", required=True,
                       help="OpenAI-compatible base URL, e.g. http://localhost:11434/v1")
    model.add_argument("--model", required=True, help="model id as the runner names it")
    model.add_argument("--runner-kind", choices=environment.RUNNER_KINDS,
                       help="default: guessed from the port (11434 ollama, 1234 lmstudio, 8080 llamacpp)")
    model.add_argument("--api-key", default="local")
    model.add_argument("--digest", help="model digest, if your runner does not attest one (sha256:...)")
    model.add_argument("--chip", help="hardware chip; with --hardware-source declared, as declared")
    model.add_argument("--ram-gb", type=float)
    model.add_argument("--accel", choices=environment.ACCELS)
    model.add_argument("--hardware-source", choices=environment.HARDWARE_SOURCES, default="local",
                       help="local (default): read this machine. declared: never read this machine; "
                            "--chip/--ram-gb/--accel are the participant's own declaration (null allowed)")
    model.add_argument("--backend-id", help="id of the participant backend served by this process "
                                            "(stored as backend.backend_id)")
    frontier = parser.add_argument_group("frontier strand (native protocols through a local proxy)")
    frontier.add_argument("--provider-api", choices=api_mod.PROVIDER_APIS, default=api_mod.OPENAI_COMPLETIONS,
                          help="wire protocol of --provider-url (default: openai-completions, the local strand)")
    frontier.add_argument("--sampling", choices=api_mod.SAMPLING_POLICIES,
                          help="stamped: temperature 0 and the seed written in every body where the protocol "
                               "has a field; provider-default: none sent, and the wire log checks it. Default "
                               "stamped for openai-completions; required for any other protocol")
    frontier.add_argument("--reasoning-effort",
                          help="provider-native depth (Anthropic output_config.effort, Codex reasoning.effort, "
                               "Gemini thinkingConfig); default: the provider's own")
    frontier.add_argument("--max-output-tokens", type=int, help="per-response cap; default: tau's for the protocol")
    frontier.add_argument("--anthropic-oauth-identity", action="store_true",
                          help="anthropic-messages only: prepend the Claude Code identity sentence some subscription "
                               "tokens require (off by default: the model sees the agent's prompt and nothing else)")
    frontier.add_argument("--model-family", help="label stored as model.family (e.g. anthropic, openai, google)")
    frontier.add_argument("--strand", help="label stored in cell.json (e.g. frontier)")
    frontier.add_argument("--infra-retries", type=int, default=0,
                          help="native protocols only: a unit lost to infrastructure (quota, credentials, "
                               "provider or proxy down) is discarded and run again from the state before it, "
                               "up to N times (default 0 = never, V0.2's rule)")
    frontier.add_argument("--infra-wait-s", type=float, default=60.0,
                          help="wait before infra retry n: min(wait * 2**(n-1), --infra-max-wait-s)")
    frontier.add_argument("--infra-max-wait-s", type=float, default=3600.0)
    work = parser.add_argument_group("work")
    work.add_argument("--taskset", required=True, type=Path, help="path to the tg-taskset-1 directory")
    work.add_argument("--out", required=True, type=Path, help="where the cell's data is kept")
    work.add_argument("--oracle-timeout-s", type=int, default=300)
    work.add_argument("--rescue-timeout-s", type=float,
                      help="timeout of the rescue call (arm C); default: rescue.yaml timeout_s")
    work.add_argument("--keep-workspaces", action="store_true")
    work.add_argument("--skip-preflight", action="store_true", help="do not probe the endpoint first")
    work.add_argument("--skip-pin-check", action="store_true", help="development only")
    off = parser.add_argument_group("offline rehearsal")
    off.add_argument("--offline", action="store_true", help="no server: run the cell locally")
    off.add_argument("--arms", default="A,B,C", help="ordered, comma separated (default A,B,C)")
    off.add_argument("--seed", type=int, default=7)
    off.add_argument("--mode", choices=("bench", "qualification"), default="bench")
    off.add_argument("--k-max", type=int, default=1000, help="tasks to run (default: all)")
    off.add_argument("--deadline-s", type=int, default=600)
    off.add_argument("--max-productive-turns", type=int, default=8)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.offline:
        missing = [name for name in ("server", "pin", "participant_id", "nickname")
                   if not getattr(args, name)]
        if missing:
            parser.error("online mode needs " + ", ".join("--" + m.replace("_", "-") for m in missing)
                         + " (or use --offline)")

    def log(message: str) -> None:
        print(message, flush=True)

    native = args.provider_api != api_mod.OPENAI_COMPLETIONS
    if native and args.sampling is None:
        parser.error("a native-protocol cell must declare --sampling (stamped | provider-default): "
                     "several frontier models refuse sampling fields, and the choice is the owner's")
    sampling = args.sampling or api_mod.SAMPLING_STAMPED
    if native and not args.offline:
        parser.error("--provider-api other than openai-completions runs offline only (--offline): "
                     "the arena's schemas know local runners")
    if native and args.runner_kind not in (None, "other"):
        parser.error("a native-protocol cell is not a local runner: drop --runner-kind")
    if args.anthropic_oauth_identity and args.provider_api != api_mod.ANTHROPIC_MESSAGES:
        parser.error("--anthropic-oauth-identity is for --provider-api anthropic-messages")
    if args.infra_retries and not native:
        parser.error("--infra-retries is for native-protocol cells; the local strand never retries (V0.2)")

    if not args.skip_pin_check:
        ok, text = environment.check_pin()
        if not ok:
            log(f"the pinned tau is not what is installed: {text}\n"
                "install it with: pip install 'tau-intent[bench]'")
            return 2
    try:
        taskset = load_taskset(args.taskset)
        check_runner(taskset)
    except (TasksetError, OracleError) as exc:
        log(f"cannot use the task set: {exc}")
        return 2

    kind = "other" if native else (args.runner_kind or environment.guess_runner_kind(args.provider_url))
    join = {
        "participant_id": args.participant_id or "offline",
        "runner_version": environment.runner_version(),
        "tau_intent_sha": environment.tau_intent_sha(),
        "task_set_sha": taskset.sha,
        "model": {"id": args.model,
                  "digest": args.digest or environment.model_digest(args.provider_url, args.model, kind),
                  "runner_kind": kind,
                  **({"family": args.model_family} if args.model_family else {})},
        "hardware": (environment.hardware_declared(chip=args.chip, ram_gb=args.ram_gb, accel=args.accel)
                     if args.hardware_source == "declared"
                     else environment.hardware(chip=args.chip, ram_gb=args.ram_gb, accel=args.accel)),
    }
    settings = CellSettings(
        out_dir=args.out, taskset=taskset, provider_url=args.provider_url, model=args.model,
        runner_kind=kind, participant_id=join["participant_id"], join=join,
        pin_hash=hashlib.sha256(args.pin.encode()).hexdigest() if args.pin else None,
        api_key=args.api_key, oracle_timeout_s=args.oracle_timeout_s, rescue_timeout_s=args.rescue_timeout_s,
        keep_workspaces=args.keep_workspaces, skip_preflight=args.skip_preflight,
        backend_id=args.backend_id,
        provider_api=args.provider_api, sampling=sampling, reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens, infra_retries=max(0, args.infra_retries),
        infra_wait_s=args.infra_wait_s, infra_max_wait_s=args.infra_max_wait_s, strand=args.strand,
        anthropic_oauth_identity=args.anthropic_oauth_identity)
    args.out.mkdir(parents=True, exist_ok=True)
    log(f"task set {taskset.id} {taskset.version} sha {taskset.sha[:12]} ({len(taskset.tasks)} tasks); "
        f"model {args.model} via {args.provider_api if native else kind} at "
        f"{environment.redact_host(args.provider_url, args.provider_url)}"
        + (f" (sampling {sampling}, effort {args.reasoning_effort or 'provider default'})" if native else ""))

    if args.offline:
        arms = [a.strip() for a in args.arms.split(",") if a.strip()]
        assign = {"cell_id": f"offline-{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}",
                  "mode": args.mode, "arms": ["A"] if args.mode == "qualification" else arms,
                  "seed": args.seed, "k_max": args.k_max, "deadline_s": args.deadline_s,
                  "max_productive_turns": args.max_productive_turns}
        try:
            validate_assign(assign)
            outcome = run_offline(settings, assign, log)
        except CellError as exc:
            log(f"refused [{exc.code}]: {exc}")
            return 2
        passed = sum(1 for r in outcome.records if r["oracle"]["pass"])
        log(f"cell {outcome.cell_id}: {len(outcome.records)} records, {passed} oracle passes"
            f"{', truncated' if outcome.truncated else ''}")
        log(f"data: {outcome.cell_dir}\nbundle: {outcome.bundle}")
        return 1 if outcome.fatal else 0

    cfg = OnlineConfig(server=args.server, pin=args.pin, participant_id=args.participant_id,
                       nickname=args.nickname, model=args.model, join=join, settings=settings,
                       once=args.once, log=log, http_url=args.http_url)
    try:
        return asyncio.run(run_online(cfg))
    except KeyboardInterrupt:
        log("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
