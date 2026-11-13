"""Contract tests for the Show & Sell wave-1 storage layer.

Pins the five new DynamoDB tables (units, unit_campaigns, inventory,
order_fulfillments, show_and_sells) and the show-sell-preview Cognito group to
the key/index/TTL contracts in docs/specs/show_sell/SHOW_AND_SELL_DATA_MODEL.md §6,
the IAM grants that make transactional AppSync access least-privilege in every
environment, the individual table-name outputs that are the documented
downstream wiring interface, and the recovery-import coverage for the tables
and the group.

Structural assertions parse the OpenTofu configuration semantically
(python-hcl2, the pattern established by test_iam_appsync_dynamodb_policy.py);
raw-source string checks are used only for the human-readable key-namespace
documentation, which lives in comments.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import hcl2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMODB_TF = REPO_ROOT / "tofu" / "application" / "modules" / "dynamodb" / "main.tf"
COGNITO_TF = REPO_ROOT / "tofu" / "application" / "modules" / "cognito" / "main.tf"
IAM_TF = REPO_ROOT / "tofu" / "application" / "modules" / "iam" / "main.tf"
RECOVERY_SH = REPO_ROOT / "scripts" / "ephemeral-recover-common.sh"
ENVIRONMENTS = ("dev", "ephemeral", "prod")

SHOW_SELL_TABLES = ("units", "unit_campaigns", "inventory", "order_fulfillments", "show_and_sells")

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


def _norm(value):
    """Strip the quote wrapper python-hcl2 adds around keys and strings."""
    if isinstance(value, dict):
        return {_norm(k): _norm(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _load(path: Path) -> dict:
    with path.open() as f:
        return _norm(hcl2.load(f))


def _resources(doc: dict, rtype: str) -> dict[str, dict]:
    """Merge every `resource "<rtype>" "<name>"` block into name -> body."""
    merged: dict[str, dict] = {}
    for block in doc.get("resource", []):
        if rtype in block:
            merged.update(block[rtype])
    return merged


def _outputs(doc: dict) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for block in doc.get("output", []):
        merged.update(block)
    return merged


def _table_sections(content: str) -> dict[str, str]:
    """Raw text section per table: the banner comment immediately preceding the
    resource up to (but excluding) the next table's banner — so one table's
    documentation can never satisfy another table's assertion."""
    starts = [m for m in re.finditer(r'resource\s+"aws_dynamodb_table"\s+"([^"]+)"', content)]
    banners = [m.start() for m in re.finditer(r"# =+\n", content)]
    sections: dict[str, str] = {}
    for i, m in enumerate(starts):
        preceding = [b for b in banners if b < m.start()]
        open_fence = preceding[-2] if len(preceding) >= 2 else preceding[-1]
        # The section runs from this table's opening comment fence to the next
        # table's opening fence, so one table's documentation can never satisfy
        # another table's assertion.
        following = [b for b in banners if b > m.start()]
        stop = following[0] if following else len(content)
        sections[m.group(1)] = content[open_fence:stop]
    return sections


@pytest.fixture(scope="module")
def dynamodb_doc() -> dict:
    return _load(DYNAMODB_TF)


@pytest.fixture(scope="module")
def dynamodb_tables(dynamodb_doc: dict) -> dict[str, dict]:
    return _resources(dynamodb_doc, "aws_dynamodb_table")


