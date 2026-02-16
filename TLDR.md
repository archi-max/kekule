# Kekule -- TLDR

**What**: A heterarchical AI agent swarm that self-organizes to build software, with automated verification at every checkpoint.

**Why**: One-shot AI code generation drifts from intent. Kekule decomposes work into **waypoints** with **oracle verification** so agents stay on track.

**Stack**: Python 3.11+, Claude Agent SDK (Opus 4.6), Docker, FastAPI, React/TypeScript

---

## The Big Picture

```
USER
  |
  |  "Build me X"
  v
┌─────────────────────────────────────────────────────────────────┐
│                        DASHBOARD (UI)                            │
│  Projects | Rules | Waypoint Graph | Agent Monitor | Results     │
└──────────────────────────┬──────────────────────────────────────┘
                           |
              ┌────────────┼────────────┐
              v            v            v
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  RULE    │ │ ORACLE   │ │ CODING   │
        │ ELICITOR │ │  SWARM   │ │  SWARM   │
        │          │ │          │ │          │
        │ "What to │ │ "Write   │ │ "Write   │
        │  verify" │ │  tests"  │ │  code"   │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             |            |            |
             v            v            v
        ┌─────────────────────────────────────┐
        │          WAYPOINT GATE               │
        │                                      │
        │  Oracle tests run in Docker          │
        │  All pass? -> git commit -> next WP  │
        │  Fail?    -> iterate or ask user     │
        └─────────────────────────────────────┘
```

---

## Four Subsystems

### 1. SWE-bench Harness (`src/kekule/benchmarks/`)

Runs AI agents against real GitHub issues to measure how well they solve bugs.

```
Task Selection              Agent Execution              Evaluation
─────────────              ───────────────              ──────────
HuggingFace SWE-bench  ->  N agents x M problems  ->  Docker eval
Lite dataset               in parallel                 (official SWE-bench)
                           |
                           v
                    ┌──────────────┐
                    │ Solver Agent │  (pluggable)
                    │              │
                    │ Claude SDK   │
                    │ query()      │
                    │ explores repo│
                    │ writes fix   │
                    │ produces     │
                    │ git diff     │
                    └──────────────┘
```

**Key files:**
- `harness.py` -- orchestrator: clones repos, spawns agents, collects patches
- `solver_agent.py` -- default solver using `query()` with Read/Edit/Bash tools
- `solvers/perturbation_swarm.py` -- multi-agent solver (see Swarm section)
- `config.py` -- all experiment knobs (model, problems, agents, iterations)
- `evaluator.py` -- runs official SWE-bench Docker evaluation

**Run it:**
```bash
kekule-bench --problems 2 --agents-per-problem 1 --skip-eval
```

---

### 2. Swarm Infrastructure (`src/kekule/benchmarks/swarm_*.py`)

Coordination primitives that let multiple agents work together.

```
┌─────────────────────────────────────────────────────────┐
│                    SWARM INFRA                           │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  SwarmBus    │  │ BeadsTracker │  │  SwarmHooks  │   │
│  │              │  │              │  │              │   │
│  │ Broadcast    │  │ Task DAG     │  │ Tool-call    │   │
│  │ messages     │  │ Dependencies │  │ interception │   │
│  │ between      │  │ ready/blocked│  │ auto-post    │   │
│  │ agents       │  │ tracking     │  │ findings     │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**SwarmBus** (`swarm_bus.py`): In-memory message bus. Agents broadcast findings, status updates, questions. Cursor-based reads so each agent only sees new messages. Writes to `BROADCAST.md` ledger.

**BeadsTracker** (`swarm_beads.py`): DAG-based work item tracking. Tasks have dependencies (blocked/ready). Exposed as 8 MCP tools the agents can call directly.

**SwarmHooks** (`swarm_hooks.py`): Intercepts tool calls (PostToolUse). Auto-detects when an agent reads/edits a file and posts to SwarmBus. Periodically injects swarm status into agent context.

---

### 3. Perturbation Swarm Solver (`solvers/perturbation_swarm.py`)

Multi-agent approach that decomposes a task into specialist roles.

```
Phase 0: PLAN                Phase 1: SWARM               Phase 2: SELECT
──────────────               ──────────────               ──────────────

