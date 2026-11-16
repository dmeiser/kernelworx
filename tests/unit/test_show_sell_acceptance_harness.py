"""Guards for the Show & Sell acceptance harness: where credentials may come from.

The harness (``tests/e2e/test_smoke_show_sell.py`` and its helpers) drives a
deployed stack with the standing QA fixture identities.  Nothing in CI runs it, so
the parts that are a contract rather than an interaction with a browser are
pinned here, the way ``test_provision_user_totp_credential_exposure.py`` pins
#569 and #597:

* identities and the app client id arrive only through the ``TEST_QA_SHOW_SELL_*``
  environment published by the fixture script — the harness holds no AWS
  credentials, so it cannot create, reset, or delete a user, and it cannot look
  the app client up by name (the dev pool holds many clients named
  ``KernelWorx-Web``, and only one allows ``USER_PASSWORD_AUTH``);
* one provisioning entry point: ``scripts/qa_fixture.py``.  A second script that
  creates the same identities drifts, and the drift is invisible until a lane
  finds two answers;
* no CI path may hold or need a fixture password, so no workflow may name these
  identities or run this spec;
* the Playwright trace starts after login, and a password that reaches an
  artifact fails the run rather than being quietly redacted;
* the spec is not marked ``smoke``: ``-m smoke`` runs on every push to ``dev``.

The functional half needs no network: identity plumbing is read from the
environment, and the artifact scan is pure file work.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
SPEC = E2E_DIR / "test_smoke_show_sell.py"
GRAPHQL_MODULE = E2E_DIR / "utils" / "show_sell_graphql.py"

IDENTITY_VARS = (
    "TEST_QA_SHOW_SELL_ADMIN_EMAIL",
    "TEST_QA_SHOW_SELL_ADMIN_PASSWORD",
    "TEST_QA_SHOW_SELL_ADMIN2_EMAIL",
    "TEST_QA_SHOW_SELL_ADMIN2_PASSWORD",
    "TEST_QA_SHOW_SELL_SCOUT_EMAIL",
    "TEST_QA_SHOW_SELL_SCOUT_PASSWORD",
    "TEST_QA_SHOW_SELL_OUTSIDE_EMAIL",
    "TEST_QA_SHOW_SELL_OUTSIDE_PASSWORD",
)
PREVIEW_GROUP = "show-sell-preview"
#: A value that must never appear in a message: it stands in for a real password.
SENTINEL_PASSWORD = "NotARealFixturePassword-7x"
#: A fixture password is generated from ``letters + digits + "!@#$%^&*-_+="``, so a
#: loader that pastes a value into a shell command without quoting it is running
#: the password as shell syntax.
SHELL_HOSTILE_PASSWORD = "Fixture!@#$%^&*-_+=7x'\"$(`x`)"
#: The fixture writer's own variable for where its ``0600`` file lives.
SECRETS_FILE_VAR = "QA_FIXTURE_SECRETS_FILE"


def _source(path: Path) -> str:
    """Return *path*'s text, failing with the path when it is missing."""
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing"
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    """Return the parsed module for *path*."""
    return ast.parse(_source(path), filename=str(path))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """Return the function *name*, at module level or inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in this module")


def _call_names(node: ast.AST) -> list[str]:
    """Return dotted names called anywhere inside *node*."""
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            parts: list[str] = []
            cursor: ast.expr = child.func
            while isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value
            if isinstance(cursor, ast.Name):
                parts.append(cursor.id)
            calls.append(".".join(reversed(parts)))
    return calls


# ---------------------------------------------------------------------------
# Where credentials may come from
# ---------------------------------------------------------------------------


def test_identities_arrive_only_from_the_fixture_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """``qa_identities`` reads the four personas from the environment it is given."""
    from tests.e2e.utils import show_sell_graphql as api

    for key in IDENTITY_VARS:
        monkeypatch.delenv(key, raising=False)
    for index, persona in enumerate(("admin", "admin2", "scout", "outside")):
        monkeypatch.setenv(IDENTITY_VARS[index * 2], f"qa-show-sell-{persona}@dev.kernelworx.app")
        monkeypatch.setenv(IDENTITY_VARS[index * 2 + 1], f"{SENTINEL_PASSWORD}-{persona}")

    identities = api.qa_identities()

    assert set(identities) == {"admin", "admin2", "scout", "outside"}
    assert identities["scout"]["email"] == "qa-show-sell-scout@dev.kernelworx.app"
    assert identities["outside"]["password"] == f"{SENTINEL_PASSWORD}-outside"


def test_missing_identity_names_keys_never_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stopped run says which keys are absent — never the value that is present."""
    from tests.e2e.utils import show_sell_graphql as api

    for key in IDENTITY_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TEST_QA_SHOW_SELL_ADMIN_EMAIL", "qa-show-sell-admin@dev.kernelworx.app")
    monkeypatch.setenv("TEST_QA_SHOW_SELL_ADMIN_PASSWORD", SENTINEL_PASSWORD)

    with pytest.raises(OSError) as raised:
        api.qa_identities()

    message = str(raised.value)
    assert "TEST_QA_SHOW_SELL_SCOUT_PASSWORD" in message, message
    assert "TEST_QA_SHOW_SELL_OUTSIDE_EMAIL" in message, message
    assert SENTINEL_PASSWORD not in message, "a configuration error echoed a password"


