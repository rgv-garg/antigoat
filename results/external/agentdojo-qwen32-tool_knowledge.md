# AgentDojo v1.2.2 - target

Attack: `important_instructions` (AgentDojo's strongest standard attack). Utility and attack success are
decided by AgentDojo's own code on the final state of the simulated apps (no judge model).

| Defence | Attack success (lower = better) | Utility under attack | Benign utility | Benign calls held | Errors |
|---|---|---|---|---|---|
| none | **30.7%** (291/949; 95% CI 27.8-33.7%) | 50.3% | - (0/0) | 0 of 0 risky | 0 |
| checks | **3.0%** (28/949; 95% CI 2.0-4.2%) | 54.2% | - (0/0) | 0 of 0 risky | 0 |

Per suite (attack success / benign utility):

| Defence | banking | slack | travel | workspace |
|---|---|---|---|---|
| none | 45% / - | 89% / - | 72% / - | 6% / - |
| checks | 0% / - | 20% / - | 5% / - | 0% / - |

Held calls are approved by a simulated user only when the user's own task needs that exact call
(same tool, same recipient / account / channel / file / URL as the task's reference solution).
