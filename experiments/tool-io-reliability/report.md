# Tool I/O Reliability Experiment Report

Generated: 2026-02-14 12:50:08 UTC  
Run completed: 12/12 condition-seed cells  
Evaluation completed: 12/12 condition-seed cells

## Setup

- Conditions: `toolio-baseline (p=0.00)`, `toolio-low (p=0.05)`, `toolio-medium (p=0.10)`, `toolio-high (p=0.20)`
- Seeds: `1, 2, 3`
- Tasks per run: `3` (`django__django-16379`, `django__django-14915`, `pytest-dev__pytest-5413`)
- Solver: `perturbation_swarm`
- Model: `claude-opus-4-5`
- Evaluation mode: SWE-bench full pass (`run_evaluation`) over saved predictions

## Condition Summary

| Condition | p (configured) | Patches | Patch rate | Eval pass / eval total | Resolve rate | Avg cost (USD/run) | Avg turns/run | Avg wall time/run (s) | Observed fire rate | Fired / Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| toolio-baseline | 0.00 | 8/9 | 0.889 | 4 / 7 | 0.571 | 9.558 | 375.3 | 187.0 | 0.000 | 0 / 0 |
| toolio-low | 0.05 | 8/9 | 0.889 | 5 / 8 | 0.625 | 9.585 | 368.3 | 205.9 | 0.007 | 1 / 136 |
| toolio-medium | 0.10 | 7/9 | 0.778 | 4 / 7 | 0.571 | 9.244 | 370.0 | 195.5 | 0.020 | 2 / 98 |
| toolio-high | 0.20 | 8/9 | 0.889 | 3 / 6 | 0.500 | 10.372 | 397.7 | 209.4 | 0.028 | 3 / 107 |

## Per-Task Resolve Rate (Evaluated Rows Only)

| Task | Baseline | Low | Medium | High |
|---|---:|---:|---:|---:|
| django__django-14915 | 3/3 | 2/2 | 2/2 | 1/1 |
| django__django-16379 | 1/1 | 3/3 | 2/2 | 2/2 |
| pytest-dev__pytest-5413 | 0/3 | 0/3 | 0/3 | 0/3 |

## Key Findings

1. End-to-end matrix execution and evaluation completed (`12/12` each), with solve-rate backfilled from stored predictions.
2. Overall solve performance on evaluated rows was `16/28 = 57.1%`.
3. By condition, resolve rate was: low `0.625` > baseline `0.571` = medium `0.571` > high `0.500`.
4. Patch production stayed high overall (31/36), with the main dip in `toolio-medium` (7/9).
5. Runtime and cost rose at higher perturbation (`toolio-high` highest avg cost and turns).
6. Observed perturbation fire rates were much lower than configured intensities:
   - low: observed `0.007` vs configured `0.05`
   - medium: observed `0.020` vs configured `0.10`
   - high: observed `0.028` vs configured `0.20`
7. Evaluation coverage was partial (`28/36`) because some predictions were empty and some failed to apply in SWE-bench due patch contamination (reversed patch + Django docs symlink/binary hunks).

## Notable Events

- Some runs logged fallback behavior during patch selection when endorsed diffs could not be applied cleanly (for example, binary patch application failures in Django docs assets), which contributed to occasional empty final patches.

## Artifacts

- Aggregates: `experiments/tool-io-reliability/aggregated_results.json`
- Per-run rows: `experiments/tool-io-reliability/raw_runs.json`
- Eval rows: `experiments/tool-io-reliability/eval_results.json`
- Compact table: `experiments/tool-io-reliability/summary.md`
- Per-cell raw outputs: `experiments/tool-io-reliability/results/*/iteration_0/raw_results.json`
