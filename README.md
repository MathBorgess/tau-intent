# tau-intent

Private TG artifact: an intent-history mechanism **around** Hugging Face tau, not a fork of it.

This repository is the mechanism (`capture` / `gate` / `project` / `serve`). The collider floor and the three-arm bench live in `MathBorgess/mathai-harness`. Do not merge the two.

## What a stranger needs

| | |
|---|---|
| Python | 3.12+ (tau-ai requires it) |
| Network | only to install; tests of v1 run offline against a fake provider |
| Secrets | none for the test suite |
| Tau | imported as a **pinned library** (`tau-ai==0.4.7`, extra `.[tau]`). Zero lines of tau are edited here |

## One command the committee can run

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m tau_intent.pin --check --require-installed   # V8 germ: pin intact, no local edit of tau (SKIP fails)
```

Exit code 0 on the suite means the mechanism **behaves as specified**, not that it changes a downstream outcome. That second question is the experiment, after G2.

## Arms are flags of one binary

```
A: capture=off gate=off project=off serve=off
B: capture=on  gate=on  project=on  serve=on   llm_rescue=off
C: capture=on  gate=on  project=on  serve=on   llm_rescue=on
```

A→B is a **package** (store + gate + extra tool + projected view). The isolated piece is `llm_rescue` (B×C). Do not describe A as "nothing". Do not describe B as serving the whole store.

## Bench V0 — run the arms against a local model (Gambiarra Arena)

`tau-intent bench` runs the **real** tau agent (pinned `tau-ai==0.4.7`) against the
model on your own machine, for arms A/B/C, over the task set's chain of dependent
tasks, and keeps the evolution data of the mini repository: one git commit per
task per arm. The owner decides in the arena control panel which arms you run.
Contract: [`docs/BENCH-V0-CONTRACT.md`](docs/BENCH-V0-CONTRACT.md). **V0 is
instrumentation, not measured collection:** records carry `"draft": true` and are
not a TG result before G2.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install ".[bench]"          # from a checkout of this repository (tau-ai, websockets, pytest)

# 1. start your model, with an OpenAI-compatible /v1 endpoint and tool calling
#    Ollama     http://localhost:11434/v1     (ollama pull <model>)
#    LM Studio  http://localhost:1234/v1      (start the local server)
#    llama.cpp  http://localhost:8080/v1      (llama-server --jinja ...)

# 2. join the arena (the task set is `taskset/` of mathai-harness)
tau-intent bench \
  --server ws://<arena-ip>:3000/ws --pin <PIN> \
  --participant-id <your-id> --nickname <your-name> \
  --provider-url http://localhost:11434/v1 --model <model-id> \
  --taskset <path-to>/mathai-harness/taskset --out ./bench-out
```

Leave it running: the arena sends the qualification round (Q0, plain tau, at most
two attempts) and then the bench assignment. Everything is written to
`--out/<cellId>/` first (`records.jsonl`, `cell.json`, per-arm `repo.bundle` with
one commit per task, transcripts, diffs, manifests, oracle results, the intent log
of arms B/C) and uploaded as `<cellId>.tar.gz`; if the upload fails the bundle
stays on disk and its path is printed.

What to know before you run it:

- **The agent runs shell commands on your machine** (`bash` tool, working
  directory is a temporary workspace; paths of `read`/`write`/`edit` cannot leave
  it). V0 has no sandbox beyond that: use a machine and a user you are happy to
  lend, and read the consent notice of the event.
- The model is called with `temperature=0` and the cell's `seed` **in the HTTP
  body** (checked on the wire and stamped in each manifest). One model per
  invocation; the rescue of arm C uses the same model.
- Token counts come from the endpoint's `usage`; if your runner does not return it
  in streaming responses the record says `source: "missing"` and the tokens stay
  `null`. They are never estimated. The runner probes this before the first task.
- The hidden tests are the task set's oracle; they run in a temporary directory
  outside the workspace and are never shown to the agent.

Owner's own rehearsal (E0), no server and the same records and bundle:

```bash
tau-intent bench --offline --arms A,B,C --seed 7 \
  --provider-url http://localhost:11434/v1 --model <model-id> \
  --taskset <path-to>/mathai-harness/taskset --out ./e0
# --mode qualification runs only Q0; --k-max, --deadline-s, --max-productive-turns as in bench_assign
```

## v1 scope

See [`docs/SPEC-V1.md`](docs/SPEC-V1.md) and [`AGENTS.md`](AGENTS.md). v1 slices 1–5 are on main. v1.1 is the structural gate, `files: []`, H16, and the block contract. No orchestrator adapter. No V5 labelled set in this repo (`conferir_v4_v5` only refuses a V4 report without it). No live model in CI.

Sampling note: in v1, the owner configures temperature=0 on the provider they expose.

Pre-registration of the TG is the vault file `estudos/harness-tau/2026-08-27-pre-registro.md`. **There is no `EXPERIMENTO.md` or `SPEC.md` in this repo describing another experiment.** Do not invent them.
