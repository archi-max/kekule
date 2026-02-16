# Kekule Oracle Architecture: Theory & Design

**Status**: Design phase
**Authors**: Ansh Tulsyan, Jack Armitage, Claude (debate partner)
**Date**: 2026-02-14

---

## 1. Core Thesis

Any software project has an infinitely long path from intent to completion. Satisfying user demands in one pass near the end of that path is unreliable because uncertainty compounds with each decision an agent makes. The solution is to decompose the path into **waypoints** — locally verifiable intermediate states — where automated **oracles** provide deterministic verification against user-defined **rules**.

Users don't write code. They **drive** a swarm of agents from waypoint to waypoint, orchestrating complex software development through a dashboard rather than an IDE.

### The Real Problem Being Solved

**Intermediate ground truth generation.** The only ground truth is the user's final intent, but that's too far away to be useful as immediate feedback for agents. The system must decompose vague end-state goals into a sequence of locally-verifiable intermediate states. Waypoints are the vehicle; the innovation is the decomposition + verification loop.

---

## 2. Target Audience

Knowledgeable engineers who:
- Can validate and refine AI-proposed rules but don't want to write every line
- Understand software architecture well enough to steer direction
- Can evaluate oracle outputs and make course corrections
- Want to "drive" development at a higher level of abstraction

This is NOT an average user tool. It's a power tool for engineers who already understand software but want to operate at a higher bandwidth.

---

## 3. Three Core Concepts

### 3.1 Rules (User Input as Acceptance Criteria)

Users cannot enter brief, vague prompts. They provide **verifiable rules** — structured acceptance criteria with uncertainty quantification.

**Rule elicitation is collaborative**: the user provides natural language intent, the AI proposes structured rules, the user approves/modifies. The system is a **rule elicitation engine**, not a rule input form.

Example flow:
```
User: "The login page should look like this mockup"
AI proposes rule:
  - type: pixel_match
  - reference: mockup.png
  - threshold: 0.95
  - scope: /login route
  - uncertainty: 0.1 (mockup may not cover all states)
User: "Yes, but also check mobile viewport"
AI updates: adds viewport variants to oracle_config
```

Concretely:
```python
@dataclass
class Rule:
    id: str
    description: str        # NLP: "The login page should match this mockup"
    oracle_type: str        # "pixel_match" | "pytest" | "e2e" | "type_check" | "security" | ...
    oracle_config: dict     # {"reference_image": "mockup.png", "threshold": 0.95}
    uncertainty: float      # 0.0 = certain, 1.0 = vague (triggers clarification)
    waypoint_id: str        # Which waypoint this rule gates
    status: str             # "draft" | "confirmed" | "verified"
```

### 3.2 Waypoints (Progressive Refinement Checkpoints)

The infinite path is segmented into waypoints with verification gates. Each waypoint is:
- A bounded scope of work
- Gated by rules + oracle verification
- Version-controlled via git commits
- Tracked via beads dependency management

```python
@dataclass
class Waypoint:
    id: str
    description: str            # "Backend API endpoints for auth"
    rules: list[Rule]           # Acceptance criteria
    beads_task_id: str          # Links to beads dependency graph
    git_ref: str | None         # Commit SHA when waypoint is achieved
    status: str                 # "pending" | "active" | "passed" | "failed"
    parent_waypoint: str | None # Dependency chain
```

**Waypoint generation is collaborative**: AI proposes waypoint boundaries, user approves/adjusts. Not too fine-grained (micromanaging), not too coarse (losing verification benefit).

**Waypoint granularity principle**: Each waypoint should be independently verifiable by its oracle battery. If you can't write concrete oracles for a waypoint, it's too vague — decompose further.

### 3.3 Oracles (Automated Verification at Scale)

Oracles are NOT LLM-judging-LLM. Oracles are **LLM-authored, tool-executed verification artifacts**.

The pipeline:
```
User Rule (structured)
  -> Oracle Agent (LLM writes the test/verification)
    -> Oracle Artifact (pytest file, Playwright script, pixel-match config, k6 script)
      -> Tool Execution (deterministic, repeatable)
        -> Pass/Fail with evidence
```