def test_client_id_and_urls_are_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client id is supplied, not discovered; the base url is normalized."""
    from tests.e2e.utils import show_sell_graphql as api

    for key in (
        "TEST_USER_POOL_CLIENT_ID",
        "TEST_QA_SHOW_SELL_CLIENT_ID",
        "TEST_QA_SHOW_SELL_BASE_URL",
        "E2E_BASE_URL",
        "TEST_REGION",
        "AWS_REGION",
        "TEST_USER_POOL_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("TEST_USER_POOL_CLIENT_ID", "1example23client45id6789")
    monkeypatch.setenv("TEST_QA_SHOW_SELL_BASE_URL", "https://dev.kernelworx.app/")
    assert api.client_id() == "1example23client45id6789"
    assert api.base_url() == "https://dev.kernelworx.app"
    assert api.region() == "us-east-1"
    assert api.pool_id() == ""

    # The fallback that every other e2e run already sets must keep working.
    monkeypatch.delenv("TEST_QA_SHOW_SELL_CLIENT_ID", raising=False)
    monkeypatch.delenv("TEST_USER_POOL_CLIENT_ID", raising=False)
    monkeypatch.setenv("TEST_QA_SHOW_SELL_CLIENT_ID", "fallback-client")
    monkeypatch.setenv("E2E_BASE_URL", "https://dev.kernelworx.app")
    monkeypatch.setenv("TEST_REGION", "us-west-2")
    monkeypatch.setenv("TEST_USER_POOL_ID", "us-east-1_sDiuCOarb")
    assert api.client_id() == "fallback-client"
    assert api.base_url() == "https://dev.kernelworx.app"
    assert api.region() == "us-west-2"
    assert api.pool_id() == "us-east-1_sDiuCOarb"

    for key in (
        "TEST_USER_POOL_CLIENT_ID",
        "TEST_QA_SHOW_SELL_CLIENT_ID",
        "TEST_QA_SHOW_SELL_BASE_URL",
        "E2E_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(OSError):
        api.client_id()
    with pytest.raises(OSError):
        api.base_url()


def test_one_origin_drives_the_browser_and_the_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card's base URL has to move the browser, not only the GraphQL probes.

    ``tests/e2e/pages/base_page.py`` and ``tests/e2e/utils/auth.py`` navigate
    ``E2E_BASE_URL`` and fall back to ``https://localhost:5173``, while the probes
    read ``TEST_QA_SHOW_SELL_BASE_URL``.  A runbook that sets the card's key and a
    harness that reads the other one produces a journey that opens a local
    developer server and stops before step 1 — which is what the first version of
    this runbook did.
    """
    from tests.e2e.utils import show_sell_graphql as api

    monkeypatch.delenv("TEST_QA_SHOW_SELL_BASE_URL", raising=False)
    monkeypatch.delenv("E2E_BASE_URL", raising=False)
    with pytest.raises(EnvironmentError) as raised:
        api.publish_base_url()
    for key in ("TEST_QA_SHOW_SELL_BASE_URL", "E2E_BASE_URL"):
        assert key in str(raised.value), f"the stopped run does not name {key}"

    monkeypatch.setenv("TEST_QA_SHOW_SELL_BASE_URL", "https://dev.kernelworx.app/")
    assert api.publish_base_url() == "https://dev.kernelworx.app"
    assert os.environ["E2E_BASE_URL"] == "https://dev.kernelworx.app"

    # A leftover E2E_BASE_URL must not leave the browser somewhere else.
    monkeypatch.setenv("E2E_BASE_URL", "https://localhost:5173")
    assert api.publish_base_url() == "https://dev.kernelworx.app"
    assert api.base_url() == os.environ["E2E_BASE_URL"], "the two halves aim at different deployments"

    # With only the knob the other e2e suites already use, that knob wins.
    monkeypatch.delenv("TEST_QA_SHOW_SELL_BASE_URL", raising=False)
    monkeypatch.setenv("E2E_BASE_URL", "https://pr-999.kernelworx.app")
    assert api.publish_base_url() == "https://pr-999.kernelworx.app"


