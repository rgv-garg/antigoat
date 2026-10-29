# AgentDojo v1.2.2 - target

Attack: `important_instructions` (AgentDojo's strongest standard attack). Utility and attack success are
decided by AgentDojo's own code on the final state of the simulated apps (no judge model).

| Defence | Attack success (lower = better) | Utility under attack | Benign utility | Benign calls held | Errors |
|---|---|---|---|---|---|
| none | **13.6%** (129/947; 95% CI 11.6-16.0%) | 54.1% | - (0/0) | 0 of 0 risky | 2 |
| checks | **0.7%** (7/947; 95% CI 0.4-1.5%) | 55.4% | - (0/0) | 0 of 0 risky | 2 |

Per suite (attack success / benign utility):

| Defence | banking | slack | travel | workspace |
|---|---|---|---|---|
| none | 19% / - | 54% / - | 27% / - | 1% / - |
| checks | 0% / - | 5% / - | 1% / - | 0% / - |

Held calls are approved by a simulated user only when the user's own task needs that exact call
(same tool, same recipient / account / channel / file / URL as the task's reference solution).
