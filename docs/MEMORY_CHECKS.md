# Memory Checks — the governed-memory half of AntiGOAT

The project has two halves of equal weight: **AntiGOAT**, a black-box auditor that *proves* an agent
leaks, resurrects or can be poisoned; and **Memory Checks**, the governed-memory layer that *stops* it.
This document is the defence. It maps every mechanism to the four pillars the problem statement names,
and backs each one with a **measured** result, not a design claim.

Reproduce the whole table in seconds, no GPU and no API key:

```bash
LLM_BASE_URL=mock EMBED_MODEL=hash python scripts/governance_report.py   # 14/14 mechanisms
pytest -q tests/test_core.py                                            # pinned in CI
```

## The four pillars → mechanism → measured result

| Pillar | Mechanism | What it guarantees | Measured |
|---|---|---|---|
| **Provenance** | Provenance tracking | every memory carries its source + a trust rank; a document and a citizen fact are told apart | ✅ doc trust 1 < citizen trust 2 |
| **Provenance** | Trust-gated decision use | an uploaded document is **not** usable for a decision; only a signed policy is | ✅ `usable_for_decisions=False` |
| **Consistency** | Write-time contradiction log | two conflicting values for one topic are flagged at write time | ✅ 1 event logged |
| **Consistency** | Contradiction view | a citizen's conflicting memories are listed on demand | ✅ phone: two values surfaced |
| **Access control** | Cross-citizen walls | A's secret is retrievable by A, never surfaces for B | ✅ B retrieves it = False |
| **Poisoning** | Action gate | a fake notice reaches the decision context undefended, but is withheld with checks on | ✅ off = in context, on = withheld |
| **Poisoning** | Data-fence (read gate) | untrusted memory is presented to the agent as fenced **data**, never instructions | ✅ record replaced with "withheld" notice |
| **Poisoning** | Untrusted content can't become a rule | a document is never promoted to a usable official policy with checks on | ✅ usable policies off=1, **on=0** |
| **Poisoning** | Leave-one-out attribution | the exact memory that caused a bad approval is isolated by hiding memories one at a time | ✅ 1 cause isolated |
| **Poisoning** | Post-incident rollback | quarantining the culprit (and its derivatives) flips the bad decision back to safe | ✅ decision_after = reject |
| **Poisoning** | Source retraction | judging a source untrustworthy quarantines everything from it, derivatives included | ✅ quarantined on flag |
| **Integrity** | Tamper-evident write log (keyed HMAC) | the append-only log verifies and stores only keyed hashes, never plaintext | ✅ verifies, no plaintext |
| **Integrity** | Fail-closed (fault-injected) | if the verifier errors, the decision defaults to **reject** — *measured*, not just stated | ✅ reject on injected fault |
| **Erasure** | Verified Erasure (entity-level, receipt) | "forget my name" removes the value everywhere, redacts the entangled story, receipt residue 0 | ✅ residue 0, 0 copies left |

## How the mechanisms fit together

- **At write time**, every memory is labelled with its source and a trust rank (signed official > the
  citizen > an uploaded document > the web). Trust flows **down** through consolidation: a summary of an
  untrusted memory stays untrusted — it cannot be laundered into a trusted fact. A write that contradicts
  an existing value is logged as a contradiction.
- **At read time**, retrieved memory is separated from instructions: untrusted content is wrapped and
  presented as fenced **data** (the data-fence), so a poisoned memory cannot issue commands. For a
  high-stakes decision the retrieved record is withheld entirely unless it comes from a signed source
  (the action gate), and an uploaded document is never promoted to a usable policy.
- **After an incident**, a post-incident auditor attributes a bad action to the memory that caused it
  (leave-one-out: hide each memory and see which flip the outcome), then quarantines that memory and
  everything derived from it, and confirms the decision no longer stands. A whole source can be retracted
  the same way.
- **Throughout**, an append-only write log chains entries with a keyed HMAC, so tampering is detectable
  and no plaintext secret is ever stored in the log or in a receipt.
- **Erasure** is first-class: "forget X" resolves the value (including spelled-out and Hindi/Devanagari
  forms), sweeps every store (our memory, chat context, routing log, and on Mem0 the vectors + both
  history columns), redacts entangled memories, writes keyed-HMAC tombstones so the value cannot return,
  rescans, and emits a signed receipt reporting residue 0.

## What is ours alone

Two things here are not part of a standard memory-governance toolkit, and we **measure** both:

1. **Verified Erasure** — entity-level "forget X" with a signed, residue-0 receipt and keyed-HMAC
   tombstones that re-arm on every later write, retrieval and reply.
2. **The AntiGOAT audit** — an adaptive, multilingual attacker with an exact binomial test and a
   **calibrated false-alarm rate**, which found a real, *unplanted* model weakness that a fixed probe
   list misses.

## Utility — the defence does not over-block

A governance layer that refuses legitimate use is useless. We measure both sides:
- **False-quarantine of legitimate updates: 0%.** With checks on, ordinary citizen writes and updates
  (name, phone, an address change, a locker code) are all stored, none wrongly quarantined.
- **Signed policy is still learned.** A genuine signed policy remains usable for decisions — the defence
  blocks the attacks, not legitimate governance. (The `authority` rule in the audit is the formal
  counterweight: "Strict" mode, which over-blocks, fails it on purpose.)

Both are rows in the `scripts/governance_report.py` table (**16/16**), reproduced with no GPU.

## Standards & compliance mapping

Memory governance is a security-and-privacy problem, so each mechanism maps onto recognised frameworks.
This is our own analysis of where the controls land.

| Framework | Item | Our mechanism |
|---|---|---|
| **OWASP Top 10 for LLM Apps (2025)** | LLM01 Prompt Injection | data-fence (read gate), quarantine |
| | LLM02 Sensitive Information Disclosure | cross-citizen walls, Verified Erasure |
| | LLM04 Data and Model Poisoning | authority routing, action gate, source counting |
| | LLM06 Excessive Agency | action gate, fail-closed |
| | LLM08 Vector and Embedding Weaknesses | provenance + walls over the vector store (incl. Mem0) |
| | LLM09 Misinformation | write-time contradiction, trust-flows-down |
| **OWASP Agentic Security Initiative** | Memory Poisoning | the whole poisoning-governance pillar + the AntiGOAT audit |
| **MITRE ATLAS** | LLM prompt injection / poison retrieved data | data-fence, authority, action gate |
| | Adversarial evaluation of a deployed model | AntiGOAT's adaptive white-box attacker |
| **NIST AI RMF** | **Measure** function | AntiGOAT: a calibrated audit with a false-alarm rate |
| | **Manage** function | Memory Checks controls + post-incident rollback / retraction |
| **NIST AI 600-1 (GenAI profile)** | Information integrity; Data privacy | contradiction + provenance; Verified Erasure |
| **India DPDP Act, 2023** | Right to erasure | Verified Erasure reaches derived/entangled data, with a receipt |
| | Right to correction | write-time contradiction + update handling |

## Honest limitations

- Isolation/deletion/poisoning on our own store use **planted** bugs (ablation only). The non-planted
  headlines are unmodified Mem0 (entangled deletion), the held-out set, and the calibration poisoning.
- Value resolution is pattern-based plus an optional model call; an unusual way of writing a value can be
  missed — tombstones and the reply guard are the second line.
- A third memory stack (LangMem) and a generic HTTP target adapter are scoped future work; two real
  stacks (our store + unmodified Mem0) and two model sizes are done.