def test_the_spec_publishes_the_origin_before_any_navigation() -> None:
    """The publish has to be a session fixture, not a step inside the journey."""
    tree = _tree(SPEC)
    fixture = _function(tree, "target_origin")
    decorators = [ast.unparse(node) for node in fixture.decorator_list]
    assert any("autouse=True" in node for node in decorators), "the origin fixture is not autouse"
    assert any('scope="session"' in node or "scope='session'" in node for node in decorators), (
        "the origin fixture must be session-scoped so one run has one target"
    )
    assert "api.publish_base_url" in _call_names(fixture)
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    hardcoded = [text for text in literals if "://" in text]
    assert not hardcoded, f"the spec hardcodes an origin instead of using the published one: {hardcoded}"


def test_failure_evidence_masks_live_fixture_codes() -> None:
    """A step usually stops while it waits on a code it just read, on screen.

    Pixels survive the artifact scan — ``redact_and_scan`` reads text — so the
    failure screenshot needs the same masks as the step screenshots.
    """
    from tests.e2e.pages import show_sell_page as pages

    assert pages.CODE_MASK_SELECTORS, "no fixture-code surface is masked"
    assert all("data-testid" in selector for selector in pages.CODE_MASK_SELECTORS)

    page_body = ast.unparse(_function(_tree(E2E_DIR / "pages" / "show_sell_page.py"), "code_mask_locators"))
    assert "CODE_MASK_SELECTORS" in page_body, "the page object masks a different list than the failure path"

    failure_body = ast.unparse(_function(_tree(SPEC), "_record_failure"))
    assert "mask=code_mask_locators(page)" in failure_body, "the failure screenshot is taken unmasked"


def test_no_step_screenshot_can_omit_its_masks() -> None:
    """Every screenshot passes a mask list, and ``masks`` has no default to fall back on.

    Steps 8 and 9 are the Unit Campaign's roster page, which renders
    ``Join code: <strong data-testid="join-code">`` while the campaign is open
    (``frontend/src/pages/UnitCampaignWorkspacePage.tsx:138``).  QA read a live join
    code out of ``08-roster-shows-scout.png`` and ``09-roster-removal.png`` while the
    same record claimed fixture codes were absent: those two call sites simply
    omitted ``masks=``, and the parameter's ``None`` default let them.  Pixels are
    the one evidence channel ``redact_and_scan`` cannot repair afterwards.
    """
    tree = _tree(SPEC)
    shots = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_screenshot"
    ]
    assert len(shots) >= 11, f"the journey records {len(shots)} screenshots; 12 steps expect at least 11"
    for call in shots:
        step = call.args[1].value if len(call.args) > 1 and isinstance(call.args[1], ast.Constant) else "<unknown>"
        masks = [keyword for keyword in call.keywords if keyword.arg == "masks"]
        assert masks, f"the {step!r} screenshot at line {call.lineno} is taken with no masks"
        assert "code_mask_locators" in ast.unparse(masks[0].value), f"the {step!r} screenshot masks a different list"

    signature = _function(tree, "_screenshot").args
    assert not signature.defaults, "_screenshot masks has a default, so a call site can forget it silently"
    assert not any(default is not None for default in signature.kw_defaults), (
        "_screenshot masks has a default, so a call site can forget it silently"
    )

    # The failure path calls the browser API directly, so it is pinned the same way.
    direct = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "screenshot"
    ]
    assert direct, "no direct page.screenshot call found"
    for call in direct:
        assert any(keyword.arg == "mask" for keyword in call.keywords), (
            f"page.screenshot at line {call.lineno} has no mask"
        )


