# Waypoint Architecture

**Status**: Design phase
**Date**: 2026-02-14

---

## 1. What Waypoints Are

Waypoints turn the oracle system from a one-shot tool into a **progression loop with git checkpoints and oracle gates**.

The oracle system today:
```
rules.json -> generate oracles -> run in Docker -> pass/fail (done)
```

With waypoints:
```
goal -> decompose into waypoints -> for each waypoint:
  generate oracles -> coding swarm works -> run oracles ->
    pass? -> git commit, advance
    fail? -> feed back failures, retry or escalate
```

A waypoint is a **locally verifiable intermediate state** — a bounded scope of work gated by rules and oracle verification, version-controlled via git commits, and dependency-tracked via beads.

---

## 2. Where State Lives

Three existing systems, each stores one piece:

| What | Stored in | Why |
|---|---|---|
| Waypoint ordering + dependencies | **Beads** (`bd`) | Already has DAG tracking with ready/blocked |
| Waypoint code state | **Git** commits/tags | Each passed waypoint = a tagged commit, rollback = `git reset` |
| Waypoint metadata (rules, status, results) | **Filesystem** | JSON files in `.kekule/waypoints/` |

No database needed. No new infrastructure.

---

## 3. Filesystem Structure

```
.kekule/
  waypoints/
    manifest.json          # Source of truth: waypoint list + DAG edges
    wp-001/
      waypoint.json        # {id, description, status, beads_id, git_ref}
      rules.json           # Rules for this waypoint
      oracle_results/      # Results from each oracle run attempt
        attempt-001.json   # {timestamp, results: [OracleResult, ...], passed}
        attempt-002.json
    wp-002/
      waypoint.json
      rules.json
      oracle_results/
    wp-003/
      ...
```

### manifest.json

Source of truth for waypoint DAG:

```json
{
  "goal": "Build a REST API for user management",
  "waypoints": ["wp-001", "wp-002", "wp-003", "wp-004"],
  "dependencies": [
    ["wp-002", "wp-001"],
    ["wp-003", "wp-001"],
    ["wp-004", "wp-002"],
    ["wp-004", "wp-003"]
  ],
  "active": "wp-001"
}
```

Dependencies read as: `["wp-002", "wp-001"]` means wp-002 depends on wp-001 (wp-001 must pass before wp-002 starts).

### waypoint.json

Per-waypoint metadata:

```json
{
  "id": "wp-001",
  "description": "Project scaffolding and data models",
  "status": "active",
  "beads_task_id": "swarm-3",
  "git_ref": null,
  "max_attempts": 3,
  "current_attempt": 1
}
```

Status values: `pending` | `active` | `passed` | `failed` | `skipped`

---

## 4. Data Model

Extends existing oracle schemas:

```python
@dataclass
class Waypoint:
    id: str                     # "wp-001"
    description: str            # "Project scaffolding and data models"
    status: str                 # "pending" | "active" | "passed" | "failed" | "skipped"
    rules: list[Rule]           # Acceptance criteria (from oracle/schemas.py)
    beads_task_id: str | None   # Links to beads dependency graph
    git_ref: str | None         # Commit SHA when waypoint is achieved
    max_attempts: int           # Max coding swarm iterations before escalation
    current_attempt: int        # Current attempt number

@dataclass
class WaypointManifest:
    goal: str                   # User's original goal
    waypoints: list[str]        # Ordered waypoint IDs
    dependencies: list[tuple[str, str]]  # [from, to] DAG edges
    active: str | None          # Currently active waypoint ID
```

---

## 5. Execution Flow

### Core Loop (pseudocode)

```python
async def run_waypoint_loop(goal: str, repo_path: Path):
    # Phase 0: Decompose goal into waypoints (collaborative with user)
    manifest = await decompose_into_waypoints(goal, repo_path)

    # Phase 1: Execute waypoints in topological order
    while (wp := next_ready_waypoint(manifest)) is not None:
        manifest.active = wp.id

        # Generate oracles for this waypoint's rules
        rules = load_rules(wp)
        oracle_paths = await generate_all_oracles(rules, repo_path)

        # Attempt loop
        for attempt in range(wp.max_attempts):
            # Coding swarm works toward this waypoint
            await run_coding_swarm(wp, repo_path)

            # Run oracle battery
            results = await run_oracles(rules, oracle_paths, repo_path)
            save_attempt(wp, attempt, results)

            if all(r.passed for r in results):
                # WAYPOINT PASSED
                git_ref = git_commit_and_tag(repo_path, wp.id)
                wp.status = "passed"
                wp.git_ref = git_ref
                break
            else:
                # Feed failures back to coding swarm for next attempt
                failures = [r for r in results if not r.passed]
                if attempt == wp.max_attempts - 1:
                    decision = await escalate_to_user(wp, failures)
                    if decision == "override":
                        wp.status = "passed"
                        break
                    elif decision == "skip":
                        wp.status = "skipped"
                        break

        save_manifest(manifest)
```

