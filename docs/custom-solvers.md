# Building Custom Solvers for SWE-bench

This guide explains how to build your own solver agents and plug them into the Kekule SWE-bench harness. The architecture is designed for experimentation -- you can create arbitrary solver strategies, run them as a swarm, and compare results.

## Architecture: How Solvers Plug In

```
                        harness.py (orchestrator)
                              |
                    +---------+---------+
                    |                   |
              run_iteration()     run_iteration()
                    |                   |
          +---------+---------+         ...
          |         |         |
    solve_swe_task  solve_swe_task  solve_swe_task
    (your solver)   (your solver)   (your solver)
          |         |         |
          v         v         v
      git diff   git diff   git diff
          |         |         |
          +----+----+----+----+
               |
         best-of-N selection
               |
         SWE-bench Docker eval
```

The key function the harness calls for each agent is `solve_swe_task()`. This is where your custom solver logic lives. The harness handles everything else: cloning repos, managing workspaces, collecting patches, running evaluation.

## Quick Start: Create a Custom Solver

### Step 1: Create your solver file

Create a new file at `src/kekule/benchmarks/solvers/my_solver.py`:

```python
"""
My custom SWE-bench solver.
"""

import asyncio
import time
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from .config import HarnessConfig
from .task_selector import SWETask
from .tracing import AgentTraceData


# Your custom system prompt -- this is where the magic happens
MY_SYSTEM_PROMPT = """
You are an expert software engineer. You have a specific methodology:

1. First, read the failing test (if any) to understand the expected behavior
2. Then trace the code path from the test to the bug
3. Make the minimal fix
4. Verify by running the relevant tests

Do NOT create branches or commits. Edit files directly.
"""


def build_prompt(task: SWETask) -> str:
    """Build the prompt for your solver."""
    return f"""## Issue: {task.instance_id}

**Repo:** {task.repo}

### Problem
{task.problem_statement}

The repo is checked out at commit `{task.base_commit}`. Fix the issue.
"""


async def solve_swe_task(
    task: SWETask,
    agent_id: str,
    workspace_dir: Path,
    ref_repo_dir: Path,
    config: HarnessConfig,
    trace_data: AgentTraceData,
    agent_api_key: str = "",
) -> dict:
    """
    Your custom solver implementation.

    This function signature MUST match the one in solver_agent.py.
    The harness calls this for each agent.
    """
    import subprocess

    start_time = time.time()

    # Setup workspace (copy reference repo)
    from .solver_agent import setup_workspace, extract_patch
    try:
        repo_dir = await asyncio.to_thread(
            setup_workspace, task, workspace_dir, ref_repo_dir
        )
    except Exception as e:
        trace_data.error = f"workspace_setup: {e}"
        return {
            "instance_id": task.instance_id,
            "model_name_or_path": f"kekule-my-solver-{config.model}",
            "model_patch": "",
            "agent_id": agent_id,
            "error": str(e),
        }

    # --- YOUR CUSTOM AGENT LOGIC HERE ---

    options = ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": MY_SYSTEM_PROMPT,
        },
        model=config.model,
        permission_mode="bypassPermissions",
        cwd=str(repo_dir),
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        max_turns=config.max_agent_turns,
    )

    prompt = build_prompt(task)

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                trace_data.num_turns = message.num_turns
                trace_data.total_cost_usd = message.total_cost_usd or 0.0
    except Exception as e:
        trace_data.error = str(e)

    # --- END CUSTOM LOGIC ---

    # Extract patch (always do this)
    patch = extract_patch(repo_dir)
    trace_data.patch_produced = bool(patch.strip())
    elapsed = time.time() - start_time

    return {
        "instance_id": task.instance_id,
        "model_name_or_path": f"kekule-my-solver-{config.model}",
        "model_patch": patch,
        "agent_id": agent_id,
        "duration_s": elapsed,
        "num_turns": trace_data.num_turns,
        "cost_usd": trace_data.total_cost_usd,
    }
```

### Step 2: Run it

Use the `--solver` flag to select your solver by filename (without `.py`):

```bash
uv run kekule-bench --solver my_solver --experiment-name "my-experiment" --problems 1 --agents-per-problem 1 --iterations 1 --skip-eval
```

The harness dynamically imports `solve_swe_task` from `solvers/my_solver.py`. No need to edit `harness.py`.

Available solvers are any `.py` file in `src/kekule/benchmarks/solvers/` that exports a `solve_swe_task()` function. The default solver is `solvers/default.py`.

### Step 3: Compare solvers (A/B testing)

**Option A:** Run separate experiments and compare results in Langfuse:

```bash
uv run kekule-bench --solver default --experiment-name "baseline" --problems 5 --skip-eval
uv run kekule-bench --solver my_solver --experiment-name "my-approach" --problems 5 --skip-eval
```

**Option B:** Create a dispatcher solver that routes agents to different strategies:

```python
# src/kekule/benchmarks/solvers/ab_test.py

from ..solver_agent import solve_swe_task as default_solver
from .my_solver import solve_swe_task as my_solver


async def solve_swe_task(task, agent_id, workspace_dir, ref_repo_dir, config, trace_data, agent_api_key=""):
    """Dispatch to different solvers based on agent number."""
    parts = agent_id.rsplit("-", 2)
    agent_num = int(parts[-2]) if len(parts) >= 2 else 0

    if agent_num % 2 == 0:
        return await default_solver(task, agent_id, workspace_dir, ref_repo_dir, config, trace_data, agent_api_key)
    else:
        return await my_solver(task, agent_id, workspace_dir, ref_repo_dir, config, trace_data, agent_api_key)
```

```bash
uv run kekule-bench --solver ab_test --experiment-name "ab-test-v1" --agents-per-problem 4 --problems 5
```

## Solver Design Patterns

### Pattern 1: Different System Prompts

The simplest customization -- change what instructions the agent gets:

```python
PROMPTS = {
    "test_first": "Always start by finding and running the failing test...",
    "grep_first": "Start by grepping for the error message in the codebase...",
    "docs_first": "Start by reading the module docstrings to understand the architecture...",
}

async def solve_swe_task(...):
    strategy = PROMPTS[config.strategy]  # Add strategy to config
    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": strategy},
        ...
    )
```

### Pattern 2: Multi-Pass Solver

Run the agent multiple times with different strategies, keep the best patch:

```python
async def solve_swe_task(task, agent_id, workspace_dir, ref_repo_dir, config, trace_data, **kwargs):
    best_patch = ""
    best_turns = 0

    for pass_num, strategy in enumerate(["explore", "fix", "verify"]):
        # Each pass gets a fresh workspace copy
        pass_workspace = workspace_dir / f"pass{pass_num}"
        repo_dir = await asyncio.to_thread(setup_workspace, task, pass_workspace, ref_repo_dir)

        prompt = f"[Strategy: {strategy}] {build_prompt(task)}"
        if best_patch:
            prompt += f"\n\nA previous attempt produced this patch:\n```diff\n{best_patch}\n```\nImprove upon it."

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                best_turns += message.num_turns

        patch = extract_patch(repo_dir)
        if len(patch) > len(best_patch):
            best_patch = patch

    return {"instance_id": task.instance_id, "model_patch": best_patch, ...}
```

### Pattern 3: Swarm with Shared Knowledge

Multiple agents working on the same problem, sharing discoveries via files:

```python
import json

SHARED_KNOWLEDGE_FILE = "/tmp/kekule-swarm-knowledge.json"

async def solve_swe_task(task, agent_id, workspace_dir, ref_repo_dir, config, trace_data, **kwargs):
    repo_dir = await asyncio.to_thread(setup_workspace, task, workspace_dir, ref_repo_dir)

    # Read knowledge from previous agents
    knowledge = ""
    try:
        with open(SHARED_KNOWLEDGE_FILE) as f:
            entries = json.load(f)
        relevant = [e for e in entries if e["instance_id"] == task.instance_id]
        if relevant:
            knowledge = "\n\n## Discoveries from Other Agents\n"
            for e in relevant:
                knowledge += f"\n- Agent {e['agent_id']}: {e['finding']}\n"
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    prompt = build_prompt(task) + knowledge

    # Run agent
    async for message in query(prompt=prompt, options=options):
        ...

    # Share what this agent learned (write to shared file)
    patch = extract_patch(repo_dir)
    entry = {
        "instance_id": task.instance_id,
        "agent_id": agent_id,
        "finding": f"Modified {len(patch.splitlines())} lines in the patch",
        "patch_preview": patch[:500],
    }
    try:
        with open(SHARED_KNOWLEDGE_FILE) as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []
    entries.append(entry)
    with open(SHARED_KNOWLEDGE_FILE, "w") as f:
        json.dump(entries, f)

    return {"instance_id": task.instance_id, "model_patch": patch, ...}
```

### Pattern 4: Tool-Restricted Solver

Test how agents perform with limited tools:

```python
# Read-only explorer (can only read, not edit)
READONLY_TOOLS = ["Read", "Glob", "Grep", "Bash"]

# Minimal editor (no web access)
OFFLINE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]

# Full power
ALL_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task", "WebFetch", "WebSearch"]
```

### Pattern 5: Model Comparison

Run the same prompt against different models:

```python
MODELS = ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku"]

async def solve_swe_task(task, agent_id, ..., config, trace_data, **kwargs):
    agent_num = int(agent_id.rsplit("-", 2)[-2])
    model = MODELS[agent_num % len(MODELS)]

    options = ClaudeAgentOptions(
        model=model,  # Override per-agent
        ...
    )
```

## File-by-File Reference

```
src/kekule/benchmarks/
  |
  |-- harness.py          DO NOT MODIFY: Loads solver via --solver flag automatically.
  |
  |-- solver_agent.py     REFERENCE: The default solver implementation.
  |                        Key functions you can reuse:
  |                          solve_swe_task()   -- Main entry point (the contract)
  |                          setup_workspace()  -- Copy repo to agent workspace
  |                          extract_patch()    -- Get git diff from workspace
  |                          build_swe_prompt() -- Build the prompt from task
  |
  |-- solvers/             YOUR SOLVERS GO HERE: Drop .py files with solve_swe_task()
  |   |-- default.py       Re-exports solver_agent.solve_swe_task
  |   |-- my_solver.py     CREATE: Your custom solver
  |   |-- ab_test.py       CREATE: Optional dispatcher for A/B testing
  |
  |-- config.py            EXTEND: Add custom config fields for your solver
  |
  |-- task_selector.py     EXTEND: Add custom task filtering logic
  |
  |-- evaluator.py         RARELY MODIFY: Handles JSONL writing + Docker eval
  |
  |-- tracing.py           EXTEND: Add custom hooks to track solver-specific metrics
```

## Swarm Experiment Ideas

Here are experiment configurations you can run to explore swarm behavior:

### Experiment 1: Scale Test
```bash
# How does solve rate scale with number of agents?
kekule-bench --experiment-name "scale-1" --problems 3 --agents-per-problem 1 --iterations 3 --skip-eval
kekule-bench --experiment-name "scale-3" --problems 3 --agents-per-problem 3 --iterations 3 --skip-eval
kekule-bench --experiment-name "scale-5" --problems 3 --agents-per-problem 5 --iterations 3 --skip-eval
# Compare best-of-N pass rates in Langfuse
```

### Experiment 2: Strategy Diversity
```bash
# Use an A/B dispatch solver with 3 different strategies
kekule-bench --solver ab_test --experiment-name "strategy-diversity" --problems 5 --agents-per-problem 3 --iterations 1
# agent0: test-first, agent1: grep-first, agent2: docs-first
# Does strategy diversity improve best-of-N?
```

### Experiment 3: Iterative Refinement
```bash
# Run 5 iterations, each building on previous knowledge
kekule-bench --solver shared_knowledge --experiment-name "iterative" --problems 3 --agents-per-problem 1 --iterations 5
# Use shared knowledge pattern so later iterations learn from earlier ones
```

### Experiment 4: ChatOverflow Collaboration
```bash
# Do agents solve more when they can share Q&A?
kekule-bench --experiment-name "with-forum" --problems 5 --agents-per-problem 3 --enable-chatoverflow
# vs baseline without:
kekule-bench --experiment-name "no-forum" --problems 5 --agents-per-problem 3
```

## The `solve_swe_task` Contract

Your solver function MUST:

1. **Accept these parameters** (same signature as `solver_agent.solve_swe_task`):
   ```python
   async def solve_swe_task(
       task: SWETask,           # The problem to solve
       agent_id: str,           # Unique agent identifier
       workspace_dir: Path,     # Your isolated workspace directory
       ref_repo_dir: Path,      # Pre-cloned reference repo to copy from
       config: HarnessConfig,   # Full config (model, max_turns, etc.)
       trace_data: AgentTraceData,  # Tracing accumulator
       agent_api_key: str = "", # Optional ChatOverflow API key
   ) -> dict:
   ```

2. **Return a dict** with at minimum:
   ```python
   {
       "instance_id": task.instance_id,       # Required
       "model_name_or_path": "your-solver",   # Required (used in predictions JSONL)
       "model_patch": "diff --git ...",        # Required (the git diff patch)
       "agent_id": agent_id,                  # Required
   }
   ```

3. **Use `setup_workspace()` and `extract_patch()`** from `solver_agent.py` for workspace management and patch extraction, unless you have a reason to do it differently.

4. **Set `trace_data` fields** if you want tracing:
   - `trace_data.num_turns` -- Number of agent turns
   - `trace_data.total_cost_usd` -- API cost
   - `trace_data.patch_produced` -- Whether a patch was generated
   - `trace_data.error` -- Error message if failed

Everything else (cloning, parallelism, evaluation, reporting) is handled by the harness.
