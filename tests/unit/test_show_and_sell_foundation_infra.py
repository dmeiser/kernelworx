"""Leaf 1.7.3 contract: the `units` and `unit_campaigns` tables and their plumbing.

Pins the parts of the Show & Sell Stage 1 foundation that later waves build on
and that nothing else in the suite covers:

- `tofu/application/modules/dynamodb/main.tf` declares the two tables with the
  data model §6.1/§6.2 key and GSI layout, the UnitInvite TTL on
  `expiresAtEpoch`, and reuse of the existing PITR / encryption / tagging /
  deletion-protection variables (no per-table overrides that could drift).
- EVERY marker-capable table arms the marker TTL on `expiresAtEpoch`
  (data model §8.9): unit-scoped markers land in `units`, campaign-scoped
  markers (join now, sales later) land in `unit_campaigns`. The test
  enumerates the shared `MARKER_CAPABLE_TABLE_KEYS` contract instead of
  pinning one table, so a new marker-capable table cannot land un-armed.
- `catalogId-index` exists on `unit_campaigns`: the catalog soft-delete usage
  guard for Unit Campaign references must be a Query, never a Scan
  (impact map §3.3).
- Both tables join `table_arns`/`table_names` and get individual outputs; the
  pre-existing `public_order_throttles` gains its individual output because the
  Unit-invite redemption throttle reuses that table under its own key contract
  (data model §6.6, impact map §4.4).
- All three environments pass the three new keys into the Lambda module, and
  the module exports them to every function (`PUBLIC_ORDER_THROTTLES_TABLE_NAME`
  included). Env visibility never replaces scoped IAM: `units` and
  `unit_campaigns` are excluded from the broad admin-role and AppSync DynamoDB
  policies (gate verdict (f) on PR #912) and served ONLY by the new
  unit / unit-campaign domain roles, whose inline policies carry
  `dynamodb:TransactWriteItems` scoped to the one table plus its indexes for
  the shared idempotent write helper. The roles are exported as module outputs
  and imported by the recovery script; each environment wires them into
  `lambda_domain_role_arns` per function key as the Unit handlers land (Stage 1
  ships no Unit function keys, and the lambda module fails plan loudly for any
  key missing from the map).
- `scripts/ephemeral-env.sh` exports the new table names in both the `up` and
  `env` blocks, and `.env.example` carries an override placeholder for each.

Precedent for reading `.tf` with python-hcl2: `test_public_api_key_surface.py`,
`test_iam_appsync_dynamodb_policy.py`. Recovery-import coverage for the new
tables is asserted behaviorally by
`test_ephemeral_reliability.py::test_dynamic_resource_import_coverage`.
"""

from __future__ import annotations

import re
from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMODB_TF = REPO_ROOT / "tofu" / "application" / "modules" / "dynamodb" / "main.tf"
IAM_TF = REPO_ROOT / "tofu" / "application" / "modules" / "iam" / "main.tf"
LAMBDA_TF = REPO_ROOT / "tofu" / "application" / "modules" / "lambda" / "main.tf"
EPHEMERAL_ENV_SCRIPT = REPO_ROOT / "scripts" / "ephemeral-env.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENVIRONMENT_DIRS = ("dev", "prod", "ephemeral")

NEW_TABLES = ("units", "unit_campaigns")

# The Show & Sell domain roles (gate verdict (f) on PR #912): each is the ONLY
# IAM grant on its table, scoped to the table plus its GSIs. The unit role also
# carries the Unit-invite redemption failure counter table (data model §6.6),
# which no other role touches.
DOMAIN_ROLES = {
    "lambda_unit_execution": ("units", 'var.dynamodb_table_arns["public_order_throttles"]'),
    "lambda_unit_campaign_execution": ("unit_campaigns", None),
}