### What `next_ready_waypoint` does

Returns the next waypoint whose:
- Status is `pending`
- All dependencies have status `passed` (or `skipped`)

This is a topological sort — same logic as `BeadsTracker.ready()`.

---

## 6. Two-Swarm Parallelism

The oracle swarm and coding swarm operate on the **same codebase** but from **different information sources**:

- **Oracle swarm**: reads user rules, writes verification artifacts (tests)
- **Coding swarm**: reads waypoint goals, writes implementation code

They can run in parallel because **a test can be written before the code it tests exists**. A test for "GET /users returns a list" can be authored before the endpoint is built. It will fail until the coding swarm implements it — which is exactly the desired behavior.

### Pipeline Parallelism

The oracle swarm for waypoint N+1 can start while the coding swarm for waypoint N is still running:

```
Timeline:
─────────────────────────────────────────────────────────────►

WP1:  [oracle gen ████]
      [coding swarm ████████████████]
      [oracle run ██] PASS ✓ → git commit

WP2:        [oracle gen ████████]       ← starts while WP1 coding runs
                  [coding swarm █████████████]
                  [oracle run ██] FAIL ✗
                  [coding swarm ██████]  ← iterate with failure feedback
                  [oracle run ██] PASS ✓ → git commit

WP3:              [oracle gen ████]     ← starts after WP1 passes (dep)
                        [coding swarm ████████]
                        [oracle run ██] PASS ✓ → git commit

WP4:                                    ← waits for WP2 + WP3 (deps)
                              [oracle gen ████]
                              [coding swarm ████████]
                              [oracle run ██] PASS ✓ → done
```

### When to Generate Oracles

| Timing | Tradeoff |
|---|---|
| **Eager** (as soon as rules exist) | Faster pipeline, but oracles may miss context from earlier waypoints |
| **Just-in-time** (when waypoint becomes active) | Oracles see full repo state, but no parallelism |
| **Hybrid** (generate eagerly, regenerate JIT) | Best of both — start early, refine when ready |

Recommended: **Hybrid**. Generate broad structural tests eagerly (API endpoints exist, types are correct). Regenerate detailed behavioral tests just-in-time when the waypoint activates and prior waypoints have committed their code.

### Oracle Regeneration

Oracles are regenerated per waypoint activation, not once upfront, because:
- Later waypoints build on earlier code; tests must reflect current state
- Rules may be refined as users see intermediate results
- The oracle agent reads the current repo state when generating

---

## 7. Failure Handling

### Within a Waypoint (retry loop)

```
Attempt 1: coding swarm produces code → oracle battery → 3/5 pass
  → failures fed back as structured feedback:
    "FAIL: test_create_user — expected 201, got 404 (endpoint not found)"
    "FAIL: test_user_validation — email field not validated"

Attempt 2: coding swarm iterates with feedback → oracle battery → 4/5 pass
  → remaining failure fed back

Attempt 3: coding swarm iterates → oracle battery → 5/5 pass → COMMIT
```

### Escalation to User

After `max_attempts`, escalate:

1. **Override**: User accepts current state despite failures (logged with rationale)
2. **Skip**: Waypoint skipped, dependents may fail
3. **Modify rules**: User loosens or clarifies rules, attempts reset
4. **Add attempts**: User grants more iterations
5. **Manual fix**: User edits code directly, then re-runs oracles

### Waypoint Rollback

If a waypoint fails permanently and the user wants to undo:

```bash
git reset --hard <previous-waypoint-git-ref>
```

All code from the failed waypoint is reverted. The waypoint is marked `failed`. The user can modify rules and retry from the clean checkpoint.

### Cross-Waypoint Regression

When waypoint N's code breaks waypoint M's oracles (M < N):

