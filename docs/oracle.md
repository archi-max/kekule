# Oracle Generator

The Oracle Generator turns structured **Rules** into executable **pytest tests**, runs them in **Docker containers**, and returns **pass/fail results with evidence**. It uses the Claude Agent SDK to autonomously explore a codebase and write verification artifacts.

## How It Works

```
rules.json                    # User-defined acceptance criteria
  |
  v
Oracle Agent (Claude SDK)     # Explores repo, writes pytest test file per rule
  |
  v
Docker Container              # Isolated execution: --network=none, resource-limited
  |
  v
OracleResult                  # pass/fail, stdout/stderr evidence, exit code, timing
```

The pipeline separates **intent** (rules), **verification** (AI-generated tests), and **execution** (Docker). The AI writes the tests; Docker runs them deterministically.

---

## Prerequisites

- Python 3.11+
- Docker (daemon must be running)
- `ANTHROPIC_API_KEY` set in environment
- The `kekule` package installed (`uv sync`)

If Docker gives permission errors:

```bash
sudo chown root:docker /var/run/docker.sock
```

---

## Quick Start

### 1. Write a rules file

```json
{
  "rules": [
    {
      "id": "divide_by_zero_raises",
      "description": "Calculator.divide(a, 0) must raise ZeroDivisionError for any value of a",
      "oracle_type": "pytest",
      "oracle_config": {
        "target_module": "src/calculator/core.py",
        "class": "Calculator",
        "method": "divide"
      },
      "uncertainty": 0.0,
      "status": "confirmed"
    }
  ]
}
```

### 2. Generate test artifacts

```bash
python -m kekule.oracle generate \
  --rules rules.json \
  --repo /path/to/repo
```

A Claude Agent SDK agent explores the repo and writes a pytest file per rule into `oracle_artifacts/<rule_id>/`.

### 3. Run in Docker

```bash
python -m kekule.oracle run \
  --rules rules.json \
  --repo /path/to/repo
```

Each test runs in an isolated container. Output:

```
============================================================
ORACLE RESULTS
============================================================
  [PASS] divide_by_zero_raises (exit_code=0, 31.2s)

Total: 1 | Passed: 1 | Failed: 0
============================================================
```

### 4. Or elicit rules interactively

```bash
python -m kekule.oracle elicit \
  --repo /path/to/repo \
  --intent "verify the temperature converter handles edge cases" \
  --output rules.json
```

A Claude agent explores the repo and proposes concrete, testable rules as JSON.

---

## CLI Reference

### `python -m kekule.oracle generate`

Generate pytest test files from rules without executing them.

| Flag | Required | Default | Description |
|---|---|---|---|
| `--rules PATH` | Yes | | Path to rules JSON file |
| `--repo PATH` | Yes | | Path to local repository |
| `--output-dir PATH` | No | `<repo>/oracle_artifacts/<rule_id>/` | Output directory for test files |
| `--model MODEL` | No | `claude-sonnet-4-5` | Claude model for generation |
| `--max-turns N` | No | `30` | Max agent turns per rule |
| `--max-parallel N` | No | `3` | Max concurrent agent generations |

### `python -m kekule.oracle run`

Generate test files **and** execute them in Docker containers.

| Flag | Required | Default | Description |
|---|---|---|---|
| `--rules PATH` | Yes | | Path to rules JSON file |
| `--repo PATH` | Yes | | Local repo path or `https://` / `git@` URL |
| `--commit SHA` | For URLs | | Git commit SHA to checkout |
| `--docker-image IMAGE` | No | `python:3.11-slim` | Base Docker image |
| `--timeout SECONDS` | No | `300` | Per-container timeout |
| `--output-dir PATH` | No | auto | Artifact output directory |
| `--model MODEL` | No | `claude-sonnet-4-5` | Claude model for generation |
| `--max-parallel N` | No | `3` | Max concurrent containers |

Exits with code 1 if any oracle fails.

### `python -m kekule.oracle elicit`

Interactively generate rules by having Claude explore a repo.

| Flag | Required | Default | Description |
|---|---|---|---|
| `--repo PATH` | Yes | | Path to local repository |
| `--intent TEXT` | No | auto-detect | What to verify (natural language) |
| `--model MODEL` | No | `claude-sonnet-4-5` | Claude model |
| `--output PATH` | No | stdout | Save rules JSON to file |

---

## Rule Format

### Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | string | Yes | | Unique identifier, `snake_case` |
| `description` | string | Yes | | What to verify -- must be concrete enough to write a test from |
| `oracle_type` | string | No | `"pytest"` | Artifact type (only `"pytest"` currently) |
| `oracle_config` | object | No | `{}` | Hints for the agent: target module, expected behavior, test cases |
| `uncertainty` | float | No | `0.5` | 0.0 = very clear, 1.0 = vague |
| `status` | string | No | `"draft"` | `"draft"`, `"confirmed"`, or `"verified"` |

