# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kekule is a heterarchical swarm of agents aimed to self-organize to solve problems and explore frontier capabilities of models in swarm settings. It enables multiple Claude agents to dynamically form organizational patterns—from hierarchical to peer-to-peer—based on the task at hand.

**Tech Stack**: Python 3.11+, uv package manager, Claude Agent SDK

**Key Dependencies**:
- `claude-agent-sdk` - Build autonomous agents with tools (Read, Write, Bash, WebSearch, etc.)
- `pydantic` - Data validation and configuration
- `pydantic-settings` - Settings management

## Development Commands

### Environment Setup
```bash
uv sync                    # Install dependencies
uv sync --extra dev        # Install with dev dependencies
```

### Running Code
```bash
uv run python -m kekule.main  # Run the agent SDK examples
```

### Testing & Quality
```bash
uv run pytest              # Run all tests
uv run pytest tests/path/to/test.py  # Run specific test file
uv run pytest -k test_name # Run specific test by name
uv run pytest --cov        # Run tests with coverage

uv run ruff check .        # Lint code
uv run ruff format .       # Format code
uv run mypy src/           # Type check
```

### Dependencies
```bash
uv add package-name        # Add a new dependency
uv add --dev package-name  # Add a dev dependency
uv remove package-name     # Remove a dependency
```

## Architecture

### Core Concepts

**Heterarchical Organization**: Unlike traditional hierarchical systems with fixed roles, Kekule allows agents to self-organize into different patterns based on task requirements. Agents can act as coordinators, workers, or peers depending on the context.

**Self-Organization**: Agents dynamically form collaboration structures without centralized control, enabling emergent problem-solving behaviors.

**Frontier Exploration**: The project aims to discover and test the limits of multi-agent collaboration with frontier models.

### Core Components (Planned)

1. **Orchestrator** (`src/kekule/orchestrator/`)
   - Facilitates agent self-organization
   - Supports multiple organizational patterns
   - Manages agent lifecycle and communication

2. **Agents** (`src/kekule/agents/`)
   - Base agent implementation using Claude Agent SDK
   - Built-in tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, etc.
   - Dynamic role adaptation
   - Inter-agent communication protocols

3. **Patterns** (`src/kekule/patterns/`)
   - Hierarchical: Coordinator delegates to workers
   - P2P: Agents collaborate directly as peers
   - Hybrid: Dynamic switching between patterns
   - Emergent: Allow new patterns to form naturally

4. **Benchmarks** (`src/kekule/benchmarks/`)
   - SWE Bench integration (placeholder)
   - Evaluation harness
   - Performance metrics

5. **Observability** (`src/kekule/observability/`)
   - Structured logging (placeholder)
   - Tracing and metrics (placeholder)
   - Swarm behavior analysis

6. **State Management** (`src/kekule/state/`)
   - Persistence layer (placeholder)
   - Checkpointing and recovery
   - Shared knowledge base

### Current Status

- Basic project structure with uv
- Example agents using Claude Agent SDK in `src/kekule/main.py`
  - Simple query agent demonstrating basic usage
  - Code analysis agent with file tools (Read, Glob, Grep)
- Orchestrator and swarm coordination: Not yet implemented
- SWE Bench integration: Placeholder only

### Claude Agent SDK Usage

The project uses the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) which provides:

**Available Tools**: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebSearch`, `WebFetch`, and more

**Permission Modes**:
- `default` - Requires approval for each tool use
- `acceptEdits` - Auto-approves file edits, prompts for other actions
- `bypassPermissions` - Runs without prompts (for CI/CD)

**Basic Pattern**:
```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Your task here",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Glob"],
        permission_mode="acceptEdits",
        system_prompt="Your system prompt"
    )
):
    # Handle messages
    pass
```

## Environment Variables

Create a `.env` file based on `.env.example`:
- `ANTHROPIC_API_KEY`: Your Anthropic API key (required)

## Code Style

- Use type hints for all function signatures
- Follow PEP 8 style guide (enforced by ruff)
- Write docstrings for all public functions and classes
- Keep functions focused and composable
- Use Pydantic for configuration and data validation
- Design for agent autonomy and self-organization
