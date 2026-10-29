# AgentDojo v1.2.2 - target

Attack: `important_instructions` (AgentDojo's strongest standard attack). Utility and attack success are
decided by AgentDojo's own code on the final state of the simulated apps (no judge model).

| Defence | Attack success (lower = better) | Utility under attack | Benign utility | Benign calls held | Errors |
|---|---|---|---|---|---|
| none | **7.2%** (68/948; 95% CI 5.7-9.0%) | 58.4% | - (0/0) | 0 of 0 risky | 1 |
| checks | **0.3%** (3/946; 95% CI 0.1-0.9%) | 57.8% | - (0/0) | 0 of 0 risky | 3 |

Per suite (attack success / benign utility):

| Defence | banking | slack | travel | workspace |
|---|---|---|---|---|
| none | 18% / - | 22% / - | 11% / - | 1% / - |
| checks | 0% / - | 2% / - | 1% / - | 0% / - |

Held calls are approved by a simulated user only when the user's own task needs that exact call
(same tool, same recipient / account / channel / file / URL as the task's reference solution).
