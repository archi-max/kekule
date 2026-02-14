# Tool I/O Reliability Results Investigation

Date: 2026-02-14  
Scope: Full audit of all Tool I/O reliability artifacts currently present in this repo.

## Data Reviewed

- Canonical experiment outputs:
  - `experiments/tool-io-reliability/raw_runs.json`
  - `experiments/tool-io-reliability/aggregated_results.json`
  - `experiments/tool-io-reliability/summary.md`
  - `experiments/tool-io-reliability/results/toolio-*/iteration_0/raw_results.json`
  - `logs/run_evaluation/eval-toolio-*/*/report.json`
- Root-level eval artifacts:
  - `kekule-swarm-claude-opus-4-5.eval-toolio-*.json`

## Executive Summary

1. The canonical matrix completed cleanly: 12/12 runs had 3 submitted and 3 completed instances.
2. Accuracy is unchanged across perturbation levels: every canonical run scored 2/3 (66.7%).
3. The same instance fails in every run: `pytest-dev__pytest-5413` (0/12 pass rate).
4. Perturbations fired infrequently relative to configured intensity:
   - Low: 2/74 (2.7%)
   - Medium: 2/76 (2.6%)
   - High: 7/81 (8.6%)
5. There are 13 legacy root-level eval files (`-fullpass` / `-rerun`) that are inconsistent with canonical results and include partial/incomplete evaluations. They should not be used for analysis.

## Canonical Run Findings (Authoritative)

Canonical means the 12 runs listed in `experiments/tool-io-reliability/raw_runs.json`:
- `toolio-{baseline,low,medium,high}-seed{1,2,3}`

### Condition-Level Metrics

| Condition | Configured p | Runs | Resolve Rate | Avg Cost (USD) | Avg Turns | Avg Agent Duration (s) | Observed Fire Rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| toolio-baseline | 0.00 | 3 | 0.667 | 8.4991 | 346.3 | 177.6 | 0.000 (0/0) |
| toolio-low | 0.05 | 3 | 0.667 | 8.1173 | 339.0 | 175.5 | 0.027 (2/74) |
| toolio-medium | 0.10 | 3 | 0.667 | 8.5472 | 329.0 | 172.6 | 0.026 (2/76) |
| toolio-high | 0.20 | 3 | 0.667 | 8.5466 | 346.3 | 157.6 | 0.086 (7/81) |

### Outcome Stability

- All 12 canonical eval JSONs report:
  - `resolved_instances = 2`
  - `unresolved_instances = 1`
  - `error_instances = 0`
- Per-instance pass rate across canonical runs:
  - `django__django-14915`: 12/12 pass
  - `django__django-16379`: 12/12 pass
  - `pytest-dev__pytest-5413`: 0/12 pass

### Failure Signature for `pytest-dev__pytest-5413`

- Every canonical eval report fails exactly:
  - `testing/code/test_excinfo.py::test_excinfo_repr_str`
- Representative failure from `logs/run_evaluation/eval-toolio-high-seed3/.../test_output.txt`:
  - expected: `"<ExceptionInfo ValueError tblen=4>"`
  - actual from patch behavior: `""`
- Practical interpretation:
  - The solver repeatedly applies semantic changes to `ExceptionInfo.__str__` that do not satisfy the target regression test.
  - Perturbation does not appear to be the root cause of this failure because it reproduces in baseline and all perturbed conditions.

## Perturbation Analysis

### Fired vs Eligible

- Across all perturbed conditions (low+medium+high): 11/231 = 4.76%.
- By condition:
  - Low (p=0.05): 2/74 = 2.70%
  - Medium (p=0.10): 2/76 = 2.63%
  - High (p=0.20): 7/81 = 8.64%

The ordering is monotonic (high > low/medium), but realized rates are much lower than configured intensity values.

### Where Perturbations Landed

Across canonical runs, perturbation opportunities were heavily concentrated in `pytest-dev__pytest-5413`:
- `django__django-14915`: eligible 25, fired 3
- `django__django-16379`: eligible 27, fired 3
- `pytest-dev__pytest-5413`: eligible 179, fired 5

## Legacy Artifact Audit (`-fullpass` / `-rerun`)

There are 13 extra root eval files beyond canonical outputs:
- 12 `*-fullpass.json`
- 1 `baseline-seed1-rerun.json`

Problems identified:
- Several files are incomplete (completed < submitted).
- Some include `error_instances > 0` or `empty_patch_instances > 0`.
- Example: `medium-seed2-fullpass` has `completed_instances=1`, `empty_patch_instances=2`.

These files are inconsistent with canonical run tracking and should be treated as stale/diagnostic artifacts only.

## Reliability Conclusion

- On the current 3-task matrix, Tool I/O degradation (as configured) did not reduce pass rate relative to baseline.
- The dominant blocker is a persistent solver miss on one task (`pytest-dev__pytest-5413`), not perturbation intensity.
- Current matrix size is too small to claim robust insensitivity; result stability may be dominated by task mix.

## Recommended Actions Before Next Rerun

1. Archive or delete non-canonical root eval artifacts (`*-fullpass.json`, `*-rerun.json`) to avoid reporting confusion.
2. Keep `raw_runs.json` + `aggregated_results.json` as single source of truth for this experiment.
3. Add a guard in reporting scripts to ignore files not present in `raw_runs.json`.
4. Improve solver behavior for `pytest-dev__pytest-5413`:
   - add targeted guidance to avoid changing `ExceptionInfo.__str__` semantics incorrectly
   - add pre-eval self-check for `test_excinfo_repr_str`.
5. Increase experiment breadth (more SWE-bench instances) before drawing robustness claims about perturbation intensity.
