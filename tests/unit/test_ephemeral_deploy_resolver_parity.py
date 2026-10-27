"""Guard: the resolver-ordering deploy steps must not carry a hand-maintained target list.

`scripts/appsync-ensure-resolver-order.sh` used to take its `-t` addresses from
copy-pasted lists in `scripts/ephemeral-env.sh` and
`.github/workflows/deploy-shared.yml`. Every previous ordering outage (#298-#301,
then #750 / the 13 consecutive failed prod deploys fixed by #845) was "the plan
deletes an AppSync function or data source and the list was not updated", so the
parity test that kept the two lists in sync only kept them wrong in the same way.

The guard now derives its exclusions from the plan JSON, so these tests pin the
new contract: both deploy paths call the same guard, neither passes any target,
and the guard actually derives the `-exclude` set from the plan.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EPHEMERAL = REPO_ROOT / "scripts" / "ephemeral-env.sh"
DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy-shared.yml"
GUARD = REPO_ROOT / "scripts" / "appsync-ensure-resolver-order.sh"

GUARD_SCRIPT = "appsync-ensure-resolver-order.sh"
TARGET_FLAG_RE = re.compile(r"^\s*-t\s+module\.appsync\.", re.MULTILINE)

# The addresses #845 added by hand. They are unnecessary once the guard derives
# its exclusions, and re-adding them would re-open the class of failure.
RETIRED_HAND_MAINTAINED_TARGETS = (
    "module.appsync.aws_appsync_function.inject_global_payment_methods",
    "module.appsync.aws_appsync_function.set_owner_account_id_in_stash",
    "module.appsync.aws_appsync_function.filter_payment_methods_by_access",
    "module.appsync.aws_appsync_resolver.create_order",
    "module.appsync.aws_appsync_resolver.public_create_order",
    "module.appsync.aws_appsync_resolver.list_my_shares",
)


def _call_site(path: Path) -> str:
    """Return the invocation of the guard script in a deploy path."""
    text = path.read_text()
    assert GUARD_SCRIPT in text, f"{path} no longer invokes {GUARD_SCRIPT}"
    start = text.index(GUARD_SCRIPT)
    # The invocation runs to the next blank line (both call sites are single
    # backslash-continued commands inside a larger step/script).
    end = text.index("\n\n", start)
    return text[start:end]


def test_neither_call_site_passes_targets() -> None:
    for path in (EPHEMERAL, DEPLOY):
        invocation = _call_site(path)
        assert not TARGET_FLAG_RE.search(invocation), (
            f"{path} passes hand-maintained -t targets to the guard; the guard derives "
            "its exclusions from the plan JSON, so the list must stay empty"
        )
        for target in RETIRED_HAND_MAINTAINED_TARGETS:
            assert target not in invocation, f"{path} re-introduces the retired target {target}"


def test_both_call_sites_pass_the_environment_through() -> None:
    """Ephemeral still needs its run-scoped -var; prod needs no extra arguments."""
    assert '-var="environment=$RUN_ID"' in _call_site(EPHEMERAL)


def test_guard_derives_its_exclusions_from_the_plan() -> None:
    guard = GUARD.read_text()
    assert "tofu show -json" in guard, "the guard must read the plan it just made"
    for resource_type in ("aws_appsync_function", "aws_appsync_datasource"):
        assert f'"{resource_type}"' in guard, f"the guard no longer detects {resource_type} deletions"
    assert 'index("delete")' in guard, "the guard no longer selects planned deletions"
    assert '"-exclude=$addr"' in guard, "the guard no longer defers the planned deletions with -exclude"
    assert "-target=" not in guard, "targeted applies are retired: they need a hand-maintained list"


def test_guard_keeps_the_noop_and_abort_contracts() -> None:
    guard = GUARD.read_text()
    assert "No AppSync function/datasource deletions planned; resolver ordering guard not needed." in guard
    assert "aborting before the main apply" in guard, "a guard failure must abort before the main apply"
