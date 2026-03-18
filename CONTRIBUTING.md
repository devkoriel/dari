# Contributing to Dari

Thanks for your interest in contributing to 다리 (Dari)!

## Important Note

This bot is deployed directly to a personal machine via a self-hosted GitHub Actions runner. Because of this, **direct pushes to `main` are not allowed**. All changes must go through a pull request.

## How to Contribute

1. **Fork** this repository
2. **Create a branch** for your changes
3. **Make your changes** and ensure all checks pass
4. **Open a pull request** against `main`

## Development Setup

```bash
git clone https://github.com/<your-username>/dari.git
cd dari
uv sync --extra dev
```

## Running Checks Locally

```bash
# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format --check src/ tests/

# Tests
uv run python -m pytest tests/ -v
```

All three checks must pass before a PR can be merged.

## Code Style

- Formatted and linted with [Ruff](https://docs.astral.sh/ruff/)
- Type hints on all function signatures
- `structlog` for logging (not `print` or `logging`)
- Async-first for I/O operations

## PR Requirements

- All CI checks must pass (Lint + Test)
- At least 1 approving review required
- Branch must be up to date with `main`
