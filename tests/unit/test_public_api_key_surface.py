"""Contract tests for the public order API-key surface - the OpenTofu half.

Harness split (public-orders spec §10.4): no Python GraphQL parser exists in this
repo and no Python test reads `schema.graphql`, so the schema-directive half of
this contract lives in `tests/unit/check_public_api_key_surface.test.ts` (vitest,
`guards` job, reads the schema as text with anchored patterns). This file pins
the `.tf`/workflow half with python-hcl2 (precedent:
`test_lambda_unit_resolver_wiring.py`).

Pinned here:

- `api.tf` declares exactly one PRIMARY auth mode (Cognito, `default_action =
  "ALLOW"`) and exactly one ADDITIONAL mode (`API_KEY`), in the provider-verified
  shape: the block carries only `authentication_type`. There is no
  `api_key_config` block and no nested `authentication_provider` block - spec rev
  6 claimed both, the provider schema contains neither, and that shape would not
  plan.
- The key is a separate `aws_appsync_api_key` with a `description` and an
  EXPLICIT `expires`. The provider defaults to 7 days, which would silently kill
  the public page a week after deploy; AWS caps a key at 365 days and requires
  the timestamp rounded down to the nearest hour.
- The key value reaches every consumer: the module output, the `appsync_api_key`
  output in all three environments, `VITE_APPSYNC_API_KEY` in the deploy build
  env, and BOTH `TEST_`/`VITE_` exports in BOTH `ephemeral-env.sh` blocks
  (ephemeral CI evaluates those hand-written exports; missing either leaves every
  ephemeral integration/E2E public test without the key).

DEFERRED ON PURPOSE - one thing only. Whether input types genuinely need no
auth directive is still UNVERIFIED and is asserted nowhere. Everything else about
multi-auth reachability was MEASURED live on an ephemeral stack by the
KW-PUBLIC-ORDERS-SPIKE-1 experiment and is pinned: directive exclusivity (a
Cognito caller on an `@aws_api_key`-only field gets `errorType: "Unauthorized"`,
"Not Authorized to access <field> on type Query", never a resolver-level
NOT_FOUND), the converse rule (no-directive fields and types are reachable only
through the default Cognito mode - confirmed against real production fields), and
the stricter one (a marked root returning an UNMARKED type resolves the root but
DENIES the sub-fields, so the directive is an obligation across the whole type
closure). The live assertions live in
`tests/integration/resolvers/publicAuthModes.integration.test.ts`; the closure
walk lives in the vitest guard.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hcl2
import pytest
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

PUBLIC_API_KEY_ROOT_FIELDS = {"publicGetOrderOffer", "publicCreateOrder", "publicGetOrderReceipt"}
PUBLIC_API_KEY_TYPES = {
    "PublicOrderOffer",
    "PublicProduct",
    "PublicPaymentMethod",
    "PublicLineItem",
    "PublicOrderReceipt",
    "PublicOrderReceiptLookup",
}


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
    return _resources(_api_tf(), "aws_appsync_api_key")


def _api_key_body() -> dict:
    keys = _api_key_resources()
    assert len(keys) == 1, "AppSync allows one key per API-key mode; declare exactly one resource"
    return keys[0][1]


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
    user_pool_config, lambda_authorizer_config). Spec rev 6's nested
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
    label, body = _api_key_resources()[0]
    assert "api_id" in body, "the key must be attached to the API"
    assert "appsync_graphql_api.main" in str(body["api_id"])
    description = _norm(body.get("description", ""))
    assert description, "the key needs a description: it is the only human-facing handle in the console"
    assert "count" not in body and "for_each" not in body, (
        "the key must exist in every environment (dev, prod, and ephemeral) or the public surface is dead there"
    )
    assert label == "public", f"the key resource label is referenced by recovery imports: {label}"


def test_expires_is_explicit_rfc3339_and_hour_rounded():
    """Never omit `expires`: the provider default is 7 days. AWS requires the
    timestamp rounded DOWN to the nearest hour."""
    body = _api_key_body()
    assert "expires" in body, "aws_appsync_api_key must carry an explicit expires (provider default is 7 days)"
    raw = body["expires"]
    assert isinstance(raw, str), "expires must be a literal string, not a computed value"
    value = _norm(raw)
    assert "${" not in value and "timestamp(" not in value, (
        "expires must be a fixed literal: a computed value (e.g. timestamp()) would replace the key on every plan"
    )
    parsed = datetime.strptime(value, EXPIRES_FORMAT)
    assert parsed.minute == 0 and parsed.second == 0, f"expires must be rounded to the hour: {value}"


def test_expires_is_inside_the_service_cap_and_still_live():
    """The declared expiry must sit within AWS's 365-day cap and in the future.

    This test is a deliberate date gate: it starts failing when the declared key
    would be rejected or has expired, which is the renewal runbook firing (see the
    `expires` comment in api.tf and the ExpiredAPIKeys alarm in the spec's §9).
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
    script = EPHEMERAL_ENV_SCRIPT.read_text()
    for key in ("TEST_APPSYNC_API_KEY", "VITE_APPSYNC_API_KEY"):
        occurrences = re.findall(rf'echo "export {key}=\$\(tofu output -raw appsync_api_key\)"', script)
        assert len(occurrences) == 2, f"{key} must be exported in both the up and env blocks of ephemeral-env.sh"


def test_generator_manages_the_key_for_integration_and_frontend_envs():
    module = _load_generator()
    assert "appsync_api_key" in module.REQUIRED_OUTPUTS, "a stack without the key output must fail loudly"
    assert "TEST_APPSYNC_API_KEY" in module.INTEGRATION_STRUCTURAL_KEYS
    assert "VITE_APPSYNC_API_KEY" in module.FRONTEND_STRUCTURAL_KEYS

    outputs = {
        "appsync_api_url": "https://api.appsync-api.us-east-1.amazonaws.com/graphql",
        "appsync_api_key": "key123",
        "cognito_user_pool_id": "pool",
        "cognito_client_id": "client",
        "cognito_domain": "login.test.kernelworx.app",
    }
    assert module.expected_integration_values(outputs, "us-east-1")["TEST_APPSYNC_API_KEY"] == "key123"
    assert module.expected_frontend_values(outputs, "us-east-1")["VITE_APPSYNC_API_KEY"] == "key123"


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


@pytest.mark.skip(reason="the input-type no-directive rule was never measured; do not freeze an assumption")
def test_input_types_need_no_auth_directive():
    """GAP - the spike measured fields and types, not inputs.

    `PublicCreateOrderInput` reuses `AddressInput`/`LineItemInput`, so if inputs
    ever turned out to need a directive, three input types would have to carry it.
    Verify it on a live stack before writing the assertion; the schema currently
    carries no directive on any input type.
    """
