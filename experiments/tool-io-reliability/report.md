# Tool I/O Reliability Experiment Report

Generated: 2026-02-14 01:30:40 UTC  
Run completed: 12/12 condition-seed cells

## Setup

- Conditions: `toolio-baseline (p=0.00)`, `toolio-low (p=0.05)`, `toolio-medium (p=0.10)`, `toolio-high (p=0.20)`
- Seeds: `1, 2, 3`
- Tasks per run: `3` (`django__django-16379`, `django__django-14915`, `pytest-dev__pytest-5413`)
- Solver: `perturbation_swarm`
- Model: `claude-opus-4-5`
- Evaluation mode: `skip_eval=True` (no SWE-bench pass/fail scoring in this run)

## Condition Summary

| Condition | p (configured) | Patches | Patch rate | Avg cost (USD/run) | Avg turns/run | Avg wall time/run (s) | Observed fire rate | Fired / Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| toolio-baseline | 0.00 | 8/9 | 0.889 | 9.558 | 375.3 | 222.1 | 0.000 | 0 / 0 |
| toolio-low | 0.05 | 8/9 | 0.889 | 9.585 | 368.3 | 256.0 | 0.007 | 1 / 136 |
| toolio-medium | 0.10 | 7/9 | 0.778 | 9.244 | 370.0 | 227.3 | 0.020 | 2 / 98 |
| toolio-high | 0.20 | 8/9 | 0.889 | 10.372 | 397.7 | 246.6 | 0.028 | 3 / 107 |

## Per-Task Patch Rate

| Task | Baseline | Low | Medium | High |
|---|---:|---:|---:|---:|
| django__django-14915 | 3/3 | 2/3 | 2/3 | 2/3 |
| django__django-16379 | 2/3 | 3/3 | 2/3 | 3/3 |
| pytest-dev__pytest-5413 | 3/3 | 3/3 | 3/3 | 3/3 |

## Key Findings

1. End-to-end matrix execution completed successfully (`12/12`), with Langfuse enabled for all cells.
2. No agent-level hard failures were recorded (`error_rows = 0`).
3. Patch production stayed high overall (31/36), with the main dip in `toolio-medium` (7/9).
4. Runtime and cost rose modestly at higher perturbation (`toolio-high` had highest avg cost and turns).
5. Observed perturbation fire rates were much lower than configured intensities:
   - low: observed `0.007` vs configured `0.05`
   - medium: observed `0.020` vs configured `0.10`
   - high: observed `0.028` vs configured `0.20`
6. Since SWE-bench evaluation was skipped, this run supports reliability/behavioral analysis (cost, turns, patch production, perturbation telemetry), but not definitive solve-rate conclusions.

## Notable Events

- Some runs logged fallback behavior during patch selection when endorsed diffs could not be applied cleanly (for example, binary patch application failures in Django docs assets), which contributed to occasional empty final patches.

## Artifacts

- Aggregates: `experiments/tool-io-reliability/aggregated_results.json`
- Per-run rows: `experiments/tool-io-reliability/raw_runs.json`
- Compact table: `experiments/tool-io-reliability/summary.md`
- Per-cell raw outputs: `experiments/tool-io-reliability/results/*/iteration_0/raw_results.json`
