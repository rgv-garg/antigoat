# Memory Checks: the governed-memory library

The project has two halves of equal weight. **AntiGOAT** is a black-box auditor that *proves* whether
an agent leaks, resurrects deleted data or can be poisoned. **Memory Checks** is the governed-memory
layer that *stops* it. This document covers Memory Checks: how to use it in any agent, how each
mechanism maps to the four pillars PS4 names, and the measured result behind every one. These are
results, not design claims.

```bash
LLM_BASE_URL=mock EMBED_MODEL=hash python scripts/governance_report.py   # 16/16 mechanisms, no GPU
pytest -q tests/                                                        # incl. the invariants
```

## Use it in your agent

Every agent stores what it learns, loads memory into the prompt, takes actions, and (under India's
DPDP Act) must be able to forget. Route those four things through one object:

```python
from memorychecks import GovernedMemory

mem = GovernedMemory()                     # mode "on"; backend "ours" | "mem0" | "langgraph"

mem.write(user, "My phone is 98765 43210.", source="user")      # labelled with source and trust
mem.write(user, page_text, source="web")                         # a claim, never an authority
ctx = mem.read(user, question)                                   # ctx.prompt -> your system prompt
d = mem.allow(user, "waive address proof", must_mention=["address proof"])   # decision gate
receipt = mem.erase(user, "please forget my phone number")       # Verified Erasure

# tool-using agents: a risky call after reading untrusted content is held for the user
mem.begin_turn(user, request)
fenced = mem.observe(user, tool_output, source="tool")
if mem.allow_call(user, "send_email", args).allowed: ...
```

`GovernedMemory(mode="off")` is the same memory with every check switched off. Run your agent both
ways and point AntiGOAT at both to see exactly what Memory Checks changes. A worked example is
[`examples/memory_agent.py`](../examples/memory_agent.py), an independent LangGraph agent that
switches between plain and governed memory with one setting.

**Sources** and how far each is trusted: `operator` (signed; the only source that can authorise a
risky decision) > `user` > `document` / `tool` > `web` / `email`. An unknown source is treated as
`web`. **Kinds:** `fact`, `preference`, `note`, `policy`, `instruction`, `conversation`, `summary`.

**Three memory backends, one interface:**
- **ours:** our own store.
- **mem0:** unmodified Mem0 2.2.1, including its vector store, `messages` buffer and `history` table.
- **langgraph:** LangGraph's `BaseStore`, the store LangGraph and LangMem agents write to. Every read
  and write goes through its `get` / `put` / `search` / `delete` API.

The same guarantees hold on all three (`tests/test_any_agent.py`).

## The four pillars: mechanism and measured result

| Pillar | Mechanism | What it guarantees | Measured |
|---|---|---|---|
| **Provenance** | Provenance tracking | every memory carries its source and a trust rank; a document and a user's fact are told apart | ✅ document trust 1 < user trust 2 |
| **Provenance** | Trust-gated decision use | an uploaded document is **not** usable for a decision; only a signed policy is | ✅ `usable_for_decisions=False` |
| **Consistency** | Write-time contradiction log | two conflicting values for one topic are flagged at write time | ✅ 1 event logged |
| **Consistency** | Contradiction view | a user's conflicting memories are listed on demand | ✅ phone: two values surfaced |
| **Access control** | Cross-user walls | A's secret is retrievable by A and never surfaces for B | ✅ B retrieves it = False |
| **Poisoning** | Action gate | undefended, a fake notice sits in the decision's context; with checks on it is withheld | ✅ off = in context, on = withheld |
| **Poisoning** | Data-fence | retrieved memory reaches the agent inside a per-reply fence; nothing written in it is carried out | ✅ record replaced with a "withheld" notice |
| **Poisoning** | Untrusted content can't become a rule | a document is never promoted to a usable official policy with checks on | ✅ usable policies: off 1, **on 0** |
| **Poisoning** | Leave-one-out attribution | the exact memory behind a bad approval is found by hiding memories one at a time | ✅ 1 cause isolated |
| **Poisoning** | Post-incident rollback | quarantining the culprit (and its derivatives) flips the bad decision back to safe | ✅ decision afterwards = reject |
| **Poisoning** | Source retraction | judging a source untrustworthy quarantines everything from it, derivatives included | ✅ quarantined on flag |
| **Integrity** | Tamper-evident write log | keyed-HMAC digests and links: any edit, insertion or removal is detected; no plaintext is stored | ✅ verifies; no plaintext |
| **Integrity** | Fail-closed (fault-injected) | if the verifier errors, the decision defaults to **reject**, and this is measured, not just stated | ✅ reject on an injected fault |
| **Erasure** | Verified Erasure | "forget my name" removes the value everywhere, redacts the story it appears in, and the receipt shows residue 0 | ✅ residue 0, no copies left |
| **Utility** | No false quarantine | ordinary writes and updates are stored, never wrongly quarantined | ✅ 0 of 5 (0%) |
| **Utility** | Signed policy still learned | the defence blocks attacks, not legitimate governance | ✅ usable signed policies = 1 |

## How the mechanisms fit together

- **At write time**, every memory is labelled with its source and trust rank. Trust flows **down**
  through consolidation: a summary is never more trusted than its least-trusted input. A write that
  contradicts an existing value is logged, and instruction-shaped text from an untrusted source is held
  in quarantine rather than dropped. One origin pushing many claims at the same decision is treated as
  a drip attack, and independent origins are counted, not copies.
