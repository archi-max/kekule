FROM python:3.13-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    docker.io \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock .python-version ./
COPY src/ src/

# Install all dependencies (core + benchmarks)
RUN uv sync --extra benchmarks --frozen

# Copy remaining project files
COPY .env.example .env.example
COPY docs/ docs/
COPY .claude/ .claude/
COPY CLAUDE.md TLDR.md README.md ./

# Ensure workspace directories exist
RUN mkdir -p results workspaces output status input logs

# Default environment
ENV PYTHONUNBUFFERED=1

# Usage:
#   docker run -e ANTHROPIC_API_KEY=sk-ant-... kekule kekule-bench --help
#   docker run -e ANTHROPIC_API_KEY=sk-ant-... kekule kekule-improve --help
#
# For SWE-bench Docker eval (requires Docker-in-Docker):
#   docker run -v /var/run/docker.sock:/var/run/docker.sock \
#     -e ANTHROPIC_API_KEY=sk-ant-... kekule kekule-improve --epochs 2 --problems 3
#
# Optional env vars:
#   LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL  (tracing)
#   CHATOVERFLOW_API_URL, CHATOVERFLOW_API_KEY                    (Q&A forum)

ENTRYPOINT ["uv", "run"]
CMD ["kekule-improve", "--help"]
