"""Contract tests for the public order WRITE path (#679 write slice).

The failure this slice closes was live on dev: ``publicCreateOrder`` existed in
the schema with ``PublicOrderReceipt!`` and had no resolver anywhere, so AppSync
answered ``Cannot return null for non-nullable type: 'PublicOrderReceipt'``.
These tests pin the wiring that makes that impossible to reintroduce:

- every ``@aws_api_key`` root field in the schema has a resolver;
- the ``publicCreateOrder`` pipeline exists, is a PIPELINE resolver, and lists
  its functions in the order the spec's §5.3 requires - most importantly the
  cap-gated increment BEFORE the order write, so a losing concurrent writer
  writes no order row;
- the reused ``get_catalog`` function appears once per pipeline (the duplicate
  function id rule, #438), and the two token steps are two resources;
- the receipt read is a direct UNIT resolver on the public-orders Lambda, not a
  pipeline.

Harness: python-hcl2 over the OpenTofu module (the pattern of
test_appsync_pipeline_functions.py / test_edge_security.py) plus a text read of
schema.graphql, which no Python GraphQL parser exists for.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_edge_security import TF_APP, load_hcl

APPSYNC_DIR = TF_APP / "modules" / "appsync"
SCHEMA = TF_APP / "schema" / "schema.graphql"
RESOLVER_FILES = ("resolvers_mutations.tf", "resolvers_queries.tf")

PUBLIC_ROOT_FIELDS = ("publicGetOrderOffer", "publicCreateOrder", "publicGetOrderReceipt")

# The spec §5.3 pipeline order. get_catalog is REUSED from the authenticated
# createOrder pipeline (it reads ctx.stash.catalogId, which the campaign step
# stashes), so it is the one function shared across pipelines here.
EXPECTED_PIPELINE = [
    "aws_appsync_function.validate_public_token",
    "aws_appsync_function.validate_public_token_step2",
    "aws_appsync_function.get_campaign_for_public_order",
    "aws_appsync_function.get_catalog",
    "aws_appsync_function.validate_payment_method_public",
    "aws_appsync_function.increment_public_order_count",
    "aws_appsync_function.create_public_order",
]


def _norm(value: object) -> str:
    """Decode a python-hcl2 scalar: strip its quote wrapper, ${...} wrapper, and
    the trailing ``.function_id`` of a function reference."""
    text = str(value)
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if text.startswith("${") and text.endswith("}"):
        text = text[2:-1]
    text = text.strip()
    return text[: -len(".function_id")] if text.endswith(".function_id") else text


def _resolvers() -> list[tuple[str, str, dict]]:
    out = []
    for filename in RESOLVER_FILES:
        doc = load_hcl(APPSYNC_DIR / filename)
        for resource in doc.get("resource", []):
            for name, attrs in resource.get("aws_appsync_resolver", {}).items():
                out.append((filename, name, attrs))
    return out


def _pipeline_functions(field: str) -> list[str]:
    for _, _, attrs in _resolvers():
        if _norm(attrs.get("field", "")) != field:
            continue
        functions: list[str] = []
        for cfg in attrs.get("pipeline_config", []):
            functions.extend(_norm(fn) for fn in cfg.get("functions", []))
        return functions
    raise AssertionError(f"no resolver declared for field {field}")


def _schema_public_root_fields() -> list[str]:
    """Root-field names carrying @aws_api_key, read from the schema text.

    Line-scanned rather than regex-spanned: the argument doc comments contain
    parentheses, and a lazy multi-line regex could satisfy one field by running
    into the NEXT field's directive. The scan stops at the next field
    declaration, so a field that lost its directive cannot borrow a neighbor's.
    """
    lines = SCHEMA.read_text(encoding="utf-8").splitlines()
    found: list[str] = []
    for index, line in enumerate(lines):
        match = re.match(r"^  (\w+)\(?", line)
        if not match or match.group(1) not in PUBLIC_ROOT_FIELDS:
            continue
        for following in lines[index + 1 : index + 20]:
            if re.match(r"^  \w+\(?", following):
                break
            if re.match(r"^  \):\s*\w+!\s*@aws_api_key\s*$", following):
                found.append(match.group(1))
                break
    return found


def test_every_public_root_field_has_a_resolver():
    """The exact regression this slice closes: a schema field with no resolver.

    A non-null field with no resolver does not fail the plan - it fails at
    query time with "Cannot return null for non-nullable type", which is what
    the buyer's submit hit on dev.
    """
    declared = _schema_public_root_fields()
    assert set(declared) == set(PUBLIC_ROOT_FIELDS), (
        f"schema no longer declares the three public root fields: {declared}"
    )

    resolved = {_norm(attrs.get("field", "")) for _, _, attrs in _resolvers()}
    missing = [field for field in PUBLIC_ROOT_FIELDS if field not in resolved]
    assert not missing, f"@aws_api_key root fields without a resolver: {missing}"


def test_public_create_order_pipeline_order():
    functions = _pipeline_functions("publicCreateOrder")

    assert functions == EXPECTED_PIPELINE, functions


def test_cap_increment_runs_before_the_order_write():
    """The bound lives in the increment's condition, so it must gate the write.

    Reordering these two would let a writer at the cap create an order row and
    only then fail the counter - the overshoot the spec's §5.3 step 6 exists to
    make impossible.
    """
    functions = _pipeline_functions("publicCreateOrder")

    assert functions.index("aws_appsync_function.increment_public_order_count") < functions.index(
        "aws_appsync_function.create_public_order"
    )


def test_token_authorization_is_two_distinct_functions():
    """A pipeline may list a function id only once (#438), so step 2 is its own resource."""
    functions = _pipeline_functions("publicCreateOrder")

    assert "aws_appsync_function.validate_public_token" in functions
    assert "aws_appsync_function.validate_public_token_step2" in functions
    assert len(functions) == len(set(functions)), functions


def test_public_create_order_resolver_is_a_pipeline_with_its_own_root_code():
    for _, _, attrs in _resolvers():
        if _norm(attrs.get("field", "")) == "publicCreateOrder":
            assert _norm(attrs.get("kind", "")) == "PIPELINE"
            assert "data_source" not in attrs, "a pipeline resolver must not bind a unit data_source"
            code = str(attrs["code"])
            assert "public_create_order_pipeline_resolver.js" in code
            return
    raise AssertionError("publicCreateOrder resolver missing")


def test_public_get_order_receipt_is_a_unit_resolver_on_the_public_orders_lambda():
    for _, _, attrs in _resolvers():
        if _norm(attrs.get("field", "")) == "publicGetOrderReceipt":
            assert _norm(attrs.get("kind", "UNIT")) == "UNIT"
            assert "public_orders" in str(attrs["data_source"])
            assert "lambda_unit_resolver.js" in str(attrs["code"])
            return
    raise AssertionError("publicGetOrderReceipt resolver missing")


def test_every_new_public_write_resolver_source_exists():
    """A typo in a file() path fails every tofu plan; catch it in CI instead."""
    sources = set()
    for filename in RESOLVER_FILES:
        text = (APPSYNC_DIR / filename).read_text(encoding="utf-8")
        sources.update(re.findall(r'file\("\$\{local\.js_resolvers_dir\}/([^"]+)"\)', text))
    for filename in ("functions_profiles.tf", "functions_campaigns.tf", "functions_orders.tf"):
        text = (APPSYNC_DIR / filename).read_text(encoding="utf-8")
        sources.update(re.findall(r'file\("\$\{local\.js_resolvers_dir\}/([^"]+)"\)', text))

    resolvers_dir = TF_APP / "appsync" / "js-resolvers"
    missing = [name for name in sorted(sources) if not (resolvers_dir / name).is_file()]
    assert not missing, f"resolver sources referenced but absent: {missing}"
    assert (resolvers_dir / "lib" / "public_order.js").is_file()
    assert Path(resolvers_dir, "increment_public_order_count_fn.test.js").is_file()