- **Detection**: Optionally re-run all prior waypoint oracles after each commit
- **Response**: Block waypoint N, show user which prior oracles regressed
- **Resolution**: User decides — fix the regression, modify the earlier rules, or override

---

## 8. Mapping to Existing Infrastructure

| Waypoint concept | Existing code | Location |
|---|---|---|
| Generate oracles from rules | `generate_all_oracles()` | `oracle/agent.py` |
| Run oracle battery in Docker | `run_oracles()` | `oracle/runner.py` |
| Load/elicit rules | `elicit_rules()`, `load_rules_from_file()` | `oracle/elicitor.py` |
| Waypoint dependency DAG | `BeadsTracker.add_dependency()`, `.ready()`, `.blocked()` | `benchmarks/swarm_beads.py` |
| Coding swarm execution | `run_swarm_agent()` | `benchmarks/solvers/perturbation_swarm.py` |
| Inter-agent communication | `SwarmBus` | `benchmarks/swarm_bus.py` |
| Git checkpointing | Standard git | `git commit`, `git tag`, `git reset` |

### New Code Needed

| Component | Purpose |
|---|---|
| `waypoint_runner.py` | The core loop (decompose → iterate → checkpoint) |
| `waypoint_decomposer.py` | Turns goal into waypoint DAG (similar to `plan_roles()` in perturbation_swarm) |
| `Waypoint` / `WaypointManifest` schemas | Added to `oracle/schemas.py` |
| `.kekule/waypoints/` filesystem management | Read/write manifest + waypoint JSON |

---

## 9. What's Actually Different

Why this isn't just "run Claude Code, then run pytest":

| Property | Without waypoints | With waypoints |
|---|---|---|
| Tests | Must pre-exist | Generated from rules by oracle swarm |
| Progress | All or nothing | Incremental, checkpointed |
| Failure recovery | Start over | Roll back to last passed waypoint |
| Agent scope | Unbounded (whole task) | Bounded (single waypoint) |
| User control | Prompt and pray | Steer between waypoints, modify rules |
| Verification | Manual review or pre-existing CI | Automated, scaled, per-waypoint |
| Feedback loop | None (one shot) | Structured: fail → specific feedback → retry |

---

## 10. Example Walkthrough

**Goal**: "Add user authentication to this FastAPI app"

### Decomposition (AI + user, collaborative)

```
WP-001: "Add User model and database migration"
  Rules:
  - User model has id, email, hashed_password fields
  - Alembic migration creates users table
  - Model can be imported from app.models

WP-002: "Add registration endpoint" (depends: WP-001)
  Rules:
  - POST /auth/register accepts {email, password}
  - Returns 201 with user id on success
  - Returns 409 if email already exists
  - Password is hashed (not stored plaintext)

WP-003: "Add login endpoint with JWT" (depends: WP-001)
  Rules:
  - POST /auth/login accepts {email, password}
  - Returns 200 with {access_token} on valid credentials
  - Returns 401 on invalid credentials
  - Token is valid JWT with user_id claim

WP-004: "Add auth middleware" (depends: WP-002, WP-003)
  Rules:
  - Protected routes return 401 without token
  - Protected routes return 200 with valid token
  - Expired tokens return 401
```

### Execution

```
WP-001 activates
  Oracle swarm: writes test_user_model.py, test_migration.py
  Coding swarm: creates User model, writes migration
  Oracle run: 3/3 pass → git commit "wp-001: User model and migration"

WP-002 activates (WP-001 passed)
  Oracle swarm: writes test_registration.py (was generated eagerly during WP-001)
  Coding swarm: implements /auth/register
  Oracle run: 3/4 pass — "password stored plaintext" fails
  Coding swarm: adds bcrypt hashing
  Oracle run: 4/4 pass → git commit "wp-002: Registration endpoint"

WP-003 activates (WP-001 passed)
  Oracle swarm: writes test_login.py, test_jwt.py
  Coding swarm: implements /auth/login + JWT
  Oracle run: 4/4 pass → git commit "wp-003: Login with JWT"

WP-004 activates (WP-002 + WP-003 passed)
  Oracle swarm: writes test_auth_middleware.py
  Coding swarm: adds middleware, protects routes
  Oracle run: 3/3 pass → git commit "wp-004: Auth middleware"

DONE — all waypoints passed
```

User drove through 4 waypoints. Never wrote code. Defined rules. Approved outcomes. Overrode zero oracles because the tests caught real issues (plaintext passwords) and the swarm fixed them.
