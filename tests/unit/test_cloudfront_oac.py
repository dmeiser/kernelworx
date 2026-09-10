"""Focused tests for the CloudFront S3 origin migration from the deprecated
Origin Access Identity (OAI) to Origin Access Control (OAC) (#335), plus the
one-time destroy-ordering scaffold that fixes the resulting deploy failure.

#335/#359 removed aws_cloudfront_origin_access_identity.main from the config,
leaving a dangling destroy in state; because nothing references the OAI,
OpenTofu scheduled its destroy before/parallel to the OAC cutover and
CloudFront rejected it (CloudFrontOriginAccessIdentityInUse — the live
distribution still referenced the OAI until the cutover Deployed). A first
scaffold (#374) re-added the resource with count = 0 plus depends_on, but
depends_on inside a count = 0 block is inert (no graph node), so prod run
34409731134 destroyed unordered and 409'd before the gate ever ran. The
module now carries the second-generation one-time scaffold (removed in
KW-OAI-SCAFFOLD-CLEANUP-1 once the legacy OAI is gone from every
environment):

- terraform_data.legacy_oai_destroy_gate polls
  `aws cloudfront get-distribution --query 'Distribution.Status'` until the
  distribution reaches Deployed (the OAI InUse check runs against the live
  config; UpdateDistribution returns at acceptance, before signing switches),
  THEN destroys the legacy OAI out-of-band via AWS CLI, looking it up by its
  pre-#335 comment (`OAI for <site_domain>`, unique per environment because
  dev and prod share an AWS account). No match / NoSuch passes idempotently;
  more than one exact comment match fails loudly and deletes nothing.
- A removed block with lifecycle { destroy = false } makes OpenTofu FORGET
  the legacy OAI in state instead of scheduling a provider destroy.
- Behavioral tests execute the gate's rendered local-exec command with a
  stubbed `aws` executable (and a no-op `sleep`) on PATH and assert the
  observable call log and exit status: idempotent no-match/NoSuch passes,
  ambiguous comment matches fail without deleting, the ETag-conditional
  delete runs only after the Deployed poll, InUse/unknown errors retry, and
  unknown failures ultimately fail the apply.
- aws_s3_bucket_policy.static depends on the gate so the principal flip (OAI
  canonical user -> Service+SourceArn) cannot cut S3 access for the live
  distribution while it still signs as the OAI.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2) and assert the *meaning* of the OAC contract:

- No aws_cloudfront_origin_access_identity resource exists anywhere in the
  tofu tree (OAI is deprecated: no SSE-KMS, no dynamic requests, legacy
  request signing); state is dropped via the removed block, the real destroy
  is the gate's out-of-band CLI delete.
- The cloudfront module defines aws_cloudfront_origin_access_control.main
  with origin type "s3", signing behavior "always", and sigv4 signing.
- The distribution's S3 origin references the OAC and no longer sets an
  OAI path.
- The static bucket policy grants s3:GetObject to the
  cloudfront.amazonaws.com service principal, scoped to this distribution
  via the AWS:SourceArn condition (the OAC signing model), instead of the
  OAI canonical user, and waits for the Deployed gate before flipping.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import textwrap
from pathlib import Path

import hcl2
import pytest

from tests.unit.test_edge_security import (
    TF_APP,
    _clean,
    block,
    first_resource,
    load_hcl,
    resources,
)

CLOUDFRONT_DIR = TF_APP / "modules" / "cloudfront"


def _tf_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.tf") if ".terraform" not in p.parts)


@pytest.fixture(scope="module")
def cloudfront_doc() -> dict:
    return load_hcl(CLOUDFRONT_DIR / "main.tf")


@pytest.fixture(scope="module")
def all_tofu_docs() -> list[dict]:
    return [load_hcl(p) for p in _tf_files(TF_APP)]


def test_no_origin_access_identity_anywhere(all_tofu_docs: list[dict]) -> None:
    for doc in all_tofu_docs:
        assert resources(doc, "aws_cloudfront_origin_access_identity") == [], (
            "aws_cloudfront_origin_access_identity is deprecated (#335); "
            "state is forgotten via the removed block and the real destroy is "
            "the gate's out-of-band CLI delete"
        )


def test_legacy_oai_removed_block_forgets_state(cloudfront_doc: dict) -> None:
    removed = cloudfront_doc.get("removed", [])
    assert isinstance(removed, list) and len(removed) == 1, "exactly one removed block expected"
    entry = block(removed)
    assert entry["from"] == "${aws_cloudfront_origin_access_identity.main}", (
        "the removed block must forget the legacy OAI state object"
    )
    lifecycle = block(entry.get("lifecycle"))
    assert lifecycle.get("destroy") is False, (
        "the removed block must FORGET (destroy = false); the gate's local-exec "
        "performs the real destroy after the Deployed gate"
    )


def test_legacy_oai_destroy_gate_polls_for_deployed(cloudfront_doc: dict) -> None:
    gate = first_resource(cloudfront_doc, "terraform_data", "legacy_oai_destroy_gate")
    assert gate["depends_on"] == ["${aws_cloudfront_distribution.site}"]
    provisioner = block(gate.get("provisioner"))
    assert "local-exec" in provisioner, "gate must run a local-exec poll"
    command = provisioner["local-exec"]["command"]
    assert "aws cloudfront get-distribution" in command
    assert "Distribution.Status" in command
    assert "Deployed" in command
    assert "exit 1" in command, "the gate must fail the apply if the distribution never deploys"


# Values substituted for the provisioner's OpenTofu interpolations so the
# rendered command can run against the stubbed `aws` executable.
GATE_STUB_DIST_ID = "DISTRIBUTION123"
GATE_STUB_SITE_DOMAIN = "gate-test.example.com"
GATE_STUB_PLACEHOLDERS = {
    "${aws_cloudfront_distribution.site.id}": GATE_STUB_DIST_ID,
    "${local.site_domain}": GATE_STUB_SITE_DOMAIN,
}

AWS_STUB_HEADER = 'echo "aws $*" >> "$STUB_LOG"\n'

_MISSING_ERROR = (
    "An error occurred (NoSuchCloudFrontOriginAccessIdentity) when calling the "
    "GetCloudFrontOriginAccessIdentity operation: The specified origin access "
    "identity does not exist."
)
_IN_USE_ERROR = (
    "An error occurred (CloudFrontOriginAccessIdentityInUse) when calling the "
    "DeleteCloudFrontOriginAccessIdentity operation: The origin access identity "
    "is still in use by a distribution."
)
_UNKNOWN_ERROR = (
    "An error occurred (AccessDenied) when calling the DeleteCloudFrontOriginAccessIdentity operation: Access denied."
)
_THROTTLE_ERROR = (
    "An error occurred (Throttling) when calling the GetCloudFrontOriginAccessIdentity operation: Rate exceeded."
)
_LIST_ERROR = (
    "An error occurred (Throttling) when calling the ListCloudFrontOriginAccessIdentities operation: Rate exceeded."
)

# Stub behavior notes (mirroring the real AWS CLI):
# - a list query with no matches prints nothing to stdout under --output text
#   when the filter yields an empty list;
# - service errors are printed to stderr and exit non-zero;
# - a successful delete prints nothing and exits 0.
_NO_MATCH_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + "  *list-cloud-front-origin-access-identities*) true ;;\n"
    + "  *delete-cloud-front-origin-access-identity*) exit 0 ;;\n"
    + '  *get-cloud-front-origin-access-identity*) echo "UNUSED-TAG" ;;\n'
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_TWO_MATCH_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + '  *list-cloud-front-origin-access-identities*) echo "OAI111 OAI222" ;;\n'
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_DELETE_OK_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + '  *list-cloud-front-origin-access-identities*) echo "OAI1" ;;\n'
    + "  *delete-cloud-front-origin-access-identity*) exit 0 ;;\n"
    + '  *get-cloud-front-origin-access-identity*) echo "ETAG1" ;;\n'
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_MISSING_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + '  *list-cloud-front-origin-access-identities*) echo "OAI1" ;;\n'
    + "  *get-cloud-front-origin-access-identity*)"
    + f" echo {_MISSING_ERROR!r} >&2; exit 1 ;;\n"
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_IN_USE_THEN_OK_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + '  *list-cloud-front-origin-access-identities*) echo "OAI1" ;;\n'
    + "  *delete-cloud-front-origin-access-identity*)\n"
    + '    n=$(( $(cat "$STUB_STATE/delete_count" 2>/dev/null || echo 0) + 1 ))\n'
    + '    echo "$n" > "$STUB_STATE/delete_count"\n'
    + '    if [ "$n" -lt 2 ]; then\n'
    + f"      echo {_IN_USE_ERROR!r} >&2\n"
    + "      exit 1\n"
    + "    fi\n"
    + "    exit 0 ;;\n"
    + '  *get-cloud-front-origin-access-identity*) echo "ETAG1" ;;\n'
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_UNKNOWN_DELETE_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + '  *list-cloud-front-origin-access-identities*) echo "OAI1" ;;\n'
    + "  *delete-cloud-front-origin-access-identity*)"
    + f" echo {_UNKNOWN_ERROR!r} >&2; exit 1 ;;\n"
    + '  *get-cloud-front-origin-access-identity*) echo "ETAG1" ;;\n'
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_THROTTLE_ONCE_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + '  *list-cloud-front-origin-access-identities*) echo "OAI1" ;;\n'
    + "  *delete-cloud-front-origin-access-identity*) exit 0 ;;\n"
    + "  *get-cloud-front-origin-access-identity*)\n"
    + '    n=$(( $(cat "$STUB_STATE/get_count" 2>/dev/null || echo 0) + 1 ))\n'
    + '    echo "$n" > "$STUB_STATE/get_count"\n'
    + '    if [ "$n" -eq 1 ]; then\n'
    + f"      echo {_THROTTLE_ERROR!r} >&2\n"
    + "      exit 1\n"
    + "    fi\n"
    + '    echo "ETAG1" ;;\n'
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_LIST_THROTTLE_ONCE_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + "  *list-cloud-front-origin-access-identities*)\n"
    + '    n=$(( $(cat "$STUB_STATE/list_count" 2>/dev/null || echo 0) + 1 ))\n'
    + '    echo "$n" > "$STUB_STATE/list_count"\n'
    + '    if [ "$n" -eq 1 ]; then\n'
    + f"      echo {_LIST_ERROR!r} >&2\n"
    + "      exit 1\n"
    + "    fi\n"
    + '    echo "OAI1" ;;\n'
    + "  *delete-cloud-front-origin-access-identity*) exit 0 ;;\n"
    + '  *get-cloud-front-origin-access-identity*) echo "ETAG1" ;;\n'
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_LIST_THROTTLE_ALWAYS_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + "  *list-cloud-front-origin-access-identities*)"
    + f" echo {_LIST_ERROR!r} >&2; exit 1 ;;\n"
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)

_THROTTLE_ALWAYS_STUB = (
    AWS_STUB_HEADER
    + 'case "$*" in\n'
    + '  *list-cloud-front-origin-access-identities*) echo "OAI1" ;;\n'
    + "  *get-cloud-front-origin-access-identity*)"
    + f" echo {_THROTTLE_ERROR!r} >&2; exit 1 ;;\n"
    + '  *get-distribution*) echo "Deployed" ;;\n'
    + '  *) echo "unexpected aws invocation: $*" >&2; exit 99 ;;\n'
    + "esac\n"
)


def _render_gate_script(cloudfront_doc: dict, tmp_path: Path) -> Path:
    """Render the gate's local-exec command into a runnable shell script."""
    gate = first_resource(cloudfront_doc, "terraform_data", "legacy_oai_destroy_gate")
    provisioner = block(gate.get("provisioner"))
    local_exec = provisioner["local-exec"]
    assert local_exec.get("interpreter") == ["/bin/bash", "-c"]
    command = local_exec["command"]
    # python-hcl2 keeps the heredoc markers and the marker-indentation; the
    # real provisioner receives the body with common leading whitespace stripped.
    assert command.startswith('"<<-EOT\n'), "expected an indented heredoc command"
    body = re.sub(r"\n[ \t]*EOT\"$", "", command[len('"<<-EOT\n') :])
    script_text = textwrap.dedent(body)
    # python-hcl2 preserves Terraform's $${...} escapes verbatim; Terraform
    # collapses them to literal ${...} in the provisioner command.
    script_text = script_text.replace("$${", "${")
    for placeholder, value in GATE_STUB_PLACEHOLDERS.items():
        assert placeholder in script_text, f"missing interpolation {placeholder}"
        script_text = script_text.replace(placeholder, value)
    script = tmp_path / "legacy_oai_destroy_gate.sh"
    script.write_text(script_text)
    return script


