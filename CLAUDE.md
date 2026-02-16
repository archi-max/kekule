# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kekule is a heterarchical swarm of agents aimed to self-organize to solve problems and explore frontier capabilities of models in swarm settings. Named after August Kekule's famous ouroboros dream that led to discovering benzene's ring structure, the project explores how analogical reasoning and structured exploration can unlock breakthrough capabilities in agent swarms.

**Built for**: Built with Opus 4.6: a Claude Code hackathon (Cerebral Valley & Anthropic)

**Team**: Ansh Tulsyan & Jack Armitage

**Tech Stack**: Python 3.11+, uv package manager, Claude Agent SDK (Opus 4.6)

**Key Dependencies**:
- `claude-agent-sdk` - Build autonomous agents with tools (Read, Write, Bash, WebSearch, etc.)
- `httpx` - HTTP client for API interactions
- `pydantic` / `pydantic-settings` - Data validation and configuration
- `datasets` (optional) - HuggingFace datasets for SWE-bench
- `swebench` (optional) - Official SWE-bench evaluation harness
- `langfuse` (optional) - Tracing and observability

## Development Commands

### Environment Setup
```bash
uv sync                        # Install core dependencies
uv sync --extra dev            # Install with dev dependencies
uv sync --extra benchmarks     # Install with SWE-bench + LangFuse
uv sync --extra dev --extra benchmarks  # Install everything
```

### Running Code
```bash
# Run the agent SDK examples
uv run python -m kekule.main

# Run the SWE-bench harness
uv run kekule-bench --help
uv run kekule-bench --dry-run
uv run kekule-bench --problems 1 --agents-per-problem 1 --iterations 1 --skip-eval

# Run with a custom solver and experiment name
uv run kekule-bench --solver my_solver --experiment-name "my-experiment" --problems 2 --skip-eval

# Run the standalone solver on a question file
uv run python -m kekule.solver.main solve input/question.json
```

### Testing & Quality
```bash
uv run pytest              # Run all tests
uv run pytest tests/path/to/test.py  # Run specific test file
uv run pytest -k test_name # Run specific test by name
uv run pytest --cov        # Run tests with coverage

uv run ruff check .        # Lint code
uv run ruff format .       # Format code
uv run mypy src/           # Type check
```

### Dependencies
```bash
uv add package-name        # Add a new dependency
uv add --dev package-name  # Add a dev dependency
uv remove package-name     # Remove a dependency
```

## Architecture

### Project Structure

```
src/kekule/
  __init__.py           # Package root
  main.py               # Demo agents (simple query, code analysis)
  solver/               # Expert Solver Agent
    agent.py            # Core agent using ClaudeSDKClient
    schemas.py          # Question/SolverResponse dataclasses
    utils.py            # File I/O, status tracking, MCP config loading
    api_client.py       # ChatOverflow API client (optional skill)
  benchmarks/           # SWE-bench Evaluation Harness
    harness.py          # Main orchestrator (entry point)
    solver_agent.py     # Default solver using claude_agent_sdk.query()
    config.py           # HarnessConfig dataclass
    task_selector.py    # SWE-bench Lite dataset loader + task picker
    evaluator.py        # Predictions writer + Docker-based evaluation
    tracing.py          # LangFuse tracing + conversation capture
    swarm_bus.py        # Inter-agent message bus
    swarm_beads.py      # Task dependency DAG (MCP tools)
    swarm_hooks.py      # Tool-call interception + auto-coordination
    failure_analyst.py  # Post-mortem failure diagnosis
    oracle_bridge.py    # Multi-strategy oracle system
    waypoint_coordinator.py  # Cross-epoch learning agent
    prompt_config.py    # Prompt load/save/snapshot
    task_splitter.py    # Deterministic train/test split
    self_improving_harness.py  # Outer loop orchestrator
    solvers/            # Pluggable solver modules (--solver flag)
      default.py        # Re-exports solver_agent.solve_swe_task
      perturbation_swarm.py  # Multi-agent role-based solver
      oracle_swarm.py   # Swarm + oracle feedback loop
  oracle/               # Oracle verification system
    agent.py            # Test generation agent
    runner.py           # Docker execution engine
    schemas.py          # Rule, OracleResult models
    __main__.py         # CLI (generate/run/elicit)
    elicitor/           # 3-phase rule elicitation pipeline
  ui/                   # Dashboard backend (FastAPI)
    app.py              # FastAPI app + routes
    models.py           # API models
    state.py            # Persistence
    benchmark_scanner.py  # Scan evaluation results
    routes/             # REST endpoints
    templates/          # Jinja2 HTML templates
  ui-frontend/          # Dashboard frontend (React + Vite + Tailwind)
```

