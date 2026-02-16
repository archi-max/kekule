---
name: kekule-bench
description: Run self-improving SWE-bench experiments with agent swarms, oracle verification, failure analysis, and cross-epoch learning. Use when user asks to "run an experiment", "benchmark the swarm", "test on SWE-bench", "improve the solver", "analyze failures", "check experiment results", or "tune oracle strategies".
license: MIT
metadata:
  author: Kekule Team
  version: 1.0.0
---

# Kekule Benchmark Harness

A skill for running self-improving agent swarm experiments on SWE-bench. The system runs multiple epochs where agent swarms solve GitHub issues, a failure analyst diagnoses what went wrong, and a waypoint coordinator adjusts prompts, oracle strategies, and agent composition for the next epoch.

## Architecture

```
Epoch N:
  1. Swarm agents solve tasks (coding + oracle roles in parallel)
  2. Docker eval scores patches (FAIL_TO_PASS, regressions)
  3. Failure analyst diagnoses each failed train task
  4. Waypoint coordinator produces:
     - lessons_text (generic coding advice for swarm prompt)
     - oracle_adjustments (add/remove/tune verification strategies)
     - composition (agent counts, parallelism, planner hints)
  5. Next epoch runs with all adjustments applied
```

## Prerequisites

Before running experiments, ensure:

```bash
# 1. Environment variables (source .env or export)
source .env  # ANTHROPIC_API_KEY (required), LANGFUSE keys (optional)

# 2. Docker is running and accessible (only needed for evaluation, not for the swarm itself)
docker ps  # verify Docker daemon is running
# On Linux: sudo chown root:docker /var/run/docker.sock  # if permission denied

# 3. Check which SWE-bench eval images are available
docker images --filter "reference=sweb.eval*" --format "{{.Repository}}" | sed 's/sweb.eval.x86_64.//'
```

## Running Experiments

### Self-Improving Loop (recommended)

The main command is `kekule-improve`:

```bash
set -a && source .env && set +a && \
uv run python -m kekule.benchmarks.self_improving_harness \
  --train-ids <task1> <task2> <task3> \
  --test-ids <task4> <task5> \
  --epochs 2 \
  --experiment-name "my-experiment" \
  2>&1
```

> Use `--epochs 2` or more to get the full self-improving loop (failure analysis + waypoint coordinator). With `--epochs 1`, only the swarm runs -- no post-run analysis is generated.

### Key Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--solver` | `oracle_swarm` | `oracle_swarm` (with verification agents) or `perturbation_swarm` (coding only) |
| `--train-ids` | - | Explicit train task IDs (coordinator sees full logs) |
| `--test-ids` | - | Explicit test task IDs (coordinator sees pass/fail only) |
| `--epochs` | 3 | Number of self-improving epochs |
| `--start-epoch` | 0 | Resume from this epoch (loads prior lessons/config) |
| `--max-parallel` | 6 | Max concurrent agents |
| `--max-turns` | - | Max agent turns per task (unlimited if unset) |
| `--enable-chatoverflow` | off | Register agents on ChatOverflow Q&A forum |
| `--skip-eval` | off | Skip Docker evaluation (useful for testing) |
| `--prompts-dir` | - | Directory with custom prompt overrides |
| `--export-prompts` | - | Export default prompts to a directory and exit |
| `--dataset` | `lite` | `lite` (300 tasks) or `full` (2294 tasks) |

### Important Behavior Notes

- **`--epochs 1` skips post-run analysis.** Failure analysis and the waypoint coordinator only run *between* epochs (to produce lessons, oracle adjustments, and composition changes for the next epoch). With `--epochs 1`, no analysis is generated -- no `failure_diagnoses.json` or `coordinator_output.json`. Use `--epochs 2` or more to get the full self-improving loop with diagnostics.
- **`--skip-eval` reports 0% scores.** When Docker evaluation is skipped, all scores show 0/N (0.0%). Patches are still generated and oracle checks still run -- the 0% only reflects that the SWE-bench Docker harness didn't verify them. Run eval separately (see "Running Docker Eval Separately" below) to get real scores.
- **Docker is only required for evaluation**, not for running the swarm itself. You can run experiments with `--skip-eval` without Docker.

