"""Verified Erasure - entity-level forgetting (Memory Checks v3).

Why this exists (the bug a teammate found by hand):
    "my name is Teja" -> "once Teja and Raghu had a fight at school" -> "please forget my name"
Every memory library we looked at deletes FACTS ("Citizen's name is Teja"), but privacy is
about the PERSON/VALUE. The fight story is a different fact, so it survives - and
"who had a fight with Raghu?" brings the name straight back. Deleting by topic word
("name") cannot catch it, because the story never says the word "name".

Verified Erasure works on values, not facts:
  1. resolve   turn the request ("forget my name") into the concrete values to erase
               ("Teja"), using the citizen's own memories (regex first, LLM optional).
               A value is kept only if it really occurs in their memory (no hallucination).
  2. variants  the same value as it may be written: any case, digits with spaces/dashes,
               Devanagari digits, Devanagari / Roman spelling of a name.
  3. sweep     every place text lives - memories of every status, raw chat turns,
               summaries, uploaded documents, the routing log, chat history, and (on the
               Mem0 backend) Mem0's vector payloads, `messages` buffer and `history` log.
  4. redact    an entangled memory keeps its useful part ("[erased] and Raghu had a fight");
               a memory that was only about the value is deleted.
  5. tombstone a salted HASH of each value (never the value itself) is kept, and every
               later write, retrieval and reply is checked against it - so the value can
               never be re-learned from a leftover copy we did not know about.
  6. verify    re-scan every location; the signed receipt records the per-location residue
               (all zeros) instead of a promise.

The scanner (`find`, `scan`) also runs with Checks OFF - that is the "Memory X-ray" in the
demo: same request, OFF deletes one fact and the X-ray still lights up, ON leaves nothing.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------- topics
# What a spoken forget-request is about ("forget my name" -> the name).
TOPICS: dict[str, str] = {
    "name": r"\bname\b|\bnaam\b|\bnam\b|नाम",
    "phone": r"phone|mobile|\bnumber\b|फ़ोन|फोन|मोबाइल|नंबर",
    "address": r"address|pin\s?code|\bpata\b|पता|\bhouse\b|\bghar\b",
    "code": r"\bcode\b|code\s?word|password|secret|\bpin\b|कोड",
    "email": r"e-?mail|ईमेल",
    "aadhaar": r"aadhaa?r|\buid\b|आधार",
    "birth": r"birth|\bdob\b|janam|जन्म",
    "family": r"father|mother|wife|husband|\bson\b|daughter|family|brother|sister|\bpita\b|\bmata\b|"
              r"papa|mummy|bhai|behen|पिता|माता|पत्नी|पति|भाई|बहन",
}
ALL_RE = re.compile(r"\b(everything|all|sab|sabhi|saara|sara)\b|सब", re.I)

# Values that can be pulled out of a memory's text, per topic.
_PHONE = r"(?<![\d०-९])(?:\+?91[\s-]?)?[6-9६-९][\d०-९]{4}[\s-]?[\d०-९]{5}(?![\d०-९])"
_AADHAAR = r"(?<![\d०-९])[\d०-९]{4}[\s-]?[\d०-९]{4}[\s-]?[\d०-९]{4}(?![\d०-९])"
_CODE = r"\b[a-z]+-\d{3,4}\b"
_EMAIL = r"[\w.+-]+@[\w-]+\.[\w.]+"
_PIN = r"(?<![\d०-९])[1-9][\d०-९]{5}(?![\d०-९])"
_DATE = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b"
_NUM = r"(?<![\d०-९])[\d०-९]{4,}(?![\d०-९])"

_WORD = r"[A-Za-zऀ-ॿ][A-Za-zऀ-ॿ'.]*"
# "my name is Teja", "mera naam teja hai", "मेरा नाम तेजा है", "call me Teja" (any case)
_NAME_CUES = re.compile(
    r"(?:\bname\s+is|\bname'?s|\bnaam\s+(?:hai\s+)?|\bnam\s+|नाम\s+(?:है\s+)?|\bcall\s+me|\bcalled|"
    r"\bme\s+\(|\bmyself)"
    rf"\s*[:\-]?\s*({_WORD}(?:\s+{_WORD})?)", re.I)
# weaker cues need a Capitalised word: "I am Teja", "this is Teja", "main Teja hoon"
_NAME_CUES_CAP = re.compile(
    r"(?:\b[Ii]\s+am|\b[Ii]'m|\b[Tt]his\s+is|\b[Mm]ain|\b[Mm]ai)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
# "my father Ramesh", "papa ka naam Suresh", "my brother is Raghu"
_FAMILY_CUES = re.compile(
    r"\b(?:father|mother|wife|husband|son|daughter|brother|sister|papa|mummy|bhai|behen|pita|mata)"
    rf"(?:'s name)?(?:\s+(?:is|ka naam|ki naam|named|called|hai))?\s*[:\-]?\s*({_WORD})", re.I)
_ADDRESS_CUE = re.compile(r"\b(?:address|pata|live at|live in|rehta hoon|rehti hoon)\s*(?:is|hai|:)?\s*([^.;\n]{4,60})", re.I)

# Words that are never a name value even if they follow a cue word.
_STOP = {
    "is", "a", "an", "the", "and", "from", "here", "hai", "hoon", "hu", "hun", "my", "mera", "meri", "ka",
    "ki", "ke", "to", "in", "at", "of", "for", "not", "very", "so", "also", "sure", "fine", "good", "ok",
    "okay", "sorry", "trying", "going", "looking", "calling", "applying", "new", "citizen", "user", "and",
    "raghu's", "है", "हूँ", "हूं", "का", "की", "के", "mujhe", "aap", "please", "just", "only", "back",
    "unable", "able", "with", "your", "you", "he", "she", "it", "we", "they", "this", "that", "there",
    "बहुत", "भी", "aadhaar", "applicant", "resident", "student", "farmer", "worker",
}

_VALUE_RX = {
    "phone": [_PHONE],
    "aadhaar": [_AADHAAR],
    "code": [_CODE],
    "email": [_EMAIL],
    "birth": [_DATE],
    "address": [_PIN],
}

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_BOUND_L = r"(?<![A-Za-z0-9_ऀ-ॿ])"
_BOUND_R = r"(?![A-Za-z0-9_ऀ-ॿ])"
MASK = "[erased]"


# ----------------------------------------------------------------------------- helpers
def _clean_name(raw: str) -> str:
    words = [w.strip(".,'\"()") for w in raw.split()]
    keep = []
    for w in words:
        if not w or w.lower() in _STOP:
            break
        keep.append(w)
    return " ".join(keep)


def values_in(text: str, topic: str) -> list[str]:
    """Values of `topic` that this memory text states."""
    out: list[str] = []
    for rx in _VALUE_RX.get(topic, []):
        out += [m.group(0) for m in re.finditer(rx, text, re.I)]
    if topic == "name":
        for rx in (_NAME_CUES, _NAME_CUES_CAP):
            for m in rx.finditer(text):
                v = _clean_name(m.group(1))
                if v and len(v) >= 2:
                    out.append(v)
    if topic == "family":
        for m in _FAMILY_CUES.finditer(text):
            v = _clean_name(m.group(1))
            if v and len(v) >= 2:
                out.append(v)
    if topic == "address":
        for m in _ADDRESS_CUE.finditer(text):
            v = m.group(1).strip(" ,")
            if len(v) >= 4:
                out.append(v)
    if topic == "code" and not out:
        out += [m.group(0) for m in re.finditer(_NUM, text)]
    return out


def explicit_values(request: str) -> list[str]:
    """Values the citizen spelled out in the request itself ("delete kesar-4135")."""
    vals = []
    for rx in (_CODE, _EMAIL, _PHONE, _AADHAAR, _NUM):
        vals += [m.group(0) for m in re.finditer(rx, request, re.I)]
    vals += re.findall(r"[\"“']([^\"”']{2,40})[\"”']", request)
    # de-duplicate, longest first (a phone number also matches the generic number pattern)
    seen, out = set(), []
    for v in sorted(vals, key=len, reverse=True):
        k = normalize(v)
        if k and not any(k in s for s in seen):
            seen.add(k)
            out.append(v)
    return out


def normalize(v: str) -> str:
    v = v.translate(_DEV_DIGITS).lower().strip()
    if re.fullmatch(r"[\d\s\-.+]+", v):
        return re.sub(r"\D", "", v)
    return re.sub(r"\s+", " ", v)


# A tiny Roman <-> Devanagari bridge for names (Teja <-> तेजा), so a name erased in one
# script is also found in the other. Good enough for common Indian names; the optional
# LLM resolver can add more spellings.
_DEV2ROM = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ट": "t",
    "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ं": "n", "ँ": "n", "ः": "h", "्": "", "़": "",
}
_ROM_CONS = [("chh", "छ"), ("kh", "ख"), ("gh", "घ"), ("ch", "च"), ("jh", "झ"), ("th", "थ"), ("dh", "ध"),
             ("ph", "फ"), ("bh", "भ"), ("sh", "श"), ("k", "क"), ("g", "ग"), ("j", "ज"), ("t", "त"),
             ("d", "द"), ("n", "न"), ("p", "प"), ("b", "ब"), ("m", "म"), ("y", "य"), ("r", "र"),
             ("l", "ल"), ("v", "व"), ("w", "व"), ("s", "स"), ("h", "ह"), ("f", "फ"), ("z", "ज"), ("c", "क"),
             ("q", "क"), ("x", "क्स")]
_ROM_VOW = [("aa", "आ", "ा"), ("ai", "ऐ", "ै"), ("au", "औ", "ौ"), ("ee", "ई", "ी"), ("oo", "ऊ", "ू"),
            ("a", "अ", ""), ("i", "इ", "ि"), ("u", "उ", "ु"), ("e", "ए", "े"), ("o", "ओ", "ो")]


def _dev_to_roman(s: str) -> str:
    out = []
    for i, ch in enumerate(s):
        r = _DEV2ROM.get(ch)
        if r is None:
            out.append(ch)
            continue
        out.append(r)
        # inherent 'a' after a consonant not followed by a matra/virama (only mid-word)
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if "क" <= ch <= "ह" and nxt and not ("ा" <= nxt <= "्") and nxt not in "ंँः":
            out.append("a")
    return "".join(out)


def _roman_to_dev(s: str) -> str:
    s, out, i, after_cons = s.lower(), [], 0, False
    while i < len(s):
        for rom, full, matra in _ROM_VOW:
            if s.startswith(rom, i):
                out.append(matra if after_cons else full)
                i += len(rom)
                after_cons = False
                break
        else:
            for rom, dev in _ROM_CONS:
                if s.startswith(rom, i):
                    if after_cons:
                        out.append("")  # consonant cluster: inherent vowel dropped (approx.)
                    out.append(dev)
                    i += len(rom)
                    after_cons = True
                    break
            else:
                out.append(s[i])
                i += 1
                after_cons = False
    return "".join(out)


def variants(value: str) -> list[str]:
    """Spellings of `value` to look for."""
    v = value.strip()
    out = {v}
    m = re.fullmatch(r"([a-z]+)-(\d{3,4})", v, re.I)
    if m:  # a code word: its digits are the secret part ("I told Raghu 7342")
        out.add(m.group(2))
    if re.search(r"[ऀ-ॿ]", v):
        out.add(_dev_to_roman(v))
    elif re.fullmatch(r"[A-Za-z][A-Za-z .']+", v):
        dev = _roman_to_dev(v)
        # a Roman name ending in short 'a' is written with a long aa in Hindi (Teja -> तेजा)
        out.add(dev + "ा" if v.lower().endswith("a") and not v.lower().endswith("aa") else dev)
    return [x for x in out if x]


def pattern(value: str) -> re.Pattern:
    """A regex that finds `value` (and its variants) inside any text."""
    alts = []
    for v in variants(value):
        n = normalize(v)
        if re.fullmatch(r"\d+", n):  # digits: allow separators and Devanagari digits
            dig = {"0": "[0०]", "1": "[1१]", "2": "[2२]", "3": "[3३]", "4": "[4४]", "5": "[5५]",
                   "6": "[6६]", "7": "[7७]", "8": "[8८]", "9": "[9९]"}
            body = r"[\s\-.]?".join(dig[c] for c in n)
            alts.append(rf"(?<![\d०-९]){body}(?![\d०-९])")
        else:
            body = r"\s+".join(re.escape(w) for w in v.split())
            alts.append(_BOUND_L + body + _BOUND_R)
    return re.compile("|".join(alts), re.I)


def _h(salt: bytes, s: str) -> str:
    return hashlib.sha256(salt + normalize(s).encode()).hexdigest()


# ----------------------------------------------------------------------------- resolution
@dataclass
class Resolution:
    values: list[str] = field(default_factory=list)   # concrete values to erase
    topics: list[str] = field(default_factory=list)
    picks: list = field(default_factory=list)          # items whose topic matched (fact-level view)
    everything: bool = False


def resolve(request: str, memories: list, use_llm: bool = False) -> Resolution:
    """Work out what the citizen wants erased. `memories` = the citizen's own items."""
    res = Resolution()
    texts = [m.text for m in memories]
    res.values = explicit_values(request)
    res.topics = [t for t, rx in TOPICS.items() if re.search(rx, request, re.I)]
    # an explicit value already says what to erase: "please delete kesar-4135" is not a phone request
    if res.values and re.search(_CODE, request, re.I):
        res.topics = [t for t in res.topics if t not in ("phone", "aadhaar")]
    if res.values:
        res.picks = [m for m in memories if any(pattern(v).search(m.text) for v in res.values)]
    elif res.topics:
        res.picks = [m for m in memories if any(re.search(TOPICS[t], m.text, re.I) for t in res.topics)]
        for t in res.topics:
            for m in res.picks:
                res.values += values_in(m.text, t)
    elif ALL_RE.search(request):
        res.everything = True
        res.picks = list(memories)
        for m in memories:
            for t in TOPICS:
                res.values += values_in(m.text, t)
    else:  # "forget it / that": the latest thing they told us
        facts = [m for m in memories if m.btype == "personal_fact"] or list(memories)
        last = max(facts, key=lambda m: getattr(m, "created", 0), default=None)
        if last is not None:
            res.picks = [m for m in facts if last.parents and m.parents == last.parents] or [last]
            for m in res.picks:
                for t in TOPICS:
                    res.values += values_in(m.text, t)
    if use_llm and (res.topics or res.everything):
        res.values += _llm_values(request, texts)
    # keep values that really occur in this citizen's memory (anti-hallucination), dedupe
    seen, keep = set(), []
    for v in sorted({v.strip(" .,") for v in res.values if v and v.strip()}, key=len, reverse=True):
        k = normalize(v)
        if not k or k in seen or len(k) < 2:
            continue
        if res.values and texts and not any(pattern(v).search(t) for t in texts):
            continue
        seen.add(k)
        keep.append(v)
    res.values = keep
    return res


