# Self-Improving Oracle Swarm

A self-improving loop that connects Kekule's **benchmark harness** and **oracle verification system** to iteratively improve agent performance on SWE-bench.

## How It Works

```
                   ┌──────────────────────────────────────────┐
                   │            EPOCH LOOP                     │
                   │                                           │
  ┌────────────┐   │   ┌────────────────────────────────┐     │
  │ Train/Test │───┼──>│  Swarm Solver (per task)        │     │
  │   Split    │   │   │                                 │     │
  └────────────┘   │   │  Phase 0: Plan roles            │     │
                   │   │  Phase 1: Agents + Oracles run   │     │
                   │   │  Phase 2: Oracle feedback loop   │     │
                   │   │  Phase 3: Select best patch      │     │
                   │   └───────────────┬────────────────┘     │
                   │                   │                       │
                   │                   ▼                       │
                   │   ┌────────────────────────────────┐     │
                   │   │  SWE-bench Evaluation           │     │
                   │   │  (Docker, optional)              │     │
                   │   └───────────────┬────────────────┘     │
                   │                   │                       │
                   │                   ▼                       │
                   │   ┌────────────────────────────────┐     │
                   │   │  Waypoint Coordinator           │     │
                   │   │                                 │     │
                   │   │  Train: results + logs          │     │
                   │   │  Test:  pass/fail only          │     │
                   │   │                                 │     │
                   │   │  Outputs:                       │     │
                   │   │  • lessons_text → swarm prompt  │     │
                   │   │  • oracle adjustments           │     │
                   │   │  • composition changes          │     │
                   │   └───────────────┬────────────────┘     │
                   │                   │                       │
                   │            apply adjustments              │
                   │                   │                       │
                   │              next epoch ──────────────────┘
                   └──────────────────────────────────────────┘
```

## Two Loops

### Inner Loop (per task)

Each task gets a swarm of agents that self-organize to solve a GitHub issue:

1. **Planner** reads the issue, assigns 2-4 specialist roles (e.g., `root_cause_tracer`, `fix_implementer`)
2. **Oracle roles** are injected — one per enabled oracle strategy (e.g., `oracle_unit_test`, `oracle_regression`). They generate verification tests in parallel with coding agents
3. Coding agents work on the fix, oracle agents generate checks
4. After the swarm completes, oracle checks run against the fix
5. If checks fail → launch another swarm round with failure feedback
6. Accept the best patch after max rounds

### Outer Loop (across epochs)

The waypoint coordinator analyzes epoch results and adjusts three things:

| Output | What it adjusts | Example |
|--------|-----------------|---------|
| `lessons_text` | Swarm system prompt | "For Django ORM issues, run the full test module" |
| `oracle_adjustments` | Oracle strategy composition | Add e2e test oracle, disable regression oracle |
| `composition` | Agent counts & parallelism | Reduce to 2 coding agents, switch oracles to sequential |

**Generalization constraint**: The coordinator sees full logs for **train** tasks but only pass/fail for **test** tasks. The train/test split stays fixed across epochs to prevent overfitting.

## Quick Start

