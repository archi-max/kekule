#!/usr/bin/env python3
"""
Push stored experiment results to Langfuse retroactively.

Since the experiments ran without Langfuse enabled, the per-turn conversation
data was not captured. This script pushes the metadata we do have:
  - Per-experiment traces (intensity, solver, cost, turns, duration)
  - Per-task spans (patches, roles, eval pass/fail)

Reads credentials from .env or environment variables.

Usage:
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    uv run python experiments/push_to_langfuse.py
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt")

# Load .env file if it exists
ROOT = Path(__file__).resolve().parent.parent
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

EXPERIMENT_ROOT = ROOT / "experiments" / "uncertainty-injection"

TASK_IDS = [
    "django__django-16379",
    "django__django-14915",
    "pytest-dev__pytest-5413",
]


def main():
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    base_url = os.environ.get("LANGFUSE_BASE_URL")

    if not all([secret_key, public_key, base_url]):
        print("Error: Set LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL")
        print("       Either in .env or as environment variables.")
        sys.exit(1)

    import ssl
    import httpx
    from langfuse import Langfuse

    # Langfuse's internal httpx client doesn't use SSL_CERT_FILE,
    # so we pass a custom client with the system CA bundle.
    ssl_ctx = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
    httpx_client = httpx.Client(verify=ssl_ctx)

    langfuse = Langfuse(
        secret_key=secret_key,
        public_key=public_key,
        host=base_url,
        httpx_client=httpx_client,
    )
    print(f"Connected to Langfuse at {base_url}")

    # Load aggregated results
    agg_path = EXPERIMENT_ROOT / "aggregated_results.json"
    if not agg_path.exists():
        print(f"Error: {agg_path} not found. Run experiments first.")
        sys.exit(1)

    with open(agg_path) as f:
        experiments = json.load(f)

    # Load eval results
    eval_path = EXPERIMENT_ROOT / "eval_results.json"
    eval_data = {}
    if eval_path.exists():
        with open(eval_path) as f:
            for er in json.load(f):
                eval_data[er["name"]] = er.get("eval_results", {})

    print(f"Loaded {len(experiments)} experiments")

    for exp in experiments:
        name = exp["name"]
        raw_results = exp.get("raw_results", [])
        er = eval_data.get(name, {})
        per_task_eval = er.get("instances", {}) if isinstance(er, dict) else {}

        total_resolved = er.get("passed", 0) if isinstance(er, dict) else 0
        total_eval = er.get("total", 0) if isinstance(er, dict) else 0

        # Create a top-level span for this experiment
        experiment_span = langfuse.start_span(
            name=name,
            metadata={
                "solver": exp.get("solver"),
                "perturbation_intensity": exp.get("intensity"),
                "description": exp.get("description", ""),
                "total_cost_usd": exp.get("total_cost"),
                "total_turns": exp.get("total_turns"),
                "avg_duration_s": exp.get("avg_duration_s"),
                "patches_produced": exp.get("patches_produced"),
                "resolved": total_resolved,
                "total_eval": total_eval,
                "resolve_rate": total_resolved / total_eval if total_eval > 0 else None,
            },
            input={"task_ids": TASK_IDS},
        )

        # Create a child span for each task
        for r in raw_results:
            instance_id = r.get("instance_id", "unknown")
            task_eval = per_task_eval.get(instance_id, {})
            resolved = task_eval.get("resolved", None)

            patch = r.get("model_patch", "")
            roles = r.get("roles", [])

            task_span = experiment_span.start_span(
                name=f"task-{instance_id}",
                metadata={
                    "instance_id": instance_id,
                    "agent_id": r.get("agent_id"),
                    "num_turns": r.get("num_turns"),
                    "cost_usd": r.get("cost_usd"),
                    "duration_s": r.get("duration_s"),
                    "swarm_agents": r.get("swarm_agents"),
                    "perturbation_intensity": r.get("perturbation_intensity"),
                    "roles": roles,
                    "resolved": resolved,
                    "patch_size_bytes": len(patch),
                },
                input={
                    "instance_id": instance_id,
                    "roles": roles,
                },
                output={
                    "patch_produced": bool(patch.strip()),
                    "patch": patch[:5000],
                    "resolved": resolved,
                    "num_turns": r.get("num_turns"),
                    "cost_usd": r.get("cost_usd"),
                },
            )

            # Add eval result as an event if we have it
            if task_eval:
                task_span.create_event(
                    name="eval-result",
                    metadata={
                        "resolved": resolved,
                        "patch_applied": task_eval.get("patch_successfully_applied"),
                    },
                )

            # Add a generation to capture the patch as "model output"
            gen = task_span.start_generation(
                name=f"patch-{instance_id}",
                model=r.get("model_name_or_path", "kekule-swarm-claude-opus-4-5"),
                output=patch[:5000] if patch else "(no patch)",
                metadata={
                    "roles": roles,
                    "num_turns": r.get("num_turns"),
                },
            )
            gen.end()

            task_span.end()

        experiment_span.update(
            output={
                "resolved": total_resolved,
                "total": total_eval,
                "resolve_rate": f"{total_resolved}/{total_eval}" if total_eval > 0 else "N/A",
                "total_cost_usd": exp.get("total_cost"),
                "total_turns": exp.get("total_turns"),
            },
        )
        experiment_span.end()

        print(f"  Pushed: {name} ({len(raw_results)} tasks, "
              f"resolved={total_resolved}/{total_eval}, "
              f"cost=${exp.get('total_cost', 0):.2f})")

    langfuse.flush()
    langfuse.shutdown()
    print(f"\nDone. Pushed {len(experiments)} experiment traces to Langfuse.")
    print("Note: Per-turn conversation data was not captured (Langfuse was disabled during runs).")
    print("To get full conversation traces, re-run experiments with Langfuse enabled.")


if __name__ == "__main__":
    main()
