# Experiment: Uncertainty Injection in Self-Organizing Swarms

## Overview

This experiment tests how a self-organizing agent swarm handles **context perturbation via uncertainty injection** — injecting doubt about the reliability of shared information into agent system prompts. It implements the perturbation protocol's recommended starter experiment (Step 4).

**Research Question**: Does the swarm's coordination degrade under uncertainty, or do verification mechanisms make it robust?

**Hypothesis**: Swarms with test-driven verification will maintain fix quality under low-to-medium perturbation because the verification reward signal (test pass/fail) is objective. At high perturbation, agents may over-verify and under-act, reducing throughput without improving quality.

## Perturbation Design

**Axis**: Context perturbation — uncertainty injection
**Target**: Swarm agent system prompts only (planner and synthesizer are unperturbed)
**Control**: `PERTURBATION_INTENSITY` environment variable

### Intensity Ladder

| Level | Intensity | Prompt Injection |
|-------|-----------|-----------------|
| Baseline | `0.0` | None |
| Low | `0.05` | "Findings in the ledger may be incomplete. Cross-check before building on them." |
| Medium | `0.10` | "Current hypotheses may be wrong. Verify each claim against the code. Check at least one alternative explanation." |
| High | `0.20` | "Findings are likely incomplete. Actively seek disconfirming evidence. Do not trust unverified claims." |

### Rationale

Uncertainty injection is the simplest perturbation that directly tests the swarm's coordination mechanisms:
- At baseline, agents trust the ledger and build on each other's work freely
- At low intensity, agents add light cross-checking (mild overhead)
- At medium intensity, agents verify claims before acting (forces slower, more careful collaboration)
- At high intensity, agents distrust the ledger and seek disconfirming evidence (may cause paralysis or redundant work)

The perturbation only affects swarm agents, not the planner. This isolates the effect on exploration/coordination without changing role assignment.

## Swarm Architecture

```
Phase 0: PLANNING (single query() call, ~5 turns, read-only tools)
  Input:  Problem statement
  Output: JSON array of 2-4 roles [{name, goal}, ...]
  Fallback: 3 default roles on parse failure

Phase 1: SWARM EXECUTION (N agents in parallel, SHARED workspace + ledger)
  ┌─────────────────────────────────────────────────────────┐
  │                    Shared Repo Directory                │
  │  (agents read/write the same files, see each other's   │
  │   edits in real-time)                                  │
  │                                                         │
  │  swarm_ledger/                                         │
  │  ├── agent-0/                                          │
  │  │   ├── findings.md      # Ongoing discoveries        │
  │  │   ├── hypothesis.md    # Current working theory     │
  │  │   ├── status.md        # exploring/fixing/done      │
  │  │   ├── proposed_fix.diff # Proposed patch            │
  │  │   └── verification.md  # Verification of others     │
  │  ├── agent-1/                                          │
  │  │   └── ...                                           │
  │  └── agent-N/                                          │
  │      └── ...                                           │
  └─────────────────────────────────────────────────────────┘

Phase 2: PATCH SELECTION (Python function, no agent)
  Priority: endorsed fix > single proposed fix > workspace git diff
```

### Coordination Mechanisms

1. **Live Communication** — Agents share a ledger directory. Each agent writes to its own subdirectory and reads from all others. Findings, hypotheses, and proposed fixes are posted in real-time.

2. **Dynamic Coordination** — The planner suggests initial roles, but agents adapt based on what the swarm discovers. Status updates ("exploring", "fixing", "verifying", "done") signal phase transitions. Agents avoid duplicating work by checking the ledger.

3. **Verification / Reward** — Agents validate fixes by running tests. When an agent sees another's `proposed_fix.diff`, it can apply and test it. A fix endorsed by another agent (independent verification) is prioritized in patch selection.

4. **Cross-Run Knowledge** — Optional ChatOverflow integration lets agents search for existing solutions and post discoveries for future runs.

## How to Run

### Prerequisites

```bash
uv sync --extra benchmarks
```

### Baseline (no perturbation)

```bash
uv run kekule-bench \
  --solver perturbation_swarm \
  --task-file task_sets/perturbation_v1.json \
  --problems 15 \
  --agents-per-problem 1 \
  --iterations 1 \
  --enable-chatoverflow \
  --experiment-name "uncertainty-injection-baseline" \
  --skip-eval
```