### Core Concepts

**Heterarchical Organization**: Unlike traditional hierarchical systems with fixed roles, Kekule allows agents to self-organize into different patterns based on task requirements.

**Two Agent Patterns**:
1. **Expert Solver** (`solver/`) - Stateful agent using `ClaudeSDKClient` for solving individual questions with MCP tools
2. **SWE-bench Solver** (`benchmarks/solver_agent.py`) - Stateless agent using `query()` for solving GitHub issues in isolated repo workspaces

**SWE-bench Harness** (`benchmarks/`) - Full experiment orchestrator that runs N agents x M problems x K iterations in parallel, collects git patches, and evaluates them against the official SWE-bench Docker harness.

### How the Solver Agent Works

The solver agent (`src/kekule/solver/agent.py`) uses the `ClaudeSDKClient` class from the Claude Agent SDK:

1. Receives a `Question` (title, body, context, tags, previous attempts)
2. Builds a system prompt (claude_code preset + expert solver instructions)
3. Configures MCP servers (Context7 for docs, ChatOverflow optionally)
4. Opens a `ClaudeSDKClient` session and sends the question as a prompt
5. Streams the response, tracking tool usage and code snippets
6. Parses the final response to extract confidence and answer/attempt classification
7. Returns a `SolverResponse` saved to disk

### How the SWE-bench Harness Works

See `docs/benchmarks.md` for detailed flowcharts and architecture diagrams.

The harness (`src/kekule/benchmarks/harness.py`) orchestrates the full experiment:

1. **Task Selection** - Loads SWE-bench Lite from HuggingFace, picks tasks
2. **Repo Caching** - Clones repos once into a shared cache (shallow clone + fetch)
3. **Workspace Setup** - Copies cached repos into per-agent isolated workspaces
4. **Agent Execution** - Spawns Claude Agent SDK agents in parallel with concurrency limits
5. **Patch Collection** - Extracts `git diff` from each agent's workspace
6. **Evaluation** - Runs official SWE-bench Docker evaluation on collected patches
7. **Reporting** - Writes predictions JSONL, per-agent results, best-of-N selection

### Telemetry & Observability

See `docs/telemetry.md` for the full guide on configuring Langfuse tracing and OpenTelemetry.

### Building Custom Solvers

See `docs/custom-solvers.md` for the full guide on building your own solver agents.

The solver is a pluggable `solve_swe_task()` async function. To create a custom solver:
1. Copy `solver_agent.py` as a starting point
2. Customize the system prompt, tools, or multi-pass strategy
3. Change the import in `harness.py` to use your solver
4. Run the harness -- everything else (cloning, eval, reporting) is handled for you

Patterns documented: different prompts, multi-pass solving, swarm with shared knowledge, tool-restricted agents, model comparison, and A/B testing via solver dispatch.

### Claude Agent SDK Usage

**Two usage patterns** are demonstrated:

**1. `query()` - Stateless streaming (used in benchmarks)**
```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Your task here",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Bash"],
        permission_mode="bypassPermissions",
        system_prompt={"type": "preset", "preset": "claude_code", "append": "..."}
    )
):
    # Handle AssistantMessage, ResultMessage
    pass
```

**2. `ClaudeSDKClient` - Stateful session (used in solver)**
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

async with ClaudeSDKClient(options=options) as client:
    await client.query(prompt)
    async for message in client.receive_response():
        # Handle messages
        pass
```

**Permission Modes**:
- `default` - Requires approval for each tool use
- `acceptEdits` - Auto-approves file edits, prompts for other actions
- `bypassPermissions` - Runs without prompts (for CI/CD and benchmarks)

## Environment Variables

Create a `.env` file based on `.env.example`:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `CHATOVERFLOW_API_URL` | No | ChatOverflow forum URL (default: `https://www.chatoverflow.dev`) |
| `CHATOVERFLOW_API_KEY` | No | ChatOverflow API key for forum interactions |
| `LANGFUSE_SECRET_KEY` | No | LangFuse secret key (enables conversation tracing) |
| `LANGFUSE_PUBLIC_KEY` | No | LangFuse public key |
| `LANGFUSE_BASE_URL` | No | LangFuse host URL (e.g., `https://cloud.langfuse.com`) |
| `CLAUDE_CODE_ENABLE_TELEMETRY` | No | Enable OTel metrics/events (set to `1`; see `docs/telemetry.md`) |

## Code Style

- Use type hints for all function signatures
- Follow PEP 8 style guide (enforced by ruff)
- Write docstrings for all public functions and classes
- Keep functions focused and composable
- Use Pydantic for configuration and data validation
- Design for agent autonomy and self-organization
