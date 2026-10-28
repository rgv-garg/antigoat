# Memory Checks on InjecAgent (public benchmark)

*Model: target. Success = the attacker's tool actually ran (code-decided). 95% Wilson intervals. Reproduce: `python scripts/eval_injecagent.py`.*

| Arm | Attack success, base | Attack success, enhanced | Model tried the attack (enh.) | Benign task finished | Benign calls held |
|---|---|---|---|---|---|
| none | 349/1054 = 33.1% [30.3, 36.0] | 598/1054 = 56.7% [53.7, 59.7] | 629/1054 | 890/1054 | 0/1054 |
| fence | 210/1054 = 19.9% [17.6, 22.4] | 201/1054 = 19.1% [16.8, 21.6] | 205/1054 | 918/1054 | 0/1054 |
| gate | 0/1054 = 0.0% [0.0, 0.4] | 0/1054 = 0.0% [0.0, 0.4] | 629/1054 | 890/1054 | 0/1054 |
| checks | 0/1054 = 0.0% [0.0, 0.4] | 0/1054 = 0.0% [0.0, 0.4] | 199/1054 | 918/1054 | 0/1054 |
