"""Pipeline-ordering contract for redeemProfileInvite (#436).

`mark_invite_used_fn.js` runs a DeleteItem that permanently consumes the
invite. If it ran before `create_share`, any create_share failure (existing
share, conditional failure, transient error) would burn the invite with no
share created and no way to retry. The pipeline must therefore create the
share first and only then mark the invite used, so a failed redemption leaves
the invite intact.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2) and assert the ordering contract directly against
resolvers_mutations.tf.
"""

from __future__ import annotations

from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVERS_MUTATIONS = REPO_ROOT / "tofu" / "application" / "modules" / "appsync" / "resolvers_mutations.tf"


def _norm(value):
    """Decode a python-hcl2 scalar: strip its quote wrapper and ${...} interpolation."""
    if isinstance(value, str):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("${") and value.endswith("}"):
            value = value[2:-1]
    return value


def _redeem_profile_invite_resolver():
    with RESOLVERS_MUTATIONS.open() as handle:
        parsed = hcl2.load(handle)
    for block in parsed["resource"]:
        for type_name, named in block.items():
            if _norm(type_name) != "aws_appsync_resolver":
                continue
            for resolver_name, attrs in named.items():
                if _norm(resolver_name) == "redeem_profile_invite":
                    return attrs
    raise AssertionError("redeem_profile_invite resolver missing from resolvers_mutations.tf")


def test_redeem_profile_invite_creates_share_before_marking_invite_used():
    """#436: create_share must execute before mark_invite_used so a failed
    share creation does not consume the invite."""
    resolver = _redeem_profile_invite_resolver()
    assert _norm(resolver.get("kind", "")) == "PIPELINE"
    pipeline = [_norm(str(fn)) for fn in resolver.get("pipeline_config", [{}])[0].get("functions", [])]

    create_share = [i for i, fn in enumerate(pipeline) if "aws_appsync_function.create_share" in fn]
    mark_invite_used = [i for i, fn in enumerate(pipeline) if "aws_appsync_function.mark_invite_used" in fn]
    assert len(create_share) == 1, f"create_share must appear exactly once in pipeline: {pipeline}"
    assert len(mark_invite_used) == 1, f"mark_invite_used must appear exactly once in pipeline: {pipeline}"
    assert create_share[0] < mark_invite_used[0], (
        f"create_share must run before mark_invite_used (invite is deleted by mark_invite_used): {pipeline}"
    )
