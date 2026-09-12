#!/usr/bin/env python3
"""Generate the integration test environment config from OpenTofu outputs.

Reads `tofu output -json` for the dev or ephemeral stack and writes the
environment variables the integration tests expect (and, optionally, the
frontend dev environment), instead of hand-maintaining values in .env or
looking resources up by naming convention via the AWS CLI.

Usage (run from the repo root):
  python3 scripts/generate_integration_env.py
      # dev stack -> ./.env

  python3 scripts/generate_integration_env.py --frontend-out frontend/.env
      # dev stack -> ./.env and frontend/.env

  python3 scripts/generate_integration_env.py --env ephemeral/pr-123
      # ephemeral stack for run id pr-123 -> ./.env

  python3 scripts/generate_integration_env.py --outputs-json captured.json --out .env
      # generate from a captured `tofu output -json` file (no stack access)

  python3 scripts/generate_integration_env.py --check --out .env
      # structural check only: every managed key present and non-empty

  python3 scripts/generate_integration_env.py --check --outputs-json captured.json --out .env
      # structural + value check against the OpenTofu outputs

Managed keys in the integration test file (from OpenTofu outputs):
  TEST_APPSYNC_ENDPOINT       <- appsync_api_url
  TEST_USER_POOL_ID           <- cognito_user_pool_id
  TEST_USER_POOL_CLIENT_ID    <- cognito_client_id
  TEST_REGION                 <- AWS_REGION env var (default us-east-1)
  E2E_BASE_URL                <- site_url (only when the stack exposes it)

Managed keys in the frontend file (with --frontend-out):
  VITE_APPSYNC_ENDPOINT            <- appsync_api_url
  VITE_APPSYNC_REGION              <- AWS_REGION env var (default us-east-1)
  VITE_COGNITO_USER_POOL_ID        <- cognito_user_pool_id
  VITE_COGNITO_USER_POOL_CLIENT_ID <- cognito_client_id
  VITE_COGNITO_DOMAIN              <- cognito_domain
  VITE_OAUTH_REDIRECT_SIGNIN       <- http://localhost:5173/
  VITE_OAUTH_REDIRECT_SIGNOUT      <- http://localhost:5173/

Existing target files are updated in place: managed keys are replaced and
every other line (secrets, test user credentials, comments) is preserved.
A missing target file is created from the matching committed template
(.env.example / frontend/.env.example) with the managed keys filled in.

The live stack path needs the root .env (TF_VAR_encryption_passphrase and
AWS credentials) and behaves read-only with respect to AWS resources: it
runs `tofu output -json` and, for backend initialization, `tofu init`
(never apply/destroy).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DEV_ENV_DIR = ROOT_DIR / "tofu" / "application" / "environments" / "dev"
EPHEMERAL_ENV_DIR = ROOT_DIR / "tofu" / "application" / "environments" / "ephemeral"
STATE_BUCKET = os.environ.get("STATE_BUCKET", "kernelworx-tofu-state-us-east-1-dev")
STATE_REGION = os.environ.get("STATE_REGION", "us-east-1")
DEFAULT_REGION = os.environ.get("AWS_REGION", "us-east-1")

INTEGRATION_TEMPLATE = ROOT_DIR / ".env.example"
FRONTEND_TEMPLATE = ROOT_DIR / "frontend" / ".env.example"

REQUIRED_OUTPUTS = ("appsync_api_url", "cognito_user_pool_id", "cognito_client_id")

# Keys that must be present and non-empty in any generated integration env file,
# regardless of which OpenTofu outputs were used (E2E_BASE_URL is conditional on
# the site_url output, so it is only checked when values are available).
INTEGRATION_STRUCTURAL_KEYS = (
    "TEST_APPSYNC_ENDPOINT",
    "TEST_USER_POOL_ID",
    "TEST_USER_POOL_CLIENT_ID",
    "TEST_REGION",
)
FRONTEND_STRUCTURAL_KEYS = (
    "VITE_APPSYNC_ENDPOINT",
    "VITE_APPSYNC_REGION",
    "VITE_COGNITO_USER_POOL_ID",
    "VITE_COGNITO_USER_POOL_CLIENT_ID",
    "VITE_COGNITO_DOMAIN",
    "VITE_OAUTH_REDIRECT_SIGNIN",
    "VITE_OAUTH_REDIRECT_SIGNOUT",
)

MANAGED_MARKER = "# managed by scripts/generate_integration_env.py"


def die(message: str) -> None:
    print(f"❌ {message}", file=sys.stderr)
    sys.exit(1)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the integration test environment config from OpenTofu outputs.",
    )
    parser.add_argument(
        "--env",
        default="dev",
        metavar="NAME",
        help="Stack to read: 'dev' (default) or 'ephemeral/<run-id>'. Ignored with --outputs-json.",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="Integration test env file to write or check (default: .env in the current directory; "
        "in --check mode, omitting it while passing --frontend-out checks the frontend file only).",
    )
    parser.add_argument(
        "--frontend-out",
        default=None,
        metavar="FILE",
        help="Frontend env file to write or check (default: none; typical value: frontend/.env).",
    )
    parser.add_argument(
        "--outputs-json",
        default=None,
        metavar="FILE",
        help="Read a captured `tofu output -json` document from FILE instead of the live stack.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify existing file(s) without writing: managed keys must be present and non-empty; "
        "with --outputs-json, values must also match the OpenTofu outputs.",
    )
    return parser.parse_args(argv)


def load_dot_env() -> None:
    """Load the repository root .env into os.environ (like deploy.sh sources it)."""
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def require_passphrase() -> None:
    if not os.environ.get("TF_VAR_encryption_passphrase"):
        die(
            "TF_VAR_encryption_passphrase is not set; the live stack path needs it from the "
            "repository root .env (see .env.example)"
        )


def run_tofu(env_dir: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tofu", "-chdir", str(env_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def fetch_live_outputs(stack: str) -> dict:
    """Run `tofu output -json` for the requested stack (read-only)."""
    require_passphrase()
    if stack == "dev":
        env_dir = DEV_ENV_DIR
        result = run_tofu(env_dir, ["output", "-input=false", "-json"])
        if result.returncode != 0:
            log("   Backend not initialized; retrying after `tofu init`...")
            init = run_tofu(env_dir, ["init", "-input=false"])
            if init.returncode != 0:
                die(
                    "`tofu init` failed in tofu/application/environments/dev; "
                    "run ./tofu/application/scripts/deploy.sh dev init manually. "
                    f"tofu said: {init.stderr.strip()}"
                )
            result = run_tofu(env_dir, ["output", "-input=false", "-json"])
    elif stack.startswith("ephemeral/"):
        run_id = stack.split("/", 1)[1]
        if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
            die(f"invalid run id in --env {stack!r}; expected ephemeral/<run-id>")
        env_dir = EPHEMERAL_ENV_DIR
        state_key = f"application/ephemeral/{run_id}/terraform.tfstate"
        # The Lambda layer archive data source needs a non-empty directory during init.
        layer_dir = ROOT_DIR / ".build" / "lambda-layer" / "python"
        layer_dir.mkdir(parents=True, exist_ok=True)
        placeholder = layer_dir / ".placeholder"
        if not placeholder.exists():
            placeholder.write_text("# placeholder\n")
        log(f"📦 Initializing OpenTofu backend for ephemeral run {run_id}...")
        init = run_tofu(
            env_dir,
            [
                "init",
                "-input=false",
                f"-backend-config=key={state_key}",
                f"-backend-config=bucket={STATE_BUCKET}",
                f"-backend-config=region={STATE_REGION}",
            ],
        )
        if init.returncode != 0:
            die(f"`tofu init` failed for ephemeral run {run_id}. tofu said: {init.stderr.strip()}")
        result = run_tofu(env_dir, ["output", "-input=false", "-json"])
    else:
        die(f"unknown --env {stack!r}; expected 'dev' or 'ephemeral/<run-id>'")

    if result.returncode != 0:
        die(f"`tofu output -json` failed. tofu said: {result.stderr.strip()}")
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        die(f"`tofu output -json` returned invalid JSON: {exc}")
    if not isinstance(raw, dict):
        die("`tofu output -json` did not return a JSON object")
    return raw


def extract_outputs(raw: dict) -> dict[str, str]:
    """Flatten `tofu output -json` into {name: value} for string outputs."""
    outputs: dict[str, str] = {}
    for name, entry in raw.items():
        value = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value:
            outputs[name] = value
    return outputs


def load_outputs(args: argparse.Namespace) -> dict[str, str] | None:
    if args.outputs_json:
        path = Path(args.outputs_json)
        if not path.exists():
            die(f"--outputs-json file not found: {path}")
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            die(f"--outputs-json file {path} is not valid JSON: {exc}")
        if not isinstance(raw, dict):
            die(f"--outputs-json file {path} must contain a JSON object")
        outputs = extract_outputs(raw)
    else:
        log(f"🔍 Reading OpenTofu outputs for stack: {args.env}")
        outputs = extract_outputs(fetch_live_outputs(args.env))
    missing = [name for name in REQUIRED_OUTPUTS if name not in outputs]
    if missing:
        die(f"missing required OpenTofu output(s): {', '.join(missing)}")
    return outputs


def expected_integration_values(outputs: dict[str, str], region: str) -> dict[str, str]:
    values = {
        "TEST_APPSYNC_ENDPOINT": outputs["appsync_api_url"],
        "TEST_USER_POOL_ID": outputs["cognito_user_pool_id"],
        "TEST_USER_POOL_CLIENT_ID": outputs["cognito_client_id"],
        "TEST_REGION": region,
    }
    if "site_url" in outputs:
        values["E2E_BASE_URL"] = outputs["site_url"]
    return values


def expected_frontend_values(outputs: dict[str, str], region: str) -> dict[str, str]:
    if "cognito_domain" not in outputs:
        die("frontend env requires the cognito_domain OpenTofu output, which this stack does not expose")
    return {
        "VITE_APPSYNC_ENDPOINT": outputs["appsync_api_url"],
        "VITE_APPSYNC_REGION": region,
        "VITE_COGNITO_USER_POOL_ID": outputs["cognito_user_pool_id"],
        "VITE_COGNITO_USER_POOL_CLIENT_ID": outputs["cognito_client_id"],
        "VITE_COGNITO_DOMAIN": outputs["cognito_domain"],
        "VITE_OAUTH_REDIRECT_SIGNIN": "http://localhost:5173/",
        "VITE_OAUTH_REDIRECT_SIGNOUT": "http://localhost:5173/",
    }


def render_managed(existing: list[str], values: dict[str, str]) -> list[str]:
    """Replace managed keys in-place; append any that are absent (with a marker comment)."""
    remaining = dict(values)
    rendered: list[str] = []
    for line in existing:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match and match.group(1) in values:
            rendered.append(f"{match.group(1)}={values[match.group(1)]}")
            remaining.pop(match.group(1))
        else:
            rendered.append(line)
    if remaining:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append(MANAGED_MARKER)
        rendered.extend(f"{key}={value}" for key, value in remaining.items())
    return rendered


def write_managed(path: Path, values: dict[str, str], template: Path) -> None:
    if path.exists():
        existing = path.read_text().splitlines()
        log(f"📝 Updating managed keys in {path}")
    else:
        if not template.exists():
            die(f"template not found: {template}")
        log(f"📝 Creating {path} from template {template}")
        existing = template.read_text().splitlines()
    path.write_text("\n".join(render_managed(existing, values)) + "\n")


def check_file(
    path: Path, values: dict[str, str] | None, structural_keys: tuple[str, ...]
) -> list[tuple[str, str]]:
    """Check a file: every managed key present and non-empty; values match when given."""
    if not path.exists():
        return [(key, "missing (file does not exist)") for key in structural_keys]
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match:
            found.setdefault(match.group(1), line.split("=", 1)[1])
    results: list[tuple[str, str]] = []
    if values is None:
        for key in structural_keys:
            if key not in found:
                results.append((key, "missing"))
            elif not found[key]:
                results.append((key, "missing (empty value)"))
            else:
                results.append((key, "ok"))
    else:
        for key, expected in values.items():
            if key not in found:
                results.append((key, "missing"))
            elif not found[key]:
                results.append((key, "missing (empty value)"))
            elif found[key] != expected:
                results.append((key, f"stale (file has {found[key]!r}, expected {expected!r})"))
            else:
                results.append((key, "ok"))
    return results


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    structural_check = args.check and not args.outputs_json
    load_dot_env()
    if structural_check:
        outputs = None
    else:
        outputs = load_outputs(args)

    values = expected_integration_values(outputs, DEFAULT_REGION) if outputs is not None else None
    frontend_values = (
        expected_frontend_values(outputs, DEFAULT_REGION)
        if args.frontend_out and outputs is not None
        else None
    )

    if not args.check:
        if values is None:  # unreachable: write mode always resolves outputs
            die("no OpenTofu outputs available")
        out_path = args.out or ".env"
        write_managed(Path(out_path), values, INTEGRATION_TEMPLATE)
        if args.frontend_out and frontend_values is not None:
            write_managed(Path(args.frontend_out), frontend_values, FRONTEND_TEMPLATE)
        log("✅ Integration test environment config generated")
        return 0

    # In check mode the default .env is only checked when no other target is
    # given, so `--check --frontend-out FILE` verifies the frontend file alone.
    out_path = args.out if args.out is not None else (".env" if not args.frontend_out else None)
    all_ok = True
    for path, expected, keys in (
        (out_path, values, INTEGRATION_STRUCTURAL_KEYS),
        (args.frontend_out, frontend_values, FRONTEND_STRUCTURAL_KEYS),
    ):
        if path is None:
            continue
        results = check_file(Path(path), expected, keys)
        bad = [(key, status) for key, status in results if status != "ok"]
        if bad:
            all_ok = False
            log(f"❌ {path}:")
            for key, status in bad:
                log(f"   - {key}: {status}")
        else:
            log(f"✅ {path}: all {len(results)} managed key(s) ok")
    if structural_check:
        log("ℹ️  structural check only (no --outputs-json supplied); values not verified")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
