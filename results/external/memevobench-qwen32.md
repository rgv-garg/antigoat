# MemEvoBench (QA, 3 rounds, feedback off) - target

Agent, judge and feedback writer: target (the authors use GPT models as judge). ASR = share of answers the judge rated MISLED (lower is better).

| Defence | ASR all rounds | Round 1 | Round 2 | Round 3 | Items | Errors | Judge failures |
|---|---|---|---|---|---|---|---|
| base | **65.1%** (211/324; 95% CI 59.8-70.1%) | 50.9% | 75.9% | 68.5% | 108 | 0 | 0 |
| original | **86.4%** (280/324; 95% CI 82.3-89.7%) | 77.8% | 91.7% | 89.8% | 108 | 0 | 0 |
| only_safe | **77.8%** (252/324; 95% CI 72.9-82.0%) | 66.7% | 82.4% | 84.3% | 108 | 0 | 0 |
| checks | **70.7%** (229/324; 95% CI 65.5-75.4%) | 56.5% | 77.8% | 77.8% | 108 | 0 | 0 |

Per domain (ASR, all rounds):

| Defence | customerservice | finance | food | health | mental | privacy | traffic |
|---|---|---|---|---|---|---|---|
| base | 87% | 62% | 67% | 40% | 58% | 78% | 69% |
| original | 98% | 84% | 96% | 70% | 75% | 87% | 100% |
| only_safe | 93% | 76% | 89% | 59% | 67% | 76% | 92% |
| checks | 93% | 53% | 82% | 49% | 64% | 76% | 83% |
