# Kekule Benchmark Data

This branch contains benchmark evaluation artifacts from Kekule experiments.

## Contents

- `kekule-*.json` -- SWE-bench evaluation result summaries (per experiment)
- `logs/run_evaluation/` -- Detailed per-task evaluation reports from SWE-bench Docker harness
- `logs/build_images/` -- Docker image build logs for SWE-bench eval containers
- `experiments/` -- Experiment runner scripts and configs
- `task_sets/` -- Curated task ID sets used in experiments

## Experiment Naming

Files follow the pattern: `kekule-{solver}-{model}.{experiment_name}.json`

| Solver | Description |
|--------|-------------|
| `claude-opus-4-5` | Single-agent baseline (default solver) |
| `swarm-claude-opus-4-5` | Perturbation swarm (multi-agent) |
| `oracle-swarm-claude-opus-4-5` | Oracle swarm with self-improving loop |

## See Also

Code and documentation are on the [`main`](../../tree/main) branch.
