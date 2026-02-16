FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    docker.io \
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
COPY CLAUDE.md TLDR.md README.md ./

# Ensure workspace directories exist
RUN mkdir -p results workspaces output status input

# Default environment
ENV PYTHONUNBUFFERED=1

# Show help by default; override with any kekule command
CMD ["uv", "run", "kekule-bench", "--help"]