### File format

Two JSON layouts are accepted:

```json
{"rules": [{"id": "...", "description": "..."}, ...]}
```

```json
[{"id": "...", "description": "..."}, ...]
```

### Writing effective rules

**Specific and testable (good):**

```json
{
  "id": "mean_empty_raises",
  "description": "Statistics.mean([]) must raise ValueError with a message containing 'empty'",
  "oracle_config": {
    "target_module": "src/calculator/stats.py",
    "class": "Statistics",
    "method": "mean"
  },
  "uncertainty": 0.0
}
```

**Vague and untestable (bad):**

```json
{
  "id": "stats_work",
  "description": "The statistics module should work correctly",
  "uncertainty": 0.9
}
```

Guidelines:

- **One behavior per rule.** "add returns correct sums" and "add records history" should be two separate rules.
- **Name the target.** Put `target_module`, `class`, and `method` in `oracle_config` so the agent knows where to look.
- **Include test cases.** If you know the expected inputs and outputs, list them in `oracle_config`. The agent uses them directly.
- **Set uncertainty honestly.** Low uncertainty (0.0-0.2) means the description is unambiguous. High uncertainty (0.7+) means the agent may guess wrong.

### `oracle_config` examples

**Concrete test cases:**

```json
{
  "oracle_config": {
    "target_module": "src/calculator/core.py",
    "class": "Calculator",
    "method": "add",
    "test_cases": [
      {"a": 2, "b": 3, "expected": 5},
      {"a": -1, "b": -1, "expected": -2}
    ]
  }
}
```

**Expected exceptions:**

```json
{
  "oracle_config": {
    "target_module": "src/calculator/core.py",
    "method": "divide",
    "expected_exception": "ZeroDivisionError",
    "normal_cases": [
      {"a": 10, "b": 2, "expected": 5.0}
    ]
  }
}
```

**Roundtrip / property-based:**

```json
{
  "oracle_config": {
    "target_module": "src/calculator/converter.py",
    "class": "TemperatureConverter",
    "test_values": [0, 100, -40, 37.5, -273.15],
    "tolerance": 1e-9
  }
}
```

---

## Docker Execution

### What happens per oracle

1. A temporary **build context** is created:
   ```
   /tmp/kekule-oracle-<rule_id>-XXXX/
     repo/           # Copy of the codebase (no .git, __pycache__, node_modules)
     oracle_tests/   # The generated test file
     Dockerfile      # Auto-generated
     .dockerignore   # Excludes .git, __pycache__, .venv, etc.
   ```

2. A **Dockerfile** is generated that auto-detects dependencies:
   - `pyproject.toml` found -> `pip install .`
   - `requirements.txt` found -> `pip install -r requirements.txt`
   - `setup.py` found -> `pip install .`
   - pytest is always installed

3. `docker build` creates the image.

4. `docker run` executes with constraints:
   - `--network=none` -- no network access (tests must be self-contained)
   - `--memory=512m` -- prevents memory exhaustion
   - `--cpus=1` -- prevents CPU hogging
   - `--rm` -- container is removed after exit

5. Exit code, stdout, and stderr are captured into an `OracleResult`.

6. Image and build context are cleaned up.

### Parallelism

Multiple oracles run concurrently (controlled by `--max-parallel`). Each gets its own container. The default is 3 concurrent containers.

### Timeouts

If a container exceeds `--timeout` seconds (default 300), it is killed and the oracle reports `FAIL` with a timeout message.

---

## Architecture

### Source files

```
src/kekule/oracle/
  __init__.py       # Package root, re-exports public API
  schemas.py        # Pydantic models: Rule, OracleResult, OracleRunRequest
  elicitor.py       # load_rules_from_file() + elicit_rules() via Claude SDK
  agent.py          # generate_oracle() + generate_all_oracles() via Claude SDK
  runner.py         # Docker lifecycle: Dockerfile generation, build, run, cleanup
  __main__.py       # CLI: generate / run / elicit subcommands
```

### Key functions

**`schemas.py`** -- Pydantic models validated on construction.

```python
from kekule.oracle import Rule, OracleResult, OracleRunRequest

rule = Rule(id="my_rule", description="X should do Y")
result = OracleResult(rule_id="my_rule", passed=True, exit_code=0)
request = OracleRunRequest(repo_path="/path", rules=[rule])
```

**`elicitor.py`** -- Load rules or generate them.

```python
from kekule.oracle.elicitor import load_rules_from_file, elicit_rules

# From file
rules = load_rules_from_file("rules.json")

# Interactive (async)
rules = await elicit_rules(repo_path="/path/to/repo", user_intent="verify auth")
```

**`agent.py`** -- Generate test files.

