# Quantified metrics

*Every Memory Checks mechanism measured as a rate over generated cases (n = 500 per row unless shown, seed 2026; deterministic, no GPU: `python scripts/metrics.py`), and the auditor's detection and false-alarm rates on the published real-model runs. 95% Wilson intervals. "Better" says which direction is good.*

| Area | Metric | Result | 95% CI | Better |
|---|---|---|---|---|
| Access control | a search returns another user's data (checks off) | **97.4%** (487/500) | 95.6–98.5% | lower |
| Access control | a search returns another user's data (checks on) | **0.0%** (0/500) | 0.0–0.8% | lower |
| Erasure | value still recoverable after 'forget' (checks off) | **100.0%** (500/500) | 99.2–100.0% | lower |
| Erasure | value still recoverable after 'forget' (checks v2) | **16.6%** (83/500) | 13.6–20.1% | lower |
| Erasure | value still recoverable after 'forget' (checks on) | **0.0%** (0/500) | 0.0–0.8% | lower |
| Poisoning | fake notice approves an application (checks off) | **77.4%** (387/500) | 73.5–80.8% | lower |
| Poisoning | fake notice approves an application (checks on) | **0.0%** (0/500) | 0.0–0.8% | lower |
| Utility | genuine signed policy applied (checks on) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Provenance | forged-signature 'circular' accepted (checks on) | **0.0%** (0/500) | 0.0–0.8% | lower |
| Post-incident | attribution recall: poison found (1 copy) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Post-incident | attribution precision: causes that are poison (1 copy) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Post-incident | rollback flips the bad approval to reject (1 copy) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Post-incident | benign memories wrongly quarantined (1 copy) | **0.0%** (0/500) | 0.0–0.8% | lower |
| Post-incident | attribution recall: poison found (2 copies) | **100.0%** (1000/1000) | 99.6–100.0% | higher |
| Post-incident | attribution precision: causes that are poison (2 copies) | **100.0%** (1000/1000) | 99.6–100.0% | higher |
| Post-incident | rollback flips the bad approval to reject (2 copies) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Post-incident | benign memories wrongly quarantined (2 copies) | **0.0%** (0/500) | 0.0–0.8% | lower |
| Consistency | contradiction recall (real conflicts flagged) | **100.0%** (227/227) | 98.3–100.0% | higher |
| Consistency | contradiction precision (flags that are real) | **100.0%** (227/227) | 98.3–100.0% | higher |
| Consistency | false flags on consistent memory | **0.0%** (0/273) | 0.0–1.4% | lower |
| Integrity | tampering detected (edit / delete / reorder / forge) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Integrity | untampered log verifies (no false alarm) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Integrity | verifier fault -> application rejected (fail-closed) | **100.0%** (500/500) | 99.2–100.0% | higher |
| Utility | legitimate messages wrongly quarantined | **0.0%** (0/500) | 0.0–0.8% | lower |
| Utility | legitimate messages mistaken for a rule claim | **0.0%** (0/500) | 0.0–0.8% | lower |
| Provenance | rule / authority claims in chat recognised as claims | **100.0%** (500/500) | 99.2–100.0% | higher |
| Auditor | known failures detected (planted bugs; reference agent) | **100.0%** (11/11) | 74.1–100.0% | higher |
| Auditor | LEAK verdicts where the system should hold (defended or clean) | **0.0%** (0/34) | 0.0–10.2% | lower |

Notes:
- a search returns another user's data (checks off): planted shared-index bug underneath in both modes
- a search returns another user's data (checks on): planted shared-index bug underneath in both modes
- value still recoverable after 'forget' (checks off): forms: plain 84/84, upper 84/84, spaced 83/83, devanagari 83/83, spelled 83/83, story 83/83
- value still recoverable after 'forget' (checks v2): forms: plain 0/84, upper 0/84, spaced 0/83, devanagari 0/83, spelled 0/83, story 83/83
- value still recoverable after 'forget' (checks on): forms: plain 0/84, upper 0/84, spaced 0/83, devanagari 0/83, spelled 0/83, story 0/83
- fake notice approves an application (checks off): 5 notice wordings incl. Hindi and an override phrasing
- fake notice approves an application (checks on): 5 notice wordings incl. Hindi and an override phrasing
- benign memories wrongly quarantined (1 copy): count over all cases
- benign memories wrongly quarantined (2 copies): count over all cases
- legitimate messages wrongly quarantined: 15 message templates (English, Hinglish, Hindi), randomised values
- legitimate messages mistaken for a rule claim: same 15 templates
- rule / authority claims in chat recognised as claims: 5 claim templates
- LEAK verdicts where the system should hold (defended or clean): defended = checks on or governed; clean = calibration leak rules, nothing planted