def test_code_bearing_steps_record_what_the_mask_matched() -> None:
    """The record says how many code elements were on screen, not only that codes are absent.

    A mask list that matched nothing looks identical to a code-free page in the
    artifacts.  Counting the matched elements is what lets a reader tell "nothing to
    hide" from "the mask missed", which is the difference QA had to find by eye.
    """
    source = _source(SPEC)
    assert source.count('"maskedCodeElements"') >= 5, (
        "the invite, join, roster, and close steps each record the mask target count"
    )
    helper = _function(_tree(SPEC), "_masked_code_elements")
    assert "code_mask_locators" in ast.unparse(helper), "the count is taken from a different list than the mask"


def test_the_runbook_loads_the_fixture_file_as_json(tmp_path: Path) -> None:
    """The human-runner recipe is executed here, against a fixture file of the real shape.

    ``scripts/qa_fixture.py`` ends ``write_secrets()`` in ``json.dump``, so the
    ``0600`` file is JSON.  The first version of this runbook told a reader to
    ``. ~/qa-fixture/secrets.json``; QA ran it verbatim and got nine ``command not
    found`` lines, zero exported keys, and a run that stopped naming the base URL it
    could not find.  The recipe is now a JSON read, and it is only a doc until this
    test runs it: the block from the README is executed with a synthetic file whose
    values are the hostile ones the fixture alphabet allows.
    """
    readme = _source(E2E_DIR / "README.md")
    for needle in (SECRETS_FILE_VAR, "~/.kernelworx/qa-fixture-secrets.json", "json.dump"):
        assert needle in readme, f"tests/e2e/README.md does not document {needle}"
    assert "set -a; ." not in readme, "the runbook still tells a reader to source the JSON file"

    agents = _source(REPO_ROOT / "AGENTS.md")
    assert SECRETS_FILE_VAR in agents, "AGENTS.md does not say where the fixture file lives"
    assert "json.dump" in agents, "AGENTS.md does not say the fixture file is JSON"

    block = _bash_block(readme, SECRETS_FILE_VAR).replace("uv run python", shlex.quote(sys.executable))
    secrets = tmp_path / "qa-fixture-secrets.json"
    secrets.write_text(
        json.dumps(
            {
                "TEST_QA_SHOW_SELL_BASE_URL": "https://dev.kernelworx.app",
                "TEST_QA_SHOW_SELL_ADMIN_EMAIL": "qa-show-sell-admin@dev.kernelworx.app",
                "TEST_QA_SHOW_SELL_ADMIN_PASSWORD": SENTINEL_PASSWORD,
                "TEST_QA_SHOW_SELL_SCOUT_PASSWORD": SHELL_HOSTILE_PASSWORD,
                "TEST_OWNER_PASSWORD": "not-a-fixture-key",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    env = {**os.environ, SECRETS_FILE_VAR: str(secrets)}

    loaded = subprocess.run(["bash", "-c", block], env=env, capture_output=True, text=True, check=False)
    assert loaded.returncode == 0, f"the documented loader stopped: {loaded.stderr}"
    assert loaded.stdout == "", f"the loader echoed something: {loaded.stdout!r}"

    probe = "\n".join(
        (
            block,
            'printf "email=%s\\n" "$TEST_QA_SHOW_SELL_ADMIN_EMAIL"',
            'printf "base=%s\\n" "$TEST_QA_SHOW_SELL_BASE_URL"',
            'printf "admin=%s\\n" "${TEST_QA_SHOW_SELL_ADMIN_PASSWORD:-unset}"',
            'printf "scout=%s\\n" "${TEST_QA_SHOW_SELL_SCOUT_PASSWORD:-unset}"',
            'printf "owner=%s\\n" "${TEST_OWNER_PASSWORD-unset}"',
            'printf "count=%s\\n" "$(env | grep -c \'^TEST_QA_SHOW_SELL_[A-Z0-9_]*=\')"',
        )
    )
    exported = subprocess.run(["bash", "-c", probe], env=env, capture_output=True, text=True, check=False)
    assert exported.returncode == 0, f"the exported values are unusable: {exported.stderr}"
    assert f"admin={SENTINEL_PASSWORD}" in exported.stdout, "the fixture password did not reach the environment"
    assert f"scout={SHELL_HOSTILE_PASSWORD}" in exported.stdout, (
        "a password with shell metacharacters was mangled, not exported"
    )
    assert "email=qa-show-sell-admin@dev.kernelworx.app" in exported.stdout
    assert "base=https://dev.kernelworx.app" in exported.stdout, (
        "the recipe leaves the run without the base URL it needs"
    )
    assert "owner=unset" in exported.stdout, "the loader exports keys the harness never reads"
    assert "count=4" in exported.stdout, "the loader exported the wrong number of fixture keys"

    # The defect, kept as a control: sourcing that same JSON file exports nothing.
    sourced = subprocess.run(
        [
            "bash",
            "-c",
            f'set -a; . "{secrets}"; set +a; '
            """printf "count=%s\\n" "$(env | grep -c '^TEST_QA_SHOW_SELL_[A-Z0-9_]*=')\"""",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "count=0" in sourced.stdout, (
        "sourcing the fixture JSON now works, so this control and the runbook warning need re-reading"
    )


def _bash_block(source: str, marker: str) -> str:
    """Return the single fenced ``bash`` block in *source* that contains *marker*.

    Args:
        source: markdown text.
        marker: text that identifies the block.

    Returns:
        The block's contents.
    """
    blocks = [block for block in re.findall(r"```bash\n(.*?)```", source, re.DOTALL) if marker in block]
    assert len(blocks) == 1, f"expected exactly one bash block naming {marker}, found {len(blocks)}"
    return blocks[0]


def test_harness_holds_no_aws_sdk_and_no_cognito_admin_actions() -> None:
    """The harness cannot create, reset, or delete a user, or enumerate clients.

    No ``boto3`` import is what makes that structural: the only auth path left is
    the public ``InitiateAuth`` a browser user takes anyway, and the app client id
    has to be supplied because nothing here can list clients to find it.
    """
    tree = _tree(GRAPHQL_MODULE)
    imported = {
        alias.name if isinstance(node, ast.Import) else node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [])
    }
    assert "boto3" not in imported, f"{GRAPHQL_MODULE.relative_to(REPO_ROOT)} imports boto3: {imported}"

    source = _source(GRAPHQL_MODULE)
    for forbidden in (
        "admin_create_user",
        "admin_set_user_password",
        "admin_resend_user_confirmation",
        "list_user_pool_clients",
    ):
        assert forbidden not in source, f"{GRAPHQL_MODULE.relative_to(REPO_ROOT)} calls {forbidden}"


# ---------------------------------------------------------------------------
# One provisioning entry point, and no credential path in CI
# ---------------------------------------------------------------------------


def test_no_second_provisioning_entry_point() -> None:
    """Only the fixture script may create the identities this harness signs in as."""
    assert not (REPO_ROOT / "scripts" / "provision_show_sell_identities.py").exists(), (
        "the acceptance harness must consume the fixture, not provision its own identities"
    )
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "scripts").glob("*"))
        if path.is_file() and "qa-show-sell" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    allowed = {"scripts/qa_fixture.py"}
    assert not [path for path in offenders if path not in allowed], (
        f"more than one script provisions the QA fixture identities: {offenders}"
    )


def test_no_ci_path_holds_or_needs_a_fixture_credential() -> None:
    """No workflow may name these identities, run this spec, or hold its passwords.

    The owner's decision is that CI is not the runner for this journey: the
    passwords live in the fixture's own ``0600`` file, and a workflow that wanted
    them would be a request to put them in repository secrets.
    """
    needles = ("qa-show-sell", "TEST_QA_SHOW_SELL", "test_smoke_show_sell", "qa_fixture")
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(needle in text for needle in needles):
            offenders.append(path.name)
    assert not offenders, f"workflows reference the QA fixture identities: {offenders}"


def test_spec_is_not_a_smoke_test() -> None:
    """``-m smoke`` runs on every push to ``dev``; this journey is not that."""
    markers = _marker_names(_tree(SPEC))
    assert "smoke" not in markers, f"pytestmark is {markers}"
    assert "slow" in markers, f"pytestmark is {markers}"
    assert "pytest.mark.smoke" not in _source(SPEC)


def _marker_names(tree: ast.Module) -> list[str]:
    """Return the marker names on the spec's module-level ``pytestmark``.

    Args:
        tree: the parsed spec module.
    """
    names: list[str] = []
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in node.targets)):
            continue
        for attribute in ast.walk(node.value):
            if isinstance(attribute, ast.Attribute) and isinstance(attribute.value, ast.Attribute):
                if attribute.value.attr == "mark":
                    names.append(attribute.attr)
    return names


