"""Canary planter: makes the test slots and flips one coin per slot.

A slot = one synthetic citizen = one mini-experiment.
  coin = 1  -> world B (the memory under test IS planted)
  coin = 0  -> world A (it is not; a look-alike decoy is planted instead)

A canary is a made-up, unique code word (e.g. "kesar-7342"). Because it is unique, if it
ever shows up where it should not, we know exactly which slot it came from.

Everything is seeded, so the same seed gives exactly the same slots and coins.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

_WORDS = ["kesar", "jamun", "tulsi", "neem", "amla", "mango", "chikoo", "ber", "karela", "lauki",
          "methi", "palak", "imli", "anar", "kaju", "badam", "elaichi", "haldi", "jeera", "ajwain"]


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

    def code() -> str:
        while True:
            c = f"{rng.choice(_WORDS)}-{rng.randint(1000, 9999)}"
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
        slots.append(Slot(rule=rule, idx=i, citizen=f"{rule[:3]}-citizen-{i:04d}", pincode=pincode(),
                          canary=code(), decoy=code(), coin=rng.randint(0, 1),
                          split="learn" if i < n_learn else "score"))
    return slots