class TestShowSellTables:
    """Table-for-table key/index/TTL contract from SHOW_AND_SELL_DATA_MODEL.md §6."""

    @pytest.mark.parametrize("table_name", SHOW_SELL_TABLES)
    def test_table_declared_with_prefixed_composite_key(self, dynamodb_tables: dict, table_name: str) -> None:
        spec = TABLE_SPECS[table_name]
        table = dynamodb_tables[table_name]
        assert table["name"] == f"${{var.name_prefix}}-{spec['aws_suffix']}${{local.table_suffix}}"
        assert table["hash_key"] == "pk"
        assert table["range_key"] == "sk"
        assert table["billing_mode"] == "PAY_PER_REQUEST"
        assert table["deletion_protection_enabled"] == "${var.enable_deletion_protection}"
        assert table["lifecycle"][0]["prevent_destroy"] == "${var.prevent_destroy}"

    @pytest.mark.parametrize("table_name", SHOW_SELL_TABLES)
    def test_gsi_layout_matches_the_data_model(self, dynamodb_tables: dict, table_name: str) -> None:
        spec = TABLE_SPECS[table_name]
        table = dynamodb_tables[table_name]
        gsi_list = table.get("global_secondary_index", [])
        assert sorted(g["name"] for g in gsi_list) == sorted(spec["indexes"])
        for gsi in gsi_list:
            assert gsi["projection_type"] == "ALL", f"{table_name}.{gsi['name']} must project ALL"
            keys = {k["attribute_name"]: k["key_type"] for k in gsi["key_schema"]}
            assert keys == spec["indexes"][gsi["name"]], f"{table_name}.{gsi['name']} key schema drift"

    @pytest.mark.parametrize("table_name", SHOW_SELL_TABLES)
    def test_attribute_definitions_match_index_keys(self, dynamodb_tables: dict, table_name: str) -> None:
        spec = TABLE_SPECS[table_name]
        table = dynamodb_tables[table_name]
        attrs = {a["name"] for a in table.get("attribute", [])}
        # All Show & Sell key attributes are String type; the set must be exactly
        # the key attributes the data model names (no unused definitions).
        assert attrs == spec["attributes"], f"{table_name}: attribute set drift: {sorted(attrs)}"
        assert all(a["type"] == "S" for a in table.get("attribute", []))

    @pytest.mark.parametrize("table_name", SHOW_SELL_TABLES)
    def test_pitr_and_no_kms(self, dynamodb_tables: dict, table_name: str) -> None:
        table = dynamodb_tables[table_name]
        assert table["point_in_time_recovery"][0]["enabled"] == "${var.enable_point_in_time_recovery}"
        assert table["server_side_encryption"][0]["enabled"] is False

    @pytest.mark.parametrize("table_name", SHOW_SELL_TABLES)
    def test_marker_ttl_on_expires_at_epoch(self, dynamodb_tables: dict, table_name: str) -> None:
        # One shared numeric epoch-seconds TTL attribute across every aggregate
        # table (SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md §4.1/§4.4: seven
        # days for idempotency markers; the units table also carries UnitInvite
        # rows on the same attribute with a longer, application-set horizon).
        table = dynamodb_tables[table_name]
        (ttl,) = table["ttl"]
        assert ttl["attribute_name"] == "expiresAtEpoch"
        assert ttl["enabled"] is True


