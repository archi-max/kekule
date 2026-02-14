# Tool I/O Reliability Experiment — Final Report

**Generated**: 2026-02-14 12:50 UTC
**Tasks**: django__django-16379, django__django-14915, pytest-dev__pytest-5413
**Experiments**: 12 (4 conditions x 3 seeds)
**Total inference cost**: ~$116.27
**Total inference runtime**: ~47.6 minutes
**Evaluation**: SWE-bench Docker harness run for all 12 cells (partial row coverage due empty/apply-failed patches)

## Perturbation Architecture

### How Perturbation Is Introduced

This experiment uses Claude Agent SDK hook-driven perturbation in `tool_io_degrade` mode.

```
run_tool_io_reliability.py
  -> sets env knobs per condition+seed
  -> perturbation_swarm.py (Phase 1 swarm agents only)
     -> build_agent_hooks(...)
     -> PerturbationPolicy(mode=tool_io_degrade, intensity=p, target_tools=[Bash])
```

For each cell, the runner sets:
- `PERTURBATION_MODE=tool_io_degrade`
- `PERTURBATION_INTENSITY in {0.00, 0.05, 0.10, 0.20}`
- `PERTURBATION_TARGET_TOOLS=Bash`
- `PERTURBATION_PHASE_SCOPE=swarm_phase1`
- `PERTURBATION_SEED in {1,2,3}`

### What Is Perturbed

- Tool I/O in swarm execution phase only.
- Targeted tool: `Bash` (verification path).
- Perturbation evaluated via `eligible` and `fired` counters per row.

### What Is Not Perturbed

- Planner (Phase 0 role planning).
- Patch selection algorithm itself (deterministic Python).
- Task statements, solver model, and task IDs.

### Configured vs Observed Dose

| Condition | Configured p | Eligible | Fired | Observed fire rate | Expected fires | Realization ratio |
|---|---:|---:|---:|---:|---:|---:|
| toolio-low | 0.05 | 136 | 1 | 0.007 | 6.8 | 0.147 |
| toolio-medium | 0.10 | 98 | 2 | 0.020 | 9.8 | 0.204 |
| toolio-high | 0.20 | 107 | 3 | 0.028 | 21.4 | 0.140 |

Observed intensity tracked the ladder (`low < medium < high`) but absolute realized dose was much lower than configured.

## Swarm Architecture

The solver kept the same 3-phase design used in the prior swarm report:

- Phase 0: planner proposes roles.
- Phase 1: swarm agents run in a shared repo and coordinate via `swarm_ledger/`.
- Phase 2: patch selection prefers endorsed/single diffs, then falls back to workspace diff.

## Condition-Level Results

| Condition | Patches | Patch rate | Eval pass / eval total | Resolve rate | Avg cost (USD/run) | Avg turns/run |
|---|---:|---:|---:|---:|---:|---:|
| toolio-baseline | 8/9 | 0.889 | 4/7 | 0.571 | 9.558 | 375.3 |
| toolio-low | 8/9 | 0.889 | 5/8 | 0.625 | 9.585 | 368.3 |
| toolio-medium | 7/9 | 0.778 | 4/7 | 0.571 | 9.244 | 370.0 |
| toolio-high | 8/9 | 0.889 | 3/6 | 0.500 | 10.372 | 397.7 |

Overall evaluated solve rate: `16/28 = 57.1%`.

## Per-Task Results

### Evaluated Resolution by Task

| Task | Baseline | Low | Medium | High |
|---|---:|---:|---:|---:|
| django__django-16379 | 1/1 | 3/3 | 2/2 | 2/2 |
| django__django-14915 | 3/3 | 2/2 | 2/2 | 1/1 |
| pytest-dev__pytest-5413 | 0/3 | 0/3 | 0/3 | 0/3 |

Interpretation:
- Both Django tasks resolved whenever evaluation actually ran on a non-corrupted patch row.
- `pytest-dev__pytest-5413` remained unsolved across all evaluated rows.

## Coverage Loss: Empty and Apply-Failed Rows

Expected evaluable rows: `36` (12 cells x 3 tasks).  
Actual evaluated rows: `28`.

### Empty Patch Rows (5)

- `toolio-baseline-seed2 / django__django-16379`
- `toolio-low-seed1 / django__django-14915`
- `toolio-medium-seed2 / django__django-16379`
- `toolio-medium-seed2 / django__django-14915`
- `toolio-high-seed3 / django__django-14915`

These rows had no tracked code diff at extraction time (`model_patch == ""`), so SWE-bench had nothing to apply.

### Patch-Apply Error Rows (3)

- `toolio-baseline-seed3 / django__django-16379`
- `toolio-high-seed1 / django__django-14915`
- `toolio-high-seed2 / django__django-16379`

These patches were contaminated by unrelated Django docs icon hunks (symlink/binary type changes under `docs/_theme/djangodocs-epub/static/docicons-*`), causing SWE-bench apply failures with reversed/symlink errors.

## Root Cause Analysis

The failure mode is pipeline-level, not SWE-bench-level:

1. Final patch extraction uses full workspace diff (`git diff`).
2. Patch selection can fall back to workspace diff when endorsed/single diff paths fail.
3. In several rows, workspace carried unrelated tracked-file mutations (docs symlink type flips), which leaked into final patch payload.
4. Empty rows occurred when no tracked diff remained in the workspace at extraction time.

Consequence: metrics include partial evaluation coverage and condition-dependent missingness.

## Comparison to Previous Report

Compared to `experiments/uncertainty-injection/final_report.md`:

- Previous run had clean evaluation coverage (`15/15`, no empty patches, no apply failures).
- This run has larger replication on perturbation conditions (3 seeds/condition) but lower evaluation integrity (`28/36` evaluated).
- The current run is still useful for hook telemetry and cost/turn effects, but solve-rate conclusions are weaker until patch hygiene is fixed.

## Conclusions

1. The hook perturbation matrix ran and evaluated end-to-end.
2. Perturbation intensity increased runtime/cost pressure at high settings.
3. Solve-rate trend on evaluated rows declines at high intensity (`0.500`) vs low (`0.625`), but coverage gaps prevent strong causal claims.
4. The main blocker to stronger inference is patch hygiene (empty rows + contaminated diffs).

## Recommended Next Pass

1. Add patch sanitization before writing predictions:
   - reject non-target files for each task
   - fail closed if patch contains binary/symlink hunks unrelated to the task fix.
2. Tighten patch selection:
   - remove/guard workspace-diff fallback or clean tracked workspace before fallback extraction.
3. Re-run the same 12-cell matrix after hygiene fixes and require `36/36` evaluable rows.

## Raw Data

- `experiments/tool-io-reliability/raw_runs.json`
- `experiments/tool-io-reliability/aggregated_results.json`
- `experiments/tool-io-reliability/eval_results.json`
- `experiments/tool-io-reliability/summary.md`
- `experiments/tool-io-reliability/report.md`
