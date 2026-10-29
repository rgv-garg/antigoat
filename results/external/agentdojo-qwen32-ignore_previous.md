# AgentDojo v1.2.2 - target

Attack: `important_instructions` (AgentDojo's strongest standard attack). Utility and attack success are
decided by AgentDojo's own code on the final state of the simulated apps (no judge model).

| Defence | Attack success (lower = better) | Utility under attack | Benign utility | Benign calls held | Errors |
|---|---|---|---|---|---|
| none | **17.7%** (168/948; 95% CI 15.4-20.3%) | 51.8% | - (0/0) | 0 of 0 risky | 1 |
| checks | **0.8%** (8/948; 95% CI 0.4-1.7%) | 53.7% | - (0/0) | 0 of 0 risky | 1 |

Per suite (attack success / benign utility):

| Defence | banking | slack | travel | workspace |
|---|---|---|---|---|
| none | 22% / - | 71% / - | 35% / - | 2% / - |
| checks | 0% / - | 5% / - | 1% / - | 0% / - |

Held calls are approved by a simulated user only when the user's own task needs that exact call
(same tool, same recipient / account / channel / file / URL as the task's reference solution).