Planner agent           ┌── Agent A (bug_reproducer)
reads the issue    -->  ├── Agent B (root_cause_tracer)  -->  Best patch
proposes 2-4 roles      └── Agent C (solution_architect)      selected by
+ dependencies                    |                           endorsement
                          communicate via SwarmBus            or git diff
                          coordinate via BeadsTracker
```

Each agent gets:
- A role-specific system prompt
- Access to SwarmBus MCP tools (broadcast, read_updates, claim_task)
- SwarmHooks for automatic coordination
- Shared repo workspace

---

### 4. Oracle Generator (`src/kekule/oracle/`)

Turns user-defined **Rules** into executable **pytest tests**, runs them in **Docker containers**, returns **pass/fail with evidence**.

```
                    ┌─────────────────────────┐
                    │     RULE ELICITATION     │
                    │     (3-phase pipeline)   │
                    └────────────┬────────────┘
                                 |
                                 v
rules.json ─────────────────> list[Rule]
                                 |
                    ┌────────────┼────────────┐
                    v            v            v
             ┌──────────┐┌──────────┐┌──────────┐
             │ Oracle   ││ Oracle   ││ Oracle   │
             │ Agent    ││ Agent    ││ Agent    │
             │          ││          ││          │
             │ Claude   ││ Claude   ││ Claude   │
             │ explores ││ explores ││ explores │
             │ repo,    ││ repo,    ││ repo,    │
             │ writes   ││ writes   ││ writes   │
             │ pytest   ││ pytest   ││ pytest   │
             └────┬─────┘└────┬─────┘└────┬─────┘
                  |           |           |
             ┌────┴─────┐┌───┴──────┐┌───┴──────┐
             │ Docker   ││ Docker   ││ Docker   │
             │ container││ container││ container│
             │ pytest   ││ pytest   ││ pytest   │
             │ isolated ││ isolated ││ isolated │
             └────┬─────┘└────┬─────┘└────┬─────┘
                  |           |           |
                  v           v           v
             OracleResult OracleResult OracleResult
             PASS/FAIL    PASS/FAIL    PASS/FAIL
```

**Key files:**
- `schemas.py` -- `Rule`, `OracleResult`, `OracleRunRequest` (Pydantic models)
- `agent.py` -- Claude SDK agent that explores repo + writes pytest file per rule
- `runner.py` -- Docker lifecycle: generate Dockerfile, build, run, collect results
- `__main__.py` -- CLI: `generate`, `run`, `elicit` subcommands

**Docker constraints per container:**
- `--network=none` (no internet)
- `--memory=512m`
- `--cpus=1`
- `--rm` (auto-cleanup)

**Run it:**
```bash
# Generate test artifacts
python -m kekule.oracle generate --rules rules.json --repo ./my-project

# Generate + run in Docker
python -m kekule.oracle run --rules rules.json --repo ./my-project

