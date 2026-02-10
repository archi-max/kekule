# Kekule 🐍

> *Named after August Kekulé's famous dream of a snake eating its own tail—the ouroboros that led to the discovery of benzene's ring structure. Just as that moment of lateral thinking revolutionized chemistry, we explore how analogical reasoning and structured exploration can unlock breakthrough capabilities in agent swarms.*

A heterarchical swarm of agents aimed to self-organize to solve problems and explore frontier capabilities of models in swarm settings.

**Built for**: [Built with Opus 4.6: a Claude Code hackathon](https://cerebralvalley.ai/) by Cerebral Valley & Anthropic

**Team**: [Ansh Tulsyan](https://github.com/archi-max) & [Jack Armitage](https://github.com/jarmitage)

## Overview

Kekule is a swarm orchestrator that enables multiple Claude agents to self-organize and collaborate on complex software engineering tasks. Unlike traditional hierarchical systems, Kekule implements a heterarchical approach where agents can dynamically form organizational patterns based on the task at hand—ranging from hierarchical (coordinator + workers) to peer-to-peer collaboration.

### Core Concepts

**Heterarchical Self-Organization**: Agents dynamically form collaboration structures without centralized control, enabling emergent problem-solving behaviors. They can shift between hierarchical and peer-to-peer patterns based on task requirements.

**Exploration & Discovery**: Inspired by Kekulé's lateral thinking and Edison's experimental approach, we aim to explore how agent swarms can discover breakthrough solutions through diverse strategies and emergent coordination—though the specific mechanisms remain to be discovered within the constraints of Claude Agent SDK.

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
uv run python -m kekule.main
```

The example demonstrates:
- Simple agent queries using Claude Agent SDK
- Code analysis with file reading tools (Read, Glob, Grep)
- Foundation for building heterarchical swarm patterns

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

- `src/kekule/main.py` - Example agent using Claude Agent SDK
- `src/kekule/` - Main package (orchestrator to be implemented)
- `tests/` - Test suite

## Built With

- **[Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)** - Autonomous agents with tools
- **Python 3.11+** - Core language
- **uv** - Fast Python package manager
- **Pydantic** - Data validation and settings

## Roadmap

### Phase 1: Foundation
- [ ] Core swarm orchestrator implementation
- [ ] Hierarchical pattern (coordinator + workers)
- [ ] Peer-to-peer pattern
- [ ] Agent communication protocols

### Phase 2: Exploration & Coordination
- [ ] Task decomposition strategies
- [ ] Inter-agent communication protocols
- [ ] Diverse problem-solving approaches
- [ ] Emergent coordination patterns

### Phase 3: Evaluation
- [ ] SWE Bench integration
- [ ] Performance metrics & benchmarking
- [ ] Logging and observability
- [ ] State persistence

## License

MIT

## Acknowledgments

- Inspired by August Kekulé's ouroboros dream and the power of analogical reasoning
- Edison's approach to productive experimentation and exploration
- Built with Claude Opus 4.6 for the Cerebral Valley hackathon