def _run_gate(script: Path, tmp_path: Path, aws_stub: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run the rendered gate with stubbed `aws`/`sleep` and return (result, aws call log).

    `sleep` is stubbed to a no-op so the 30 s retry delays do not
    slow the scenarios down.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", aws_stub), ("sleep", "exit 0\n")):
        stub = bin_dir / name
        stub.write_text("#!/bin/bash\n" + body)
        stub.chmod(0o755)
    (tmp_path / "stub-state").mkdir()
    log = tmp_path / "aws-calls.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_LOG": str(log),
        "STUB_STATE": str(tmp_path / "stub-state"),
    }
    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def _aws_calls(calls: list[str], needle: str) -> list[str]:
    return [call for call in calls if needle in call]


def test_gate_passes_idempotently_when_no_oai_matches(cloudfront_doc: dict, tmp_path: Path) -> None:
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _NO_MATCH_STUB)
    assert result.returncode == 0, result.stderr
    assert "nothing to delete" in result.stdout
    assert _aws_calls(calls, "delete-cloud-front-origin-access-identity") == []


def test_gate_refuses_ambiguous_comment_match(cloudfront_doc: dict, tmp_path: Path) -> None:
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _TWO_MATCH_STUB)
    assert result.returncode == 1
    assert "refusing to delete anything" in result.stderr
    assert _aws_calls(calls, "delete-cloud-front-origin-access-identity") == []