### Solvers

**oracle_swarm** (default): Injects oracle verification agents into the swarm. Each enabled OracleStrategy becomes a swarm role that generates tests in parallel with coding agents. After the swarm completes, oracle checks run against the patch. If checks fail, a second round starts with feedback.

**perturbation_swarm**: Coding agents only (no oracles). Cheaper and faster. Uses the same SwarmBus, beads, and role planning infrastructure.

### Available Tasks with Docker Images

Check which tasks have pre-built eval images:
```bash
docker images --filter "reference=sweb.eval*" --format "{{.Repository}}" | sed 's/sweb.eval.x86_64.//' | sort
```

Cross-reference with SWE-bench Lite:
```bash
uv run --native-tls python3 -c "
from kekule.benchmarks.task_selector import load_swebench_lite
ds = load_swebench_lite()
lite_ids = {d['instance_id'] for d in ds}
# paste task IDs to check
for t in ['django__django-16379', 'pylint-dev__pylint-7080']:
    print(f'{t}: {\"LITE\" if t in lite_ids else \"full-only\"}')"
```

### Known Passing Tasks (good for validation)
- `django__django-16379` — race condition in FileBasedCache
- `django__django-14915` — ModelChoiceField hash

### Resuming Experiments

If a run crashes mid-epoch, resume from the last completed epoch:
```bash
# ... same env setup ... \
uv run --native-tls python -m kekule.benchmarks.self_improving_harness \
  --train-ids <same tasks> \
  --test-ids <same tasks> \
  --start-epoch 1 \
  --epochs 1 \
  --experiment-name "same-experiment-name"
```

This loads lessons, oracle adjustments, and composition from `results/<experiment>/epoch_0/coordinator_output.json`.

### Running Docker Eval Separately

If an experiment ran with `--skip-eval` or the eval needs re-running:
```bash
sudo chown root:docker /var/run/docker.sock  # fix permissions if needed
uv run --native-tls python -c "
from kekule.benchmarks.evaluator import run_swebench_evaluation, print_evaluation_summary
results = run_swebench_evaluation(
    predictions_path='results/<experiment>/epoch_0/predictions_best_of_n.jsonl',
    run_id='<unique_run_id>',
    max_workers=4,
)
print_evaluation_summary(results)"
```

## Analyzing Results

### Experiment Artifacts

Each experiment saves to `results/<experiment-name>/`:

```
results/my-experiment/
  split.json                           # Train/test task IDs
  scores.json                          # Score progression per epoch
  lessons.md                           # Accumulated lessons
  prompts/                             # Editable prompt templates (8 files)
  prompt_snapshots/
    epoch_0_prompts.json               # All prompts at epoch 0
    epoch_0_config.json                # Oracle strategies + composition
  epoch_0/
    raw_results.json                   # Full results (patches, costs, turns, roles)
    coordinator_output.json            # Lessons + oracle adjustments + analysis
    failure_diagnoses.json             # Per-task failure analysis
    predictions_best_of_n.jsonl        # SWE-bench format predictions
  epoch_1/
    ...
```

### Reading Results

```bash
# Score progression
cat results/<experiment>/scores.json | python3 -m json.tool

# Coordinator lessons and oracle adjustments
cat results/<experiment>/epoch_0/coordinator_output.json | python3 -c "
import json, sys; d=json.load(sys.stdin)
print('Lessons:', d.get('lessons_text','')[:500])
print('Oracle adj:', json.dumps(d.get('oracle_adjustments',{}), indent=2))"

# Failure diagnoses
cat results/<experiment>/epoch_0/failure_diagnoses.json | python3 -c "
import json, sys
for d in json.load(sys.stdin):
    print(f'{d[\"instance_id\"]}: {d[\"root_cause\"]}')"

# Compare patches between epochs
python3 -c "
import json
for ep in [0, 1]:
    with open(f'results/<experiment>/epoch_{ep}/raw_results.json') as f:
        for r in json.load(f):
            print(f'Epoch {ep} {r[\"instance_id\"].split(\"__\")[-1]}: {len(r.get(\"model_patch\",\"\"))}B, {r.get(\"num_turns\",\"?\")} turns')"
```

