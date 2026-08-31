# tau-intent

Private TG artifact: an intent-history mechanism **around** Hugging Face tau, not a fork of it.

This repository is the mechanism (`capture` / `gate` / `project` / `serve`). The collider floor and the three-arm bench live in `MathBorgess/mathai-harness`. Do not merge the two.

## What a stranger needs

| | |
|---|---|
| Python | 3.11+ |
| Network | only to install; tests of v1 run offline against a fake provider |
| Secrets | none for the test suite |
| Tau | imported as a **pinned library**. Zero lines of tau are edited here |

## One command the committee can run

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m tau_intent.pin --check   # V8 germ: pin intact, no local edit of tau
```

Exit code 0 on the suite means the mechanism **behaves as specified**, not that it changes a downstream outcome. That second question is the experiment, after G2.

## Arms are flags of one binary

```
A: capture=off gate=off project=off serve=off
B: capture=on  gate=on  project=off serve=on
C: capture=on  gate=on  project=on  serve=on
```

A→B is a **package** (store + gate + one extra tool). The isolated piece is projection (B×C). Do not describe A as "nothing".

## v1 scope

See [`docs/SPEC-V1.md`](docs/SPEC-V1.md) and [`AGENTS.md`](AGENTS.md). Five PRs. No orchestrator adapter. No V5 labelled set. No live model in CI.

Pre-registration of the TG is the vault file `estudos/harness-tau/2026-08-27-pre-registro.md`. **There is no `EXPERIMENTO.md` or `SPEC.md` in this repo describing another experiment.** Do not invent them.
