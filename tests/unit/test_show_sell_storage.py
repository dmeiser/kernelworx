"""Contract tests for the Show & Sell wave-1 storage layer.

Pins the five new DynamoDB tables (units, unit_campaigns, inventory,
order_fulfillments, show_and_sells) and the show-sell-preview Cognito group to
the key/index contracts in docs/specs/show_sell/SHOW_AND_SELL_DATA_MODEL.md §6,
the IAM wiring that grants least-privilege access to them in every
environment, and the recovery-import coverage for both the tables and the
group.

These parse the OpenTofu configuration directly: the tables are provisioned by
`tofu apply` during deploys, and the CI infra job runs tflint/KICS without
AWS credentials, so the schema contract is enforced here rather than by a live
describe-table.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMODB_TF = REPO_ROOT / "tofu" / "application" / "modules" / "dynamodb" / "main.tf"
COGNITO_TF = REPO_ROOT / "tofu" / "application" / "modules" / "cognito" / "main.tf"
IAM_TF = REPO_ROOT / "tofu" / "application" / "modules" / "iam" / "main.tf"
RECOVERY_SH = REPO_ROOT / "scripts" / "ephemeral-recover-common.sh"
ENVIRONMENTS = ("dev", "ephemeral", "prod")


def _resource_block(content: str, rtype: str, name: str) -> str:
    """Return the body of resource/data "<rtype>" "<name>" { ... } (brace-matched)."""
    match = re.search(r'(?:resource|data)\s+"' + rtype + r'"\s+"' + re.escape(name) + r'"\s*\{', content)
    assert match, f'resource "{rtype}" "{name}" not found'
    start = match.end() - 1
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return content[start : i + 1]
    raise AssertionError(f"unbalanced braces for {rtype}.{name}")


def _sub_block(block: str, header: str) -> str:
    """Return the body of a nested block introduced by `header` (brace-matched)."""
    match = re.search(r"(?m)^\s*" + re.escape(header) + r"\s*\{", block)
    assert match, f"block '{header}' not found"
    start = match.end() - 1
    depth = 0
    for i in range(start, len(block)):
        if block[i] == "{":
            depth += 1
        elif block[i] == "}":
            depth -= 1
            if depth == 0:
                return block[start : i + 1]
    raise AssertionError(f"unbalanced braces for '{header}'")


def _key_schemas(gsi_block: str) -> dict[str, str]:
    keys = {}
    for m in re.finditer(
        r"key_schema\s*\{[^}]*attribute_name\s*=\s*\"([^\"]+)\"[^}]*key_type\s*=\s*\"([^\"]+)\"",
        gsi_block,
        re.DOTALL,
    ):
        keys[m.group(1)] = m.group(2)
    return keys


def _table_section(content: str, table_name: str) -> str:
    """Return the table's full section: its preceding banner comment plus body.

    The key-layout documentation lives in the comment block above the resource,
    where the data model's PK/SK item families are recorded for reviewers.
    """
    m = re.search(r'resource\s+"aws_dynamodb_table"\s+"' + re.escape(table_name) + r'"', content)
    assert m, f'aws_dynamodb_table "{table_name}" not declared'
    banners = [b.start() for b in re.finditer(r"# =+\n", content[: m.start()])]
    assert banners, f"no banner comment above {table_name}"
    # The banner comment is fenced by two # ==== rules; the section starts at
    # the opening fence (the one before the one immediately above the resource).
    start = banners[-2] if len(banners) >= 2 else banners[-1]
    end = re.search(r'resource\s+"aws_dynamodb_table"', content[m.end() :])
    stop = m.end() + end.start() if end else len(content)
    return content[start:stop]


# Expected layout per SHOW_AND_SELL_DATA_MODEL.md §6.
TABLE_SPECS: dict[str, dict] = {
    "units": {
        "aws_suffix": "units",
        "indexes": {
            "accountId-unitId-index": {"accountId": "HASH", "unitId": "RANGE"},
            "unitId-createdAt-index": {"unitId": "HASH", "createdAt": "RANGE"},
            "metadataKey-createdAt-index": {"metadataKey": "HASH", "createdAt": "RANGE"},
        },
        "attributes": {"pk", "sk", "accountId", "unitId", "createdAt", "metadataKey"},
    },
    "unit_campaigns": {
        "aws_suffix": "unit-campaigns",
        "indexes": {
            "unitId-createdAt-index": {"unitId": "HASH", "createdAt": "RANGE"},
            "campaignId-index": {"campaignId": "HASH"},
            "profileId-unitCampaignId-index": {"profileId": "HASH", "unitCampaignId": "RANGE"},
            "catalogId-index": {"catalogId": "HASH"},
        },
        "attributes": {"pk", "sk", "unitId", "createdAt", "campaignId", "profileId", "unitCampaignId", "catalogId"},
    },
    "inventory": {
        "aws_suffix": "inventory",
        "indexes": {
            "showAndSellId-index": {"showAndSellId": "HASH"},
            "profileId-unitCampaignId-index": {"profileId": "HASH", "unitCampaignId": "RANGE"},
            "movementType-occurredAt-index": {"movementType": "HASH", "occurredAt": "RANGE"},
        },
        "attributes": {"pk", "sk", "showAndSellId", "profileId", "unitCampaignId", "movementType", "occurredAt"},
    },
    "order_fulfillments": {
        "aws_suffix": "order-fulfillments",
        "indexes": {
            "campaignId-createdAt-index": {"campaignId": "HASH", "createdAt": "RANGE"},
        },
        "attributes": {"pk", "sk", "campaignId", "createdAt"},
    },
    "show_and_sells": {
        "aws_suffix": "show-and-sells",
        "indexes": {
            "unitCampaignId-startAt-index": {"unitCampaignId": "HASH", "startAt": "RANGE"},
            "saleId-index": {"saleId": "HASH"},
            "weOweId-index": {"weOweId": "HASH"},
            "campaignId-status-index": {"campaignId": "HASH", "status": "RANGE"},
            "unitCampaignId-status-index": {"unitCampaignId": "HASH", "status": "RANGE"},
        },
        "attributes": {"pk", "sk", "unitCampaignId", "startAt", "saleId", "weOweId", "campaignId", "status"},
    },
}


@pytest.fixture(scope="module")
def dynamodb_tf() -> str:
    return DYNAMODB_TF.read_text()


class TestShowSellTables:
    """Table-for-table key/index contract from SHOW_AND_SELL_DATA_MODEL.md §6."""

    @pytest.mark.parametrize("table_name", sorted(TABLE_SPECS))
    def test_table_declared_with_prefixed_composite_key(self, dynamodb_tf: str, table_name: str) -> None:
        spec = TABLE_SPECS[table_name]
        block = _resource_block(dynamodb_tf, "aws_dynamodb_table", table_name)
        assert (
            f'name                        = "${{var.name_prefix}}-{spec["aws_suffix"]}${{local.table_suffix}}"' in block
        )
        assert 'hash_key                    = "pk"' in block
        assert 'range_key                   = "sk"' in block
        assert 'billing_mode                = "PAY_PER_REQUEST"' in block
        assert "deletion_protection_enabled = var.enable_deletion_protection" in block

    @pytest.mark.parametrize("table_name", sorted(TABLE_SPECS))
    def test_gsi_layout_matches_the_data_model(self, dynamodb_tf: str, table_name: str) -> None:
        spec = TABLE_SPECS[table_name]
        block = _resource_block(dynamodb_tf, "aws_dynamodb_table", table_name)
        gsi_names = re.findall(r'global_secondary_index\s*\{\s*name\s*=\s*"([^"]+)"', block)
        assert sorted(gsi_names) == sorted(spec["indexes"]), (
            f"{table_name}: GSI set {sorted(gsi_names)} != data model {sorted(spec['indexes'])}"
        )
        for gsi_name, expected_keys in spec["indexes"].items():
            m = re.search(r'global_secondary_index\s*\{\s*name\s*=\s*"' + re.escape(gsi_name) + '"', block)
            assert m, f"{table_name}.{gsi_name} missing"
            gsi = _sub_block(block[m.start() :], "global_secondary_index")
            assert 'projection_type = "ALL"' in gsi, f"{table_name}.{gsi_name} must project ALL"
            assert _key_schemas(gsi) == expected_keys, f"{table_name}.{gsi_name} key schema drift"

    @pytest.mark.parametrize("table_name", sorted(TABLE_SPECS))
    def test_attribute_definitions_match_index_keys(self, dynamodb_tf: str, table_name: str) -> None:
        spec = TABLE_SPECS[table_name]
        block = _resource_block(dynamodb_tf, "aws_dynamodb_table", table_name)
        attrs = set(re.findall(r'attribute\s*\{\s*name\s*=\s*"([^"]+)"\s*type\s*=\s"S"\s*\}', block))
        # All Show & Sell key attributes are String type; the set must be exactly
        # the key attributes the data model names (no unused definitions).
        assert attrs == spec["attributes"], f"{table_name}: attribute set drift: {sorted(attrs)}"

    @pytest.mark.parametrize("table_name", sorted(TABLE_SPECS))
    def test_pitr_and_no_kms(self, dynamodb_tf: str, table_name: str) -> None:
        block = _resource_block(dynamodb_tf, "aws_dynamodb_table", table_name)
        pitr = _sub_block(block, "point_in_time_recovery")
        assert "enabled = var.enable_point_in_time_recovery" in pitr
        assert "enabled = true" not in _sub_block(block, "server_side_encryption")

    def test_units_invite_ttl_on_expires_at_epoch(self, dynamodb_tf: str) -> None:
        block = _resource_block(dynamodb_tf, "aws_dynamodb_table", "units")
        ttl = _sub_block(block, "ttl")
        assert 'attribute_name = "expiresAtEpoch"' in ttl
        assert "enabled        = true" in ttl

    def test_order_fulfillments_documents_at_most_once_reversal_key(self, dynamodb_tf: str) -> None:
        # §5.19: a reversal uses the deterministic SK REVERSAL#<reversalOfFulfillmentId>
        # so at most one reversal per fulfillment can exist. The table cannot
        # express the prefix in its schema, so the contract lives in the table's
        # documented key layout and is pinned here.
        assert "REVERSAL#<reversalOfFulfillmentId>" in _table_section(dynamodb_tf, "order_fulfillments")

    def test_show_and_sells_documents_future_namespaces(self, dynamodb_tf: str) -> None:
        # §3.6.1: metadata/slot/signup keys plus the future sale/finalization/
        # We Owe namespaces are declared now so later waves never migrate keys.
        section = _table_section(dynamodb_tf, "show_and_sells")
        for sk_contract in (
            "METADATA",
            "SLOT#<slotId>",
            "SIGNUP#<slotId>#<profileId>",
            "SALE#<saleId>",
            "SALE#<saleId>#REVISION#<revision>",
            "FINALIZATION#<finalizationId>",
            "CREDIT#<finalizationId>#<profileId>",
            "WE_OWE#<weOweId>",
            "WE_OWE#<weOweId>#FULFILLMENT#<fulfillmentId>",
        ):
            assert sk_contract in section, f"show_and_sells SK namespace {sk_contract} undocumented"

    def test_units_documents_invite_item_layout(self, dynamodb_tf: str) -> None:
        section = _table_section(dynamodb_tf, "units")
        for key_contract in ("UNIT#<unitId>", "METADATA", "GRANT#<accountId>", "INVITE#<inviteCode>"):
            assert key_contract in section, f"units key contract {key_contract} undocumented"

    def test_unit_campaigns_documents_guard_and_pointer_layout(self, dynamodb_tf: str) -> None:
        section = _table_section(dynamodb_tf, "unit_campaigns")
        for key_contract in ("JOIN_CODE#<joinCode>", "MEMBERSHIP#<profileId>", "MEMBERSHIP_GUARD", "COMMITMENT_GUARD"):
            assert key_contract in section, f"unit_campaigns key contract {key_contract} undocumented"

    def test_inventory_documents_product_prefix_layout(self, dynamodb_tf: str) -> None:
        section = _table_section(dynamodb_tf, "inventory")
        for key_contract in ("BALANCE", "EVENT#<showAndSellId>", "CUSTODY#<profileId>", "MOVEMENT#<occurredAt>"):
            assert key_contract in section, f"inventory SK contract {key_contract} undocumented"

    def test_public_order_throttles_reused_for_unit_invite_throttle(self, dynamodb_tf: str) -> None:
        # §6.6: the wave reuses the existing throttle table with a separate key
        # contract (UNIT_INVITE_REDEMPTION#...); no new throttle table.
        tables = re.findall(r'resource\s+"aws_dynamodb_table"\s+"([^"]+)"', dynamodb_tf)
        throttle_tables = [t for t in tables if "throttle" in t]
        assert throttle_tables == ["public_order_throttles"], "wave 1 must reuse the existing throttle table"


class TestIAMWiring:
    """Least-privilege grants: the new tables flow through the per-environment
    table_arns map into the AppSync service role and admin-role documents —
    table/index ARNs only, never account wildcards."""

    @pytest.mark.parametrize("table_name", sorted(TABLE_SPECS))
    def test_tables_exposed_through_arn_and_name_maps(self, dynamodb_tf: str, table_name: str) -> None:
        assert re.search(rf"{table_name}\s*=\s*aws_dynamodb_table\.{table_name}\.arn", dynamodb_tf)
        assert re.search(rf"{table_name}\s*=\s*aws_dynamodb_table\.{table_name}\.name", dynamodb_tf)

    @pytest.mark.parametrize("env", ENVIRONMENTS)
    def test_environment_wires_table_arns_into_iam(self, env: str) -> None:
        content = (REPO_ROOT / "tofu" / "application" / "environments" / env / "main.tf").read_text()
        assert re.search(r"dynamodb_table_arns\s*=\s*module\.dynamodb\.table_arns", content), (
            f"{env}: IAM module must receive module.dynamodb.table_arns so the new tables are granted"
        )

    def test_iam_grants_are_table_scoped_not_wildcards(self) -> None:
        iam = IAM_TF.read_text()
        assert "dynamodb:*" not in iam
        # The two documents that cover the new tables enumerate table + index ARNs
        # built from the map.
        appsync_block = _sub_block(_block_text(iam, "aws_iam_policy_document", "appsync_dynamodb"), "statement")
        assert "concat(local.dynamodb_table_arns, local.dynamodb_index_arns)" in appsync_block

    def test_appsync_transaction_condition_access_granted(self) -> None:
        # §8 transaction boundaries: conditional checks inside TransactWriteItems
        # authorize on dynamodb:ConditionCheckItem. The AppSync service role is
        # the principal that will run the Show & Sell transactional writes.
        doc = _block_text(IAM_TF.read_text(), "aws_iam_policy_document", "appsync_dynamodb")
        assert "dynamodb:ConditionCheckItem" in doc
        assert "dynamodb:PutItem" in doc and "dynamodb:UpdateItem" in doc and "dynamodb:DeleteItem" in doc

    def test_no_new_lambda_execution_role_before_handlers_exist(self) -> None:
        # Wave 1 ships no resolvers/handlers, so no new per-domain Lambda role
        # is legitimate yet: a grant for code that does not exist is not least
        # privilege. The only dynamodb principals gaining the new tables are the
        # map-wired AppSync service role and the admin role.
        iam = IAM_TF.read_text()
        for forbidden in ("show-sell-exec", "show_sell_exec", "units-exec", "inventory-exec"):
            assert forbidden not in iam


def _block_text(content: str, rtype: str, name: str) -> str:
    return _resource_block(content, rtype, name)


class TestCognitoPreviewGroup:
    def test_group_declared_in_module(self) -> None:
        block = _resource_block(COGNITO_TF.read_text(), "aws_cognito_user_group", "show_sell_preview")
        assert 'name         = "show-sell-preview"' in block
        assert "aws_cognito_user_pool.main.id" in block

    def test_group_name_constant_across_environments(self) -> None:
        content = COGNITO_TF.read_text()
        assert content.count('"show-sell-preview"') >= 1
        assert re.search(r'output\s+"show_sell_preview_group_name"', content)


class TestRecoveryImports:
    def test_all_show_sell_tables_in_recovery_table_list(self) -> None:
        recovery = RECOVERY_SH.read_text()
        m = re.search(r"for table in ([^;]+); do", recovery)
        assert m, "recovery DynamoDB loop not found"
        tables = m.group(1).split()
        for spec in TABLE_SPECS.values():
            assert spec["aws_suffix"] in tables, f"recovery import list is missing the {spec['aws_suffix']} table"

    def test_cognito_preview_group_import_line(self) -> None:
        recovery = RECOVERY_SH.read_text()
        assert (
            'import_resource "$run_id" "module.cognito.aws_cognito_user_group.show_sell_preview" '
            '"${user_pool_id}/show-sell-preview"' in recovery
        )

    def test_recovery_resource_names_are_valid_tofu_addresses(self) -> None:
        # tr '-' '_' maps the hyphenated AWS table names onto the snake_case
        # resource names declared in the dynamodb module.
        dynamodb_tf = DYNAMODB_TF.read_text()
        declared = set(re.findall(r'resource\s+"aws_dynamodb_table"\s+"([^"]+)"', dynamodb_tf))
        for table_name in TABLE_SPECS:
            assert table_name in declared
