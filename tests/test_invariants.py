"""The Memory Checks guarantees, stated precisely and checked on the REAL code.

Each property below is checked by Hypothesis against the actual implementation on hundreds of
generated inputs (texts, sources, value formats, users, faults, tamperings). This is the
executable form of the defence's claims: it constrains the code that runs, not a model of it.

  I1  No elevation        nothing from an untrusted source ever becomes usable for a risky decision,
                          whatever its wording or a forged signature
  I2  Trust only falls    a derived memory (summary) is never more trusted than its least-trusted
                          parent, and a summary is never itself an authority
  I3  Erasure complete    after "forget X" no copy of X survives in any form it was written in
                          (case, spacing, separators, Devanagari digits), it never reaches the
                          prompt, and no later non-user write can bring it back
  I4  Isolation           one user's memory never surfaces for another, even with the planted
                          shared-index bug switched on underneath
  I5  Fail closed         whatever fault the decision path raises, the risky action is refused
  I6  Tamper evidence     any edit, insertion or removal in the write log is detected; a forged
                          entry computed without the key is rejected; with a trusted head, cutting
                          records off the end is detected too
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_BASE_URL", "mock")
os.environ.setdefault("EMBED_MODEL", "hash")

import hashlib

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from memorychecks.checks import MemoryChecks, sign
from memorychecks.store import DEFAULT_BUGS, GLOBAL, MemoryStore

FAST = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
NONE_PLANTED = {k: False for k in DEFAULT_BUGS}

texts = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1, max_size=160)
untrusted_sources = st.one_of(st.sampled_from(["citizen", "document", "web", "agent"]),
                              st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12))
belief_types = st.sampled_from(["personal_fact", "preference", "world_fact", "policy", "instruction",
                                "conversation", "summary", "document"])
users = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=10).filter(lambda u: u != GLOBAL)
WORDS = ["kesar", "haldi", "jamun", "rasgulla", "imli", "elaichi", "chikoo", "mosambi"]
codes = st.builds(lambda w, d: f"{w}-{d}", st.sampled_from(WORDS), st.integers(1000, 9999))
phones = st.integers(6_000_000_000, 9_999_999_999).map(str)
DEVANAGARI = str.maketrans("0123456789", "०१२३४५६७८९")


def _on(bugs=None) -> MemoryStore:
    return MemoryStore(MemoryChecks.from_spec("on"), dict(NONE_PLANTED if bugs is None else bugs))


# ----------------------------------------------------------------------------- I1
@FAST
@given(src=untrusted_sources, btype=belief_types, text=texts,
       forged=st.one_of(st.none(), st.text(max_size=64)))
def test_I1_untrusted_never_authorises(src, btype, text, forged):
    store = _on()
    meta = {"signature": forged} if forged is not None else {}
    iid = store.add("u", text, src, btype, meta=meta)
    if iid is not None:
        assert not store.checks.usable_for_action(store.items[iid])
    assert all(p.source == "admin_signed" for p in store.policies())


@FAST
@given(text=texts, sig=st.text(min_size=1, max_size=64))
def test_I1_forged_operator_signature_is_not_authority(text, sig):
    assume(sig != sign(text))
    store = _on()
    store.add(GLOBAL, text, "admin_signed", "policy", meta={"signature": sig})
    assert store.policies() == []


# ----------------------------------------------------------------------------- I2
STORED_AS = {"admin_signed": "world_fact", "citizen": "personal_fact", "document": "world_fact", "web": "world_fact"}


@FAST
@given(srcs=st.lists(st.sampled_from(sorted(STORED_AS)), min_size=1, max_size=6), seed=st.integers(0, 10**6))
def test_I2_trust_never_rises_through_derivation(srcs, seed):
    store = _on()
    ids = []
    for i, s in enumerate(srcs):
        text = f"note {seed}-{i} about pincode 5600{i:02d}"
        meta = {"signature": sign(text)} if s == "admin_signed" else {}
        iid = store.add("u", text, s, STORED_AS[s], meta=meta)
        if iid is not None:
            ids.append(iid)
    assume(ids)
    d = store.add("u", f"summary {seed}", "agent", "summary", parents=tuple(ids))
    assert d is not None
    derived = store.items[d]
    assert derived.trust <= min(store.items[i].trust for i in ids)
    assert not store.checks.usable_for_action(derived)


# ----------------------------------------------------------------------------- I3
def _written_forms(value: str, how: str) -> str:
    if value[0].isalpha():                                  # a code word-1234
        return {"plain": value, "upper": value.upper(), "spaced": value.replace("-", " - "),
                "devanagari": value.translate(DEVANAGARI)}[how]
    return {"plain": value, "upper": value, "spaced": f"{value[:5]} {value[5:]}",
            "devanagari": value.translate(DEVANAGARI)}[how]


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(value=st.one_of(codes, phones), how=st.sampled_from(["plain", "upper", "spaced", "devanagari"]),
       relative=st.sampled_from(["Raghu", "Suresh", "Imran", "Joseph"]))
def test_I3_erasure_leaves_no_copy_in_any_form(value, how, relative):
    from memorychecks import GovernedMemory
    m = GovernedMemory(mode="on")
    written = _written_forms(value, how)
    m.write("u", f"Please note my code is {written}.", source="user")
    m.write("u", f"Yesterday I gave {relative} the number {written} at the counter.", source="user")
    r = m.erase("u", f"please forget {value}")
    assert r["residue"] == 0, r["where"]
    assert m.scan("u", [written]) == m.scan("u", [value])               # every form, one fingerprint
    assert sum(m.scan("u", [value]).values()) == 0
    prompt = m.read("u", f"what number did I give {relative}?").prompt
    assert written not in prompt and value not in prompt
    for src in ("agent", "web", "document"):                           # no back door for it
        m.write("u", f"(restored) code {written}", source=src, kind="note")
    assert sum(m.scan("u", [value]).values()) == 0


# ----------------------------------------------------------------------------- I4
@FAST
@given(a=users, b=users, secret=codes, query=texts)
def test_I4_no_cross_user_retrieval_even_with_shared_index_bug(a, b, secret, query):
    assume(a != b)
    store = _on(bugs=DEFAULT_BUGS)                              # planted shared_index bug underneath
    store.add(a, f"my code word is {secret}", "citizen", "personal_fact")
    assert all(it.owner in (b, GLOBAL) for it in store.visible(b))
    assert all(it.owner != a for it in store.search(b, f"{query} {secret}", k=8))


# ----------------------------------------------------------------------------- I5
@settings(max_examples=40, deadline=None)
@given(err=st.sampled_from([RuntimeError, ValueError, TimeoutError, KeyError, ConnectionError, MemoryError]))
def test_I5_any_fault_refuses_the_risky_action(err):
    import sahayak.agents as A
    from memorychecks import GovernedMemory
    s = A.Sahayak("on")
    s.register("u", "560001")
    s.admin_policy("UIDAI circular: address proof is waived for applicants from pincode 560001.")
    real = A.llm_chat

    def boom(*a, **k):
        raise err("injected fault")
    A.llm_chat = boom
    try:
        assert s.apply("u", has_address_proof=False)["approved"] is False
    finally:
        A.llm_chat = real

    class Broken(list):
        def __iter__(self):
            raise err("injected fault")
    m = GovernedMemory(mode="on")
    assert m.allow("u", "waive", evidence=Broken()).allowed is False


# ----------------------------------------------------------------------------- I6
@FAST
@given(n=st.integers(2, 25), data=st.data())
def test_I6_any_tampering_is_detected(n, data):
    c = MemoryChecks.from_spec("on")
    for i in range(n):
        c.append_chain(f"{i}|u|citizen|personal_fact|record {i}")
    head = c.chain[-1]["hash"]
    assert c.verify_chain() and c.verify_chain(head=head)
    attack = data.draw(st.sampled_from(["edit", "drop_middle", "forge_unkeyed", "truncate"]))
    k = data.draw(st.integers(0, n - 2))
    if attack == "edit":
        field = data.draw(st.sampled_from(["payload", "hash", "prev"]))
        c.chain[k][field] = c.chain[k][field][:-1] + ("0" if c.chain[k][field][-1:] != "0" else "1")
        assert not c.verify_chain()
    elif attack == "drop_middle":
        del c.chain[k]
        assert not c.verify_chain()
    elif attack == "forge_unkeyed":   # an insider rewrites a record and recomputes with a plain hash
        prev = c.chain[k]["prev"]
        payload = "hmac:" + "f" * 32
        c.chain[k] = {"prev": prev, "payload": payload,
                      "hash": hashlib.sha256((prev + "|" + payload).encode()).hexdigest()}
        assert not c.verify_chain()
    else:                             # cut records off the end: caught against a trusted head
        del c.chain[k + 1:]
        assert not c.verify_chain(head=head)
