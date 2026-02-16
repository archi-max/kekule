# Oracle Dashboard UI

The "driving" interface where engineers orchestrate agent swarms between waypoints, define rules, monitor progress, and validate oracle results.

## Concept

See [../THEORY.md](../THEORY.md) for the full architecture. This project implements the **Dashboard** — the frontend where users steer development instead of writing code.

## What This Does

The dashboard provides:

1. **Rule Elicitation** — Collaborative interface to turn NLP into structured, verifiable rules
2. **Waypoint Graph** — Visual DAG showing waypoint dependencies, status, and progress
3. **Agent Monitor** — Real-time view of swarm agents (who's doing what, where, status)
4. **Oracle Results** — Pass/fail per rule with evidence (test output, screenshots, diffs)
5. **Waypoint Controls** — Approve/reject/override at waypoint gates
6. **Conflict Resolution** — Parallel path visualization when oracles disagree

## Core Views

### 1. Project Setup View
- User describes project goal in natural language
- AI proposes rules (structured acceptance criteria)
- User confirms/modifies rules
- Rules displayed as cards with oracle_type, uncertainty, status

### 2. Waypoint Map View
- DAG visualization of waypoints (beads dependency graph)
- Each node shows: description, rule count, status (pending/active/passed/failed)
- Edges show dependencies
- Click waypoint to see details, rules, oracle results
- Git commit SHA displayed on completed waypoints

### 3. Swarm Monitor View
- Real-time agent status (from SwarmBus data)
- Per-agent: role, current file, phase (exploring/fixing/verifying/done)
- Message feed from SwarmBus (findings, broadcasts, status updates)
- Beads task board: ready / in-progress / blocked / done

### 4. Oracle Results View
- Per-waypoint verification results
- Each rule: pass/fail badge, oracle type icon, evidence expandable
- Evidence types: test output (terminal), screenshots (pixel match), diffs, logs
- Override button with rationale input (audit trail)
- Re-run button for individual oracles

### 5. Conflict Resolution View
- When oracle disagrees: show forked paths
- Side-by-side comparison of parallel approaches
- User picks winner or merges
- History of overrides and rationale

## Data Sources

| Data | Source | Protocol |
|---|---|---|
| Agent status | SwarmBus | WebSocket / polling against bus API |
| Waypoint graph | Beads (bd CLI) | REST API wrapper or direct bd queries |
| Oracle results | Oracle Runner output | File-based (oracle_artifacts/) or API |
| Rules | Rule Elicitor | API (create/update/confirm rules) |
| Git state | Git | git log, git diff via API |
| Agent messages | SwarmBus ledger | File watch (BROADCAST.md) or API |

## Backend API (to build)

The UI needs a thin API layer over existing infrastructure:

```
POST   /api/rules              # Create rule (from elicitor)
PUT    /api/rules/:id          # Update/confirm rule
GET    /api/rules              # List all rules
GET    /api/waypoints          # Get waypoint DAG
POST   /api/waypoints/:id/approve   # Approve waypoint
POST   /api/waypoints/:id/reject    # Reject, trigger re-work
GET    /api/swarm/status       # Current swarm agent statuses
GET    /api/swarm/messages     # Recent SwarmBus messages
GET    /api/oracle/:waypoint   # Oracle results for waypoint
POST   /api/oracle/:waypoint/run    # Trigger oracle battery
POST   /api/override           # User override with rationale
```

## Tech Stack (suggested)

- **Frontend**: React + TypeScript (or Svelte — TBD based on preference)
- **State management**: Minimal — server-driven, polling/WebSocket for real-time
- **Visualization**: D3.js or dagre for waypoint DAG
- **Backend API**: FastAPI (Python) — wraps SwarmBus, BeadsTracker, Oracle Runner
- **Styling**: Tailwind CSS

## Directory Structure (proposed)

```
oracle/ui/
  backend/
    app.py              # FastAPI application
    routes/
      rules.py          # Rule CRUD endpoints
      waypoints.py      # Waypoint graph + controls
      swarm.py          # SwarmBus status + messages
      oracle.py         # Oracle results + trigger
    models.py           # Pydantic models for API
  frontend/
    src/
      components/
        RuleCard.tsx
        WaypointGraph.tsx
        AgentMonitor.tsx
        OracleResults.tsx
        ConflictView.tsx
      pages/
        Setup.tsx
        Dashboard.tsx
      App.tsx
      main.tsx
    package.json
    tsconfig.json
    vite.config.ts
  README.md
```

## Running

```bash
# Backend
cd oracle/ui/backend && uv run uvicorn app:app --reload

# Frontend
cd oracle/ui/frontend && npm install && npm run dev
```

## Integration with Oracle Generator

The UI calls the Oracle Generator's API/CLI to:
1. Trigger rule elicitation (conversational agent)
2. Generate oracle artifacts from confirmed rules
3. Execute oracle battery and display results
4. Regenerate oracles when rules change or waypoints advance