This inverts the SWE-bench model:

| | Code | Tests |
|---|---|---|
| SWE-bench | LLM writes | Humans wrote |
| Kekule | Coding Swarm writes | Oracle Swarm writes (from rules) |

Both sides are LLM-generated, but from **different inputs** (problem statement vs. user rules) and verified by **deterministic tool execution**. This is adversarial decomposition, not circular validation.

**Oracle types** (extensible — new types can be created on demand by the Oracle Creator):
- `pytest` — unit tests
- `e2e` — Playwright/Cypress end-to-end tests
- `pixel_match` — screenshot comparison against reference
- `type_check` — mypy/tsc type verification
- `lint` — ruff/eslint code quality
- `security` — bandit/semgrep security scanning
- `load` — k6/locust performance testing
- `concurrency` — race condition / thread safety tests
- `accessibility` — axe-core a11y checks
- `api_contract` — OpenAPI schema validation
- `cocotb_rtl` — RTL testbenches via cocotb + Icarus Verilog
- `android_espresso` — Android UI tests via Espresso + Robolectric
- *...any domain the Oracle Creator agent can build a config for*

**Key insight**: No one is scaling verification engines. Individual tools exist (pytest, Playwright, etc.) but no one is having LLMs automatically compose batteries of these tools from acceptance criteria and run them at scale. That's the oracle innovation.

**Self-extending**: When a needed oracle type doesn't exist, the Oracle Creator agent builds one on demand — determining the Docker environment, execution commands, agent prompts, and pass/fail detection. It self-validates by building the image and running a hello-world test before registering. See [ORACLE_CREATOR.md](ORACLE_CREATOR.md) for the full design.

**If the LLM fails to write good oracles from clear rules, the bottleneck is model capability, not architecture.** The architecture is designed to benefit from model improvements over time.

---

## 4. Two-Swarm Architecture

The coding swarm and the oracle swarm operate on the **same codebase** but from **fundamentally different information sources**:

- **Oracle Swarm**: reads user rules, understands the project stack, writes verification artifacts
- **Coding Swarm**: reads problem statement/waypoint goals, writes implementation code

They can run in parallel — the oracle swarm can start writing e2e tests while the coding swarm writes the code. In practice, launching fully in parallel may be difficult initially, so they may be launched sequentially or staggered as needed.

### Pipeline

```
User (NLP)
  -> Rule Elicitor (collaborative, AI + user)
    -> Rules (structured, verifiable)

              |                           |
              v                           v
    ┌──────────────────┐      ┌──────────────────┐
    │   ORACLE SWARM   │      │   CODING SWARM   │
    │                  │      │                  │
    │ Reads: rules     │      │ Reads: waypoint  │
    │ Writes: test     │      │   goals, context │
    │   artifacts      │      │ Writes: code     │
    │                  │      │                  │
    │ Can start early  │      │ Uses beads for   │
    │ (e2e tests       │      │ coordination     │
    │  before code)    │      │                  │
    └────────┬─────────┘      └────────┬─────────┘
             │                         │
             v                         v
    ┌─────────────────────────────────────────────┐
    │            WAYPOINT GATE                     │
    │                                              │
    │  Oracle artifacts execute against code       │
    │  All rules pass? -> git commit -> next WP    │
    │  Fail? -> iterate or escalate to user        │
    └─────────────────────────────────────────────┘
```

### Oracle Regeneration

Oracles are regenerated **per waypoint**, not once upfront, because:
- Later waypoints build on earlier code; tests need to reflect current state
- Rules may be refined as users see intermediate results
- The oracle agent reads the current repo state when generating

---

## 5. Conflict Resolution Protocol

When oracles disagree with code or with each other:

1. **Soft failure** (oracle confidence < threshold): Flag to user on dashboard, continue on current path
2. **Hard failure** (oracle deterministic fail): Block waypoint, escalate to user
3. **Conflict** (rule A passes, rule B fails): Fork — create two parallel waypoints exploring different approaches, let user pick after both produce results
4. **User override**: User can override any oracle with rationale (logged for audit trail)

