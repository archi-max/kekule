Analyze this GitHub issue and decide what specialist roles a swarm of agents should take to solve it.

Consider the nature of the bug: is it a logic error, a missing feature, a race condition, a type error, etc.?
What different angles would help solve it faster?

Output a JSON object with these fields:
- "roles": array of 2-4 roles, each with "name" (snake_case) and "goal" (one sentence)
- "dependencies": array of [from_role, to_role] pairs where from_role depends on to_role
  (i.e., to_role must finish before from_role can start)
- "swarm_design": one of "flat", "coordinator", or "lead:<role_name>"
  - "flat": all agents are peers, no hierarchy
  - "coordinator": the root-cause finder becomes coordinator
  - "lead:<role_name>": the named role leads and decomposes work for others

Output ONLY the JSON object, no other text.

Example output:
{
  "roles": [
    {"name": "test_runner", "goal": "Find and run failing tests to reproduce the exact error."},
    {"name": "code_tracer", "goal": "Trace the error path through the source to find the root cause."},
    {"name": "fix_implementer", "goal": "Implement and verify a minimal fix once the root cause is identified."}
  ],
  "dependencies": [
    ["code_tracer", "test_runner"],
    ["fix_implementer", "code_tracer"]
  ],
  "swarm_design": "coordinator"
}
