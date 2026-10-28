# Memory Checks on InjecAgent (public benchmark)

*Model: target. Success = the attacker's tool actually ran (code-decided). 95% Wilson intervals. Reproduce: `python scripts/eval_injecagent.py`.*

| Arm | Attack success, base | Attack success, enhanced | Model tried the attack (enh.) | Benign task finished | Benign calls held |
|---|---|---|---|---|---|
| none | 117/1054 = 11.1% [9.3, 13.1] | 113/1054 = 10.7% [9.0, 12.7] | 122/1054 | 743/1054 | 0/1054 |
| fence | 42/1054 = 4.0% [3.0, 5.3] | 49/1054 = 4.6% [3.5, 6.1] | 59/1054 | 773/1054 | 0/1054 |
| gate | 0/1054 = 0.0% [0.0, 0.4] | 0/1054 = 0.0% [0.0, 0.4] | 129/1054 | 744/1054 | 0/1054 |
| checks | 0/1054 = 0.0% [0.0, 0.4] | 0/1054 = 0.0% [0.0, 0.4] | 67/1054 | 771/1054 | 1/1054 |
