# CDK Infrastructure - uv Usage

This CDK project uses **uv** for Python package management.

## Setup

Install dependencies:
```bash
uv sync
```

This creates `.venv/` and installs all dependencies from `uv.lock`.

## Common Commands

### Install a new package
```bash
uv add <package-name>
```

### Install a new dev package
```bash
uv add --dev <package-name>
```

### Run commands with uv
```bash
# Format code
uv run black cdk/ tests/
uv run isort cdk/ tests/

# Type check
uv run mypy cdk/

# Run tests with coverage
uv run pytest --cov=cdk --cov-fail-under=100

# CDK commands
uv run cdk synth
uv run cdk diff
uv run cdk deploy --profile dev
```

### Update dependencies
```bash
uv sync --upgrade
```

## Quality Standards

This project maintains **100% test coverage**. All code must pass:

1. `uv run isort cdk/ tests/`
2. `uv run black cdk/ tests/`
3. `uv run mypy cdk/`
4. `uv run pytest --cov=cdk --cov-fail-under=100`

See `AGENT.md` in the project root for complete quality standards.