def test_gate_deletes_oai_with_if_match_after_deployed(cloudfront_doc: dict, tmp_path: Path) -> None:
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _DELETE_OK_STUB)
    assert result.returncode == 0, result.stderr
    deletes = _aws_calls(calls, "delete-cloud-front-origin-access-identity")
    assert len(deletes) == 1
    assert "--if-match ETAG1" in deletes[0]
    # The Deployed poll must complete before the destroy is attempted.
    poll_positions = [i for i, c in enumerate(calls) if "get-distribution" in c]
    assert poll_positions and poll_positions[-1] < calls.index(deletes[0])


def test_gate_treats_missing_during_destroy_as_success(cloudfront_doc: dict, tmp_path: Path) -> None:
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _MISSING_STUB)
    assert result.returncode == 0, result.stderr
    assert "treating as deleted" in result.stdout
    assert _aws_calls(calls, "delete-cloud-front-origin-access-identity") == []


def test_gate_retries_conflict_until_delete_succeeds(cloudfront_doc: dict, tmp_path: Path) -> None:
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _IN_USE_THEN_OK_STUB)
    assert result.returncode == 0, result.stderr
    assert len(_aws_calls(calls, "delete-cloud-front-origin-access-identity")) == 2


def test_gate_fails_after_three_unknown_delete_errors(cloudfront_doc: dict, tmp_path: Path) -> None:
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _UNKNOWN_DELETE_STUB)
    assert result.returncode == 1
    assert "failed 3 times" in result.stderr
    assert len(_aws_calls(calls, "delete-cloud-front-origin-access-identity")) == 3


