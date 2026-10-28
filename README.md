# 🐐 AntiGOAT: audit any AI agent's memory, and fix what the audit finds

**Team Nvindians · AEGIS 2026 (Infosys × IISc × NVIDIA) · PS4: Agent Memory Governance Evaluation**

[![tests](https://github.com/rgv-garg/antigoat/actions/workflows/ci.yml/badge.svg)](https://github.com/rgv-garg/antigoat/actions/workflows/ci.yml)
&nbsp;licence: MIT

> **Governed memory is memory an attacker can't tell apart.** If an outsider, just by talking to
> your agent, can tell what another user told it, whether it really forgot what it was asked to
> forget, or whether a planted document is steering its decisions, then its memory is not governed.
> **AntiGOAT** turns each of those promises into a statistical test you can run against any deployed
> agent. **Memory Checks** is the layer that makes the tests pass.

```mermaid
flowchart LR
  A["🐐 AntiGOAT<br/>(the auditor)"] -- "talks to it like a user<br/>(HTTP or Python)" --> G["Any agent"]
  G -- "write · read · allow · erase" --> M["🛡️ Memory Checks<br/>(the governed-memory library)"]
  M --> S[("Any memory:<br/>our store · Mem0 · LangGraph")]
  A -. "LEAK / PASS with a calibrated<br/>false-alarm rate" .-> V["verdict"]
```

The project has two halves of equal weight:

- **AntiGOAT, the auditor.** It runs a black-box audit of *your* deployed agent, not a fixed benchmark.
  Two "twin worlds" differ in one memory, and a coin per synthetic user picks the world. An adaptive,
  multilingual (English / Hindi / Hinglish) attacker talks to the agent and has to tell the worlds
  apart. An exact binomial test gives the verdict, with a **calibrated false-alarm rate**. A guess
  counts only if the agent writes the secret's real digits, so there is no judge model to fool.
  There are 12 rules: isolation, deletion, *entangled* deletion, seven query-only poisoning classes,
  an adaptive white-box attacker, and one **must-learn** rule, so a defence that blocks everything
  fails too.
- **Memory Checks, the governed-memory library.** It covers the four pillars PS4 names: provenance,
  consistency, access control and poisoning governance. It has 14 switchable checks plus **Verified
  Erasure**, which resolves "forget my name" to the value, removes it everywhere it was mentioned,
  keeps a keyed fingerprint so it cannot come back, and issues a signed receipt with residue 0. Any
  agent can use it through four calls (`write`, `read`, `allow`, `erase`), on any of three memory
  backends.

Both halves are tested against **Sahayak**, an Aadhaar help-desk agent (three sub-agents on one
shared memory, voice, Indian languages); against an independent **reference agent built on
LangGraph**; and against the unmodified **Mem0** library.

## What the audit found (real models)

Qwen3-32B and Qwen3-8B, 3 seeds, Holm-corrected at α = 0.01. Each cell is the attacker's accuracy at
telling the twin worlds apart: about 50% means nothing leaks, and bold means a significant leak. Full
tables are in [`RESULTS.md`](RESULTS.md).

| Rule (what must not happen) | Memory | Checks **off** (32B / 8B) | Checks **on** |
|---|---|---|---|
| Isolation: one user's data reaches another | Sahayak store | **88% / 88%** | 48% (chance) |
| Deletion: "forgotten" data comes back | Sahayak store | **82% / 85%** | 51% |
| Entangled deletion: "forget X" leaves X inside a story | Sahayak store | **94% / 91%** | 46% |
| Deletion | **unmodified Mem0** | **65% / 68%** | 51% |
| Entangled deletion (our earlier v2 defence: **74% / 79%**) | **unmodified Mem0** | **74% / 78%** | 51% |
| Poisoning: a fake uploaded notice flips the decision | Sahayak store | **100%** | 51% |
| Poisoning with **nothing planted** (false-alarm calibration run) | Sahayak store | **100%** | chance |
| *Must learn:* a genuine signed policy is applied | Sahayak store | 100% | **100%** (Strict mode: 52%) |

- **Beyond our own app and our own attacks.** On the public **InjecAgent** benchmark (1,054 tool-injection
  cases we did not write, success decided by code), attacks succeed **33% / 57%** (base / enhanced) on
  Qwen3-32B and **11%** on Nemotron with no defence, and **0.0%** with Memory Checks on both, while
  benign tasks finished go *up* (890 → 918 of 1,054). An independent LangGraph agent that is not Sahayak,
  audited blind over HTTP, leaks deletion and entangled deletion **99–100%** on both models, passes
  isolation (no false alarm), and holds everything once its memory goes through Memory Checks.
- **Findings we did not plant.** After `delete()`, Mem0 2.2.1's own `history()` still returns the
  deleted text, and its message buffer re-feeds it to extraction (this extends Mem0 issue
  [#7452](https://github.com/mem0ai/mem0/issues/7452)). Fact-level deletion also leaves the value
  inside other memories, on Mem0 and on LangGraph's store alike. With every planted bug switched off,
  Qwen still approves **100%** of fake-notice applications. That is a real model weakness, and the
  action gate stops it.
- **Better, not just working.** Against the same attacks, a prompt warning and a regex write filter
  both leak **100%**. An LLM-judge write filter gets to 56% but loses utility (88% of signed policy
  learned). Only Memory Checks blocks the poison **and** keeps 100% of legitimate learning. It also
  wrongly quarantines **0%** of ordinary updates.
- **Not fitted to our tests.** On a held-out run (unseen canary values, poison written in Hindi, a fresh
  seed, the defence frozen beforehand), every off-cell still leaks and every on-cell holds.

## Works with any agent, any memory, any model

| Claim | How | Evidence |
|---|---|---|
| **Any agent** | AntiGOAT needs only what a user can do: talk, ask it to forget, come back later. Describe your agent's HTTP API in a 10-line JSON file ([`targets/`](targets)), or pass a Python function. A rule that needs a capability the agent lacks is skipped and reported, never faked. | Auditing Sahayak **over HTTP as a black box gives the same numbers as in-process** (`test_black_box_http_audit_matches_in_process`). An independent [LangGraph memory agent](examples/memory_agent.py), audited blind (deterministic run): isolation **holds**, while deletion and entangled deletion **leak 100%**. With its memory routed through Memory Checks, **all hold** (`test_reference_agent_not_sahayak_found_and_fixed`). |
| **Any memory** | Memory Checks runs on three backends behind one interface: our store, **unmodified Mem0**, and **LangGraph's `BaseStore`**, which LangGraph and LangMem agents use (the in-memory and Postgres stores share its API). | The same guarantees hold on all three (`test_governed_memory_same_guarantees_on_every_backend`). On a real model with LangGraph underneath, document poisoning, authority impersonation and a delayed trigger leak **100% / 100% / 84%** with checks off and all hold with checks on ([`RESULTS.md`](RESULTS.md) §4). |
| **Any model** | It talks to any OpenAI-compatible endpoint: vLLM, NVIDIA NIM, or a hosted API. | Real runs on Qwen3-32B, Qwen3-8B and NVIDIA **Nemotron 3 Nano** (two model families). On Nemotron, isolation / deletion / entangled leak **91% / 81% / 82%** with checks off and all hold with checks on ([`RESULTS.md`](RESULTS.md) §5). An offline mock model runs CI. |

## Memory Checks: the four pillars, every mechanism measured

| Pillar | Mechanisms | Measured |
|---|---|---|
| **Provenance** | every write records its source and trust; only a signed operator source can authorise a risky decision; trust can only fall through summaries | ✅ 16/16 deterministic checks ([`docs/MEMORY_CHECKS.md`](docs/MEMORY_CHECKS.md)) |
| **Consistency** | write-time contradiction detection; conflicting values are listed on demand | ✅ |
| **Access control** | per-user walls in every agent and channel | ✅ even with a planted shared-index bug underneath |
| **Poisoning governance** | action gate (decisions and tool calls), data-fence, quarantine, source counting, slow-drip detection, leave-one-out attribution with rollback, source retraction | ✅ real-model results above |
| **Integrity & erasure** | Verified Erasure with keyed-HMAC tombstones; a keyed, tamper-evident write log; fail-closed | ✅ residue 0 in every written form |

- **Property-checked invariants** ([`tests/test_invariants.py`](tests/test_invariants.py)). Six
  guarantees are checked against the real code on hundreds of generated inputs each: no elevation,
  trust only falls, erasure is complete in every written form (case, spacing, Devanagari digits),
  isolation, fail-closed, and tamper evidence. These tests **found two real bugs**, both fixed: a
  crash on malformed signatures, and an unkeyed log digest from which short secrets could be
  brute-forced.
- **Cost:** about +0.2 ms per write (≈0.6 ms on LangGraph) and nothing measurable per read
  ([`results/latency.md`](results/latency.md)).
- **Standards:** OWASP Top 10 for LLM Apps 2025 (LLM01, 02, 04, 06, 08, 09), OWASP Agentic Security
  (memory poisoning), MITRE ATLAS, NIST AI RMF (Measure, Manage), India's DPDP Act (erasure,
  correction). The mapping is in [`docs/MEMORY_CHECKS.md`](docs/MEMORY_CHECKS.md).

## Metrics: every mechanism as a measured rate

Each row is a rate over **500 generated cases** (seeded, 95% Wilson interval), checks off vs on, so
"it works" is a number rather than an example. These measure the mechanisms themselves
(`python scripts/metrics.py`, about 6 seconds, no GPU); the real-model audit tables above measure model
behaviour. Full table: [`results/metrics.md`](results/metrics.md).

| What is measured | Checks off | Checks on |
|---|---|---|
| A user's search returns another user's data (planted shared-index bug underneath) | **97.4%** | **0.0%** (≤ 0.8%) |
| A value is still recoverable after "forget" (6 written forms incl. Devanagari digits, spelled-out names, a story) | **100%** (v2: 16.6%) | **0.0%** (≤ 0.8%) |
| A fake notice gets an application approved (5 wordings incl. Hindi) | **77.4%** | **0.0%** (≤ 0.8%) |
| A forged-signature "circular" is accepted | | **0.0%** |
| A genuine signed policy is applied (utility) | | **100%** |
| Ordinary messages wrongly quarantined / mistaken for a rule claim | | **0.0% / 0.0%** |
| Attribution finds the poison: recall / precision, incl. two redundant copies | | **100% / 100%** |
| Rollback turns the bad approval back into a reject; benign memories caught up in it | | **100%**; **0** |
| Contradictions: recall / precision / false flags on consistent memory | | **100% / 100% / 0.0%** |
| Tampering with the write log detected; untampered log verifies | | **100% / 100%** |
| Verifier fault leads to reject (fail-closed) | | **100%** |
| **The auditor:** known failures detected / LEAK verdicts where the system should hold (published real-model runs) | | **11 of 11 / 0 of 34** |

## Quick start (laptop, no GPU, no API key, about 2 minutes)

```bash
git clone https://github.com/rgv-garg/antigoat && cd antigoat
pip install -r requirements.txt -r requirements-mem0.txt
pytest -q                                   # 49 tests incl. real Mem0, LangGraph and the invariants
python scripts/governance_report.py         # the 16/16 Memory Checks table
python run_experiment.py --slots 60 --sessions 0,1 --tag try          # a full audit (mock model)
bash scripts/serve_web.sh                   # Sahayak + Memory X-ray at http://localhost:8100
```

**Audit your own agent.** Describe how to talk to it, then run the audit:

```bash
cp targets/reference_agent.json my_agent.json      # set base_url and the chat endpoint
python run_experiment.py --target my_agent.json --rules isolation,deletion,entangled
```

**Put Memory Checks in front of your agent's memory:**

```python
from memorychecks import GovernedMemory
mem = GovernedMemory()                                   # backend="ours" | "mem0" | "langgraph"
mem.write(user, "My phone is 98765 43210.", source="user")
mem.write(user, page_text, source="web")                 # a claim, never an authority
prompt = BASE_PROMPT + mem.read(user, question).prompt   # fenced: its contents are never carried out
mem.begin_turn(user, request); mem.observe(user, tool_output, source="tool")
if mem.allow_call(user, "send_email", args).allowed: ...  # risky call after untrusted input -> held
receipt = mem.erase(user, "please forget my phone number")    # Verified Erasure, signed receipt
```

**Real models:** point `.env` at any OpenAI-compatible endpoint (`bash scripts/use_env.sh open` for
local vLLM). [`docs/RUNBOOK.md`](docs/RUNBOOK.md) covers running on Brev GPUs.

## Rigor

- **Pre-registered** hypotheses, metrics and thresholds ([`PREREGISTRATION.md`](PREREGISTRATION.md)).
  Holm-Bonferroni across each family, 3 seeds, Clopper-Pearson intervals, effect sizes (Cohen's h),
  and a residual-risk upper bound when a rule holds.
- **Calibrated:** with every planted bug off, the auditor sits at chance, so it raises no false alarms.
  **Held out:** unseen values, an unseen language and a frozen defence.
- **Ablation:** switching off one check brings back exactly its leak (`python run_ablation.py`).
- **Public benchmark:** the same library on InjecAgent, 1,054 tool-injection cases we did not write:
  attack success **0.0%** (95% CI ≤ 0.4%) on both models, with no loss of benign tasks
  ([`RESULTS.md`](RESULTS.md) §2).
- **It audits us too.** On unmodified Mem0, AntiGOAT flagged a fail-open *in our own defence* (an empty
  store made audit forks default to checks-off). It is fixed and pinned by a regression test that fails on
  the old code ([`RESULTS.md`](RESULTS.md) §6).
- **Every number traced:** [`docs/EVIDENCE.md`](docs/EVIDENCE.md) maps each claim to the file and
  command that produced it.

## Honest limits

- Sahayak's own store carries four **planted** bugs, copied from published 2026 incidents. They are
  used for ablation only. The headline findings that are not planted are Mem0, LangGraph, entangled
  deletion, the calibration poisoning and the reference agent.
- Value resolution in erasure is pattern-based (plus an optional model call), so an unusual spelling
  can be missed. Tombstones and the reply guard are the second line of defence.
- The tool-call gate escalates to the user. A user who approves everything gets no protection from it.
- Auditing a black box without a no-memory endpoint lets the audit's own messages linger. That can
  only hide a leak, never fake one, so LEAK verdicts stay sound and PASS verdicts are conservative.
- ε is a simplified lower bound for balanced coins, not a full differential-privacy audit.

## Layout

| Path | What |
|---|---|
| `antigoat/` | the auditor: rules (`worlds.py`), attackers, statistics, runner, **targets** (any agent) |
| `memorychecks/` | the defence as a library: checks, Verified Erasure, three backends, governance, **`GovernedMemory`** |
| `sahayak/` | the Aadhaar reference agent (Intake, Verification, Grievance) built on Memory Checks |
| `examples/memory_agent.py` | an independent LangGraph memory agent, plain or governed |
| `targets/` | JSON descriptions of agents to audit over HTTP |
| `web/` | the live demo: Sahayak, the Memory X-ray, the governance panel, the findings page |
| `scripts/` | grids (`bigrun2.sh`, `bigrun3.sh`), the public benchmark, reports, serving |
| `tests/` | 49 tests: core, any-agent, invariants |
| `docs/` | [`EXPLAINER.md`](docs/EXPLAINER.md) (start here), [`MEMORY_CHECKS.md`](docs/MEMORY_CHECKS.md), [`EVIDENCE.md`](docs/EVIDENCE.md) |

## Credits

The coin-flip audit adapts one-run privacy auditing (Steinke, Nasr & Jagielski, NeurIPS 2023). The
public benchmark is InjecAgent (Zhan et al., Findings of ACL 2024). We tested the Mem0 and LangGraph
open-source libraries as shipped. Models: Qwen3 and NVIDIA Nemotron, served on NVIDIA GPUs through Brev.
