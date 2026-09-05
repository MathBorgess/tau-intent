# Task catalog — everything that can be tested, and what to expect

Every substrate the mechanism can run against, whether it is code or not, with its oracle, its dependency structure, its licence, and the effect size to expect **before** running it. Execution instructions live in `docs/RUNBOOK.md`.

Provenance is marked on every row, because half of this was read in primary source and half was not. **Nothing below may be cited in the thesis without opening the source named in the last column.**

---

## 0. The four properties that decide whether a substrate is usable

Derived in the vault, and every row is scored against them:

| Property | Why it is required |
|---|---|
| **Independent witness** | The effect must be observable without trusting the agent's report. Otherwise `AUSENTE` is unfalsifiable and capture is self-report |
| **Typed, resettable state** | Identity, overlap and size need a typed space; the measurement replica needs a fork |
| **Deterministic oracle** | Without `suite_pass` there is no `k/r`, and without `k/r` the trigger rules and the regression census have no input |
| **Dependency between tasks** | The object of the thesis. A benchmark of independent tasks measures *reuse of experience*, not *continuation of a dependent sequence* — a different claim |

**Only one substrate has all four: SWE-Milestone.** That is the finding that keeps code in the design.

---

## 1. Code — brownfield

### SWE-Milestone (primary arm)

The only substrate with an explicit dependency DAG. **98 graded tasks · 109 inter-milestone dependencies · 7 repositories · 5 languages.** Read in primary source (arXiv 2603.13428v4, Table 3, Appendix B.3).

| Repository | Language | Tasks | Deps | Δ LoC / task | Files / task | LoC per file | LoC CV |
|---|---|---|---|---|---|---|---|
| zeromicro/go-zero | Go | **23** | 25 | 278 | 10.2 | 27.3 | **1.29** |
| element-hq/element-web | TypeScript | **18** | 12 | 445 | 27.2 | 16.4 | 0.87 |
| nushell/nushell | Rust | **13** | 28 | 1268 | 63.3 | 20.0 | 1.10 |
| apache/dubbo | Java | **12** | 9 | 346 | 10.8 | 32.0 | 0.76 |
| scikit-learn/scikit-learn | **Python** | **12** | 14 | 1167 | 58.6 | 19.9 | 0.84 |
| BurntSushi/ripgrep | Rust | **11** | 12 | 134 | 5.5 | 24.4 | 0.83 |
| navidrome/navidrome | Go | **9** | 9 | 656 | 13.2 | **49.7** | 1.02 |
| **Total** | | **98** | **109** | 570 | 27.4 | 20.8 | 0.96 |

Language attribution is **inferred from project names**, not stated in the paper — it reconciles exactly with the paper's "five programming languages", which is strong but is still inference.

**Coverage today, and what each resolver unlocks.** A trajectory is one repository's DAG, so a resolver does not improve existing trajectories — it adds whole ones:

| Resolver | Trajectories | Tasks | % of 98 | Deps |
|---|---|---|---|---|
| Python (today) | 1 | 12 | 12.2% | 14 |
| + Go | 3 | 44 | 44.9% | 48 |
| + Rust | 5 | 68 | 69.4% | 88 |
| + TypeScript | 6 | 86 | 87.8% | 100 |
| + Java | 7 | **98** | 100% | 109 |

Oracle: F2P tests (17.1 avg) plus P2P regression tests (6218 avg). Deterministic. Grading is per-milestone F1 over fixed/broken tests.

**Expectation, from the paper itself:** overall scores drop from `>80%` on isolated tasks to **38.03%** in continuous settings. scikit-learn shows the largest degradation — Claude Sonnet 4.6 at **93.2% isolated → 21.1% continuous**. That drop *is* the phenomenon this thesis studies; a substrate that does not reproduce it is not measuring it.

⚠️ **Cost, from the paper:** a single full evaluation runs at ≈**US$500** with a frontier model. Budget the arm, not the task.

### Other brownfield references (not arms)

| Benchmark | Why it is here | Verdict |
|---|---|---|
| SWE-bench / SWE-bench Pro / Multi-SWE-bench | The anchor everyone knows; commit-level, ~33–246 LoC | **Reference only** — no inter-task dependency |
| SWE-CI | Chains commit-to-commit CI rounds | Closest alternative for dependency; not evaluated here |
| SlopCodeBench | Measures structural erosion and verbosity drift over a sequence | **Reference for the construct anchor** — it is where the degradation signature comes from |

---

## 2. Code — greenfield

### Commit0 (ceiling arm)

54 Python libraries written from scratch, specification and test suite already validated against the original implementation. Used as the **ceiling arm**: intent coverage ≈100% by construction, so a null there means the mechanism does not move the outcome even where conditions are ideal.

- Sliced into 10–12 dependent tasks by the CodeFlowBench method (AST dependency tree, paired test per subproblem).
- API, modules and domain vocabulary **renamed** before generating statements, to reduce training contamination.
- Reference implementation already exists — it is not written by hand.
- Python only, so the mechanism runs on it **today**, with no resolver work.

**Expectation:** this is the cheapest place to fail. If the ceiling arm is null with declared power, do not run the realistic arm.

---

## 3. Outside code

### STATE-Bench — the non-code arm (Microsoft, MIT)

**450 tasks · 3 domains — Travel 150, Customer Support 150, Shopping Assistant 150.** Pre-populated environments, user simulators, task-local sandbox database, `pass@1` averaged over **five runs per task** (an `r = 5` built into the benchmark).