# Interactive rule elicitation
python -m kekule.oracle elicit --repo ./my-project --output rules.json
```

---

## Rule Elicitation Pipeline

Three-phase pipeline that turns vague user intent into concrete, testable rules.

```
┌──────────────────────────────────────────────────────────────────┐
│                     ELICITATION PIPELINE                          │
│                                                                   │
│   Phase 1: CONVERSE          Phase 2: GENERATE     Phase 3: REVIEW│
│   ─────────────────          ─────────────────     ───────────────│
│                                                                   │
│   ClaudeSDKClient            query() stateless     query() review │
│   (multi-turn)               Intent -> Rules       Rules -> Gaps  │
│                                                                   │
│   Agent explores repo        Agent explores code   Reviewer asks: │
│   User describes intent      Grounds rules in      "Can I write a │
│   Agent asks questions       actual modules,       pytest from    │
│   User clarifies             classes, methods      this rule?"    │
│   Agent captures Intent                                           │
│                                                         |         │
│                                                    ┌────┴────┐    │
│                                                    |         |    │
│                                              auto-resolve  escalate│
│                                              (from code)  (to user)│
│                                                    |         |    │
│                                                    v         v    │
│                                               refine_rules  ask  │
│                                               (Phase 2      user │
│                                                again)            │
└──────────────────────────────────────────────────────────────────┘
```

**Key decision**: auto-resolve vs. escalate
- **Auto-resolvable** (answer is in the code): "What exception does this raise?" "What type does it return?"
- **Needs user** (product decision): "What latency is acceptable?" "Should this require auth?"

**Files:**
- `elicitor/conversation.py` -- Phase 1 (ClaudeSDKClient, multi-turn)
- `elicitor/rule_generator.py` -- Phase 2 (query(), stateless)
- `elicitor/reviewer.py` -- Phase 3 (query(), adversarial)
- `elicitor/escalation.py` -- triage logic (pure Python, no LLM)
- `elicitor/pipeline.py` -- orchestrator loop
- `elicitor/simulate.py` -- pre-scripted simulation scenarios

**Run simulations:**
```bash
python -m kekule.oracle.elicitor.simulate --scenario 1   # clear intent
python -m kekule.oracle.elicitor.simulate --scenario 2   # vague intent
```

---

## Rule Format

```json
{
  "rules": [
    {
      "id": "divide_by_zero_raises",
      "description": "Calculator.divide(a, 0) must raise ZeroDivisionError",
      "oracle_type": "pytest",
      "oracle_config": {
        "target_module": "src/calculator/core.py",
        "class": "Calculator",
        "method": "divide",
        "test_cases": [
          {"a": 10, "b": 0, "expected_exception": "ZeroDivisionError"}
        ]
      },
      "uncertainty": 0.0,
      "status": "confirmed"
    }
  ]
}
```

| Field | What it does |
|---|---|
| `id` | Unique snake_case identifier |
| `description` | What to verify -- must be specific enough to write a test from |
| `oracle_type` | Always `"pytest"` (extensible later) |
| `oracle_config` | Target module/class/method + concrete test cases |
| `uncertainty` | 0.0 = crystal clear, 1.0 = too vague |
| `status` | `draft` -> `confirmed` -> `verified` |

---

## Dashboard (`src/kekule/ui/` + `src/kekule/ui-frontend/`)

Full-stack web app for driving agent development through waypoints.

```
┌─────────────────────────────────────────────────────────┐
│                    DASHBOARD                             │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐│
│  │ Projects │  │ Rules    │  │ Waypoint │  │ Swarm   ││
│  │          │  │          │  │ Graph    │  │ Monitor ││
│  │ Create   │  │ CRUD     │  │ DAG viz  │  │ Agent   ││
│  │ Manage   │  │ Elicit   │  │ Approve  │  │ status  ││
│  │          │  │ Confirm  │  │ Reject   │  │ Messages││
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘│
│                                                          │
│  Backend: FastAPI (localhost:8000)                        │
│  Frontend: React + Vite (localhost:5173)                  │
│  State: JSON persistence + in-memory SwarmBus/Beads      │
└─────────────────────────────────────────────────────────┘
```

**Backend routes:**
- `POST /api/projects` -- create project
- `POST /api/rules` -- create/update rules
- `GET /api/waypoints` -- get waypoint DAG
- `POST /api/waypoints/:id/approve` -- approve waypoint gate
- `GET /api/swarm/status` -- agent statuses
- `GET /api/swarm/messages` -- SwarmBus feed
- `POST /api/oracle/:waypoint/run` -- trigger oracle execution

**Run it:**
```bash
# Backend
cd src/kekule/ui && uvicorn app:app --reload

# Frontend
cd src/kekule/ui-frontend && npm install && npm run dev
```

---

## End-to-End Flow

```
1. USER creates project in Dashboard
        |
2. USER describes intent via Rule Elicitor
        |
        v
3. CONVERSATION AGENT explores repo, asks questions
        |
4. RULE GENERATOR produces concrete Rules from intent
        |
5. REVIEWER audits rules, auto-resolves gaps
        |
        v
6. ORACLE AGENTS generate pytest files per rule
        |
7. DOCKER CONTAINERS run tests, collect pass/fail
        |
        v
8. DASHBOARD shows results
        |
   ┌────┴────┐
   |         |
 PASS      FAIL
   |         |
   v         v
9a. Git    9b. Iterate:
commit       - coding swarm fixes code
next WP      - re-run oracles
             - or escalate to user