class TestKeyNamespaceDocumentation:
    """The prefixed-SK item families are a code-visible contract: each table's
    banner comment records them, and these raw-source checks pin that record
    (comments are not representable in the HCL parse)."""

    @pytest.fixture(scope="module")
    def sections(self) -> dict[str, str]:
        return _table_sections(DYNAMODB_TF.read_text())

    def test_units_documents_invite_and_marker_layout(self, sections: dict[str, str]) -> None:
        s = sections["units"]
        for contract in ("UNIT#<unitId>", "METADATA", "GRANT#<accountId>", "INVITE#<inviteCode>"):
            assert contract in s, f"units key contract {contract} undocumented"
        assert "14 days" in s and "7 days" in s, "invite vs marker TTL horizons undocumented"

    def test_unit_campaigns_documents_guard_and_pointer_layout(self, sections: dict[str, str]) -> None:
        s = sections["unit_campaigns"]
        for contract in ("JOIN_CODE#<joinCode>", "MEMBERSHIP#<profileId>", "MEMBERSHIP_GUARD", "COMMITMENT_GUARD"):
            assert contract in s, f"unit_campaigns key contract {contract} undocumented"

    def test_inventory_documents_product_prefix_layout(self, sections: dict[str, str]) -> None:
        s = sections["inventory"]
        for contract in ("BALANCE", "EVENT#<showAndSellId>", "CUSTODY#<profileId>", "MOVEMENT#<occurredAt>"):
            assert contract in s, f"inventory SK contract {contract} undocumented"

    def test_order_fulfillments_documents_at_most_once_reversal_key(self, sections: dict[str, str]) -> None:
        # §5.19: deterministic SK REVERSAL#<reversalOfFulfillmentId> bounds any
        # fulfillment to one reversal; the schema cannot express the prefix.
        assert "REVERSAL#<reversalOfFulfillmentId>" in sections["order_fulfillments"]

    def test_show_and_sells_documents_future_namespaces(self, sections: dict[str, str]) -> None:
        # §3.6.1: metadata/slot/signup keys plus the future sale/finalization/
        # We Owe namespaces are declared now so later waves never migrate keys.
        s = sections["show_and_sells"]
        for contract in (
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
            assert contract in s, f"show_and_sells SK namespace {contract} undocumented"

    def test_sections_do_not_bleed_into_the_next_table(self, sections: dict[str, str]) -> None:
        # A table's section must stop at its own resource declaration boundary,
        # so a contract string can only be satisfied by that table's own banner.
        for table_name, section in sections.items():
            for other in SHOW_SELL_TABLES:
                if other == table_name:
                    continue
                assert f'resource "aws_dynamodb_table" "{other}"' not in section, (
                    f"{table_name} section bleeds into the {other} declaration"
                )


class TestTableOutputs:
    """Individual table-name outputs are the documented downstream interface
    (SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md §4.1) alongside the maps."""

    def test_maps_include_every_show_sell_table(self, dynamodb_doc: dict) -> None:
        outs = _outputs(dynamodb_doc)
        for table_name in SHOW_SELL_TABLES:
            assert outs["table_arns"]["value"][table_name] == f"${{aws_dynamodb_table.{table_name}.arn}}"
            assert outs["table_names"]["value"][table_name] == f"${{aws_dynamodb_table.{table_name}.name}}"

    @pytest.mark.parametrize("table_name", SHOW_SELL_TABLES)
    def test_individual_table_name_output(self, dynamodb_doc: dict, table_name: str) -> None:
        outs = _outputs(dynamodb_doc)
        out = outs[f"{table_name}_table_name"]
        assert out["value"] == f"${{aws_dynamodb_table.{table_name}.name}}"


class TestIAMWiring:
    """Least-privilege grants: the new tables flow through the per-environment
    table_arns map into the AppSync service role and admin-role documents —
    table/index ARNs only, never account wildcards — and the AppSync direct
    path is actually authorized for TransactWriteItems (§8 transaction
    boundaries; SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md §4.2 IAM notes:
    ConditionCheckItem is not permission to invoke TransactWriteItems)."""

    def test_appsync_dynamodb_policy_exact_actions_include_transact_write(self) -> None:
        doc = _load(IAM_TF)
        actions = _appsync_actions(doc)
        assert sorted(actions) == sorted(EXPECTED_APPSYNC_ACTIONS)
        assert "dynamodb:TransactWriteItems" in actions
        assert "dynamodb:ConditionCheckItem" in actions
        assert "dynamodb:Scan" not in actions
        assert not any(a.endswith(":*") for a in actions)

    def test_appsync_dynamodb_policy_scoped_to_tables_and_indexes(self) -> None:
        doc = _load(IAM_TF)
        (statement,) = _appsync_statement(doc)
        raw = statement["resources"]
        raw = raw if isinstance(raw, list) else [raw]
        resources = [r[2:-1] if isinstance(r, str) and r.startswith("${") and r.endswith("}") else r for r in raw]
        assert resources == ["concat(local.dynamodb_table_arns, local.dynamodb_index_arns)"]

    def test_no_wildcard_dynamodb_grants_anywhere(self) -> None:
        assert "dynamodb:*" not in IAM_TF.read_text()

    @pytest.mark.parametrize("env", ENVIRONMENTS)
    def test_environment_wires_table_arns_into_iam(self, env: str) -> None:
        content = (REPO_ROOT / "tofu" / "application" / "environments" / env / "main.tf").read_text()
        assert re.search(r"dynamodb_table_arns\s*=\s*module\.dynamodb\.table_arns", content), (
            f"{env}: IAM module must receive module.dynamodb.table_arns so the new tables are granted"
        )

    def test_no_new_lambda_execution_role_before_handlers_exist(self) -> None:
        # Wave 1 ships no resolvers/handlers, so no new per-domain Lambda role
        # is legitimate yet: a grant for code that does not exist is not least
        # privilege. The only dynamodb principals gaining the new tables are the
        # map-wired AppSync service role and the admin role.
        iam = IAM_TF.read_text()
        for forbidden in ("show-sell-exec", "show_sell_exec", "units-exec", "inventory-exec"):
            assert forbidden not in iam


EXPECTED_APPSYNC_ACTIONS = [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:ConditionCheckItem",
    "dynamodb:TransactWriteItems",
    "dynamodb:Query",
    "dynamodb:BatchGetItem",
    "dynamodb:BatchWriteItem",
]


def _appsync_data_documents(doc: dict) -> dict:
    merged: dict[str, dict] = {}
    for block in doc.get("data", []):
        if "aws_iam_policy_document" in block:
            merged.update(block["aws_iam_policy_document"])
    return merged["appsync_dynamodb"]


def _appsync_statement(doc: dict) -> list[dict]:
    return _appsync_data_documents(doc)["statement"]


def _appsync_actions(doc: dict) -> list[str]:
    (statement,) = _appsync_statement(doc)
    return statement["actions"]


class TestCognitoPreviewGroup:
    def test_group_declared_with_exact_name_on_the_main_pool(self) -> None:
        doc = _load(COGNITO_TF)
        group = _resources(doc, "aws_cognito_user_group")["show_sell_preview"]
        assert group["name"] == "show-sell-preview"
        assert group["user_pool_id"] == "${aws_cognito_user_pool.main.id}"
        assert group["lifecycle"][0]["prevent_destroy"] == "${var.prevent_destroy}"

    def test_group_name_output(self) -> None:
        doc = _load(COGNITO_TF)
        out = _outputs(doc)["show_sell_preview_group_name"]
        assert out["value"] == "${aws_cognito_user_group.show_sell_preview.name}"

    def test_group_name_constant_across_environments(self) -> None:
        # The literal group name carries no environment interpolation: every
        # environment's pool gets the same group name.
        doc = _load(COGNITO_TF)
        group = _resources(doc, "aws_cognito_user_group")["show_sell_preview"]
        assert "${" not in group["name"]


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