- **At read time**, only the user's own memory (and global policy) is searched. Retrieved memory is
  enclosed in a fence marked with a random tag the stored text cannot fake, and the agent is told that
  nothing inside the fence is to be carried out.
- **At decision time**, a risky decision may rest only on a source allowed to authorise it (a signed
  operator policy). For a tool call, reads pass, and a risky call in a turn that has read untrusted
  content is held for the user's confirmation. If there is no confirmer, or the check errors, the call
  is refused.
- **After an incident**, leave-one-out attribution finds the memory that caused a bad action. Rollback
  then quarantines it and everything derived from it, and re-runs the decision to confirm it no longer
  stands. A whole source can be retracted the same way.
- **Throughout**, an append-only write log chains entries with a keyed HMAC, so any edit, insertion or
  removal is detected. Checked against a trusted head (a signed receipt's `chain_head`), truncation of
  the log is detected too. No plaintext secret is ever stored in the log or in a receipt. Keys come
  from `MEMORYCHECKS_SIGNING_KEY`, and without it each process uses a random key; nothing is
  hard-coded.
- **Erasure** is first-class. "Forget X" resolves the value (including spelled-out forms, spacing,
  separators and Devanagari digits), sweeps every store (memories of every status, chat context,
  routing log, and on Mem0 the vectors plus both history columns), and redacts entangled memories. It
  then writes keyed-HMAC tombstones, which are checked on every later write, retrieval and reply, so
  the value cannot return. Finally it re-scans and issues a signed receipt that records the residue.

## Property-checked invariants

`tests/test_invariants.py` checks each guarantee against the real implementation on hundreds of
generated inputs: texts, sources, value formats, users, faults and tamperings.

| Invariant | Statement |
|---|---|
| I1 No elevation | nothing from an untrusted source ever becomes usable for a risky decision, whatever its wording or a forged signature |
| I2 Trust only falls | a derived memory is never more trusted than its least-trusted parent, and a summary is never an authority |
| I3 Erasure complete | after "forget X" no copy of X survives in any form it was written in, it never reaches the prompt, and no later non-user write can bring it back |
| I4 Isolation | one user's memory never surfaces for another, even with the planted shared-index bug underneath |
| I5 Fail closed | whatever fault the decision path raises, the risky action is refused |
| I6 Tamper evidence | any edit, insertion or removal is detected; an entry forged without the key is rejected; against a trusted head, truncation is detected |

These tests **found two bugs**, both fixed. First, signature verification crashed on a non-ASCII
"signature", so a crafted upload could crash the write path. Second, the write log used unkeyed
SHA-256: anyone with write access could re-forge it, and short secrets could be brute-forced from its
digests.

## What is ours alone

Two things here are not part of a standard memory-governance toolkit, and we **measure** both:

1. **Verified Erasure.** An entity-level "forget X" with a signed, residue-0 receipt, and keyed-HMAC
   tombstones that re-arm on every later write, retrieval and reply.
2. **The AntiGOAT audit.** An adaptive, multilingual attacker with an exact binomial test and a
   **calibrated false-alarm rate**, usable against any agent over HTTP. It found a real, *unplanted*
   model weakness that a fixed probe list misses.

## Cost

About +0.2 ms per write on our store and +0.6 ms on LangGraph, with nothing measurable per read
(`scripts/latency.py`, [`../results/latency.md`](../results/latency.md)).

## Standards and compliance mapping

Memory governance is a security and privacy problem, so each mechanism maps onto recognised
frameworks. This is our own analysis of where the controls land.

| Framework | Item | Our mechanism |
|---|---|---|
| **OWASP Top 10 for LLM Apps (2025)** | LLM01 Prompt Injection | data-fence, quarantine, tool-call gate |
| | LLM02 Sensitive Information Disclosure | cross-user walls, Verified Erasure |
| | LLM04 Data and Model Poisoning | authority routing, action gate, source counting |
| | LLM06 Excessive Agency | action gate and tool-call gate, fail-closed |
| | LLM08 Vector and Embedding Weaknesses | provenance and walls over the vector store (incl. Mem0, LangGraph) |
| | LLM09 Misinformation | write-time contradiction, trust flowing down |
| **OWASP Agentic Security Initiative** | Memory Poisoning | the whole poisoning-governance pillar, plus the AntiGOAT audit |
| **MITRE ATLAS** | LLM prompt injection; poisoned retrieved data | data-fence, authority, action gate |
| | Adversarial evaluation of a deployed model | AntiGOAT's adaptive white-box attacker |
| **NIST AI RMF** | **Measure** function | AntiGOAT: a calibrated audit with a false-alarm rate |
| | **Manage** function | Memory Checks controls, plus post-incident rollback and retraction |
| **NIST AI 600-1 (GenAI profile)** | Information integrity; data privacy | contradiction and provenance; Verified Erasure |
| **India DPDP Act, 2023** | Right to erasure | Verified Erasure reaches derived and entangled data, with a receipt |
| | Right to correction | write-time contradiction and update handling |

## Honest limitations

- Isolation, deletion and poisoning on Sahayak's own store use **planted** bugs, for ablation only.
  The headline findings that are not planted are unmodified Mem0, LangGraph's store, entangled
  deletion, the held-out set, the calibration poisoning, and the independent reference agent.
- Value resolution is pattern-based, plus an optional model call. An unusual way of writing a value
  can be missed; tombstones and the reply guard are the second line of defence.
- Provenance is not fact-checking. Two untrusted sources can still disagree, and the layer records the
  conflict rather than deciding which is true.
- The tool-call gate escalates to the user. A user who approves every request gets no protection from it.