---

## 6. Existing Infrastructure (what Kekule already has)

| Component | Status | Location |
|---|---|---|
| SwarmBus | Working | `src/kekule/benchmarks/swarm_bus.py` — cursor-based message bus, filesystem ledger |
| BeadsTracker | Working | `src/kekule/benchmarks/swarm_beads.py` — wraps `bd` CLI, dependency DAG, 8 MCP tools |
| Perturbation Swarm | Working | `src/kekule/benchmarks/solvers/perturbation_swarm.py` — 3-phase orchestrator |
| Role Planning | Working | Planner agent outputs roles + deps + design as JSON |
| Swarm Designs | Partial | flat, coordinator, lead:\<role\> patterns |
| Patch Selection | Working | Endorsement-based selection from ledger |
| Hooks | Working | `src/kekule/benchmarks/swarm_hooks.py` for tool-call interception |

---

## 7. What Needs to Be Built

### Project 1: Oracle Generator (`src/kekule/oracle/`)

The oracle-generating agent/swarm that turns user rules into executable verification artifacts. **Partially built** — elicitor, agent, and Docker runner exist for pytest.

Remaining work:
- Oracle Creator agent (creates new oracle types on demand) — see [ORACLE_CREATOR.md](ORACLE_CREATOR.md)
- `OracleTypeConfig` schema and dynamic loading from `.kekule/oracle_types/`
- Parameterize `agent.py` and `runner.py` to use oracle type configs instead of hardcoding pytest
- Waypoint integration (generate/run per waypoint, feedback loop) — see [WAYPOINTS.md](WAYPOINTS.md)
- Built-in configs for common types (playwright, cocotb, etc.)

### Project 2: Dashboard UI (`oracle/ui/`)

The "driving" interface where engineers orchestrate agents between waypoints.

Core responsibilities:
- Rule elicitation interface (collaborative NLP -> structured rules)
- Waypoint graph visualization (dependency DAG from beads)
- Agent status monitoring (from SwarmBus — who's doing what, where)
- Oracle results display (pass/fail per rule, with evidence)
- Approve/reject/override controls at waypoint gates
- Parallel path visualization (when conflicts create forks)
- Git history integration (waypoints as commits)
- Oracle type management (browse existing types, create new ones via oracle creator)

---

## 8. MVP Progression

### v0: Single Agent + Waypoints + Manual Oracle Review
- Prove that intermediate checkpointing reduces drift vs. one-shot

### v1: Add Oracle Battery (LLM-generated, tool-executed)
- Prove that automated multi-tool verification catches issues humans miss

### v2: Add Coding Swarm
- Prove that parallelism improves outcomes when verification is solid

### v3: Add Oracle Swarm (parallel with coding swarm)
- Prove that concurrent test generation + code writing is faster than sequential

### v4: Full Dashboard
- Prove that "driving" is a viable interaction model for software development

---

## 9. Open Questions

1. **Oracle quality metrics**: How do we measure whether a generated oracle is "good"? Coverage? Mutation testing on the oracle itself?
2. **Waypoint rollback**: When a waypoint fails repeatedly, do we rewind to the previous git checkpoint? How much agent context is lost?
3. **Cross-waypoint oracle evolution**: When waypoint 3's code breaks waypoint 1's oracles, who detects and handles regression?
4. **Oracle cost**: Generating a full test battery per waypoint is expensive. What's the minimum viable oracle set?
5. **Swarm size scaling**: Does adding more agents actually help, or does coordination overhead dominate past N=4?

---

## 10. Key Insight Summary

> The architecture separates **intent** (rules), **execution** (coding swarm), and **verification** (oracle swarm + tools) into three independent streams that converge at waypoint gates. Each stream can improve independently — better rule elicitation, better coding models, better test generation — and the waypoint structure bounds the blast radius of any single failure.

> The bet is that LLMs are already good enough to write verification code from clear rules, and will only get better. The architecture doesn't need perfect oracles today — it needs oracles that are better than no verification, which is the current state of long-running agent tasks.