# logical table key -> Lambda environment variable name (impact map §4.4).
ENV_VARS = {
    "units": "UNITS_TABLE_NAME",
    "unit_campaigns": "UNIT_CAMPAIGNS_TABLE_NAME",
    "public_order_throttles": "PUBLIC_ORDER_THROTTLES_TABLE_NAME",
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


def _resources(doc: dict, resource_type: str) -> dict[str, dict]:
    """Return {label: body} for every resource of the given type."""
    found: dict[str, dict] = {}
    for entry in doc.get("resource", []):
        for type_name, bodies in entry.items():
            if _norm(type_name) != resource_type:
                continue
            for label, attrs in bodies.items():
                found[_norm(label)] = attrs
    return found


def _outputs(doc: dict) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for entry in doc.get("output", []):
        for name, bodies in entry.items():
            found[_norm(name)] = bodies[0] if isinstance(bodies, list) else bodies
    return found


def _dynamodb_doc() -> dict:
    return _load(DYNAMODB_TF)


def _table(label: str) -> dict:
    tables = _resources(_dynamodb_doc(), "aws_dynamodb_table")
    assert label in tables, f"the dynamodb module must declare aws_dynamodb_table.{label}"
    return tables[label]


def _gsi(table: dict) -> dict[str, list[tuple[str, str]]]:
    """{index name: [(attribute, HASH|RANGE), ...]} for one table body."""
    indexes = table.get("global_secondary_index", [])
    if isinstance(indexes, dict):
        indexes = [indexes]
    out: dict[str, list[tuple[str, str]]] = {}
    for index in indexes:
        name = _norm(index["name"])
        keys = [(_norm(k["attribute_name"]), _norm(k["key_type"])) for k in index.get("key_schema", [])]
        out[name] = keys
    return out


def _attributes(table: dict) -> set[str]:
    return {_norm(a["name"]) for a in table.get("attribute", [])}


# ---------------------------------------------------------------------------
# Table layout (data model §6.1 / §6.2)
# ---------------------------------------------------------------------------


def test_both_tables_are_declared_with_pk_sk_and_all_gsi_projections():
    for label in NEW_TABLES:
        table = _table(label)
        assert _norm(table["hash_key"]) == "pk", f"{label}: pk must be `pk` (item collections share it)"
        assert _norm(table["range_key"]) == "sk", f"{label}: sk must be `sk`"
        assert _norm(table["billing_mode"]) == "PAY_PER_REQUEST"
        for name, keys in _gsi(table).items():
            assert keys[0][1] == "HASH", f"{label}/{name}: first key must be HASH"
        projections = {_norm(i["name"]): _norm(i["projection_type"]) for i in table["global_secondary_index"]}
        assert set(projections) == set(_gsi(table)), f"{label}: every GSI must declare its projection"
        assert set(projections.values()) == {"ALL"}, (
            f"{label}: GSIs use ALL projection so list pages need no back-fill read: {projections}"
        )


def test_units_gsis_match_the_data_model():
    gsi = _gsi(_table("units"))
    assert gsi == {
        "accountId-unitId-index": [("accountId", "HASH"), ("unitId", "RANGE")],
        "unitId-createdAt-index": [("unitId", "HASH"), ("createdAt", "RANGE")],
        "metadataKey-createdAt-index": [("metadataKey", "HASH"), ("createdAt", "RANGE")],
    }


def test_unit_campaigns_gsis_match_the_data_model_including_the_catalog_usage_guard():
    gsi = _gsi(_table("unit_campaigns"))
    assert gsi == {
        "unitId-createdAt-index": [("unitId", "HASH"), ("createdAt", "RANGE")],
        "campaignId-index": [("campaignId", "HASH")],
        "profileId-unitCampaignId-index": [("profileId", "HASH"), ("unitCampaignId", "RANGE")],
        # HASH-only: the catalog soft-delete usage guard Queries this index; a
        # missing index there would force a Scan (impact map §3.3).
        "catalogId-index": [("catalogId", "HASH")],
    }


def test_every_gsi_key_attribute_is_declared():
    """A table whose index key attribute is undeclared is rejected by AWS."""
    for label in NEW_TABLES:
        table = _table(label)
        declared = _attributes(table)
        for name, keys in _gsi(table).items():
            for attribute, _ in keys:
                assert attribute in declared, f"{label}/{name} uses undeclared attribute {attribute}"


def test_every_marker_capable_table_arms_the_marker_ttl():
    """The marker TTL is numeric epoch seconds on `expiresAtEpoch`, armed on
    EVERY table markers can land in (data model §8.9): unit-scoped markers in
    `units`, campaign-scoped markers (join now, sales later) in
    `unit_campaigns`. Enumerating the shared contract tuple - not pinning one
    table and asserting another's absence - is what keeps a future
    marker-capable table from landing without its TTL armed.

    This mirrors the moto fixture contract in
    `test_table_schemas.py::TestMarkerTtlContract`.
    """
    from tests.unit.table_schemas import MARKER_CAPABLE_TABLE_KEYS

    assert set(MARKER_CAPABLE_TABLE_KEYS) == {"units", "unit_campaigns"}
    for label in MARKER_CAPABLE_TABLE_KEYS:
        ttl = _table(label).get("ttl")
        assert isinstance(ttl, list) and len(ttl) == 1, f"{label} must declare exactly one ttl block"
        assert _norm(ttl[0]["attribute_name"]) == "expiresAtEpoch"
        assert ttl[0]["enabled"] is True


def _data_documents(doc: dict, data_type: str) -> dict[str, dict]:
    """Return {label: body} for every data source document of the given type."""
    found: dict[str, dict] = {}
    for entry in doc.get("data", []):
        for type_name, bodies in entry.items():
            if _norm(type_name) != data_type:
                continue
            for label, attrs in bodies.items():
                found[_norm(label)] = attrs[0] if isinstance(attrs, list) else attrs
    return found


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def test_new_tables_reuse_the_existing_pitr_encryption_and_lifecycle_variables():
    """No per-table literals: PITR, encryption, tagging, deletion protection and
    prevent_destroy all come from the module variables, so prod PITR cannot
    drift (impact map §4.1)."""
    existing = _table("campaigns")
    for label in NEW_TABLES:
        table = _table(label)
        for key in (
            "deletion_protection_enabled",
            "point_in_time_recovery",
            "server_side_encryption",
            "tags",
            "lifecycle",
        ):
            assert key in table, f"{label} is missing {key}"
        assert str(table["point_in_time_recovery"]) == str(existing["point_in_time_recovery"])
        assert str(table["server_side_encryption"]) == str(existing["server_side_encryption"])
        assert str(table["deletion_protection_enabled"]) == str(existing["deletion_protection_enabled"])
        assert str(table["lifecycle"]) == str(existing["lifecycle"])


def test_names_follow_the_module_naming_convention():
    """The recovery script resolves each table as `kernelworx-<slug><suffix>`, so a
    table name that departs from `<name_prefix>-<slug><table_suffix>` is invisible
    to recovery (its import would be skipped for a table that exists)."""
    for label, slug in (("units", "units"), ("unit_campaigns", "unit-campaigns")):
        # raw (not _norm): _norm strips the ${...} wrappers and would make an
        # interpolated segment indistinguishable from a literal.
        name = str(_table(label)["name"]).strip('"')
        expected = f"${{var.name_prefix}}-{slug}${{local.table_suffix}}"
        assert name == expected, f"{label} name must be {expected!r}, got {name!r}"


# ---------------------------------------------------------------------------
# Least-privilege IAM (gate verdict (f) on PR #912)
# ---------------------------------------------------------------------------


def test_unit_domain_roles_exist_with_the_scoped_transact_write_grant():
    """The unit / unit-campaign domain roles are the only IAM grants on the two
    tables, scoped to the one table plus its GSIs, and they carry
    `dynamodb:TransactWriteItems` - the shared mutation helper's marker insert
    rides inside every Show & Sell mutation's transaction (data model §8.9,
    impact map §4.2)."""
    doc = _load(IAM_TF)
    roles = _resources(doc, "aws_iam_role")
    policies = _resources(doc, "aws_iam_role_policy")
    attachments = _resources(doc, "aws_iam_role_policy_attachment")
    documents = _data_documents(doc, "aws_iam_policy_document")
    for role_label, extra_key in DOMAIN_ROLES.items():
        policy_label = role_label.replace("_execution", "_dynamodb")
        basic_label = role_label.replace("_execution", "_basic")
        assert role_label in roles, f"missing aws_iam_role.{role_label}"
        # hcl2 keeps interpolations as "${...}" wrappers; compare the raw form.
        assert policies.get(policy_label, {}).get("role") == f"${{aws_iam_role.{role_label}.id}}"
        assert attachments.get(basic_label, {}).get("role") == f"${{aws_iam_role.{role_label}.name}}"

        statements = _as_list(documents[policy_label]["statement"])
        assert len(statements) == 1, f"{policy_label} must be a single scoped statement"
        actions = {_norm(action) for action in _as_list(statements[0]["actions"])}
        assert "dynamodb:TransactWriteItems" in actions, f"{policy_label} must grant TransactWriteItems"
        # Scoped to exactly the domain table and its indexes - never the broad
        # table list, and never the other domain's table.
        resources = [str(resource) for resource in _as_list(statements[0]["resources"])]
        # hcl2 keeps the quoted form for the interpolated index ARN.
        table_key, extra = extra_key
        expected = [
            f'${{var.dynamodb_table_arns["{table_key}"]}}',
            f'"${{var.dynamodb_table_arns["{table_key}"]}}/index/*"',
        ]
        if extra is not None:
            expected.append(f"${{{extra}}}")
        assert resources == expected, (
            f"{policy_label} resources must be the {table_key} table plus its indexes only: {resources}"
        )
        other = set(NEW_TABLES) - {table_key}
        assert not any(other_table in resource for resource in resources for other_table in other)


def test_unit_domain_role_names_follow_the_module_and_recovery_convention():
    """The recovery script resolves each role as `kernelworx-<slug><suffix>`, so
    the name pattern is part of the recovery contract."""
    roles = _resources(_load(IAM_TF), "aws_iam_role")
    for role_label, slug in (
        ("lambda_unit_execution", "lambda-unit-exec"),
        ("lambda_unit_campaign_execution", "lambda-unit-campaign-exec"),
    ):
        name = str(roles[role_label]["name"]).strip('"')
        assert name == f"${{var.name_prefix}}-{slug}${{local.role_suffix}}", (
            f"{role_label} name must be ${{var.name_prefix}}-{slug}${{local.role_suffix}}, got {name!r}"
        )


def test_broad_dynamodb_policies_exclude_the_domain_scoped_tables():
    """`units` and `unit_campaigns` must not ride the broad admin-role and
    AppSync table lists: those policies build from the locals filtered here, so
    the widening the gate rejected cannot silently return."""
    doc = _load(IAM_TF)
    locals_body = doc["locals"][0]
    scoped_keys = {_norm(key) for key in _as_list(locals_body["domain_scoped_table_keys"])}
    assert scoped_keys == set(NEW_TABLES)
    broad = str(locals_body["broad_table_arns"])
    assert "!contains(local.domain_scoped_table_keys, k)" in broad, (
        "the broad table list must exclude the domain-scoped keys"
    )
    assert _norm(str(locals_body["dynamodb_table_arns"])) == "local.broad_table_arns"
    assert "local.broad_table_arns" in str(locals_body["dynamodb_index_arns"])
    # The admin-role and AppSync documents both consume the filtered locals.
    for document in ("lambda_dynamodb", "appsync_dynamodb"):
        resources = _as_list(_data_documents(doc, "aws_iam_policy_document")[document]["statement"])[0]["resources"]
        assert [_norm(str(resource)) for resource in _as_list(resources)] == [
            "concat(local.dynamodb_table_arns, local.dynamodb_index_arns)"
        ]


# ---------------------------------------------------------------------------
# Outputs and environment plumbing
# ---------------------------------------------------------------------------


def test_table_arns_table_names_and_individual_outputs_cover_the_new_tables():
    doc = _dynamodb_doc()
    arns = _norm(str(_outputs(doc)["table_arns"]["value"]))
    names = _norm(str(_outputs(doc)["table_names"]["value"]))
    for label in NEW_TABLES:
        assert f"aws_dynamodb_table.{label}.arn" in arns, f"table_arns is missing {label}"
        assert f"aws_dynamodb_table.{label}.name" in names, f"table_names is missing {label}"
        assert f"{label}_table_name" in _outputs(doc), f"missing individual output {label}_table_name"
    # The throttle table existed without an individual output; the Unit-invite
    # redemption throttle needs it (impact map §4.4).
    assert "public_order_throttles_table_name" in _outputs(doc)


def test_all_environments_pass_the_new_keys_to_the_lambda_module():
    for environment in ENVIRONMENT_DIRS:
        doc = _load(REPO_ROOT / "tofu" / "application" / "environments" / environment / "main.tf")
        raw = next(body for entry in doc.get("module", []) for name, body in entry.items() if _norm(name) == "lambda")
        lambda_module = raw[0] if isinstance(raw, list) else raw
        table_names = lambda_module["table_names"]
        for key in (*NEW_TABLES, "public_order_throttles"):
            assert key in table_names, f"{environment}: lambda table_names is missing {key}"
            assert _norm(table_names[key]) == f"module.dynamodb.{key}_table_name"


def test_lambda_module_exports_the_new_table_names_to_every_function():
    """`local.common_env` is merged into every function's environment, so the new
    names reach all handlers. Visibility is not authorization: the scoped role
    policies are unchanged by this (no handler in this wave touches them)."""
    doc = _load(LAMBDA_TF)
    locals_body = doc["locals"][0]
    common_env = locals_body["common_env"]
    for key, env_var in ENV_VARS.items():
        assert env_var in common_env, f"common_env is missing {env_var}"
        assert _norm(common_env[env_var]) == f"var.table_names.{key}", (
            f"common_env.{env_var} must read the module variable"
        )


# ---------------------------------------------------------------------------
# Ephemeral env exports and .env.example placeholders
# ---------------------------------------------------------------------------


def _case_blocks(lines: list[str]) -> dict[str, tuple[int, int]]:
    label_indexes = [i for i, line in enumerate(lines) if re.match(r"^  (up|env|down)\)$", line)]
    esac_index = next(i for i, line in enumerate(lines) if line == "esac")
    blocks: dict[str, tuple[int, int]] = {}
    for i, start in enumerate(label_indexes):
        label = lines[start].strip().rstrip(")")
        end = label_indexes[i + 1] if i + 1 < len(label_indexes) else esac_index
        blocks[label] = (start, end)
    return blocks


def test_ephemeral_env_exports_the_new_tables_in_up_and_env_only():
    """Direct-SDK cleanup in ephemeral CI reads these exports; a name missing
    from either block leaves that suite unable to reach the table."""
    lines = EPHEMERAL_ENV_SCRIPT.read_text().splitlines()
    blocks = _case_blocks(lines)
    assert set(blocks) == {"up", "env", "down"}, f"ephemeral-env.sh case blocks changed: {sorted(blocks)}"
    for env_var, slug in (
        ("UNITS_TABLE_NAME", "units"),
        ("UNIT_CAMPAIGNS_TABLE_NAME", "unit-campaigns"),
        ("PUBLIC_ORDER_THROTTLES_TABLE_NAME", "public-order-throttles"),
    ):
        per_block = {}
        for label, (start, end) in blocks.items():
            block = lines[start:end]
            per_block[label] = sum(
                1 for line in block if line == f'    echo "export {env_var}=kernelworx-{slug}-ue1-${{RUN_ID}}"'
            )
        assert per_block == {"up": 1, "env": 1, "down": 0}, (
            f"{env_var} must be exported exactly once in up and env and never in down; got {per_block}"
        )


def test_env_example_carries_an_override_placeholder_for_each_new_table():
    text = ENV_EXAMPLE.read_text()
    for env_var in ("UNITS_TABLE_NAME", "UNIT_CAMPAIGNS_TABLE_NAME", "PUBLIC_ORDER_THROTTLES_TABLE_NAME"):
        assert re.search(rf"^# {env_var}=$", text, re.MULTILINE), f".env.example needs a `# {env_var}=` placeholder"