```

---

## Project Layout

```
kekule/
  CLAUDE.md                          # Instructions for Claude Code
  TLDR.md                            # This file
  pyproject.toml                     # Package config, CLI entry points

  src/kekule/
    main.py                          # Demo agents
    solver/                          # Expert question-solving agent
      agent.py                       #   ClaudeSDKClient, MCP tools
      schemas.py                     #   Question, SolverResponse
    benchmarks/                      # SWE-bench experiment harness
      harness.py                     #   Main orchestrator
      solver_agent.py                #   Default solver (query())
      config.py                      #   HarnessConfig
      task_selector.py               #   SWE-bench Lite loader
      evaluator.py                   #   Docker eval + results
      tracing.py                     #   LangFuse integration
      swarm_bus.py                   #   Inter-agent message bus
      swarm_beads.py                 #   Task dependency DAG
      swarm_hooks.py                 #   Tool-call interception
      solvers/
        default.py                   #   Re-exports solver_agent
        perturbation_swarm.py        #   3-phase multi-agent solver
    oracle/                          # Oracle verification system
      schemas.py                     #   Rule, OracleResult, OracleRunRequest
      agent.py                       #   Test generation agent
      runner.py                      #   Docker execution engine
      __main__.py                    #   CLI (generate/run/elicit)
      elicitor/                      #   3-phase rule elicitation
        conversation.py              #     Phase 1: multi-turn intent
        rule_generator.py            #     Phase 2: intent -> rules
        reviewer.py                  #     Phase 3: adversarial audit
        escalation.py                #     Auto-resolve vs. escalate
        pipeline.py                  #     Orchestrator loop
        simulate.py                  #     Pre-scripted simulations
    ui/                              # Dashboard backend (FastAPI)
      app.py                         #   FastAPI app
      models.py                      #   API models
      state.py                       #   App state + persistence
      routes/                        #   REST endpoints
    ui-frontend/                     # Dashboard frontend (React)
      src/pages/                     #   ProjectList, ProjectDetail, SwarmMonitor
      src/components/                #   RuleCard, WaypointCard, AgentMonitor

  oracle/                            # Design docs + samples
    THEORY.md                        #   Core architecture thesis
    generator/samples/               #   Sample calculator project + rules

  docs/                              # Usage documentation
    oracle.md                        #   Oracle Generator guide
    benchmarks.md                    #   SWE-bench harness guide
    custom-solvers.md                #   Build your own solver
    perturbation-protocol.md         #   Multi-agent research protocol

  tests/test_oracle/                 # Unit tests (47 passing)
```

---

## Key Commands

```bash
# Setup
uv sync --extra dev --extra benchmarks

# Oracle: generate tests from rules
python -m kekule.oracle generate --rules rules.json --repo ./project

# Oracle: generate + run in Docker
python -m kekule.oracle run --rules rules.json --repo ./project

# Oracle: interactive rule elicitation
python -m kekule.oracle elicit --repo ./project --output rules.json

# Oracle: simulate conversations
python -m kekule.oracle.elicitor.simulate --scenario 1

# SWE-bench: run experiments
kekule-bench --problems 2 --agents-per-problem 1 --skip-eval

# Tests
pytest tests/test_oracle/ -v

# Dashboard
cd src/kekule/ui && uvicorn app:app --reload
cd src/kekule/ui-frontend && npm run dev
```

---

## Claude Agent SDK Patterns Used

| Pattern | Where | What it does |
|---|---|---|
| `query()` stateless | oracle agent, rule generator, reviewer, SWE solver | Fire-and-forget: send prompt, stream response, done |
| `ClaudeSDKClient` stateful | conversation agent, expert solver | Multi-turn: send message, get response, send follow-up, maintains full context |
| `create_sdk_mcp_server()` | swarm_beads.py | Expose custom tools (swarm_broadcast, swarm_claim_task) to agents |
| PostToolUse hooks | swarm_hooks.py | Intercept tool calls to auto-post findings to SwarmBus |
| `bypassPermissions` | all automated agents | No approval prompts (CI/CD mode) |
| `allowed_tools` | everywhere | Restrict which tools agents can use (e.g., no Write for reviewer) |