- **Oracle: deterministic assertions on the resulting environment state** — whether the correct booking, refund or account update happened. This is the property that makes it usable.
- ⚠️ It **also** reports an LLM-judged "UX Score" (1–5 conversation quality), and the Agent Learning Track references a "locked judge". **Use the deterministic half; refuse the judge half**, and say so in the write-up.
- **Agent Learning Track** — 100 train trajectories per domain, 50 held-out test tasks per domain, and a retrieval hook the mechanism plugs straight into:

  ```python
  def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]
  ```

  Learning extraction is user-owned (memory store, skills library, index — anything local); retrieval is read-only; domain tools stay benchmark-controlled. Test task definitions **must not** be used as oracle inputs for extraction.

**What it measures, precisely:** whether what the mechanism captured on earlier tasks improves performance on *held-out* tasks. That is **reuse of experience**, not continuation of a dependent sequence. It is a different claim from the code arm and must be reported as such.

Provenance: repository README and `docs/AGENT_LEARNING_TRACK.md`, read via fetch — **not** the paper.

### τ²-bench (Sierra, MIT)

Conversational agents under dual control in **non-code** domains — `airline`, `retail`, `telecom`, `banking_knowledge`, `mock`. Evaluation via task schema with `evaluation_criteria.actions` and `reward_basis`.

**Tasks are independent single conversations — no dependency between them.** Useful as a clean environment for the **model-handoff** question specifically (produce under M1, serve to M2, within one task), not as a dependent-sequence substrate.

> ⚠️ **Name collision, and this project punishes that kind of error.** This package imports `tau_agent` from `tau-ai==0.4.1`, the Hugging Face harness. τ²-bench is Sierra's and is a different thing. **They are not the same `tau`.** Never imply a relationship.

### The `Handoff Debt` protocol — a method, not a substrate

arXiv:2606.02875v1, **read in primary source**. Not a task set to run against: a **protocol to copy**. Interrupt an agent at deterministic handoff points, freeze the repository, and serve successors one of four views — `repository only` · `raw trace` · `summary notes` · `structured notes`. 75 source tasks → 181 handoff-point tasks → **724 takeover runs per successor model**.

Their measured result is the reference expectation for this whole line of work:

| Successor | View | Solved | Events | Prompt tokens |
|---|---|---|---|---|
| Qwen→Qwen | Repository only | 46.4% | 99 | 1.63M |
| | Raw trace | 52.5% (+6.1 pp) | 41 (−59%) | 811k (−50%) |
| | Summary notes | 51.4% (+5.0 pp) | 53 (−46%) | 602k (**−63%**) |
| | Structured notes | 50.8% (+4.4 pp) | 55 (−44%) | 660k (−60%) |
| Qwen→Gemma | Repository only | 42.5% | 49 | 738k |
| | Raw trace | 49.2% (+6.6 pp) | 21 (−57%) | 300k (−59%) |
| | Summary notes | 44.2% (+1.7 pp) | 33 (−33%) | 319k (−57%) |
| | Structured notes | 43.6% (+1.1 pp) | 39 (−20%) | 317k (−57%) |
| Qwen→Devstral | Repository only | 34.3% | 175 | 3.94M |

Verbatim: *"context-bearing handoffs reduce median agent events by 20–59% and cumulative prompt tokens by 42–63% relative to repository-only takeover. Solved-rate effects are smaller and model-dependent, but efficiency gains are consistent."*

Their `repository only` **is this project's condition A**, measured by a third party — and they find it *"appears cheap at handoff time, but the successor pays later by repeating tests and re-deriving intent."*

### Rejected, with the reason stated

| Candidate | Rejected because |
|---|---|
| **AMA-Bench** (2602.22769) — 208 trajectories, 6 domains, 2496 QA pairs, 3.38 mean hops | Graded by **LLM-as-judge** (Qwen3-32B). Useful as a taxonomy of memory dimensions — Recall, Causal Inference, State Updating, State Abstraction — and as related work. Not an oracle |
| **LoCoMo / LongMemEval** (the Mem0 line) | Dialogue QA, LLM-as-a-Judge outcome, and the update decision is model-mediated. Related work, not architecture |
| Any conversation, negotiation, or irreversible external action | No re-observable effect ⇒ no independent witness ⇒ `AUSENTE` unfalsifiable ⇒ no measurement fork. **Declared degraded mode, never an arm** |

---

## 4. The whole catalog, scored

| Substrate | Kind | Tasks | Witness | Typed state | Oracle | Dependency | Runs today? |
|---|---|---|---|---|---|---|---|
| **SWE-Milestone** | code, brownfield | 98 (12 reachable) | git | AST | tests | **DAG, 109** | only scikit-learn |
| **Commit0** | code, greenfield | 10–12 per library | git | AST | tests | sliced by AST | **yes** |
| **STATE-Bench** | non-code | 450 (+300 train traj.) | store read | schema | **deterministic assertions** | ✗ (transfer, not sequence) | needs `state` adapter |
| **τ²-bench** | non-code | 4 domains | store read | schema | task schema | ✗ | needs `state` adapter |
| **Handoff Debt** | protocol | 181 handoff points | git | AST | tests | single interruption | reusable as method |

---

## 5. Expectations, written before running

Registered so that no result is rationalised afterwards.

- **Efficiency effects are the strong prediction.** Third-party measurement puts them at −20 to −59% events and −42 to −63% prompt tokens. That is the direction and the order of magnitude to expect.
- **Outcome effects are small and model-dependent.** +1.1 to +6.6 pp solved-rate in the reference, and one *negative* cell. A null on the outcome with an effect on cost is the **predicted** result, not a disappointment.
- **Context can hurt.** They report negative solved-rate for note-based handoff in one state. The regression census stays unconditional.
- **The ceiling arm is where to fail cheaply.** Null there with declared power means the realistic arm does not run.
- **Above the 7B class the outcome gain is not expected to return.** The registered prediction says the benefit of budgeted selection is absorbed by 7B and reverses by 14B; any model able to sustain multi-turn agentic work is above that class.
