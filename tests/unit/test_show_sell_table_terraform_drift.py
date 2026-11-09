"""
Terraform drift guard for the five Show & Sell tables (wave 1).

Pins tests/unit/table_schemas.py (what the tests build) and the
environment/lambda env maps to tofu/application/modules/dynamodb/main.tf
(what deploys). A change to either side without the other fails here
instead of at deploy time or, worse, silently testing the wrong shape
(integration plan section 5 step 5; the clean-room GSI-drift lesson).

The parser is deliberately narrow: it reads only the machine-formatted
dynamodb module's resource blocks (hash/range keys, attribute names, GSI
names, TTL attribute), which is the full contract the handlers rely on.
"""

import re
from pathlib import Path
from typing import Any, Dict, Set

from tests.unit.table_schemas import (
    TABLE_NAMES,
    create_inventory_table_schema,
    create_order_fulfillments_table_schema,
    create_show_and_sells_table_schema,
    create_unit_campaigns_table_schema,
    create_units_table_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMODB_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "dynamodb" / "main.tf"
LAMBDA_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "lambda" / "main.tf"
ENVIRONMENTS = [
    REPO_ROOT / "tofu" / "application" / "environments" / env / "main.tf" for env in ("dev", "prod", "ephemeral")
]

# table slug -> (terraform resource name, test schema builder)
SHOW_AND_SELL_TABLES: Dict[str, Any] = {
    "units": create_units_table_schema,
    "unit_campaigns": create_unit_campaigns_table_schema,
    "inventory": create_inventory_table_schema,
    "show_and_sells": create_show_and_sells_table_schema,
    "order_fulfillments": create_order_fulfillments_table_schema,
}

ENV_VAR_BY_SLUG = {
    "units": "UNITS_TABLE_NAME",
    "unit_campaigns": "UNIT_CAMPAIGNS_TABLE_NAME",
    "inventory": "INVENTORY_TABLE_NAME",
    "show_and_sells": "SHOW_AND_SELLS_TABLE_NAME",
    "order_fulfillments": "ORDER_FULFILLMENTS_TABLE_NAME",
    "public_order_throttles": "PUBLIC_ORDER_THROTTLES_TABLE_NAME",
}


def _extract_resource_block(tf_source: str, resource_name: str) -> str:
    """Return the body of one aws_dynamodb_table resource block."""
    marker = f'resource "aws_dynamodb_table" "{resource_name}" {{'
    start = tf_source.find(marker)
    assert start != -1, f"resource {resource_name} not found in dynamodb module"
    depth = 0
    for index in range(start + len(marker) - 1, len(tf_source)):
        char = tf_source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return tf_source[start : index + 1]
    raise AssertionError(f"unbalanced braces in resource {resource_name}")


def _scalar(block: str, field: str) -> str:
    match = re.search(rf'^\s*{field}\s*=\s*"([^"]+)"', block, re.MULTILINE)
    assert match, f"field {field} not found"
    return match.group(1)


def _optional_scalar(block: str, field: str) -> Any:
    match = re.search(rf'^\s*{field}\s*=\s*"([^"]+)"', block, re.MULTILINE)
    return match.group(1) if match else None


def _attribute_names(block: str) -> Set[str]:
    return set(re.findall(r'attribute\s*\{\s*name\s*=\s*"([^"]+)"', block))


def _gsi_names(block: str) -> Set[str]:
    return set(re.findall(r'global_secondary_index\s*\{\s*name\s*=\s*"([^"]+)"', block))


def _schema_hash_key(schema: Dict[str, Any]) -> str:
    return next(k["AttributeName"] for k in schema["KeySchema"] if k["KeyType"] == "HASH")


def _schema_range_key(schema: Dict[str, Any]) -> Any:
    ranges = [k["AttributeName"] for k in schema["KeySchema"] if k["KeyType"] == "RANGE"]
    return ranges[0] if ranges else None


class TestTerraformMatchesTestSchemas:
    def test_all_five_tables_exist_in_terraform(self) -> None:
        source = DYNAMODB_MODULE.read_text()
        for slug in SHOW_AND_SELL_TABLES:
            assert f'resource "aws_dynamodb_table" "{slug}"' in source, f"{slug} missing from dynamodb module"

    def test_base_keys_match(self) -> None:
        source = DYNAMODB_MODULE.read_text()
        for slug, builder in SHOW_AND_SELL_TABLES.items():
            block = _extract_resource_block(source, slug)
            schema = builder()
            assert _scalar(block, "hash_key") == _schema_hash_key(schema), f"{slug} hash key drift"
            assert _optional_scalar(block, "range_key") == _schema_range_key(schema), f"{slug} range key drift"

    def test_table_names_match(self) -> None:
        source = DYNAMODB_MODULE.read_text()
        for slug in SHOW_AND_SELL_TABLES:
            block = _extract_resource_block(source, slug)
            # Terraform builds names as ${name_prefix}-<kebab>${local.table_suffix};
            # the test schema pins the concrete dev name.
            kebab = slug.replace("_", "-")
            tf_name = _scalar(block, "name")
            assert kebab in tf_name, f"{slug}: terraform name {tf_name} does not contain {kebab}"
            assert TABLE_NAMES[slug] == f"kernelworx-{kebab}-ue1-dev", f"{slug}: TABLE_NAMES drift"

    def test_gsi_sets_match(self) -> None:
        source = DYNAMODB_MODULE.read_text()
        for slug, builder in SHOW_AND_SELL_TABLES.items():
            block = _extract_resource_block(source, slug)
            schema = builder()
            expected = {g["IndexName"] for g in schema["GlobalSecondaryIndexes"]}
            assert _gsi_names(block) == expected, f"{slug} GSI drift: tf={_gsi_names(block)} test={expected}"

    def test_key_attributes_declared(self) -> None:
        source = DYNAMODB_MODULE.read_text()
        for slug, builder in SHOW_AND_SELL_TABLES.items():
            block = _extract_resource_block(source, slug)
            schema = builder()
            declared = _attribute_names(block)
            key_attributes = {k["AttributeName"] for k in schema["KeySchema"]}
            for gsi in schema["GlobalSecondaryIndexes"]:
                key_attributes |= {k["AttributeName"] for k in gsi["KeySchema"]}
            assert key_attributes <= declared, f"{slug}: undeclared key attributes {key_attributes - declared}"

    def test_ttl_attribute_is_expires_at_epoch(self) -> None:
        source = DYNAMODB_MODULE.read_text()
        for slug in SHOW_AND_SELL_TABLES:
            block = _extract_resource_block(source, slug)
            assert "ttl {" in block, f"{slug}: no ttl block"
            assert 'attribute_name = "expiresAtEpoch"' in block, f"{slug}: ttl attribute drift"


class TestEnvironmentMapsCoverTheFiveTables:
    def test_all_environments_name_the_five_tables(self) -> None:
        for env_file in ENVIRONMENTS:
            source = env_file.read_text()
            for slug in SHOW_AND_SELL_TABLES:
                pattern = rf"^\s*{re.escape(slug)}\s*=\s*module\.dynamodb\.{re.escape(slug)}_table_name"
                assert re.search(pattern, source, re.MULTILINE), f"{env_file}: table_names entry missing for {slug}"

    def test_lambda_common_env_exports_the_five_names(self) -> None:
        source = LAMBDA_MODULE.read_text()
        for slug, env_var in ENV_VAR_BY_SLUG.items():
            pattern = rf"^\s*{re.escape(env_var)}\s*=\s*var\.table_names\.{re.escape(slug)}\b"
            assert re.search(pattern, source, re.MULTILINE), f"lambda common_env missing {env_var}"
