# Responsible disclosure: Mem0 `delete()` is not durable

This folder documents a finding AntiGOAT surfaced in the **real, unmodified Mem0 library**
(`mem0ai==2.2.1`) — not in our own planted testbed. It is written up for a responsible
disclosure to the Mem0 maintainers.

## Related report (read first)
Mem0 issue **#7452** ("delete_all() leaves the scope's session messages, which are re-sent to the LLM
on the next add()") already reports the `messages` part for `delete_all()`. Its community fix, PR #7455,
was closed by a bot without review, and it deliberately leaves single `delete(memory_id)` out. So the
right move is a **comment on #7452**, not a new issue. The comment adds what #7452 doesn't cover:
1. single `delete(memory_id)` has the same `messages` residue;
2. the `history` table keeps the deleted text in **two** rows (ADD.new_memory and DELETE.old_memory), and
   Mem0's public `history(memory_id)` call returns it;
3. memories that merely *mention* a deleted value (e.g. a story containing a name) are untouched, so
   fact-level deletion can't satisfy an erasure request about a person;
4. measured behavioural resurrection (the resurrection curve below).

## How to post it (5 minutes, the only manual step)
1. Open https://github.com/mem0ai/mem0/issues/7452.
2. Paste the body below as a comment (drop the title), starting with "Adding two related cases".
3. Attach `mem0_min_repro.py` and its output from one run on Mem0's default stack.
4. Submit.

> Keep the tone as a *finding + question*, never an accusation. It reads as helpful, and it
> gives the maintainers an easy "yes/intended" or "thanks, we'll fix it."

---

## Issue title
```
delete() is not durable: deleted content persists in messages/history and can re-enter active memory
```

## Issue body
**Environment:** `mem0ai==2.2.1`, local Qdrant vector store, OpenAI extraction (also reproduced with an OpenAI-compatible local model).

**Summary**

Adding two related cases to this issue. When a memory is removed with `Memory.delete(id)`, it correctly disappears from `search()`, but the raw text is **not** removed from Mem0's internal `messages` buffer or the `history` table (both the ADD row's `new_memory` and the DELETE row's `old_memory`; `Memory.history(id)` returns both). Because that buffer is re-fed to the extraction LLM on subsequent `add()` calls, the "deleted" fact can be re-learned into active memory and becomes retrievable again. In short: deletion is not durable.

**Minimal reproduction** (attached `mem0_min_repro.py`, depends only on `mem0`):
1. `add()` a fact → `search()` finds it.
2. `delete()` the matching memory → `search()` no longer finds it. ✅
3. Query the store directly: the deleted text is still present in `history.old_memory`, `history.new_memory`, and `messages.content`.
4. `add()` a few unrelated turns → `search()` finds the "deleted" fact again.

**What we observed** (synthetic data):
- **Data at rest (deterministic, no model involved):** after `delete()`, the deleted string remained in the internal tables in **30/30** cases.
- **Resurrection (behavioral):** after continued normal use, the deleted fact became retrievable again in a clear majority of trials. In a blind two-world audit (80 scored trials/checkpoint), an auditor's ability to tell "was told then deleted" from "never told" rose from ~50% right after deletion to **78% after 1 session, 74% after 5, 80% after 10** (p ≈ 4e‑7, 1e‑5, 3e‑8). Purging the `messages`/`history` residue on delete removed the effect entirely (back to ~50%, not significant).

**Expected:** after `delete()`, the content should not remain in buffers that feed re-extraction, so a deleted fact should not reappear.

**Why it matters:** for deployments under right-to-erasure obligations (GDPR / India's DPDP), "deleted" data reappearing is a compliance and correctness problem, independent of any attacker.

**Question:** is the retention in `messages`/`history` intended (e.g. as an audit log)? If so, is there a supported way to make erasure cover those stores so deleted facts don't re-enter memory? Happy to send a PR that evicts deleted content from the message buffer on `delete()`.

---

## Getting your own output (for credibility)
Run the minimal repro once so the issue contains *your* real output, not a summary:

```bash
# Option A — Mem0's default stack (most credible for maintainers)
pip install mem0ai==2.2.1
export OPENAI_API_KEY=sk-...
python mem0_min_repro.py

# Option B — your Brev endpoint (no OpenAI key needed), run before `brev stop`
export OPENAI_API_KEY=not-needed
export OPENAI_BASE_URL=http://localhost:8000/v1
export MEM0_LLM_MODEL=nemotron-nano
python mem0_min_repro.py
```

The **data-at-rest** lines (steps 2–3) are the deterministic anchor — they need no model, so
"the model hallucinated" can't apply. That alone is the core of the finding.
