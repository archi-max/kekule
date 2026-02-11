# Perturbation Protocol for Agent Swarms

This document defines a lightweight, repeatable protocol for studying multi-agent LLM systems as dynamical social systems. Instead of only measuring final task success, the protocol measures how teams reroute under controlled perturbations introduced via agent hooks.

The goal is to map behavioral attractors (stable coordination patterns), locate brittle regimes, and then deliberately exploit self-organization in swarm design. Perturbation is the method: we inject controlled disruptions to uncover latent capabilities (for example rerouting, spontaneous role shifts, and robust arbitration), then encode those capabilities into explicit coordination mechanisms.

## Step overview

Use this as the quick map before reading the full protocol:

0. **Fixed baseline definition** - lock tasks, environment, team config, prompts, and evaluation settings.
1. **Instrumentation-first hooks** - collect trajectory data with logging-only hooks.
2. **Choose one perturbation axis** - select a single channel (context, tool I/O, flow, timing, or social).
3. **Encode perturbation policy with a knob** - define intensity, scope, and firing policy.
4. **Starter perturbation** - begin with mild, reversible uncertainty injection.
5. **Experimental matrix** - run baseline + low/medium/high intensity across multiple seeds.
6. **Metrics to collect** - capture task, trajectory, and coordination/failure metrics.
7. **Interpretation framework** - read results as attractor/regime shifts, not just score deltas.
8. **Escalation ladder** - increase perturbation strength only after single-axis effects are clear.
9. **Exploit discovered capabilities** - convert robust self-organizing behaviors into swarm design primitives and validate them.

Safety and governance guardrails apply throughout all steps.

## Why this protocol exists

Kekule focuses on heterarchical self-organization. For benchmark tasks like SWE-bench, that means success depends less on abstract emergence and more on robust coordination under constraints:

- shared artifacts (repo state, logs, diffs, tests)
- partial local views per agent
- noisy and asynchronous interaction
- pressure to converge without premature lock-in

Perturbations let us study this directly. If we place structured obstacles between the swarm and its goal, we can measure rerouting capacity ("cognitive light cone") rather than just one-shot correctness.

## Conceptual model

Treat the team as a coupled system:

- **Units:** individual agents with partial state
- **Coupling:** message passing, shared files, tool results, coordination prompts
- **Field:** shared workspace artifacts that bias future reads/writes
- **Control parameters:** coupling strength, message rate, context window, exploration temperature
- **Attractors:** recurring team behaviors (early lock-in, patch thrash, stable verification loop, etc.)

We expect phase-like behavior:

- under-coupling -> incoherence
- over-coupling -> premature consensus
- balanced coupling + dissent -> convergent verification

## Core principles

1. **Instrument before perturbing**
   - Add logging-only hooks first.
   - Do not change behavior until baseline traces are stable.

2. **One axis at a time**
   - Vary one perturbation knob per experiment.
   - Keep model, prompt family, tasks, and environment fixed.

3. **Mild, reversible first**
   - Start with low-intensity perturbations that do not fabricate evidence.
   - Maintain a kill switch to disable all perturbations immediately.

4. **Measure trajectories, not only outcomes**
   - Success/failure alone hides coordination dynamics.
   - Capture hypothesis churn, verification timing, and lock-in points.

5. **Escalate systematically**
   - Move from meta-context nudges to stronger perturbations only after single-axis effects are understood.

## Scope and assumptions

This protocol is designed for:

