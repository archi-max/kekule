# Tool I/O Reliability Experiment

This experiment probes swarm robustness when verification tool outputs are degraded through Claude Agent SDK hooks.

## Matrix

- Conditions: `toolio-baseline`, `toolio-low`, `toolio-medium`, `toolio-high`
- Seeds: `1, 2, 3`
- Perturbation mode: `tool_io_degrade`
- Target tool: `Bash`
- Phase scope: `swarm_phase1`

## Run

```bash
uv run python experiments/run_tool_io_reliability.py
```

Optional SWE-bench evaluation:

```bash
RUN_TOOLIO_EVAL=1 uv run python experiments/run_tool_io_reliability.py
```

## Outputs

- `experiments/tool-io-reliability/raw_runs.json`
- `experiments/tool-io-reliability/aggregated_results.json`
- `experiments/tool-io-reliability/summary.md`
