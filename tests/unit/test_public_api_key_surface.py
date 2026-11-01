"""Contract tests for the public orders API-key surface - the OpenTofu half.

Harness split (public-orders spec §10.4): no Python GraphQL parser exists in this
repo and no Python test reads `schema.graphql`, so the schema-directive half of
this contract lives in `tests/unit/check_public_api_key_surface.test.ts` (vitest,
`guards` job, reads the schema as text with anchored patterns). This file pins
the `.tf`/workflow/script half with python-hcl2 (precedent:
`test_lambda_unit_resolver_wiring.py`).

Pinned here:

- `api.tf` declares exactly one PRIMARY auth mode (Cognito, `default_action =
  "ALLOW"`) and exactly one ADDITIONAL mode (`API_KEY`), in the provider-verified
  shape: the block carries only `authentication_type`. There is no
  `api_key_config` block and no nested `authentication_provider` block - neither
  exists in the provider schema, and that shape would not plan.
- The key is a separate `aws_appsync_api_key` with a `description` and an
  EXPLICIT `expires`. The provider defaults to 7 days, which would silently kill
  the public page a week after deploy; AWS caps a key at 365 days and requires
  the timestamp rounded down to the nearest hour.
- SEC-3 rotation model: an expires-only edit does NOT rotate the key (the
  provider updates `expires` in place via UpdateApiKey; the key material never
  changes). Rotation is explicit and two-phase via
  `var.public_orders_key_slots` ("a" steady state, "ab" add-new, "b"
  remove-old) over two counted key resources, and the module output prefers
  the rotation slot while it exists. The old contract (exactly one key
  resource, no `count`) asserted the broken one-key premise and is replaced by
  the assertions pinning the slot model.
- The key value reaches every consumer: the module output, the `appsync_api_key`
  output in all three environments, `VITE_APPSYNC_API_KEY` in the deploy build
  env, and BOTH `TEST_`/`VITE_` exports in BOTH `ephemeral-env.sh` blocks
  (ephemeral CI evaluates those hand-written exports; missing either leaves every
  ephemeral integration/E2E public test without the key).

The recovery import for the key is pinned behaviorally instead, in
`test_ephemeral_reliability.py`, which executes the recover script against a
stubbed AWS CLI and asserts the `tofu import` calls it issues.

The scope is campaign-level (#679 rev 7): the key is what makes the campaign's
`publicGetOrderOffer` root field reachable at all, and the per-campaign share
token carried in the URL is the authorization.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hcl2
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
API_TF = REPO_ROOT / "tofu" / "application" / "modules" / "appsync" / "api.tf"
APP_SYNC_OUTPUTS = REPO_ROOT / "tofu" / "application" / "modules" / "appsync" / "outputs.tf"
ENVIRONMENT_DIRS = ("dev", "prod", "ephemeral")
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-shared.yml"
EPHEMERAL_ENV_SCRIPT = REPO_ROOT / "scripts" / "ephemeral-env.sh"
GENERATOR = REPO_ROOT / "scripts" / "generate_integration_env.py"

# AWS service cap for an AppSync API key's lifetime.
SERVICE_CAP_DAYS = 365
EXPIRES_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# The resource label in api.tf. Recovery imports and the schema guard both name
# it, so it is pinned here rather than discovered.
API_KEY_RESOURCE_LABEL = "public_orders"


def _norm(value):
    """Decode a python-hcl2 scalar: strip its quote wrapper and ${...} interpolation."""
    if isinstance(value, str):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("${") and value.endswith("}"):
            value = value[2:-1]
    return value


def _load(path: Path) -> dict:
    with path.open() as handle:
        return hcl2.load(handle)


def _resources(doc: dict, resource_type: str) -> list[tuple[str, dict]]:
    """Return [(label, body), ...] for every resource of the given type."""
    found: list[tuple[str, dict]] = []
    for entry in doc.get("resource", []):
        for type_name, bodies in entry.items():
            if _norm(type_name) != resource_type:
                continue
            for label, attrs in bodies.items():
                found.append((_norm(label), attrs))
    return found


def _outputs(doc: dict) -> dict[str, dict]:
    """Return {name: body} for every top-level output."""
    found: dict[str, dict] = {}
    for entry in doc.get("output", []):
        for name, bodies in entry.items():
            found[_norm(name)] = bodies[0] if isinstance(bodies, list) else bodies
    return found


def _api_tf() -> dict:
    return _load(API_TF)


def _graphql_api() -> dict:
    apis = _resources(_api_tf(), "aws_appsync_graphql_api")
    assert len(apis) == 1, "the appsync module must declare exactly one GraphQL API"
    return apis[0][1]


def _api_key_resources() -> list[tuple[str, dict]]:
    return sorted(_resources(_api_tf(), "aws_appsync_api_key"))


def _api_key_body() -> dict:
    """The slot-A (established) key body."""
    keys = {label: body for label, body in _api_key_resources()}
    assert set(keys) == {API_KEY_RESOURCE_LABEL, "public_orders_rotation"}, (
        "SEC-3: exactly the two rotation slots must exist (slot A + rotation slot B)"
    )
    return keys[API_KEY_RESOURCE_LABEL]


def _rotation_key_body() -> dict:
    keys = {label: body for label, body in _api_key_resources()}
    return keys["public_orders_rotation"]


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_integration_env", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Auth mode
# ---------------------------------------------------------------------------


def test_primary_mode_stays_cognito_with_allow_default():
    """The API_KEY mode is additive: Cognito remains the primary/default mode, so
    the resolver-only authorization posture (#71) is unchanged."""
    api = _graphql_api()
    assert _norm(api["authentication_type"]) == "AMAZON_COGNITO_USER_POOLS"
    pools = api.get("user_pool_config")
    assert isinstance(pools, list) and len(pools) == 1, "exactly one primary user_pool_config"
    assert _norm(pools[0]["default_action"]) == "ALLOW"


def test_exactly_one_additional_provider_and_it_is_api_key():
    api = _graphql_api()
    additional = api.get("additional_authentication_provider")
    assert isinstance(additional, list), "additional_authentication_provider must be a block"
    assert len(additional) == 1, "exactly one additional auth mode"
    assert _norm(additional[0]["authentication_type"]) == "API_KEY"


def test_additional_provider_uses_the_provider_verified_shape():
    """The block accepts only authentication_type (plus openid_connect_config,
    user_pool_config, lambda_authorizer_config). A nested
    `authentication_provider` / `api_key_config` shape does not exist in the
    provider schema and would fail plan, so pin its absence."""
    body = _graphql_api()["additional_authentication_provider"][0]
    keys = {_norm(key) for key in body if _norm(key) not in {"__is_block__", "__comments__"}}
    assert keys == {"authentication_type"}, f"unexpected nested config in the additional provider: {keys}"
    assert "api_key_config" not in keys
    assert "authentication_provider" not in keys


# ---------------------------------------------------------------------------
# The key resource
# ---------------------------------------------------------------------------


def test_key_is_a_separate_resource_with_a_description():
    label, body = next((label, body) for label, body in _api_key_resources() if label == API_KEY_RESOURCE_LABEL)
    assert "api_id" in body, "the key must be attached to the API"
    assert "appsync_graphql_api.main" in str(body["api_id"])
    description = _norm(body.get("description", ""))
    assert description, "the key needs a description: it is the only human-facing handle in the console"
    # The "slot A"/"slot B" tags in the descriptions are what the ephemeral
    # recovery import matches on (AppSync keys have no name).
    assert "slot A" in description
    assert label == API_KEY_RESOURCE_LABEL, f"the key resource label is referenced by recovery imports: {label}"


def test_expires_is_explicit_rfc3339_and_hour_rounded():
    """Never omit `expires`: the provider default is 7 days. AWS requires the
    timestamp rounded DOWN to the nearest hour. Both rotation slots carry the
    same literal."""
    for fetch in (_api_key_body, _rotation_key_body):
        body = fetch()
        assert "expires" in body, "aws_appsync_api_key must carry an explicit expires (provider default is 7 days)"
        raw = body["expires"]
        assert isinstance(raw, str), "expires must be a literal string, not a computed value"
        value = _norm(raw)
        assert "${" not in value and "timestamp(" not in value, (
            "expires must be a fixed literal: a computed value (e.g. timestamp()) would replace the key on every plan"
        )
        parsed = datetime.strptime(value, EXPIRES_FORMAT)
        assert parsed.minute == 0 and parsed.second == 0, f"expires must be rounded to the hour: {value}"


def test_rotation_is_modeled_by_slots_and_an_expires_only_change_is_not_rotation():
    """SEC-3: pin the rotation model and document why it exists.

    The provider implements an `expires` change as an in-place UpdateApiKey:
    the key id and the key material never change, so editing `expires` (the
    old runbook's whole rotation procedure) renews lifetime but leaves a
    leaked key VALID. A real rotation must create fresh key material and then
    destroy the old key, which the two counted slot resources +
    `var.public_orders_key_slots` make explicit: "ab" creates slot B (the
    output, and therefore every bundle, cuts over to it while A stays valid),
    "b" destroys slot A (actual revocation).
    """
    variables_doc = _load(API_TF.with_name("variables.tf"))
    variables = {_norm(name) for entry in variables_doc.get("variable", []) for name in entry}
    assert "public_orders_key_slots" in variables, (
        "rotation must be explicit terraform state, not a runbook promise: "
        "an expires-only edit updates the key in place and never revokes it"
    )
    slots = next(
        next(iter(entry.values()))
        for entry in variables_doc["variable"]
        for name in entry
        if _norm(name) == "public_orders_key_slots"
    )
    validation = str(slots.get("validation"))
    for state in ("a", "ab", "b"):
        assert f'"{state}"' in validation, f"rotation state {state!r} must be a validated value"

    for label, body in _api_key_resources():
        count = str(body.get("count", ""))
        assert "public_orders_key_slots" in count, (
            f"{label} must be gated on public_orders_key_slots so apply always yields the intended slot set"
        )
    slot_a = str(_api_key_body().get("count", ""))
    slot_b = str(_rotation_key_body().get("count", ""))
    assert '"a"' in slot_a and '"ab"' in slot_a, "slot A exists in states a and ab"
    assert '"ab"' in slot_b and '"b"' in slot_b, "slot B exists in states ab and b"
    assert "slot B" in _norm(_rotation_key_body().get("description", "")), (
        "the recovery import matches the rotation slot by its description tag"
    )


def test_module_output_prefers_the_rotation_slot() -> None:
    """While slot B exists (state "ab"/"b") the output - and therefore every
    frontend bundle - must bake B; otherwise the add-new/deploy phase would
    ship bundles still carrying the compromised key."""
    module_outputs = _outputs(_load(APP_SYNC_OUTPUTS))
    value = _norm(str(module_outputs["api_key"]["value"]))
    assert value == "nonsensitive(local.active_public_orders_api_key)"
    # The local itself must branch on the slots variable and prefer the
    # rotation slot whenever it exists.
    outputs_locals = _load(APP_SYNC_OUTPUTS).get("locals", [])
    locals_body = outputs_locals[0] if outputs_locals else {}
    active = str(locals_body.get("active_public_orders_api_key", locals_body.get('"active_public_orders_api_key"', "")))
    assert "public_orders_rotation[0].key" in active and "public_orders_key_slots" in active, (
        "the api_key output must prefer the rotation slot whenever it exists"
    )
    expires = str(module_outputs["api_key_expires"]["value"])
    assert "public_orders_key_slots" in expires


def test_expires_is_inside_the_service_cap_and_still_live():
    """The declared expiry must sit within AWS's 365-day cap and in the future.

    This test is a deliberate date gate: it starts failing when the declared key
    would be rejected or has expired, which is the renewal runbook firing (see
    the `expires` comment in api.tf and docs/PUBLIC_API_KEY_RUNBOOK.md). The
    runtime half of the spec's ExpiredAPIKeys alarm now ships in
    tofu/application/modules/alarms/ (a scheduled reminder derived from this
    same `expires` value, plus the AppSync 4xx alarm that catches day-zero
    expiry as a symptom — AWS publishes no ExpiredAPIKeys metric). This test
    stays the CI half.
    """
    value = _norm(_api_key_body()["expires"])
    parsed = datetime.strptime(value, EXPIRES_FORMAT)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert parsed > now, f"AppSync API key expires={value} is already in the past; renew it before deploying"
    assert parsed - now <= timedelta(days=SERVICE_CAP_DAYS), (
        f"AppSync API key expires={value} is more than {SERVICE_CAP_DAYS} days out; AWS rejects it"
    )


# ---------------------------------------------------------------------------
# Plumbing: tofu output -> build and test environments
# ---------------------------------------------------------------------------


def test_module_and_all_environments_expose_the_key():
    module_outputs = _outputs(_load(APP_SYNC_OUTPUTS))
    assert "api_key" in module_outputs, "the appsync module must output the key value"

    for environment in ENVIRONMENT_DIRS:
        doc = _load(REPO_ROOT / "tofu" / "application" / "environments" / environment / "main.tf")
        outputs = _outputs(doc)
        assert "appsync_api_key" in outputs, f"{environment} must expose appsync_api_key"
        assert "module.appsync.api_key" in str(outputs["appsync_api_key"]["value"])


def test_deploy_workflow_feeds_the_key_into_the_frontend_build():
    workflow = yaml.safe_load(DEPLOY_WORKFLOW.read_text())
    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
    extract = [s for s in steps if "Extract OpenTofu outputs for frontend" in s.get("name", "")]
    assert len(extract) == 1
    assert "appsync_api_key=$(tofu output -raw appsync_api_key)" in extract[0]["run"], (
        "the deploy must read the appsync_api_key tofu output"
    )

    build = [s for s in steps if "Build and deploy frontend" in s.get("name", "")]
    assert len(build) == 1
    env = build[0].get("env", {})
    assert env.get("VITE_APPSYNC_API_KEY") == "${{ steps.tofu_outputs.outputs.appsync_api_key }}", (
        "the public page's Apollo client reads VITE_APPSYNC_API_KEY from the build env"
    )


def test_ephemeral_env_exports_the_key_in_both_blocks():
    """`up` and `env` each hand-write their export lines; ephemeral CI evaluates
    them, so a key missing from either block leaves every ephemeral
    integration/E2E public test running without it."""
    lines = EPHEMERAL_ENV_SCRIPT.read_text().splitlines()
    label_indexes = [i for i, line in enumerate(lines) if re.match(r"^  (up|env|down)\)$", line)]
    esac_index = next(i for i, line in enumerate(lines) if line == "esac")
    blocks: dict[str, tuple[int, int]] = {}
    for i, start in enumerate(label_indexes):
        label = lines[start].strip().rstrip(")")
        end = label_indexes[i + 1] if i + 1 < len(label_indexes) else esac_index
        blocks[label] = (start, end)
    assert set(blocks) == {"up", "env", "down"}, f"ephemeral-env.sh case blocks changed: {sorted(blocks)}"
    for key in ("TEST_APPSYNC_API_KEY", "VITE_APPSYNC_API_KEY"):
        per_block = {}
        for label, (start, end) in blocks.items():
            block = lines[start:end]
            # Each block resolves the output once into APPSYNC_API_KEY - tolerating
            # a stack whose state predates the key - and echoes that variable per
            # key, so the contract is the read plus the echo, not one line shape.
            reads_key_output = any(
                re.match(r"^\s*APPSYNC_API_KEY=\$\(tofu output -raw appsync_api_key", line) for line in block
            )
            echoes = sum(1 for line in block if re.match(rf'^\s*echo "export {key}=\$APPSYNC_API_KEY"', line))
            per_block[label] = echoes if reads_key_output else 0
        assert per_block["up"] == 1 and per_block["env"] == 1 and per_block["down"] == 0, (
            f"{key} must be exported exactly once in the up and env blocks and never in down; got {per_block}"
        )


def test_generator_manages_the_key_for_integration_and_frontend_envs():
    module = _load_generator()
    assert "appsync_api_key" in module.OPTIONAL_OUTPUTS, (
        "a stack without the key output (predating the public-orders feature) must still generate envs"
    )
    assert "appsync_api_key" not in module.REQUIRED_OUTPUTS
    assert "TEST_APPSYNC_API_KEY" in module.INTEGRATION_CONDITIONAL_KEYS
    assert "VITE_APPSYNC_API_KEY" in module.FRONTEND_CONDITIONAL_KEYS

    present = {
        "appsync_api_url": "https://api.appsync-api.us-east-1.amazonaws.com/graphql",
        "appsync_api_key": "key123",
        "cognito_user_pool_id": "pool",
        "cognito_client_id": "client",
        "cognito_domain": "login.test.kernelworx.app",
    }
    integration = module.expected_integration_values(present, "us-east-1")
    frontend = module.expected_frontend_values(present, "us-east-1")
    assert integration["TEST_APPSYNC_API_KEY"] == "key123"
    assert frontend["VITE_APPSYNC_API_KEY"] == "key123"

    # A stack whose state predates the public-orders feature: no appsync_api_key
    # output. The generator still succeeds and simply omits the API-key vars.
    absent = {name: value for name, value in present.items() if name != "appsync_api_key"}
    assert "TEST_APPSYNC_API_KEY" not in module.expected_integration_values(absent, "us-east-1")
    assert "VITE_APPSYNC_API_KEY" not in module.expected_frontend_values(absent, "us-east-1")


def test_committed_templates_carry_placeholders_for_the_key():
    """The structural --check test drives these templates; a missing placeholder
    line fails it."""
    for path, key in (
        (REPO_ROOT / ".env.example", "TEST_APPSYNC_API_KEY"),
        (REPO_ROOT / "frontend" / ".env.example", "VITE_APPSYNC_API_KEY"),
    ):
        assert re.search(rf"^{key}=\S+$", path.read_text(), re.MULTILINE), f"{path} needs a {key} placeholder"


# ---------------------------------------------------------------------------
# Deferred: the one measured answer that is still missing
# ---------------------------------------------------------------------------


def test_input_types_need_no_auth_directive():
    """Input types carry no auth directive (server-mirroring rule)."""
    schema = (REPO_ROOT / "tofu" / "application" / "schema" / "schema.graphql").read_text()
    input_decls = [line for line in schema.splitlines() if line.lstrip().startswith("input ")]
    assert input_decls, "expected at least one input type declaration"
    for line in input_decls:
        assert "@aws" not in line, f"input declaration carries a directive: {line}"
