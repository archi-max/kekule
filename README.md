# Kekule

> *Named after August Kekule's famous dream of a snake eating its own tail -- the ouroboros that led to the discovery of benzene's ring structure. Just as that moment of lateral thinking revolutionized chemistry, we explore how analogical reasoning and structured exploration can unlock breakthrough capabilities in agent swarms.*

A self-improving heterarchical agent swarm that solves real GitHub issues by decomposing work into verified waypoints, with oracle tests that gate each step.

**Built for**: [Built with Opus 4.6: a Claude Code hackathon](https://cerebralvalley.ai/) (Cerebral Valley & Anthropic)

**Team**: [Ansh Tulsyan](https://github.com/archi-max) & [Jack Armitage](https://github.com/jarmitage)

---

## How It Works

```
USER
  |
  |  "Solve this GitHub issue"
  v
+---------------------------------------------------------+
|                   KEKULE ORCHESTRATOR                    |
|                                                         |
|  1. PLAN       2. SWARM           3. VERIFY    4. LEARN |
|  ──────────    ──────────         ──────────   ──────── |
|  Planner       Coding agents      Oracle       Waypoint |
|  decomposes    + oracle agents     tests run   coord.   |
|  into roles    work in parallel    in Docker   extracts |
|  & deps        via SwarmBus        (pytest)    lessons  |
|                                                         |
|  Roles:        Communication:      Strategies:  Adjusts:|
|  - root_cause  - SwarmBus msgs     - unit_test  - prompts|
|  - fix_impl    - BeadsTracker DAG  - regression - oracle |
|  - oracle_*    - SwarmHooks auto   - behavioral   config |
+---------------------------------------------------------+
         |                                    |
         v                                    v
    Git patch                          Next epoch
    (SWE-bench eval)                   (self-improving)
```

Kekule runs multiple agents in parallel on real GitHub issues (SWE-bench). Each agent gets a specialist role. Oracle agents generate verification tests alongside coding agents. After each round, oracle tests gate acceptance. Across epochs, a waypoint coordinator analyzes results and tunes prompts, oracle strategies, and agent composition.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for SWE-bench evaluation)
- `ANTHROPIC_API_KEY` environment variable

### Option 1: Docker

```bash
docker build -t kekule .
docker run -e ANTHROPIC_API_KEY=sk-ant-... kekule uv run kekule-bench --help
```

### Option 2: Local Setup

```bash
# Install dependencies
uv sync --extra benchmarks

# Set up environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run a single-agent SWE-bench experiment
uv run kekule-bench --problems 2 --agents-per-problem 1 --skip-eval

# Run the self-improving oracle swarm
uv run kekule-improve \
  --solver oracle_swarm \
  --problems 5 \
  --epochs 3 \
  --skip-eval
```

### Option 3: Perturbation Swarm (multi-agent)

```bash
uv run kekule-bench \
  --solver perturbation_swarm \
  --problems 2 \
  --agents-per-problem 3 \
  --skip-eval
```

---

## Architecture

### Four Subsystems

#### 1. SWE-bench Harness (`benchmarks/harness.py`)

Orchestrates full experiments: loads tasks from SWE-bench Lite, clones repos into isolated workspaces, spawns solver agents in parallel, collects git patches, and runs Docker-based evaluation.

```bash
uv run kekule-bench --problems 5 --agents-per-problem 2 --skip-eval
```

#### 2. Swarm Infrastructure (`benchmarks/swarm_*.py`)

Coordination primitives for multi-agent collaboration:

| Module | Purpose |
|--------|---------|
| `swarm_bus.py` | In-memory message bus with cursor-based reads |
| `swarm_beads.py` | DAG-based task tracking exposed as MCP tools |
| `swarm_hooks.py` | Intercepts tool calls, auto-posts findings |

#### 3. Oracle System (`oracle/`)

Turns verification rules into executable pytest tests, runs them in sandboxed Docker containers (`--network=none`, `--memory=512m`), and returns pass/fail with evidence. Includes a 3-phase rule elicitation pipeline (converse, generate, review).

```bash
uv run python -m kekule.oracle run --rules rules.json --repo ./project
```

#### 4. Self-Improving Loop (`benchmarks/self_improving_harness.py`)

Outer loop that runs multiple epochs of solving with cross-epoch learning:

1. **Inner loop**: Swarm + oracles solve tasks, oracle tests gate acceptance
2. **Outer loop**: Waypoint coordinator analyzes train results, adjusts prompts/strategies/composition
3. **Generalization**: Train/test split prevents overfitting (coordinator sees full logs for train, only pass/fail for test)

```bash
uv run kekule-improve --solver oracle_swarm --epochs 3 --problems 10
```

---

## Dashboard UI

A web UI for browsing experiment results, failure diagnoses, and score progression across epochs.

### Start the dashboard

```bash
uv run python3 -m uvicorn kekule.ui.app:app --reload --port 8000
```

Then visit:

| Route | Description |
|-------|-------------|
| `/experiments` | List all self-improving experiments with score progression |
| `/experiments/<name>` | Epoch details, coordinator output, failure diagnoses |
| `/benchmarks` | Standalone benchmark run results |
| `/api/experiments` | JSON API for programmatic access |

---

## CLI Reference

### `kekule-bench` -- SWE-bench Experiment Runner

| Flag | Default | Description |
|------|---------|-------------|
| `--solver` | `default` | Solver: `default`, `perturbation_swarm`, `oracle_swarm` |
| `--problems` | `3` | Number of SWE-bench tasks |
| `--agents-per-problem` | `1` | Agents per task (best-of-N) |
| `--iterations` | `1` | Retry iterations |
| `--model` | `claude-opus-4-5` | Model for solver agents |
| `--dataset` | `lite` | `lite` (300 tasks) or `full` (2294) |
| `--task-ids` | -- | Specific task IDs to solve |
| `--skip-eval` | off | Skip Docker evaluation |
| `--experiment-name` | auto | Name for results directory |
| `--dry-run` | off | Print config and exit |

### `kekule-improve` -- Self-Improving Oracle Swarm

| Flag | Default | Description |
|------|---------|-------------|
| `--solver` | `oracle_swarm` | Solver module |
| `--epochs` | `3` | Self-improving epochs |
| `--train-ids` | -- | Explicit train task IDs |
| `--test-ids` | -- | Explicit test task IDs |
| `--train-ratio` | `0.7` | Auto train/test split ratio |
| `--problems` | `3` | Number of problems (auto-split) |
| `--enable-chatoverflow` | off | Enable Q&A forum integration |
| `--prompts-dir` | -- | Custom prompt overrides |
| `--export-prompts` | -- | Export default prompts |
| `--skip-eval` | off | Skip Docker evaluation |

### `kekule-oracle` -- Oracle Verification

```bash
uv run python -m kekule.oracle generate --rules rules.json --repo ./project
uv run python -m kekule.oracle run --rules rules.json --repo ./project
uv run python -m kekule.oracle elicit --repo ./project --output rules.json
```

---

## Project Structure

```
src/kekule/
  main.py                          # Demo agents
  solver/                          # Expert question-solving agent
    agent.py                       #   ClaudeSDKClient session
    schemas.py                     #   Question/SolverResponse models
  benchmarks/                      # SWE-bench harness + swarm
    harness.py                     #   Main orchestrator
    solver_agent.py                #   Default single-agent solver
    config.py                      #   HarnessConfig
    task_selector.py               #   SWE-bench Lite loader
    evaluator.py                   #   Docker eval + results
    tracing.py                     #   LangFuse integration
    swarm_bus.py                   #   Inter-agent message bus
    swarm_beads.py                 #   Task dependency DAG (MCP tools)
    swarm_hooks.py                 #   Tool-call interception
    failure_analyst.py             #   Post-mortem failure diagnosis
    oracle_bridge.py               #   Multi-strategy oracle system
    waypoint_coordinator.py        #   Cross-epoch learning agent
    prompt_config.py               #   Prompt load/save/snapshot
    task_splitter.py               #   Deterministic train/test split
    self_improving_harness.py      #   Outer loop orchestrator
    solvers/
      default.py                   #   Single-agent solver
      perturbation_swarm.py        #   Multi-agent role-based solver
      oracle_swarm.py              #   Swarm + oracle feedback loop
  oracle/                          # Oracle verification system
    agent.py                       #   Test generation agent
    runner.py                      #   Docker execution engine
    schemas.py                     #   Rule, OracleResult models
    __main__.py                    #   CLI (generate/run/elicit)
    elicitor/                      #   3-phase rule elicitation
  ui/                              # Dashboard backend (FastAPI)
    app.py                         #   FastAPI app + routes
    models.py                      #   API models
    state.py                       #   Persistence
    benchmark_scanner.py           #   Scan evaluation results
    routes/                        #   REST endpoints
    templates/                     #   Jinja2 HTML templates
  ui-frontend/                     # Dashboard frontend (React)
    src/                           #   Pages + components
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `CHATOVERFLOW_API_URL` | No | ChatOverflow forum URL |
| `CHATOVERFLOW_API_KEY` | No | ChatOverflow API key |
| `LANGFUSE_SECRET_KEY` | No | LangFuse tracing (secret) |
| `LANGFUSE_PUBLIC_KEY` | No | LangFuse tracing (public) |
| `LANGFUSE_BASE_URL` | No | LangFuse host URL |

---

## Benchmark Data

Evaluation results, logs, and experiment artifacts are on the [`data`](../../tree/data) branch to keep this branch focused on code.

---

## Claude Agent SDK Patterns

| Pattern | Where | Purpose |
|---------|-------|---------|
| `query()` stateless | Oracle agent, solvers, reviewers | Fire-and-forget streaming |
| `ClaudeSDKClient` stateful | Conversation agent, expert solver | Multi-turn sessions |
| `create_sdk_mcp_server()` | `swarm_beads.py` | Custom MCP tools for agents |
| PostToolUse hooks | `swarm_hooks.py` | Auto-coordination on tool calls |
| `bypassPermissions` | All automated agents | No approval prompts |

---

## Development

```bash
uv sync --extra dev --extra benchmarks   # Install everything
uv run pytest                            # Run tests
uv run ruff check .                      # Lint
uv run ruff format .                     # Format
uv run mypy src/                         # Type check
```

---

## Documentation

- [TLDR.md](TLDR.md) -- Full architecture overview with diagrams
- [docs/self-improving-swarm.md](docs/self-improving-swarm.md) -- Self-improving loop design
- [docs/benchmarks.md](docs/benchmarks.md) -- SWE-bench harness guide
- [docs/custom-solvers.md](docs/custom-solvers.md) -- Build your own solver
- [docs/oracle.md](docs/oracle.md) -- Oracle system guide
- [docs/perturbation-protocol.md](docs/perturbation-protocol.md) -- Multi-agent protocol

## License

MIT

## Acknowledgments

- Inspired by August Kekule's ouroboros dream and the power of analogical reasoning
- Built with Claude Opus 4.6 for the Cerebral Valley x Anthropic hackathon
