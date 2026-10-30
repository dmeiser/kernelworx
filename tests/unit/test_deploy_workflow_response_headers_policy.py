"""Regression test for #725: the orphaned response headers policy deletion loop
must not abort under ``set -e`` before it can branch on
``NoSuchResponseHeadersPolicy``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-shared.yml"
STEP_NAME = "Delete orphaned CloudFront response headers policies"


def _step_run_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    matches = [s for s in steps if s.get("name") == STEP_NAME]
    assert len(matches) == 1, f"expected exactly one '{STEP_NAME}' step, found {len(matches)}"
    return str(matches[0]["run"])


def test_get_response_headers_policy_aborts_safely():
    run = _step_run_script()
    assert 'get-response-headers-policy' in run
    assert "2>aws_err.txt || true" in run, (
        "get-response-headers-policy command substitution must be guarded with "
        "'|| true' so a non-zero exit (NoSuchResponseHeadersPolicy) does not "
        "abort the step before the branch on line below runs"
    )
