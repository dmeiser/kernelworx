"""Parity guard: ephemeral-env.sh and deploy-shared.yml keep the same resolver targets."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EPHEMERAL = REPO_ROOT / "scripts" / "ephemeral-env.sh"
DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy-shared.yml"

TARGET_RE = re.compile(r"-t\s+(module\.appsync\.(?:aws_appsync_resolver|aws_appsync_function)\.[A-Za-z0-9_]+)")

# The three payment-method functions re-pointed to the shared NoneDataSource when
# the two per-purpose NONE data sources were consolidated (#750). Without these
# targets the full apply destroys the still-referenced NONE data sources before
# re-pointing the functions and AWS refuses every Deploy Production run.
NONE_DS_FUNCTION_TARGETS = (
    "module.appsync.aws_appsync_function.inject_global_payment_methods",
    "module.appsync.aws_appsync_function.set_owner_account_id_in_stash",
    "module.appsync.aws_appsync_function.filter_payment_methods_by_access",
)


def _targets(path: Path) -> set[str]:
    return set(TARGET_RE.findall(path.read_text()))


def test_target_sets_match() -> None:
    ephemeral, deploy = _targets(EPHEMERAL), _targets(DEPLOY)
    assert ephemeral == deploy, (
        "appsync-ensure-resolver-order.sh target lists diverged: "
        f"only in scripts/ephemeral-env.sh: {sorted(ephemeral - deploy)}; "
        f"only in .github/workflows/deploy-shared.yml: {sorted(deploy - ephemeral)}"
    )


def test_none_ds_function_targets_in_both() -> None:
    ephemeral, deploy = _targets(EPHEMERAL), _targets(DEPLOY)
    for target in NONE_DS_FUNCTION_TARGETS:
        assert target in ephemeral
        assert target in deploy


def test_public_create_order_target_in_both() -> None:
    target = "module.appsync.aws_appsync_resolver.public_create_order"
    assert target in _targets(EPHEMERAL)
    assert target in _targets(DEPLOY)
