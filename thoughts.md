# Swarm Demo — What Would Make the Claude Code Founder Say "Wow"

## What they've already seen (and aren't impressed by)

- Multi-agent orchestration (they built Claude Code, which already has the Task tool for spawning sub-agents)
- Best-of-N sampling (trivial parallelism)
- Agents with a chat room (ChatOverflow etc — it's middleware, not a capability)
- Fancy visualizations over basic results

They built the SDK. They know what it can do. To impress them, you need to show it doing something **they didn't realize it could do.**

---

## The key insight nobody has shown yet

Claude Code agents already have the **Task tool** — an agent can spawn sub-agents. Those sub-agents can spawn their own sub-agents. This means **recursive self-organization is already a latent capability of the SDK.** Nobody has demonstrated it.

The frontier isn't "N agents working in parallel." It's:

**One agent that realizes it can't do the task alone, decomposes it, spawns a team, and that team adapts its own structure based on what it discovers.**

The organizational chart is an OUTPUT of the run, not an input. Different tasks produce different team structures. A simple bug produces a flat structure (one agent, done). A massive refactor produces a deep tree (lead → specialists → sub-specialists). The agent decides.

---

## The Demo: "Adaptive Self-Organization"

### What you show

Give one Claude Code agent a task that's too big for it.

Not a bug fix. Something like:

> "This Flask app has no tests, no type hints, SQL injection vulnerabilities, broken error handling, and the docs are wrong. Make it production-ready."

Then watch.

### What happens

**Phase 1 — The agent assesses the scope.**
It reads the repo. It realizes: "This is 6 different workstreams. I can't do all of this in one session." It uses the Task tool to spawn specialists:
- "Security auditor — find and fix all injection vulnerabilities"
- "Test writer — add pytest tests for every endpoint"
- "Type annotator — add type hints to all public functions"

**Phase 2 — The specialists work AND adapt.**
The security auditor finds 5 vulnerabilities across 3 modules. It could fix them all, or it could spawn 3 sub-agents (one per module) to parallelize. It decides based on complexity. Simple fixes it handles directly. Complex ones it delegates.

The test writer discovers the app has no test fixtures. Instead of writing tests directly, it first spawns a sub-agent to build the test infrastructure (conftest.py, factories, fixtures), THEN spawns test-writing agents that use that infrastructure.

**Phase 3 — Results converge.**
The original agent collects results, runs the test suite, verifies everything works together. If something's broken, it spawns a fix agent.

### What the audience sees

A **tree growing in real-time** in Langfuse:

```
root-agent (assessed repo, spawned 4 specialists)
├── security-audit (found 5 issues, fixed 2 directly, spawned 3)
│   ├── fix-sql-injection-users (done, 1 file changed)
│   ├── fix-sql-injection-products (done, 2 files changed)
│   └── fix-xss-templates (done, 4 files changed)
├── test-writer (spawned infrastructure agent first, then test agents)
│   ├── test-infrastructure (created conftest.py, fixtures)
│   ├── test-auth-endpoints (12 tests, all passing)
│   ├── test-crud-endpoints (18 tests, all passing)
│   └── test-search (6 tests, all passing)
├── type-annotations (handled directly, 14 files changed)
└── doc-updater (handled directly, 3 files changed)
```

**This tree was not designed. It emerged from the task.** A different repo would produce a different tree. A simpler task would be flat. A more complex one would be deeper.

And the output is real: a working PR with 50+ files changed, 36 new tests passing, 0 security issues, full type coverage.

### The comparison that sells it

Run the same task with a single Claude Code agent (no Task tool spawning). It gets maybe 40% done before it loses context or runs out of turns. Show the diff side by side:

| | Single Agent | Self-Organizing Swarm |
|---|---|---|
| Tests added | 8 | 36 |
| Security fixes | 2/5 | 5/5 |
| Files touched | 12 | 47 |
| Type coverage | partial | complete |
| Coherent PR | no (inconsistent) | yes |
| Time | same | same |

The swarm doesn't just do more — it does it coherently, because each sub-agent has a focused scope.

---

## Why this is genuinely frontier

1. **Recursive depth is adaptive.** The security auditor decided to spawn 3 sub-agents. The test writer decided to first build infrastructure before writing tests. These are organizational decisions made by agents, not humans. You cannot predefine this structure because you don't know what the repo looks like until you read it.

2. **It's self-similar at every scale.** The root agent decomposes → specialists → sub-specialists. This is how biological systems organize (cells → tissues → organs). It's how companies organize (CEO → VPs → teams). But here, the structure EMERGES from a single starting point.

3. **It uses the SDK in a way the builders haven't seen.** The Task tool was designed for spawning helper agents. Using it recursively to build adaptive organizational structures is a novel application. This is the kind of thing that makes a tool builder think "oh, we should support this better."

4. **It produces real output.** Not a visualization. Not a metric. A working PR. The tree is just how it got there.

5. **It reveals a scaling law.** More compute = deeper trees = better results. Not linearly (like best-of-N) but structurally. The agent learns to delegate more aggressively with more budget. This is a genuinely new insight about how agent systems scale.

---

## What you need to build

**One solver file: `solvers/swarm.py`**

The solver wraps a single agent call, but the system prompt tells the agent:

```
You are a lead engineer. Assess the full scope of this task. If it requires
work across multiple independent areas, use the Task tool to spawn specialist
sub-agents for each area. Each specialist should focus on one area and do it
completely. You may give each specialist permission to spawn their own
sub-agents if the work is complex enough.

After all specialists complete, verify the combined result: run tests,
check for conflicts, ensure consistency.

Do NOT try to do everything yourself. Delegate aggressively. Your job is
to architect the approach and verify the result, not to write every line.
```

The magic is that the Claude Agent SDK already supports this via the Task tool. The agents already CAN spawn sub-agents. You're just telling them they SHOULD.

**A target repo to demo on.**

Write a deliberately janky Flask/FastAPI app (~500 lines) with known issues:
- SQL injection in 3 places
- No tests
- No type hints
- Broken error handling (bare excepts, no logging)
- Docs that don't match the code
- Hardcoded secrets

This is your "before" snapshot. The "after" is what the swarm produces.

**Langfuse traces as the visualization.**

You already have Langfuse integrated. The trace tree IS the org chart. No need to build a custom dashboard — just show Langfuse.

---

## The 2-minute pitch

"We gave one Claude Code agent a repo full of problems. It read the repo, realized the scope was too large for a single session, and spontaneously organized itself into a team of specialists. The security auditor spawned sub-agents for each vulnerability class. The test writer built test infrastructure before writing tests. The organizational structure wasn't designed — it emerged from the problem.

Here's the Langfuse trace — you can see the tree that formed. Here's the PR — 47 files changed, 36 new tests, all passing. Here's what a single agent produced on the same task — incomplete, inconsistent, 40% coverage.

The same system on a simpler task produces a flat structure. On a more complex task, it goes deeper. The depth of self-organization adapts to the problem complexity.

We think this is the future of how agent systems will work: not fixed architectures, but adaptive self-organization using the capabilities already in the SDK."