def test_gate_retries_transient_etag_read_failure(cloudfront_doc: dict, tmp_path: Path) -> None:
    # A throttled (non-NoSuch) ETag read is a retryable failure, not "gone":
    # the next attempt must re-read the ETag and proceed to the delete.
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _THROTTLE_ONCE_STUB)
    assert result.returncode == 0, result.stderr
    deletes = _aws_calls(calls, "delete-cloud-front-origin-access-identity")
    assert len(deletes) == 1 and "--if-match ETAG1" in deletes[0]
    assert len(_aws_calls(calls, "get-cloud-front-origin-access-identity")) == 2


def test_gate_retries_comment_lookup_failure_then_proceeds(cloudfront_doc: dict, tmp_path: Path) -> None:
    # A throttled comment lookup is a retryable failure, not a "no match":
    # the retry must re-run the lookup and proceed to the delete.
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _LIST_THROTTLE_ONCE_STUB)
    assert result.returncode == 0, result.stderr
    assert len(_aws_calls(calls, "list-cloud-front-origin-access-identities")) == 2
    deletes = _aws_calls(calls, "delete-cloud-front-origin-access-identity")
    assert len(deletes) == 1 and "--if-match ETAG1" in deletes[0]


def test_gate_fails_when_comment_lookup_keeps_failing(cloudfront_doc: dict, tmp_path: Path) -> None:
    # A persistent lookup failure must fail the apply rather than pass
    # idempotently — the removed block has already forgotten the OAI from
    # state, so a false "no match" would orphan it.
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _LIST_THROTTLE_ALWAYS_STUB)
    assert result.returncode == 1
    assert "failed 3 times" in result.stderr
    assert len(_aws_calls(calls, "list-cloud-front-origin-access-identities")) == 3
    assert _aws_calls(calls, "delete-cloud-front-origin-access-identity") == []