```python
from kekule.oracle.agent import generate_oracle, generate_all_oracles

# Single rule (async)
test_path = await generate_oracle(rule, repo_path="/path/to/repo")

# Multiple rules with concurrency (async)
artifact_paths = await generate_all_oracles(rules, repo_path="/path/to/repo")
# Returns: {"rule_id": Path("oracle_artifacts/rule_id/test_oracle_rule_id.py")}
```

**`runner.py`** -- Execute in Docker.

```python
from kekule.oracle.runner import run_oracles

results = await run_oracles(request, artifact_paths, max_parallel=3)
for r in results:
    print(f"{'PASS' if r.passed else 'FAIL'} {r.rule_id}: {r.evidence[:100]}")
```

### How the agent works

The oracle agent uses `claude_agent_sdk.query()` in stateless streaming mode:

```python
options = ClaudeAgentOptions(
    system_prompt={"type": "preset", "preset": "claude_code", "append": ORACLE_AGENT_SYSTEM_PROMPT},
    model="claude-sonnet-4-5",
    permission_mode="bypassPermissions",
    cwd=str(repo_path),
    allowed_tools=["Read", "Write", "Glob", "Grep", "Bash"],
    max_turns=30,
)

async for message in query(prompt=prompt, options=options):
    ...
```

The agent receives the rule description and `oracle_config` as a prompt, explores the repo using built-in tools, and writes a pytest file using the `Write` tool. It follows the same pattern as `kekule.benchmarks.solver_agent`.

---

## Sample Project

A sample calculator project is included for testing:

```
oracle/generator/samples/
  calculator/                  # Sample Python project
    pyproject.toml
    src/calculator/
      __init__.py
      core.py                  # Calculator: add, subtract, multiply, divide, power, modulo, memory, history
      converter.py             # TemperatureConverter, LengthConverter
      stats.py                 # Statistics: mean, median, variance, std_dev, percentile
      validator.py             # InputValidator: is_numeric, parse_number, parse_expression
  rules_basic.json             # 5 rules covering all 4 modules
  rules_single.json            # 1 rule (for quick testing)
```

### Run the sample end-to-end

```bash
# Generate artifacts only
python -m kekule.oracle generate \
  --rules oracle/generator/samples/rules_basic.json \
  --repo oracle/generator/samples/calculator

# Generate + run in Docker
python -m kekule.oracle run \
  --rules oracle/generator/samples/rules_basic.json \
  --repo oracle/generator/samples/calculator
```

The 5 sample rules cover:

| Rule ID | What it verifies |
|---|---|
| `calc_add_basic` | `Calculator.add` with positive, negative, and zero operands |
| `calc_divide_by_zero` | `Calculator.divide` raises `ZeroDivisionError` on zero divisor |
| `temp_converter_roundtrip` | Celsius/Fahrenheit/Kelvin roundtrip within floating-point tolerance |
| `stats_mean_basic` | `Statistics.mean` returns correct average, raises on empty list |
| `validator_parse_expression` | `InputValidator.parse_expression` parses `"3 + 4"` -> `(3.0, "+", 4.0)` |

### Verified results

All 5 rules generate valid tests (51 test functions total) that pass both locally and inside Docker containers.

---

## Programmatic Usage

Use the oracle as a library in your own scripts:

```python
import asyncio
from pathlib import Path
from kekule.oracle.elicitor import load_rules_from_file
from kekule.oracle.agent import generate_all_oracles
from kekule.oracle.runner import run_oracles
from kekule.oracle.schemas import OracleRunRequest

async def verify_repo(repo_path: str, rules_file: str):
    # Load rules
    rules = load_rules_from_file(rules_file)

    # Generate test artifacts
    artifacts = await generate_all_oracles(
        rules=rules,
        repo_path=repo_path,
        model="claude-sonnet-4-5",
        max_parallel=3,
    )

    # Run in Docker
    request = OracleRunRequest(repo_path=repo_path, rules=rules)
    results = await run_oracles(request, artifacts)

    # Process results
    for r in results:
        if not r.passed:
            print(f"FAILED: {r.rule_id}")
            print(r.evidence)

    return all(r.passed for r in results)

ok = asyncio.run(verify_repo("./my-project", "rules.json"))
```

---

## Extending

### Adding oracle types

Currently only `pytest` is supported. To add a new type (e.g., `mypy`, `ruff`, `bandit`):

1. Add the value to `OracleType` in `schemas.py`:
   ```python
   class OracleType(str, Enum):
       PYTEST = "pytest"
       TYPE_CHECK = "type_check"  # new
   ```

2. Add a type-specific system prompt in `agent.py` and branch on `rule.oracle_type`.

3. Update `_generate_dockerfile()` in `runner.py` to install the required tool in the Docker image.

### Customizing the Docker image

Use `--docker-image` to specify a different base:

```bash
python -m kekule.oracle run \
  --rules rules.json \
  --repo ./my-project \
  --docker-image python:3.12-bookworm
```

This is useful when your project requires system-level dependencies not available in `python:3.11-slim`.
