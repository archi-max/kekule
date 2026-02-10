# Kekule

A heterarchical swarm of agents aimed to self-organize to solve problems and explore frontier capabilities of models in swarm settings.

## Overview

Kekule is a swarm orchestrator that enables multiple Claude agents to self-organize and collaborate on complex software engineering tasks. Unlike traditional hierarchical systems, Kekule implements a heterarchical approach where agents can dynamically form organizational patterns based on the task at hand—ranging from hierarchical (coordinator + workers) to peer-to-peer collaboration.

The project aims to push the boundaries of what's possible with agent swarms, exploring emergent behaviors and frontier capabilities when multiple AI agents work together. It is designed to be tested on benchmarks like SWE Bench.

## Quick Start

1. Install dependencies:
```bash
uv sync
```

2. Set up your environment:
```bash
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

3. Run the example:
```bash
uv run python main.py
```

## Development

Install development dependencies:
```bash
uv sync --extra dev
```

Run tests:
```bash
uv run pytest
```

Run linting:
```bash
uv run ruff check .
```

Format code:
```bash
uv run ruff format .
```

Type checking:
```bash
uv run mypy src/
```

## Project Structure

- `main.py` - Simple example using Claude API
- `src/kekule/` - Main package (orchestrator to be implemented)
- `tests/` - Test suite

## Roadmap

- [ ] Core swarm orchestrator implementation
- [ ] Hierarchical pattern (coordinator + workers)
- [ ] Peer-to-peer pattern
- [ ] SWE Bench integration
- [ ] Logging and observability
- [ ] State persistence
