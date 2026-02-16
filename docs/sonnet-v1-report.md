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

## Why Oracles Failed to Catch the Real Issues

The oracle system triggered Round 2 on multiple tasks but never caught the actual regressions that Docker eval found. The root cause is a design flaw: **oracle agents write synthetic tests instead of running the project's actual test suite.**

### What each oracle did vs what it should have done

**pylint-7080**:
- Oracle did: Created `oracle_tests/unit_test/test_discover_files.py` that imports `_is_ignored_file` and calls it directly. Passes — the function works in isolation.
- Oracle should have: Run `pytest tests/test_self.py -x`. Would immediately show 116 failures and that pylint can't even initialize.

**sphinx-8595**:
- Oracle did: Created `oracle_tests/unit_test/test_empty_all.py` with mocked autodoc module. Passes — the mock doesn't reproduce Sphinx's real RST processing pipeline.
- Oracle should have: Run `pytest tests/test_ext_autodoc_automodule.py::test_empty_all`. Would show the exact assertion failure.

**requests-2317**:
- Oracle did: Created tests checking `b'GET'` → `'GET'` conversion. All pass.
- Oracle should have: Run `pytest test_requests.py::RequestsTestCase::test_mixed_case_scheme_acceptable`. Would catch the regression the swarm introduced.

### The root problem

The oracle role prompt says "Generate verification tests... Write tests to `oracle_tests/`". This tells agents to **write** tests. They should be told to **run existing tests**. The agents have Bash access — they can execute `pytest tests/` — but the prompt steers them toward artifact generation.

The `full_test_suite_runner` strategy was created by the coordinator to fix this, but its prompt still says "run all tests in the same test file" which the agent interprets as "write a test file that runs tests" rather than literally running `pytest`.

## Exact Steps Needed to Pass Each Failing Task

### pylint-7080: `test_ignore_path_recursive_current_dir`

The swarm modifies `_discover_files()` in `pylinter.py`, but this function is shared between user code scanning AND pylint's internal module loading. Steps needed:

1. **Do NOT modify `_discover_files()` directly** — it's used during pylint startup to load checkers
2. Apply `ignore-paths` filtering at the **caller level** where user files are queued for linting, not inside the shared discovery function
3. Filter at two levels: package directories (with `__init__.py`) AND individual `.py` files
4. Verify `python -m pylint --version` still works after patching
5. Run `pytest tests/test_self.py` — not just the target test

### sphinx-8595: `test_empty_all`

The swarm changes `if not self.__all__:` to `if self.__all__ is None:` but doesn't handle the empty list case. Steps needed:

1. Change `if not self.__all__:` → `if self.__all__ is None:` (done)
2. **Add explicit empty-list branch**: `elif len(self.__all__) == 0: return False, []`
3. Also fix the `want_all=False` path (lines 1090-1101) — when `:members: foo` is used but `__all__=[]`, filter those members out
4. Test three distinct cases: `__all__=None`, `__all__=[]`, `__all__=['item']`

### requests-2317: `test_mixed_case_scheme_acceptable`

The swarm fixes bytes→string conversion but introduces a mixed-case regression. Steps needed:

1. Use `to_native_string(method)` instead of `builtin_str(method)` in `models.py`
2. Fix the **second call site** in `sessions.py` (`method=request.method.upper()`)
3. Preserve the `.upper()` call chain — the regression happens because the casing behavior changes
4. Run `pytest test_requests.py::RequestsTestCase::test_mixed_case_scheme_acceptable` to verify no regression

## Suggested Next Experiment

### experiment: `oracle-v2-real-tests`

The single highest-impact change is fixing the oracle agents to **run existing tests instead of writing new ones**. Proposed changes:

1. **Modify the `full_test_suite_runner` oracle strategy prompt** to explicitly say:
   ```
   Use Bash to run `pytest <test_file> -x --tb=short` on the project's EXISTING test files.
   Do NOT create new test files. Find the test file related to the modified source code and
   run it directly. Report the full pytest output.
   ```

2. **Add a `target_test_runner` strategy** that runs the exact FAIL_TO_PASS test names from the problem statement (if mentioned) using Bash.

3. **Remove or demote `unit_test` and `regression_check` strategies** — they consistently produce false negatives (synthetic tests that pass when real tests fail).

4. **Run with the same 5 tasks** to directly compare oracle effectiveness.

Expected impact: If the oracle correctly runs `pytest tests/test_self.py` for pylint, it would catch the 116 regressions in Round 0, give the swarm actionable feedback ("your patch breaks pylint initialization"), and potentially lead to a correct fix by Round 2. Same for sphinx (`test_empty_all` would fail) and requests (`test_mixed_case` would fail).

## Artifacts

All data saved to `results/sonnet-v1/`:
- `scores.json` — epoch progression
- `epoch_0/raw_results.json` — full results with oracle details
- `epoch_0/coordinator_output.json` — lessons + 5 oracle adjustments
- `epoch_0/failure_diagnoses.json` — per-task failure analysis
- `epoch_1/raw_results.json` — epoch 1 with updated oracle strategies
- `lessons.md` — accumulated lessons
- `prompt_snapshots/` — full prompt state per epoch
