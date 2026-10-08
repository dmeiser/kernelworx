"""Contract test for the post-deploy static-asset drift assertion.

On 2026-10-06 the deployed ``logo.svg`` / ``logo-rotating.svg`` were deleted
out-of-band from both static buckets after deploys that verifiably uploaded
them (dev run 37525653122, prod run 37178810183). No CI path deletes those
keys (the deploy's ``s3 sync`` omits ``--delete``; the only ``--delete`` sync
against the static bucket is the manual ``frontend/deploy.sh`` one), so the
loss was invisible: CloudFront answered ``/logo.svg`` with the SPA
``index.html`` fallback - HTTP 200, ``text/html`` - and every other deploy
gate stayed green while the brand assets were broken on dev and prod.

The "Assert static brand assets are served" step in ``deploy-shared.yml`` turns
that into a red deploy. These tests run the step's real script against a mock
``curl`` so the assertions are behavioural: the step must pass only on a genuine
SVG and fail on each drift shape.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-shared.yml"
STEP_NAME = "Assert static brand assets are served"
SITE_URL = "https://dev.kernelworx.app"
ASSET_PATHS = ("/logo.svg", "/logo-rotating.svg", "/favicon.svg")

# The mock stands in for curl: it honours -o/-D/-w and answers each path from
# the scenario variables, so the test observes the step's decisions rather than
# the network.
MOCK_CURL = """\
#!/bin/bash
out=""
hdr=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -D) hdr="$2"; shift 2 ;;
    -w) shift 2 ;;
    --max-time) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
path="${url#https://dev.kernelworx.app}"
scenario="${SCENARIO:-ok}"
bad="${BAD_PATH:-/logo.svg}"
if [ "$scenario" = "transport" ] && { [ -z "$bad" ] || [ "$path" = "$bad" ]; }; then
  exit 22
fi
body="<svg xmlns=\\"http://www.w3.org/2000/svg\\" viewBox=\\"0 0 1 1\\"></svg>"
ctype="image/svg+xml"
code="200"
if [ "$scenario" = "fallback" ] && { [ -z "$bad" ] || [ "$path" = "$bad" ]; }; then
  body="<!doctype html><html><head><title>KernelWorx</title></head><body></body></html>"
  ctype="text/html"
elif [ "$scenario" = "gone" ] && { [ -z "$bad" ] || [ "$path" = "$bad" ]; }; then
  body="Not Found"
  ctype="application/xml"
  code="404"
elif [ "$scenario" = "empty-svg" ] && { [ -z "$bad" ] || [ "$path" = "$bad" ]; }; then
  body=""
fi
printf 'HTTP/1.1 %s OK\\r\\nContent-Type: %s\\r\\n\\r\\n' "$code" "$ctype" > "$hdr"
printf '%s' "$body" > "$out"
printf '%s' "$code"
"""


def _step_run_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    matches = [s for s in steps if s.get("name") == STEP_NAME]
    assert len(matches) == 1, f"expected exactly one '{STEP_NAME}' step, found {len(matches)}"
    return str(matches[0]["run"])


def run_step(tmp_path: Path, scenario: str = "ok", bad_path: str = "") -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(MOCK_CURL)
    curl.chmod(0o755)

    script = tmp_path / "step.sh"
    script.write_text(_step_run_script())

    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "E2E_BASE_URL": SITE_URL,
            "SCENARIO": scenario,
            "BAD_PATH": bad_path,
        },
    )


def test_step_fetches_every_brand_asset() -> None:
    """The step must probe all three keys, not just the two that broke."""
    script = _step_run_script()
    for path in ASSET_PATHS:
        assert path in script, f"{path} is not probed by the drift assertion"


def test_healthy_deploy_passes(tmp_path: Path) -> None:
    result = run_step(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    for path in ASSET_PATHS:
        assert f"OK: {SITE_URL}{path}" in result.stdout


def test_index_html_fallback_fails_loudly(tmp_path: Path) -> None:
    """The exact 2026-10-06 shape: HTTP 200, text/html, the SPA document."""
    result = run_step(tmp_path, scenario="fallback", bad_path="/logo.svg")

    assert result.returncode != 0
    assert "::error::" in result.stdout + result.stderr
    assert f"{SITE_URL}/logo.svg" in result.stdout + result.stderr
    assert "text/html" in result.stdout + result.stderr


def test_missing_object_fails_loudly(tmp_path: Path) -> None:
    result = run_step(tmp_path, scenario="gone", bad_path="/logo-rotating.svg")

    assert result.returncode != 0
    assert "404" in result.stdout + result.stderr


def test_svg_content_type_with_no_svg_body_fails(tmp_path: Path) -> None:
    result = run_step(tmp_path, scenario="empty-svg", bad_path="/favicon.svg")

    assert result.returncode != 0
    assert "<svg" in result.stdout + result.stderr


def test_unreachable_site_fails_loudly(tmp_path: Path) -> None:
    result = run_step(tmp_path, scenario="transport", bad_path="/logo.svg")

    assert result.returncode != 0
    assert "::error::" in result.stdout + result.stderr