# ---------------------------------------------------------------------------
# Credentials and artifacts
# ---------------------------------------------------------------------------


def test_trace_starts_after_login() -> None:
    """A trace that covers login records the Cognito password it posts."""
    tree = _tree(SPEC)
    session = _function(tree, "_persona_session")
    calls = _call_names(session)
    assert "login" in calls and "context.tracing.start" in calls, calls
    login_line = next(
        node.lineno for node in ast.walk(session) if isinstance(node, ast.Call) and _call_names(node) == ["login"]
    )
    tracing_line = next(
        node.lineno
        for node in ast.walk(session)
        if isinstance(node, ast.Call) and _call_names(node) == ["context.tracing.start"]
    )
    assert login_line < tracing_line, "tracing must start after login, not across it"


def test_artifact_hygiene_lives_outside_the_spec(tmp_path: Path) -> None:
    """The redaction and scan helpers must be importable without the spec.

    Importing ``tests.e2e.test_smoke_show_sell`` from the unit suite fails on its
    own markers, and a helper that cannot be tested is a helper nobody checks.
    """
    from tests.e2e.utils import show_sell_evidence as artifacts

    (tmp_path / "evidence.json").write_text('{"joinCode": "ABCDEFGHIJKL1234"}', encoding="utf-8")
    redactions = artifacts.redact_and_scan(tmp_path, passwords=[SENTINEL_PASSWORD], codes=["ABCDEFGHIJKL1234"])

    text = (tmp_path / "evidence.json").read_text(encoding="utf-8")
    assert redactions == 1
    assert "ABCDEFGHIJKL1234" not in text
    assert artifacts.REDACTION in text, text
    assert len(artifacts.REDACTION) == 16, "the placeholder must be the same length as a fixture code"