### Comparing Test Breakdown Across Epochs

```bash
# Check eval reports for detailed FAIL_TO_PASS / regression data
find logs/run_evaluation -name "report.json" | while read f; do
    python3 -c "
import json
with open('$f') as fp:
    for iid, s in json.load(fp).items():
        f2p = s.get('tests_status',{}).get('FAIL_TO_PASS',{})
        fixed = len(f2p.get('success',[])); total = fixed + len(f2p.get('failure',[]))
        reg = len(s.get('tests_status',{}).get('PASS_TO_PASS',{}).get('failure',[]))
        print(f'{iid}: {fixed}/{total} fixed, {reg} regressions')"
done
```

## Customizing Prompts

Export, edit, and reload prompt templates:

```bash
# Export all 8 prompts
uv run --native-tls python -m kekule.benchmarks.self_improving_harness --export-prompts ./my-prompts/

# Edit any prompt (swarm_protocol.md, coordinator.md, planner.md, etc.)
# Then run with custom prompts:
uv run --native-tls python -m kekule.benchmarks.self_improving_harness \
  --prompts-dir ./my-prompts/ \
  --train-ids ... --test-ids ... --epochs 2
```

### Prompt Keys

| Key | File | Controls |
|-----|------|----------|
| `swe_solver` | swe_solver.md | Default single-agent solver |
| `swarm_protocol` | swarm_protocol.md | Multi-agent swarm communication rules |
| `planner` | planner.md | Role decomposition agent |
| `oracle_unit_test` | oracle_unit_test.md | Unit test oracle generator |
| `oracle_regression_check` | oracle_regression_check.md | Regression oracle generator |
| `oracle_behavioral_assertion` | oracle_behavioral_assertion.md | Behavioral check generator |
| `coordinator` | coordinator.md | Waypoint coordinator (produces lessons + oracle adjustments) |
| `oracle_role` | oracle_role.md | Oracle agent swarm role template |

## UI Dashboard

Start the dashboard to browse experiments:

```bash
uv run python3 -m uvicorn kekule.ui.app:app --reload --port 8000
```

Then visit:
- `/experiments` — list all self-improving experiments with score progression
- `/experiments/<name>` — epoch details, coordinator output, failure diagnoses
- `/benchmarks` — standalone benchmark run results
- `/api/experiments` — JSON API for programmatic access

## Oracle Strategies

The coordinator can create, modify, and disable oracle strategies across epochs. Default strategies:

| Strategy | Mode | Purpose |
|----------|------|---------|
| `unit_test` | pytest | Tests verifying the fix handles reported behavior |
| `regression_check` | pytest | Tests verifying no existing functionality breaks |
| `behavioral_assertion` | bash | Lightweight `python -c` smoke checks |

The coordinator commonly creates:
- `full_test_suite_runner` — runs the project's real test suite
- `smoke_test` — runs `--version` / basic import to catch catastrophic regressions
- `str_repr_consistency_check` — verifies `__str__`/`__repr__` consistency

## Workflow Tips

1. **Start with known-passing tasks in train** to give the coordinator both success and failure patterns
2. **Use `--skip-eval` for fast iteration** on prompt changes, then re-run eval separately
3. **Check `failure_diagnoses.json`** — the failure analyst often identifies the exact fix needed
4. **The coordinator's oracle adjustments are the primary improvement mechanism** — lessons help but oracles catch bugs before submission
5. **Resume with `--start-epoch`** instead of restarting when a run crashes
6. **Fix Docker permissions** with `sudo chown root:docker /var/run/docker.sock` after container restarts
