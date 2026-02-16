# Sonnet-v1 Experiment Report

**Model**: claude-sonnet-4-5
**Solver**: oracle_swarm (coding agents + oracle verification agents in parallel)
**Epochs**: 2
**Tasks**: 3 train + 2 test (5 total)
**Total cost**: $69.34

## Score Progression

| Epoch | Train | Test | Cost | Oracle Strategies |
|-------|-------|------|------|-------------------|
| 0 | 1/3 (33%) | 1/2 (50%) | $26.08 | unit_test, regression_check, behavioral_assertion |
| 1 | 1/3 (33%) | 1/2 (50%) | $43.26 | + minimal_reproduction, regression_quick_check |

## Per-Task Results

| Task | Epoch 0 | Epoch 1 | Eval |
|------|---------|---------|------|
| django-16379 (train) | 623B, 1 round, oracles PASS | 623B, 1 round, 2/2 oracles PASS | **PASS** |
| pylint-7080 (train) | 7197B, 2 rounds, oracle FAIL | 742B, 3 rounds, oracle FAIL | FAIL |
| sphinx-8595 (train) | 909B, 2 rounds, oracle FAIL | 636B, 1 round | FAIL |
| django-14915 (test) | 3271B, 2 rounds | 764B, 1 round, oracle PASS | **PASS** |
| requests-2317 (test) | 566B, 1 round | 1707B, 1 round, 2/2 oracles PASS | FAIL |

## Key Observations

### 1. Sonnet's Oracles Were More Aggressive

In epoch 0, Sonnet's oracle agents caught failures and triggered Round 2 on **3 out of 5 tasks** (pylint, sphinx, django-14915). Compare to Opus runs where Round 2 was rare. The oracles correctly identified issues:
- **pylint**: unit_test oracle caught that the fix broke file discovery
- **sphinx**: regression_check oracle caught import errors in the test
- **django-14915**: regression_check oracle found an import error in its own test file

This made epoch 0 more expensive ($26 vs Opus ~$10-15) but produced better diagnostic signal.

### 2. Pylint Trajectory Changed Dramatically Between Epochs

**Epoch 0** (7197B patch, 306 turns, $10.12):
- Replaced `astroid`'s `modutils.get_module_files()` with a custom `_get_module_files()` that enforced `__init__.py` requirements
- This broke namespace package support → 116 test regressions
- Oracle caught it (unit_test FAIL both rounds) but the swarm couldn't fix the fundamental approach in 2 rounds

**Epoch 1** (742B patch, 693 turns, $24.61):
- Much smaller patch — stopped replacing library functions (coordinator lesson: "Prefer minimal targeted fixes over replacing standard library functions")
- Went to **Round 3** (max rounds increased by coordinator from 2→3)
- Oracle unit_test still FAILED all 3 rounds, but regression_check PASSED all 3 rounds
- The swarm iterated 3 times but kept hitting the same issue: filtering at the wrong abstraction level

The coordinator's lesson was applied (patch shrank 10x) but the architectural insight (filter at caller level, not in `_discover_files`) wasn't conveyed.

### 3. Coordinator Created 5 New Oracle Strategies

Between epochs, the coordinator created:

| Strategy | Weight | Purpose |
|----------|--------|---------|
| `target_test_executor` | 2.0 | Run exact FAIL_TO_PASS tests before submission |
| `minimal_reproduction` | 1.5 | Create minimal repro script from issue description |
| `regression_quick_check` | 1.5 | Quick check: import the module + run --version |
| `unit_test` (tuned) | - | Added: "verify target tests actually execute, not just pass" |
| `behavioral_assertion` (tuned) | - | Added: "test with both package and non-package directories" |

Epoch 1 ran with **9 agents per task** (4 coding + 5 oracle) vs 7 in epoch 0.

### 4. requests-2317 Improved But Still Failed

**Epoch 0** (566B): Simple `isinstance(bytes)` check at one location.

**Epoch 1** (1707B): Used `to_native_string()` utility, fixed a second call site (`request.method.upper()`), added a test. Oracle checks 2/2 PASSED. But Docker eval still found a regression on `test_mixed_case_scheme_acceptable` — the oracle tests didn't cover mixed-case HTTP method handling.

### 5. Failure Analyst Correctly Identified Pylint Root Cause

> "The patch replaced astroid's modutils.get_module_files() with a custom _get_module_files() that enforces __init__.py requirements by default, breaking namespace package support and causing 116 test regressions"
>
> "The fix should target pylinter.py's _discover_files() method instead of expand_modules.py"

This diagnosis was correct and led to the coordinator's lesson about not replacing library functions. But the swarm in epoch 1 still modified the wrong location — it needs the insight that the filter should be applied where user code is queued, not inside the shared file discovery mechanism.

## Comparison: Sonnet vs Opus

| Metric | Sonnet (sonnet-v1) | Opus (eval-v7-oracle) |
|--------|-------------------|----------------------|
| Model cost per task | ~$7/task | ~$4/task |
| Oracle artifact production | Better (more artifacts, more Round 2s) | Moderate (some tasks got no artifacts) |
| Patch quality | Similar (same tasks pass/fail) | Similar |
| Coordinator lessons | 1748 chars, 5 oracle adj | 1109 chars, 4 oracle adj |
| Pylint approach | Epoch 0: replace library fn (7197B) → Epoch 1: targeted fix (742B) | Consistent 742B targeted fix |
| Total cost | $69.34 | $39.92 |

Sonnet's oracles were more aggressive (more Round 2 triggers), which improved diagnostic signal but doubled cost. The actual solve rate was identical — the same tasks pass/fail regardless of model. The hard tasks (pylint, sphinx, requests) require architectural reasoning that neither model achieves through prompt-based learning alone.

## Artifacts

All data saved to `results/sonnet-v1/`:
- `scores.json` — epoch progression
- `epoch_0/raw_results.json` — full results with oracle details
- `epoch_0/coordinator_output.json` — lessons + 5 oracle adjustments
- `epoch_0/failure_diagnoses.json` — per-task failure analysis
- `epoch_1/raw_results.json` — epoch 1 with updated oracle strategies
- `lessons.md` — accumulated lessons
- `prompt_snapshots/` — full prompt state per epoch