def test_a_password_in_any_artifact_fails_the_run(tmp_path: Path) -> None:
    """A credential in an uploaded artifact is a defect, not something to hide."""
    from tests.e2e.utils import show_sell_evidence as artifacts

    (tmp_path / "notes.txt").write_text(f"join code ABCDEFGHIJKL1234, password {SENTINEL_PASSWORD}", encoding="utf-8")
    with pytest.raises(AssertionError, match="a password appears in notes.txt"):
        artifacts.redact_and_scan(tmp_path, passwords=[SENTINEL_PASSWORD], codes=["ABCDEFGHIJKL1234"])

    (tmp_path / "notes.txt").write_text("clean", encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "trace.zip", "w") as writer:
        writer.writestr("network.txt", f"password={SENTINEL_PASSWORD}")
    with pytest.raises(AssertionError, match="a password appears in trace.zip:network.txt"):
        artifacts.redact_and_scan(tmp_path, passwords=[SENTINEL_PASSWORD], codes=["ABCDEFGHIJKL1234"])


def test_account_id_normalization_matches_the_grant_rows() -> None:
    """``getMyAccount`` answers ``ACCOUNT#<sub>``; the grant rows carry the bare sub.

    Compared raw, the caller's own grant looks like somebody else's — and the
    teardown's job is to revoke everyone except the caller.
    """
    from tests.e2e.utils import show_sell_evidence as artifacts

    assert (
        artifacts.bare_account_id("ACCOUNT#11111111-2222-3333-4444-555555555555")
        == "11111111-2222-3333-4444-555555555555"
    )
    assert artifacts.bare_account_id("11111111-2222-3333-4444-555555555555") == "11111111-2222-3333-4444-555555555555"


def test_profile_id_normalization_spans_both_spellings() -> None:
    """``listMyProfiles`` answers ``PROFILE#<uuid>``; a roster row may answer the bare id.

    A joined Scout compared across those two spellings reads as missing, which is
    the failure mode that looks like a tenant-isolation bug.
    """
    import ast

    page_object = E2E_DIR / "pages" / "show_sell_page.py"
    tree = _tree(page_object)
    function = _function(tree, "profile_key")
    source = ast.unparse(function).replace("'", '"')
    assert 'removeprefix("PROFILE#")' in source, source


# ---------------------------------------------------------------------------
# The gate is asserted both ways
# ---------------------------------------------------------------------------


