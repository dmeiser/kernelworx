"""Version-surface guard for issue #768: one Python version everywhere.

The project declares its Python version on several independent surfaces: the
tracked `.python-version` pin (what `uv` provisions locally), `requires-python`
in `pyproject.toml`, the `ruff` `target-version` and `mypy` `python_version`
settings, every `actions/setup-python` step in `.github/workflows/`, and the
Lambda `runtime` / layer `compatible_runtimes` in
`tofu/application/modules/lambda/main.tf`.

The Lambda runtime is the anchor: it is the interpreter the shipped code runs
on, so every other surface must name the same minor. Before `.python-version`
was tracked, `uv` resolved the newest locally installed interpreter (3.15) while
CI and Lambda stayed on 3.14, which let a newer-minor-only construct pass
locally and fail in production.

These tests are semantic (they parse the real files and the running
interpreter), not textual, and they deliberately do NOT assert anything about an
upper bound on `requires-python` — whether to cap it is a maintainer decision,
and the guard must survive either answer.
"""

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PYTHON_VERSION_FILE = REPO_ROOT / ".python-version"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
LAMBDA_TF = REPO_ROOT / "tofu" / "application" / "modules" / "lambda" / "main.tf"

MINOR = re.compile(r"^\d+\.\d+$")


def _pin() -> str:
    """The tracked `.python-version` pin, as a `major.minor` string."""
    assert PYTHON_VERSION_FILE.is_file(), (
        f"{PYTHON_VERSION_FILE.relative_to(REPO_ROOT)} must exist and be tracked: it is what makes "
        "local `uv` resolve the same interpreter as CI and the Lambda runtime (issue #768)."
    )
    pin = PYTHON_VERSION_FILE.read_text().strip()
    assert MINOR.match(pin), f".python-version must be a single 'major.minor' line, got {pin!r}"
    return pin


def _requires_python_floor(specifier: str) -> str:
    """The `major.minor` floor of a PEP 440 specifier, ignoring any upper bound."""
    match = re.search(r"(\d+\.\d+)", specifier)
    assert match, f"cannot read a major.minor floor out of requires-python specifier {specifier!r}"
    return match.group(1)


def test_running_interpreter_matches_the_pin() -> None:
    """The interpreter executing this test is the pinned one.

    This is the check that closes the original gap: `uv run pytest` under a
    newer minor than the shipped runtime would otherwise let a newer-minor-only
    construct pass locally and break on `python3.14` in Lambda.
    """
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert running == _pin(), (
        f"tests are running on Python {running} but the project pins {_pin()}; "
        "run them through `uv run` so the .python-version pin is honored."
    )


def test_ci_setup_python_steps_match_the_pin() -> None:
    """Every `actions/setup-python` step installs the pinned minor."""
    found: list[tuple[str, str]] = []
    for workflow in sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml")):
        for version in re.findall(r"python-version:\s*[\"']?(\d+\.\d+)[\"']?", workflow.read_text()):
            found.append((workflow.name, version))

    assert found, "no setup-python python-version pins found in .github/workflows; the guard is vacuous"
    mismatched = sorted({f"{name}: {version}" for name, version in found if version != _pin()})
    assert not mismatched, (
        f"CI installs a Python other than the .python-version pin {_pin()}: {mismatched}. "
        "The Lambda runtime is the anchor; align the workflow, not the pin."
    )


def test_lambda_runtime_matches_the_pin() -> None:
    """Lambda function runtimes and the shared layer's compatible runtime name the pin."""
    source = LAMBDA_TF.read_text()
    found = re.findall(r'\b(?:runtime|compatible_runtimes)\s*=\s*(?:\[\s*)?"python(\d+\.\d+)"', source)

    assert len(found) >= 2, f"expected Lambda runtime and layer compatible_runtimes in {LAMBDA_TF.name}, got {found}"
    off_runtime = sorted({v for v in found if v != _pin()})
    assert not off_runtime, (
        f"tofu declares Lambda Python runtime(s) {off_runtime} but .python-version pins {_pin()}; "
        "the runtime is the anchor, so every other surface follows it."
    )


def test_pyproject_settings_match_the_pin() -> None:
    """`requires-python` floor, `ruff target-version` and `mypy python_version` agree with the pin."""
    config = tomllib.loads(PYPROJECT.read_text())

    pin = _pin()
    floor = _requires_python_floor(config["project"]["requires-python"])
    assert floor == pin, f"requires-python floor is {floor} but .python-version pins {pin}"

    target_version = config["tool"]["ruff"]["target-version"]
    assert target_version == f"py{pin.replace('.', '')}", (
        f"ruff target-version is {target_version!r} but the pinned Python is {pin}; "
        "the formatter's PEP 758 output depends on this (see tests/unit/test_except_syntax.py)."
    )

    mypy_version = config["tool"]["mypy"]["python_version"]
    assert mypy_version == pin, f"mypy python_version is {mypy_version!r} but the pinned Python is {pin}"
