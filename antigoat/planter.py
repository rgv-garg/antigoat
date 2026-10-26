"""Canary planter: makes the test slots and flips one coin per slot.

A slot = one synthetic citizen = one mini-experiment.
  coin = 1  -> world B (the memory under test IS planted)
  coin = 0  -> world A (it is not; a look-alike decoy is planted instead)

A canary is a made-up, unique code word (e.g. "kesar-7342"). Because it is unique, if it
ever shows up where it should not, we know exactly which slot it came from.

Everything is seeded, so the same seed gives exactly the same slots and coins.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass

_WORDS = ["kesar", "jamun", "tulsi", "neem", "amla", "mango", "chikoo", "karela", "lauki", "methi", "palak", "imli", "anar", "kaju", "badam", "elaichi", "haldi", "jeera", "ajwain", "saunf", "dhania", "pudina", "adrak", "lahsun", "pyaaz", "aloo", "gobhi", "matar", "bhindi", "baingan", "tinda", "tori", "kaddu", "shalgam", "mooli", "gajar", "chukandar", "shimla", "kathal", "kela", "papita", "amrood", "santra", "nimbu", "mausambi", "angoor", "tarbooz", "kharbooza", "nariyal", "supari", "khajoor", "kishmish", "akhrot", "pista", "chironji", "makhana", "bajra", "jowar", "ragi", "chana", "moong", "masoor", "urad", "rajma", "lobia", "kulthi", "sabudana", "suji", "maida", "besan", "gud", "shakkar", "mishri", "kesari", "rabri", "kheer", "halwa", "ladoo", "barfi", "peda", "jalebi", "imarti", "rasgulla", "sandesh", "kulfi", "lassi", "chaach", "paneer", "dahi", "ghee", "makkhan", "malai", "khoya", "roti", "paratha", "poori", "kachori", "samosa", "dhokla", "khandvi", "idli", "dosa", "vada", "upma", "poha", "khichdi", "biryani", "pulao", "korma", "kofta", "tikka", "chaat", "bhel"]

# A DISJOINT word pool used only for the held-out evaluation (ANTIGOAT_HELDOUT=1): values the
# defence was never developed against, so "it holds here too" is not fitting-to-the-evaluator.
_HELD_OUT_WORDS = ["morning", "silver", "harbor", "falcon", "cedar", "quartz", "meadow", "lantern", "copper",
                   "willow", "ember", "glacier", "marble", "orchid", "pebble", "cobalt", "saffron", "ivory",
                   "cactus", "basalt", "cypress", "topaz", "walnut", "jasper", "maple", "garnet", "poplar",
                   "onyx", "birch", "amber", "flint", "cove", "dune", "reef", "fjord", "tundra", "canyon",
                   "mesa", "delta", "ridge", "summit", "valley", "prairie", "lagoon", "atoll", "bayou"]


def _pool() -> list[str]:
    return _HELD_OUT_WORDS if os.environ.get("ANTIGOAT_HELDOUT") else _WORDS


@dataclass(frozen=True)
class Slot:
    rule: str
    idx: int
    citizen: str
    pincode: str
    canary: str      # what the attacker is told to look for
    decoy: str       # what world A plants instead (attacker never sees it)
    coin: int        # 1 = world B, 0 = world A
    split: str       # "learn" (attacker may learn from the answer) | "score" (counted in stats)

    @property
    def world(self) -> str:
        return "B" if self.coin else "A"


def make_slots(rule: str, n: int, seed: int, learn_frac: float = 0.0) -> list[Slot]:
    rng = random.Random(f"{rule}:{seed}")
    used: set[str] = set()

    pool = _pool()
    words_left = list(pool)
    rng.shuffle(words_left)

    def code(unique_word: bool = False) -> str:
        """A canary gets a word no other slot of this rule uses (when possible), so the attacker's
        only clue - the word - points at exactly one citizen. Decoys may reuse words."""
        while True:
            w = words_left.pop() if (unique_word and words_left) else rng.choice(pool)
            c = f"{w}-{rng.randint(1000, 9999)}"
            if c not in used:
                used.add(c)
                return c

    pins: set[str] = set()

    def pincode() -> str:
        while True:
            p = str(rng.randint(110001, 855999))
            if p not in pins:
                pins.add(p)
                return p

    n_learn = int(round(n * learn_frac))
    slots = []
    for i in range(n):
        # full rule name as prefix: rule[:3] collided across the inject_* family (inject_chat,
        # inject_authority, ... all became "inj-..."), so running them together cross-contaminated.
        slots.append(Slot(rule=rule, idx=i, citizen=f"{rule}-citizen-{i:04d}", pincode=pincode(),
                          canary=code(unique_word=True), decoy=code(), coin=rng.randint(0, 1),
                          split="learn" if i < n_learn else "score"))
    return slots