def test_gate_assertions_need_a_persona_outside_the_group() -> None:
    """The closed half of the preview gate needs an identity outside the group.

    The gate reads the ``cognito:groups`` claim of whoever signs in, so a fixture
    set that put every identity in ``show-sell-preview`` would leave the closed
    half unproven no matter how many steps passed.
    """
    spec_source = _source(SPEC)
    assert "outside" in spec_source, "the harness has no persona outside the preview group"
    assert PREVIEW_GROUP in spec_source

    helper = E2E_DIR / "pages" / "show_sell_page.py"
    tree = _tree(helper)
    gate = _function(tree, "gate_opens")
    arguments = [arg.arg for arg in gate.args.args]
    assert "control_test_id" in arguments, (
        "gate_opens must probe the opened route's own control: probing one route for another route's "
        "control reports a closed gate for an account that was admitted"
    )


def test_harness_never_prints_a_credential() -> None:
    """No call in the spec may be handed a password value."""
    tree = _tree(SPEC)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ".".join(_call_names(node)[-1:])
        if name.split(".")[-1] not in {"print", "write_text", "write_bytes", "writestr", "info", "warning", "error"}:
            continue
        for arg in ast.walk(node):
            if isinstance(arg, ast.Constant) and arg.value == SENTINEL_PASSWORD:
                offenders.append(f"{name} at line {node.lineno}")
            if isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Subscript):
                inner = arg.value.slice
                if (
                    isinstance(arg.slice, ast.Constant)
                    and arg.slice.value == "password"
                    and isinstance(inner, ast.Constant)
                ):
                    offenders.append(f"{name} at line {node.lineno}")
    assert not offenders, f"the spec hands a credential to output: {offenders}"


def test_harness_reads_the_graphql_shape_the_schema_declares() -> None:
    """A query the deployed API rejects looks like a tenant-isolation failure.

    ``listMyProfiles`` takes ``limit``; the Show & Sell connections take
    ``page: PageInput``.  Mixing the two is a runtime error against the real API,
    which is the worst place to learn it, so the exact operations the harness
    sends are pinned against the schema's own argument lists.
    """
    source = _source(GRAPHQL_MODULE) + _source(SPEC)
    for operation in (
        "query { listMyProfiles(limit: 100) { profiles { profileId sellerName } } }",
        "query { myUnits(page: {limit: 50}) { items { unitId } } }",
        "query { myUnits(page: {limit: 50}) { items { unitId unitType unitNumber city state displayName } } }",
        "query { getMyAccount { accountId } }",
    ):
        assert operation in source, f"the harness no longer sends {operation!r}"

    schema = (REPO_ROOT / "tofu" / "application" / "schema" / "schema.graphql").read_text(encoding="utf-8")
    assert "limit:" in _arguments_of(schema, "listMyProfiles"), "listMyProfiles no longer takes limit"
    assert "page: PageInput" in _arguments_of(schema, "myUnits"), "myUnits no longer takes page: PageInput"
    assert "page: PageInput" in _arguments_of(schema, "unitAdmins"), "unitAdmins takes page: PageInput"
    assert "unitAdmins(unitId: $unitId, page: {limit: 50})" in _source(GRAPHQL_MODULE), (
        "the harness's grant read must send page: PageInput, the shape the schema declares"
    )
    assert "page: PageInput" not in _arguments_of(schema, "listMyProfiles"), (
        "listMyProfiles takes limit, not page: PageInput — a query that sends the wrong shape fails at runtime"
    )


def _arguments_of(schema: str, field: str) -> str:
    """Return the argument list the schema declares for *field*.

    Args:
        schema: the schema text.
        field: the field name to read.
    """
    marker = f"  {field}("
    assert marker in schema, f"the schema declares no {field}"
    opening = schema.index(marker) + len(marker) - 1
    depth = 0
    for index in range(opening, len(schema)):
        if schema[index] == "(":
            depth += 1
        elif schema[index] == ")":
            depth -= 1
            if depth == 0:
                return schema[opening + 1 : index]
    raise AssertionError(f"unbalanced arguments for {field}")


