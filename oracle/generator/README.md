# Oracle Generator

Turns user-defined Rules into executable verification artifacts (test suites, configs, scripts) that gate waypoint completion.

## Concept

See [../THEORY.md](../THEORY.md) for the full architecture. This project implements the **Oracle Swarm** — the agent(s) that read structured rules and produce deterministic verification artifacts.

## What This Does

```
Rule (structured acceptance criteria)
  -> Oracle Agent reads rule + repo context
    -> Generates verification artifact (pytest, Playwright, pixel-match, etc.)
      -> Artifact executes deterministically against codebase
        -> Pass/Fail with evidence
```

## Core Components to Build

### 1. Rule Schema (`schemas.py`)
- `Rule` dataclass: id, description, oracle_type, oracle_config, uncertainty, waypoint_id
- `Waypoint` dataclass: id, description, rules, beads_task_id, git_ref, status
- `OracleResult` dataclass: rule_id, passed, evidence, artifact_path, execution_time

### 2. Rule Elicitor (`elicitor.py`)
- Conversational agent that turns user NLP into structured Rules
- Uses Claude Agent SDK (`ClaudeSDKClient` or `query()`)
- Pushes rules toward concreteness (reduces uncertainty)
- Collaborative: proposes rules, user confirms/modifies

### 3. Oracle Agent (`agent.py`)
- Takes a Rule + repo context as input
- Detects project stack (Python/JS/Go/etc.)
- Generates the appropriate verification artifact:
  - `pytest` -> writes test file
  - `e2e` -> writes Playwright/Cypress script
  - `pixel_match` -> writes screenshot comparison config
  - `type_check` -> configures mypy/tsc run
  - `security` -> configures bandit/semgrep
  - `load` -> writes k6/locust script
- Saves artifact to `oracle_artifacts/<waypoint_id>/<rule_id>/`

### 4. Oracle Runner (`runner.py`)
- Executes all oracle artifacts for a given waypoint
- Collects pass/fail results with evidence (stdout, screenshots, diffs)
- Returns structured `OracleResult` list
- Supports parallel execution of independent oracles

### 5. Waypoint Decomposer (`waypoints.py`)
- Collaborative agent that decomposes user goals into waypoints
- Assigns rules to waypoints
- Integrates with beads for dependency tracking
- Generates waypoint DAG

## Integration Points

- **Beads**: Each waypoint = a bead task. Dependencies = bead deps.
- **SwarmBus**: Oracle agents communicate findings via the existing bus.
- **Git**: Waypoint completion = git commit. Rollback = git reset to previous waypoint.
- **Coding Swarm**: Oracle artifacts are written to the repo; coding swarm's output is tested against them.

## Tech Stack

- Python 3.11+
- Claude Agent SDK (query() or ClaudeSDKClient)
- pytest, Playwright, mypy, ruff, bandit, etc. as oracle execution tools
- Beads (`bd` CLI) for waypoint dependency tracking
- Pydantic for schemas

## Directory Structure (proposed)

```
oracle/generator/
  src/
    oracle_generator/
      __init__.py
      schemas.py        # Rule, Waypoint, OracleResult
      elicitor.py       # Rule elicitation agent
      agent.py          # Oracle-generating agent
      runner.py         # Oracle execution engine
      waypoints.py      # Waypoint decomposition
      oracle_types/     # Per-type oracle generators
        __init__.py
        pytest_oracle.py
        e2e_oracle.py
        pixel_oracle.py
        type_check_oracle.py
        security_oracle.py
  tests/
    test_schemas.py
    test_elicitor.py
    test_runner.py
  pyproject.toml
```

## Running

```bash
# From the kekule root
uv run python -m oracle_generator.elicitor   # Interactive rule elicitation
uv run python -m oracle_generator.agent      # Generate oracles from rules
uv run python -m oracle_generator.runner     # Execute oracle battery
```