```bash
# Run with explicit train/test split and perturbation swarm
kekule-improve \
  --solver perturbation_swarm \
  --dataset full \
  --train-ids django__django-14534 django__django-16631 django__django-14155 \
  --test-ids django__django-11477 django__django-15022 \
  --enable-chatoverflow \
  --epochs 3 \
  --experiment-name "my-experiment" \
  --skip-eval

# Run with auto train/test split (70/30)
kekule-improve \
  --solver oracle_swarm \
  --problems 10 \
  --train-ratio 0.7 \
  --epochs 5

# Dry run (print config and exit)
kekule-improve --dry-run --problems 5

# Export default prompts for editing
kekule-improve --export-prompts ./my-prompts/

# Run with custom prompts
kekule-improve --prompts-dir ./my-prompts/ --problems 5 --epochs 3
```

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--solver` | `oracle_swarm` | Solver module: `oracle_swarm`, `perturbation_swarm`, `default` |
| `--dataset` | `lite` | SWE-bench dataset: `lite` (300 tasks) or `full` (2294 tasks) |
| `--epochs` | `3` | Number of self-improving epochs |
| `--train-ids` | — | Explicit train task IDs (overrides `--train-ratio`) |
| `--test-ids` | — | Explicit test task IDs (overrides `--train-ratio`) |
| `--train-ratio` | `0.7` | Auto-split ratio when explicit IDs not provided |
| `--problems` | `3` | Number of problems (for auto-split mode) |
| `--model` | `claude-opus-4-5` | Model for swarm agents |
| `--coordinator-model` | `claude-opus-4-5` | Model for the waypoint coordinator |
| `--enable-chatoverflow` | off | Enable ChatOverflow Q&A forum |
| `--prompts-dir` | — | Directory with prompt override files |
| `--export-prompts` | — | Export default prompts to a directory and exit |
| `--max-parallel` | `6` | Max agents running in parallel |
| `--skip-eval` | off | Skip SWE-bench Docker evaluation |

## Configurable Prompts

All system prompts are configurable via `--prompts-dir`. Export defaults first, edit, then reload:

```bash
kekule-improve --export-prompts ./prompts/
# Edit ./prompts/swarm_protocol.md, coordinator.md, etc.
kekule-improve --prompts-dir ./prompts/ --epochs 3
```

| Prompt Key | File | What it controls |
|------------|------|-----------------|
| `swe_solver` | `swe_solver.md` | Default solver system prompt |
| `swarm_protocol` | `swarm_protocol.md` | Swarm agent communication protocol |
| `planner` | `planner.md` | Role planner that decomposes tasks |
| `oracle_unit_test` | `oracle_unit_test.md` | Unit test oracle generator |
| `oracle_regression_check` | `oracle_regression_check.md` | Regression check oracle generator |
| `oracle_behavioral_assertion` | `oracle_behavioral_assertion.md` | Behavioral assertion oracle |
| `coordinator` | `coordinator.md` | Waypoint coordinator system prompt |
| `oracle_role` | `oracle_role.md` | Oracle agent swarm role template |

Prompts are versioned per epoch in `results/{experiment}/prompt_snapshots/`.

## Oracle Strategies

Three default oracle strategies are included. The coordinator can enable/disable, add new ones, or tune prompts across epochs.

| Strategy | Mode | What it generates |
|----------|------|-------------------|
| `unit_test` | pytest | Focused tests verifying the fix handles the reported behavior |
| `regression_check` | pytest | Tests verifying the fix doesn't break existing functionality |
| `behavioral_assertion` | bash | Lightweight `python -c` smoke checks |

## Output Artifacts

Each epoch saves to `results/{experiment}/`:

```
results/django-perturb-v1/
  split.json                         # Train/test task IDs
  scores.json                        # Score progression (train + test per epoch)
  lessons.md                         # Accumulated lessons text
  prompts/                           # Default prompts (editable reference)
    swe_solver.md
    swarm_protocol.md
    coordinator.md
    ...
  prompt_snapshots/
    epoch_0_prompts.json             # All prompt texts at epoch 0
    epoch_0_config.json              # Oracle strategies + composition
    epoch_1_prompts.json
    ...
  epoch_0/
    raw_results.json                 # Full agent results
    coordinator_output.json          # Coordinator analysis + adjustments
    predictions_epoch0.jsonl         # SWE-bench prediction format
    predictions_best_of_n.jsonl
  epoch_1/
    ...
```

## Architecture

### New Modules

| Module | Purpose |
|--------|---------|
| `benchmarks/task_splitter.py` | Deterministic train/test splitting (hash-based) |
| `benchmarks/oracle_bridge.py` | Multi-strategy oracle system (OracleStrategy, generate, run, feedback) |
| `benchmarks/waypoint_coordinator.py` | Epoch analysis agent (lessons + oracle adjustments + composition) |
| `benchmarks/solvers/oracle_swarm.py` | Inner loop solver (swarm + oracle roles + multi-round feedback) |
| `benchmarks/self_improving_harness.py` | Outer loop orchestrator (epoch management, artifact tracking) |
| `benchmarks/prompt_config.py` | Prompt configuration system (load/save/override/snapshot) |

### Reused Infrastructure

- `perturbation_swarm.py`: `plan_roles()`, `run_swarm_agent()`, `select_best_patch()`
- `swarm_bus.py`, `swarm_hooks.py`, `swarm_beads.py`: Full swarm communication stack
- `oracle/schemas.py`: `Rule`, `OracleResult` data models
- `oracle/agent.py`: `generate_oracle()` for pytest artifact generation
- `evaluator.py`: SWE-bench Docker evaluation pipeline
- `tracing.py`: LangFuse integration for per-epoch tracing

## Environment Variables

Set in `.env` or export before running:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `LANGFUSE_SECRET_KEY` | No | Enables trace recording |
| `LANGFUSE_PUBLIC_KEY` | No | LangFuse public key |
| `LANGFUSE_BASE_URL` | No | LangFuse host URL |
| `CHATOVERFLOW_API_URL` | No | ChatOverflow forum URL |
| `PERTURBATION_INTENSITY` | No | Uncertainty injection (0.0-0.20) |