def test_gate_fails_after_three_transient_etag_read_failures(cloudfront_doc: dict, tmp_path: Path) -> None:
    # A persistent non-NoSuch read failure must fail the apply (the removed
    # block has already forgotten the OAI from state, so silently treating it
    # as deleted would orphan it).
    script = _render_gate_script(cloudfront_doc, tmp_path)
    result, calls = _run_gate(script, tmp_path, _THROTTLE_ALWAYS_STUB)
    assert result.returncode == 1
    assert "failed 3 times" in result.stderr
    assert _aws_calls(calls, "delete-cloud-front-origin-access-identity") == []
    assert len(_aws_calls(calls, "get-cloud-front-origin-access-identity")) == 3


def test_bucket_policy_waits_for_deployed_gate(cloudfront_doc: dict) -> None:
    policy = first_resource(cloudfront_doc, "aws_s3_bucket_policy", "static")
    assert policy["depends_on"] == ["${terraform_data.legacy_oai_destroy_gate}"], (
        "the bucket-policy principal flip must wait for the OAC cutover to Deploy"
    )


def test_oac_defined_with_s3_always_sigv4(cloudfront_doc: dict) -> None:
    oac = first_resource(cloudfront_doc, "aws_cloudfront_origin_access_control", "main")
    assert oac["origin_access_control_origin_type"] == "s3"
    assert oac["signing_behavior"] == "always"
    assert oac["signing_protocol"] == "sigv4"
    lifecycle = block(oac.get("lifecycle"))
    assert lifecycle.get("prevent_destroy") is True


def test_distribution_s3_origin_uses_oac(cloudfront_doc: dict) -> None:
    dist = first_resource(cloudfront_doc, "aws_cloudfront_distribution", "site")
    origins = dist.get("origin", [])
    s3_origins = [o for o in origins if str(o.get("origin_id", "")).startswith("S3-")]
    assert s3_origins, "expected an S3 origin on the distribution"
    for origin in s3_origins:
        assert origin.get("origin_access_control_id") == ("${aws_cloudfront_origin_access_control.main.id}"), (
            "S3 origin must sign requests via the OAC"
        )
        s3_origin_config = block(origin.get("s3_origin_config"))
        assert s3_origin_config.get("origin_access_identity", "") == ""


def test_bucket_policy_grants_cloudfront_service_principal(cloudfront_doc: dict) -> None:
    policy = first_resource(cloudfront_doc, "aws_s3_bucket_policy", "static")
    raw = policy["policy"]
    # policy is a jsonencode(...) template; parse the inner object into a
    # semantic model rather than matching raw text.
    prefix = "${jsonencode("
    assert isinstance(raw, str) and raw.startswith(prefix) and raw.endswith(")}")
    inner = raw[len(prefix) : -2]
    doc = _clean(hcl2.load(io.StringIO(f"policy = {inner}")))["policy"]
    statements = doc["Statement"]
    allow = [s for s in statements if s.get("Sid") == "AllowCloudFrontAccess"]
    assert len(allow) == 1
    stmt = allow[0]
    assert stmt["Effect"] == "Allow"
    assert stmt["Principal"] == {"Service": "cloudfront.amazonaws.com"}
    assert stmt["Action"] == "s3:GetObject"
    # Scoped to this distribution only; no OAI canonical user anywhere.
    condition = stmt["Condition"]
    assert condition == {"StringEquals": {"AWS:SourceArn": "${aws_cloudfront_distribution.site.arn}"}}
    assert "canonical" not in str(stmt["Principal"]).lower()