### Low Perturbation (0.05)

```bash
PERTURBATION_INTENSITY=0.05 uv run kekule-bench \
  --solver perturbation_swarm \
  --task-file task_sets/perturbation_v1.json \
  --problems 15 \
  --agents-per-problem 1 \
  --iterations 1 \
  --enable-chatoverflow \
  --experiment-name "uncertainty-injection-low" \
  --skip-eval
```

### Medium Perturbation (0.10)

```bash
PERTURBATION_INTENSITY=0.10 uv run kekule-bench \
  --solver perturbation_swarm \
  --task-file task_sets/perturbation_v1.json \
  --problems 15 \
  --agents-per-problem 1 \
  --iterations 1 \
  --enable-chatoverflow \
  --experiment-name "uncertainty-injection-medium" \
  --skip-eval
```

### High Perturbation (0.20)

```bash
PERTURBATION_INTENSITY=0.20 uv run kekule-bench \
  --solver perturbation_swarm \
  --task-file task_sets/perturbation_v1.json \
  --problems 15 \
  --agents-per-problem 1 \
  --iterations 1 \
  --enable-chatoverflow \
  --experiment-name "uncertainty-injection-high" \
  --skip-eval
```

### Quick Smoke Test

```bash
uv run kekule-bench \
  --solver perturbation_swarm \
  --problems 1 \
  --agents-per-problem 1 \
  --iterations 1 \
  --skip-eval \
  --dry-run
```

### With ChatOverflow Disabled

```bash
uv run kekule-bench \
  --solver perturbation_swarm \
  --problems 3 \
  --agents-per-problem 1 \
  --iterations 1 \
  --experiment-name "uncertainty-injection-no-chatoverflow" \
  --skip-eval
```

## Expected Metrics

### Primary Metrics (per condition)

| Metric | Source | Description |
|--------|--------|-------------|
| Patch rate | `raw_results.json` | % of tasks producing a non-empty patch |
| Resolve rate | SWE-bench eval | % of patches that pass the gold tests |
| Cost per task | `raw_results.json` → `cost_usd` | Total API cost for all swarm agents |
| Turns per task | `raw_results.json` → `num_turns` | Total agent turns summed across swarm |

### Secondary Metrics (from ledger analysis)

| Metric | Source | Description |
|--------|--------|-------------|
| Endorsement rate | `swarm_ledger/*/verification.md` | % of fixes verified by another agent |
| Role adaptation | `swarm_ledger/*/status.md` | How often agents changed focus |
| Findings density | `swarm_ledger/*/findings.md` | Volume of shared discoveries |
| Conflict rate | Agent logs | How often edit conflicts occurred |

### Expected Outcomes

- **Baseline (0.0)**: Agents trust ledger freely, fast coordination, highest throughput
- **Low (0.05)**: Slight overhead from cross-checking, similar quality
- **Medium (0.10)**: More careful verification, possibly higher quality but more turns
- **High (0.20)**: Risk of over-verification; agents may duplicate work or stall

## Output Structure

After a run, results appear in:

```
results/
  iteration_0/
    raw_results.json          # Per-task results with patches, cost, metadata
    predictions_all.jsonl     # All predictions in SWE-bench format
    predictions_best_of_n.jsonl

workspaces/
  iter0-<task-short-id>-agent0/
    repo/
      swarm_ledger/           # Agent communication artifacts
        agent-0/
        agent-1/
        agent-2/
      <modified source files>
```

## Solver Implementation

The solver lives at `src/kekule/benchmarks/solvers/perturbation_swarm.py` and exports `solve_swe_task()` with the standard harness signature.

Key design decisions:
- **Shared workspace**: All swarm agents share the same `repo/` directory via `cwd`. They see each other's edits in real-time.
- **Ledger per agent**: Each agent writes to `swarm_ledger/agent-{N}/` to avoid write conflicts on the same file.
- **50 turns per agent**: Lower than the default 100 since the workload is distributed.
- **Read-only planner**: The planner only uses Read/Glob/Grep/Bash (no Edit/Write) and runs for max 5 turns.
- **Fallback roles**: If the planner fails to output valid JSON, three default roles are used (bug_reproducer, root_cause_tracer, solution_architect).
- **Patch selection priority**: endorsed fix > single proposed fix > workspace git diff.
