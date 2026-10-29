# MemEvoBench (QA, 3 rounds, feedback on) - target

Agent, judge and feedback writer: target (the authors use GPT models as judge). ASR = share of answers the judge rated MISLED (lower is better).

| Defence | ASR all rounds | Round 1 | Round 2 | Round 3 | Items | Errors | Judge failures |
|---|---|---|---|---|---|---|---|
| base | **65.1%** (211/324; 95% CI 59.8-70.1%) | 50.9% | 75.9% | 68.5% | 108 | 0 | 0 |
| original | **87.3%** (283/324; 95% CI 83.3-90.5%) | 77.8% | 93.5% | 90.7% | 108 | 0 | 0 |
| only_safe | **80.2%** (260/324; 95% CI 75.6-84.2%) | 66.7% | 86.1% | 88.0% | 108 | 0 | 0 |
| checks | **73.1%** (237/324; 95% CI 68.1-77.7%) | 57.4% | 79.6% | 82.4% | 108 | 0 | 0 |

Per domain (ASR, all rounds):

| Defence | customerservice | finance | food | health | mental | privacy | traffic |
|---|---|---|---|---|---|---|---|
| base | 87% | 62% | 67% | 40% | 58% | 78% | 69% |
| original | 98% | 84% | 96% | 73% | 75% | 89% | 100% |
| only_safe | 93% | 76% | 89% | 60% | 72% | 80% | 100% |
| checks | 91% | 62% | 80% | 52% | 69% | 76% | 89% |
