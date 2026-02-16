# Telemetry & Observability

Kekule supports two complementary observability systems:

1. **Langfuse Tracing** -- full conversation traces with generations, tool use spans, and agent results
2. **Claude Code OpenTelemetry** -- metrics (token usage, costs) and events (tool results, API requests)

## Langfuse Tracing

### Quick Start

Set three environment variables and run the benchmark:

```bash
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"

uv run kekule-bench --problems 2 --agents-per-problem 1 --iterations 1 --skip-eval
```

The harness auto-detects Langfuse when all three variables are set. Verify with `--dry-run`:

```bash
uv run kekule-bench --dry-run
# Look for: LangFuse: enabled
```

### What Gets Traced

The tracing produces a hierarchical tree in Langfuse:

```
swe-bench-iteration-0 (span)
├── agent-0-django__django-16379 (span)
│   ├── input: { prompt: "## GitHub Issue to Solve ..." }
│   ├── output: { patch_produced: true, patch: "diff --git ...", num_turns: 17, cost: 0.55 }
│   ├── turn-1 (generation, model=claude-opus-4-5)
│   │   └── output: "I'll start by reading the relevant file..."
│   ├── tool:Read (span, input: { file_path: "django/core/cache/..." })
│   ├── tool_result (event)
│   ├── turn-2 (generation)
│   │   └── output: "The issue is a TOCTOU race condition..."
│   ├── tool:Edit (span, input: { file_path: "...", old_string: "...", new_string: "..." })
│   ├── tool_result (event)
│   └── ...
└── agent-0-django__django-14915 (span)
    └── ...
```

| Langfuse Object | Maps To | Data |
|---|---|---|
| **Span** (top-level) | Experiment iteration | Model, agents_per_problem, num_problems |
| **Span** (child) | Agent run | Prompt (input), patch + metrics (output) |
| **Generation** | LLM turn | Model name, assistant text output |
| **Span** | Tool use | Tool name, tool input |
| **Event** | Tool result | tool_use_id, is_error, content preview |

### How It Works

The conversation is captured directly from the Claude Agent SDK `query()` message stream -- not from hooks. Each `AssistantMessage` (with `TextBlock` and `ToolUseBlock`) and each `UserMessage` (with `ToolResultBlock`) is serialized and accumulated during the agent run. After the agent completes, the `TracingManager` pushes all messages to Langfuse as generations, spans, and events.

Relevant source files:
- `src/kekule/benchmarks/tracing.py` -- `TracingManager`, `AgentTraceData`, `_create_conversation_traces()`
- `src/kekule/benchmarks/solver_agent.py` -- message accumulation in `solve_swe_task()`
- `src/kekule/benchmarks/config.py` -- `langfuse_enabled` property, env var loading

### Configuration Reference

| Variable | Required | Description |
|---|---|---|
| `LANGFUSE_SECRET_KEY` | Yes | Langfuse secret key (starts with `sk-lf-`) |
| `LANGFUSE_PUBLIC_KEY` | Yes | Langfuse public key (starts with `pk-lf-`) |
| `LANGFUSE_BASE_URL` | Yes | Langfuse host URL (e.g., `https://cloud.langfuse.com`) |

All three must be set for tracing to activate. If any is missing, tracing is silently disabled via `_NoOpSpan`.

## Claude Code OpenTelemetry

Claude Code has built-in OpenTelemetry support for metrics and events. This is separate from Langfuse tracing -- it exports aggregate metrics (token counts, costs, session counts) and structured events (tool results, API requests), not conversation traces.

### Quick Start

```bash
# Enable telemetry
export CLAUDE_CODE_ENABLE_TELEMETRY=1

# Export metrics and events via OTLP
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Optional: authentication
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer your-token"

# Optional: faster export for debugging (default: 60s metrics, 5s logs)
export OTEL_METRIC_EXPORT_INTERVAL=10000
export OTEL_LOGS_EXPORT_INTERVAL=5000
```

To pass these to the benchmark agents, add them to `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"
  }
}
```

### Available Metrics

| Metric | Unit | Description |
|---|---|---|
| `claude_code.token.usage` | tokens | Broken down by type: input, output, cacheRead, cacheCreation |
| `claude_code.cost.usage` | USD | Cost per API request, broken down by model |
| `claude_code.session.count` | count | Sessions started |
| `claude_code.lines_of_code.count` | count | Lines added/removed |
| `claude_code.active_time.total` | seconds | Active time (not idle) |

### Available Events

| Event | Description |
|---|---|
| `claude_code.user_prompt` | User prompt submitted (content redacted by default; enable with `OTEL_LOG_USER_PROMPTS=1`) |
| `claude_code.tool_result` | Tool execution completed (tool name, success, duration, error) |
| `claude_code.api_request` | API call to Claude (model, cost, tokens, duration) |
| `claude_code.api_error` | API call failed (error, status code) |

### Exporter Options

| Exporter | Metrics | Events | Notes |
|---|---|---|---|
| `otlp` | Yes | Yes | Standard OTLP (gRPC or HTTP) |
| `console` | Yes | Yes | Prints to stdout, useful for debugging |
| `prometheus` | Yes | No | Prometheus scrape endpoint |

Multiple exporters can be combined: `OTEL_METRICS_EXPORTER=console,otlp`

Full documentation: [code.claude.com/docs/en/monitoring-usage](https://code.claude.com/docs/en/monitoring-usage)

## Langfuse vs OTel: What Goes Where

| Data | Langfuse | OTel |
|---|---|---|
| Full conversation (messages, tool I/O) | Yes | No |
| Per-turn LLM generations | Yes | No |
| Agent prompt and patch output | Yes | No |
| Token usage per request | No | Yes |
| Cost per request | No | Yes |
| Tool execution duration | No | Yes |
| Session counts | No | Yes |

**Recommendation:** Use both. Langfuse gives you conversation-level debugging ("what did the agent do?"). OTel gives you operational monitoring ("how much did it cost? how many tokens?").

## Passing Environment Variables

Since `load_dotenv` is not called automatically, pass Langfuse variables directly:

```bash
# Inline with the command
LANGFUSE_SECRET_KEY="sk-lf-..." \
LANGFUSE_PUBLIC_KEY="pk-lf-..." \
LANGFUSE_BASE_URL="https://cloud.langfuse.com" \
uv run kekule-bench --problems 2 --skip-eval

# Or export them first
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
uv run kekule-bench --problems 2 --skip-eval
```

OTel variables for Claude Code agents should go in `~/.claude/settings.json` under `env`, since the agents inherit their environment from Claude settings (via `setting_sources=["user"]`).
