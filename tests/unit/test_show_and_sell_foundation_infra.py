"""Leaf 1.7.3 contract: the `units` and `unit_campaigns` tables and their plumbing.

Pins the parts of the Show & Sell Stage 1 foundation that later waves build on
and that nothing else in the suite covers:

- `tofu/application/modules/dynamodb/main.tf` declares the two tables with the
  data model §6.1/§6.2 key and GSI layout, the UnitInvite TTL on
  `expiresAtEpoch`, and reuse of the existing PITR / encryption / tagging /
  deletion-protection variables (no per-table overrides that could drift).
- `units` carries the TTL; `unit_campaigns` deliberately does NOT, so the
  UnitInvite TTL and the marker TTL convention cannot be confused.
- `catalogId-index` exists on `unit_campaigns`: the catalog soft-delete usage
  guard for Unit Campaign references must be a Query, never a Scan
  (impact map §3.3).
- Both tables join `table_arns`/`table_names` and get individual outputs; the
  pre-existing `public_order_throttles` gains its individual output because the
  Unit-invite redemption throttle reuses that table under its own key contract
  (data model §6.6, impact map §4.4).
- All three environments pass the three new keys into the Lambda module, and
  the module exports them to every function (`PUBLIC_ORDER_THROTTLES_TABLE_NAME`
  included). Env visibility never replaces scoped IAM: no handler in this wave
  touches the new tables, so no domain role is widened (AGENTS.md role-split
  rule; the Unit domain roles land with their handlers).
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
LAMBDA_TF = REPO_ROOT / "tofu" / "application" / "modules" / "lambda" / "main.tf"
EPHEMERAL_ENV_SCRIPT = REPO_ROOT / "scripts" / "ephemeral-env.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENVIRONMENT_DIRS = ("dev", "prod", "ephemeral")

NEW_TABLES = ("units", "unit_campaigns")

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


def test_units_ttl_is_expires_at_epoch_and_unit_campaigns_carries_no_ttl():
    """The UnitInvite TTL is numeric epoch seconds on `expiresAtEpoch`.

    `unit_campaigns` has no TTL block: the seven-day idempotency-marker TTL is a
    shared attribute-NAME convention, not a reason to arm TTL on a table that
    has no expiring item class yet (data model §8.9, impact map §4.1). Keeping
    the two apart is what stops a marker horizon being mistaken for an invite
    expiry.
    """
    units = _table("units")
    ttl = units.get("ttl")
    assert isinstance(ttl, list) and len(ttl) == 1, "units must declare exactly one ttl block"
    assert _norm(ttl[0]["attribute_name"]) == "expiresAtEpoch"
    assert ttl[0]["enabled"] is True
    assert "ttl" not in _table("unit_campaigns"), (
        "unit_campaigns has no expiring item class in Stage 1; arming TTL there "
        "would blur the UnitInvite TTL vs marker TTL distinction the spec calls out"
    )


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