- SWE-bench style tasks with external pass/fail validation
- teams that use shared workspace artifacts and tool calls
- Claude Code style lifecycle hooks (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`)

It can be adapted to other benchmarks if equivalent traces are available.

## Step 0: Fixed baseline definition

Pin all non-perturbation variables:

- task set (for example: fixed 5-20 SWE-bench instances)
- repo commit and dependency state
- team shape (agents per problem, max turns, tool set)
- system prompts and model
- evaluation settings

Run baseline condition multiple times (minimum 3 seeds per task) to estimate variance.

## Step 1: Instrumentation-first hooks

Enable hooks that only observe and log:

- event timestamp, task ID, session/agent ID
- lifecycle event type
- tool name + sanitized input/output summary
- files touched + diff stats
- test execution outcomes and timing
- teamwork scratch artifacts if present

Write logs to append-only storage so full trajectories can be reconstructed.

### Minimal event schema

```json
{
  "ts": "2026-02-11T00:00:00Z",
  "run_id": "iter0-seed2",
  "task_id": "django__django-16379",
  "agent_id": "agent-0",
  "event": "PostToolUse",
  "tool_name": "Bash",
  "tool_input_hash": "sha256:...",
  "tool_output_hash": "sha256:...",
  "files_touched": ["django/core/cache/backends/filebased.py"],
  "perturbation": {
    "policy_id": "none",
    "fired": false,
    "intensity": 0.0
  }
}
```

## Step 2: Choose one perturbation axis

Pick exactly one channel for a given experiment:

1. **Context perturbation**
   - Inject mild uncertainty or alternative hypotheses.
   - Omit/reorder non-critical context blocks.

2. **Tool I/O perturbation**
   - Redact or reorder selected tool outputs.
   - Delay specific output classes.

3. **Flow-control perturbation**
   - Intermittently block selected tools.
   - Add friction at specific phases.

4. **Timing perturbation**
   - Add jitter or delays around read/write cycles.
   - Probe sensitivity to asynchronous coordination.

5. **Social-layer perturbation**
   - Add dissent pressure or anti-herding prompts.
   - Test whether teams verify against artifacts or defer to consensus language.

## Step 3: Encode perturbation policy with a knob

Represent each perturbation as a policy with explicit intensity parameters:

- fire probability `p` (for example: 0.05 / 0.10 / 0.20)
- magnitude (one-line nudge vs multi-line nudge)
- target scope (selected tools, paths, or phases)
- phase gating (early exploration only vs full run)

Log every intervention:

- whether it fired
- exact transformation (or stable hash)
- current intensity level

## Step 4: Starter perturbation (recommended first run)

Start with **mild uncertainty injection** in shared summaries (no false facts).

Example intervention text:

> Note: current hypothesis may be incomplete. Check at least one alternative explanation before committing.

Where to apply:

- after selected `PostToolUse` events tied to discovery actions (`Read`, `Grep`)
- early-to-mid phase only

Why this is a good first perturbation:

- small and reversible
- tests robustness of consensus dynamics
- does not alter ground-truth artifacts or test outcomes

## Step 5: Experimental matrix

For each task:

- baseline: no perturbation
- low intensity
- medium intensity
- high intensity

Use at least 3 seeds per condition. Keep all other settings fixed.

Suggested matrix template:

| Condition | Intensity | Seeds per task |
|---|---:|---:|
| baseline | 0.00 | 3 |
| low | 0.05 | 3 |
| medium | 0.10 | 3 |
| high | 0.20 | 3 |

## Step 6: Metrics to collect

### Task-level metrics

- pass rate delta vs baseline
- time-to-first-pass delta
- patch size and touched-file locality

### Trajectory-level metrics

- time to first stable hypothesis
- number of hypothesis reversals
- exploration breadth (files/functions visited)
- test frequency and cadence
- claim grounding ratio (artifact-backed vs free-form assertions)

### Coordination/failure metrics

- early lock-in frequency
- patch thrash incidence
- endless exploration without commit
- overfitting to subset tests
- consensus-without-evidence events

## Step 7: Interpretation framework (attractor mapping)

Interpret outcomes as regime shifts, not just score changes.

- **Performance down + churn up**
  - likely fragile consensus attractor; weak arbitration

- **Performance down + early lock-in up**
  - likely premature convergence attractor

- **Performance up + verification behavior up**
  - baseline likely overconfident; perturbation acted as annealing noise

- **No change across intensities**
  - perturbation too weak or wrong channel; move to a different axis

Look for threshold effects where behavior qualitatively flips. Those boundaries are often the most informative outputs.

## Step 8: Escalation ladder

Escalate only after clear single-axis characterization:

1. meta-context uncertainty nudges
2. selective tool obstruction
3. limited tool-output redaction/reordering (no falsification)
4. timing jitter and asynchronous interference
5. composed perturbations (multi-axis)

Do not compose perturbations until single-axis causal signatures are clear.

## Step 9: Exploit latent capabilities in swarm design

This is the point of the protocol. Attractor mapping is only useful if it changes how we build swarms.

Translate findings from perturbation studies into concrete design primitives:

1. **If rerouting is robust under obstruction**
   - encode explicit fallback paths (tool fallback chains, alternate search routes, degraded-mode plans)

2. **If diversity improves outcomes before convergence**
   - enforce role asymmetry and delayed consensus (independent hypothesis generators before arbitration)

3. **If teams fail via premature lock-in**
   - add anti-lock-in mechanisms (forced falsification step, contradiction checks, dissent quotas)

4. **If synchronization timing predicts success**
   - add weak phase-coupling signals (shared phase markers for explore -> patch -> verify transitions)

5. **If specific artifacts stabilize coordination**
   - formalize those artifacts as interfaces (structured evidence ledger, patch rationale schema, verification checklist)

For each extracted primitive, run a validation loop:

- implement the primitive in swarm policy/config
- re-run baseline vs intervention across seeds
- confirm the effect persists without the original perturbation

Success criterion: the swarm should retain or improve performance because the capability is now designed-in, not because perturbation accidentally helped once.

## Suggested outputs per experiment

Each run should produce:

- baseline vs perturbed metric comparison
- trajectory plots/tables (hypothesis churn, test cadence, lock-in timing)
- failure mode taxonomy with examples
- attractor map: brittle vs robust regions by perturbation intensity
- concrete design recommendations (for example: forced falsification step, role asymmetry, diversity-preserving arbitration)

## Quick run checklist

- [ ] Baseline pinned and repeated across seeds
- [ ] Logging-only hooks validated
- [ ] Single perturbation axis selected
- [ ] Intensity ladder defined
- [ ] Guardrails and kill switch enabled
- [ ] Experimental matrix executed
- [ ] Regime-shift interpretation completed
- [ ] Latent capability -> design primitive mapping completed
- [ ] Design interventions extracted for next swarm iteration

---

In short: perturb to reveal coordination mechanics, then design swarms that stabilize useful attractors and avoid brittle ones.