def _llm_values(request: str, texts: list[str]) -> list[str]:
    """Ask the model which exact strings the request refers to (optional, off in the mock)."""
    try:
        from llm import chat, parse_json
        mem = "\n".join(f"- {t}" for t in texts[:40])
        reply = chat("sahayak", [
            {"role": "system", "content": (
                "[[TASK:erase]]\nA citizen asked an assistant to erase some of their personal data. From their "
                "stored memories, list the EXACT substrings (names, numbers, codes, places) that identify what "
                "they asked to erase, wherever they appear - including inside unrelated stories. Copy them "
                'exactly. Reply with JSON only: {"values": ["...", "..."]}')},
            {"role": "user", "content": f"REQUEST: {request}\nMEMORIES:\n{mem}"}], temperature=0, max_tokens=200)
        out = parse_json(reply, want="values")
        vals = out.get("values") if isinstance(out.get("values"), list) else []
        return [str(v) for v in vals if isinstance(v, (str, int))][:10]
    except Exception:  # noqa: BLE001 - the regex path is always there
        return []


# ----------------------------------------------------------------------------- tombstones
class Tombstones:
    """Hashes of erased values, per owner. Never stores the value itself."""

    def __init__(self, salt: bytes | None = None):
        self.salt = salt or os.urandom(16)
        self._by_owner: dict[str, dict[str, str]] = {}   # owner -> {hash: label}
        self._lock = threading.Lock()

    def add(self, owner: str, value: str, label: str = "") -> None:
        with self._lock:
            d = self._by_owner.setdefault(owner, {})
            for v in variants(value):
                d[_h(self.salt, v)] = label or "erased"

    def count(self, owner: str | None = None) -> int:
        with self._lock:
            if owner is None:
                return sum(len(d) for d in self._by_owner.values())
            return len(self._by_owner.get(owner, {}))

    def _spans(self, text: str):
        """Candidate spans: words, word n-grams (<=4), codes, digit runs (separators allowed)."""
        words = [(m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9_ऀ-ॿ][A-Za-z0-9_ऀ-ॿ'.@+-]*", text)]
        for n in range(1, 5):
            for i in range(len(words) - n + 1):
                a, b = words[i][0], words[i + n - 1][1]
                yield a, b
        for m in re.finditer(r"(?<![\d०-९])[\d०-९](?:[\s\-.]?[\d०-९]){3,15}(?![\d०-९])", text):
            yield m.start(), m.end()

    def hits(self, owner: str, text: str) -> list[tuple[int, int]]:
        with self._lock:
            d = self._by_owner.get(owner)
            if not d or not text:
                return []
            hs = set(d)
        out = []
        for a, b in self._spans(text):
            frag = text[a:b].strip(" .,'\"")
            if frag and _h(self.salt, frag) in hs:
                out.append((a, b))
        return out

    def redact(self, owner: str, text: str) -> tuple[str, int]:
        spans = self.hits(owner, text)
        if not spans:
            return text, 0
        spans.sort()
        merged = []
        for a, b in spans:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        out, last = [], 0
        for a, b in merged:
            out.append(text[last:a])
            out.append(MASK)
            last = b
        out.append(text[last:])
        return "".join(out), len(merged)

    def lift(self, owner: str, text: str) -> int:
        """The citizen re-shared a value themselves (fresh consent): stop blocking it."""
        spans = self.hits(owner, text)
        if not spans:
            return 0
        with self._lock:
            d = self._by_owner.get(owner, {})
            for a, b in spans:
                frag = text[a:b].strip(" .,'\"")
                for v in variants(frag):
                    d.pop(_h(self.salt, v), None)
        return len(spans)


def redact_text(text: str, rx: re.Pattern) -> tuple[str, int]:
    new, n = rx.subn(MASK, text)
    return new, n


_FILLER = re.compile(r"\b(citizen|said|user|the|a|an|is|was|my|me|i|and|of|to|in|at|on|that|this|it|"
                     r"name|naam|hai|mera|meri|called|summary|history|code|number|word)\b|\[erased\]|[^\w\s]", re.I)


def still_useful(text: str) -> bool:
    """After redaction, is anything worth keeping left? ("[erased] and Raghu had a fight" -> yes;
    "Citizen's name is [erased]" -> no, delete it)."""
    rest = _FILLER.sub(" ", text)
    return len([w for w in rest.split() if len(w) > 2]) >= 3