def test_identity_variables_are_documented_where_they_are_needed() -> None:
    """The runbook has to name the variables, or the next lane cannot run this."""
    readme = (E2E_DIR / "README.md").read_text(encoding="utf-8")
    for var in IDENTITY_VARS:
        assert var in readme, f"tests/e2e/README.md does not document {var}"
    assert "TEST_USER_POOL_CLIENT_ID" in readme
    assert "qa_fixture.py" in readme, "the runbook must point at the one fixture script"
    # Both origin keys, and which one wins: a reader with only the QA environment
    # has to be able to run the recipe as written.
    for var in ("TEST_QA_SHOW_SELL_BASE_URL", "E2E_BASE_URL"):
        assert var in readme, f"tests/e2e/README.md does not document {var}"
    assert "target_origin" in readme, "the runbook must say what publishes the origin"
    assert "lands with WORK-201" in readme, "the fixture script is not in this tree yet"

    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "show-sell-preview" in agents
    assert PREVIEW_GROUP in agents


def test_read_after_write_is_polled_with_a_deadline() -> None:
    """Every read of a just-written row is a bounded poll, never one snapshot.

    The reads this journey uses go through DynamoDB indexes, so a profile, a
    campaign status chip, or a roster row can answer late.  A longer sleep would
    make the harness slow and still flaky, so each wait re-reads until its deadline
    and the failure names what was actually observed.
    """
    page_tree = _tree(E2E_DIR / "pages" / "show_sell_page.py")
    for waiter in (
        "wait_for_roster_row",
        "wait_for_roster_removal",
        "wait_for_campaign_status",
        "wait_for_admin_grant_gone",
    ):
        body = ast.unparse(_function(page_tree, waiter))
        assert "expect(" in body or "reload(" in body, f"{waiter} reads once instead of polling"
        assert "AssertionError" in body, f"{waiter} gives up without naming what it saw"

    spec_tree = _tree(SPEC)
    for waiter in ("_profile_id_for", "_roster_after_removal", "_await_grants_without"):
        body = ast.unparse(_function(spec_tree, waiter))
        assert "time.monotonic()" in body, f"{waiter} has no bounded deadline"
        assert "AssertionError" in body, f"{waiter} gives up without naming what it saw"


def test_the_unit_tenant_key_varies_per_run() -> None:
    """A fixed Unit number makes a re-run fail on the duplicate answer.

    A Unit is keyed by type + number + city + state, and the shipped UI cannot
    answer that collision's second intent (the confirm never opens), so the number
    comes from DATA_ID and a Unit that already carries the key is reused.
    """
    spec = _source(SPEC)
    assert '"unit_number": _unit_number(data_id)' in spec
    assert "UNIT_NUMBER = " not in spec, "a fixed Unit number collides with a previous run's Unit"
    assert "_unit_for_key(" in spec, "a re-run must reuse the Unit its own DATA_ID created"


def test_graphql_error_shape_is_available_to_the_harness() -> None:
    """A refusal is evidence, so the code and message have to survive the helper."""
    from tests.e2e.utils import show_sell_graphql as api

    error: Any = api.GraphQLError("no", ["FORBIDDEN"], {"errors": [{"message": "no"}]})
    assert error.codes == ["FORBIDDEN"]
    assert error.payload["errors"][0]["message"] == "no"


def test_error_codes_are_read_from_every_place_the_resolver_puts_them() -> None:
    """A refusal whose code is not read reads as a refusal nobody can explain.

    The deployed API answers with the code in a different slot per resolver shape,
    and a validation error genuinely has none.  Reading only ``extensions`` is the
    same mistake that keeps the duplicate-Unit confirm from opening in the shipped
    UI (``frontend/src/lib/units.ts`` reads that one slot and misses AppSync's
    top-level ``errorType``).
    """
    from tests.e2e.utils import show_sell_graphql as api

    cases = [
        ({"extensions": {"code": "FORBIDDEN"}}, "FORBIDDEN"),
        ({"extensions": {"errorCode": "NOT_FOUND"}}, "NOT_FOUND"),
        ({"errorType": "INVALID_INPUT", "errorInfo": {"errorCode": "INVALID_INPUT"}}, "INVALID_INPUT"),
        ({"extensions": {"errorType": "UNAUTHORIZED"}}, "UNAUTHORIZED"),
        ({}, ""),
    ]
    for error, expected in cases:
        summaries = api.error_summaries({"errors": [{"message": "no", **error}]})
        assert summaries == [{"message": "no", "code": expected}], f"{error} read as {summaries}"
