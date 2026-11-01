"""Pipeline-order contract for the publicCreateOrder write path (#679).

The buyer-side half of the campaign-keyed public orders feature is a pure
APPSYNC_JS pipeline whose step order is load-bearing twice over:

- ``validate_payment_method_public`` must run BEFORE
  ``increment_public_order_count``. Step 5 rejects caller-input violations that
  are already decidable while the catalog is in hand (an unknown product id, a
  soft-deleted catalog) before issuing any datastore call, so a rejected order
  never reaches the cap's atomic ADD — otherwise such rejections silently burn
  the campaign's 500-order lifetime counter with no order row to show for it.
- ``increment_public_order_count`` must run BEFORE ``create_public_order`` and
  stay adjacent to it: the increment's ConditionExpression is the authoritative
  cap bound, and the pair is atomic-by-adjacency (the accepted overcount for a
  PutItem failure depends on this order).
- ``throttle_public_order_create`` (SEC-6) runs immediately after
  authorization and before the profile/catalog/payment reads, so a flooding
  token does no further work per request.
- ``get_profile_for_public_order_step2`` (SEC-4) must run AFTER
  ``get_profile_for_public_order`` and BEFORE ``validate_payment_method_public``
  and ``send_public_order_emails``: the owner id coming off the eventually
  consistent GSI locator is not trusted for the payment read or the mailer
  until the strongly consistent base-table read confirms it.

Parsed with python-hcl2 via the harness in test_public_settings_pipeline_wiring.py.
"""

from pathlib import Path

from tests.unit.test_public_settings_pipeline_wiring import MUTATION_RESOLVERS, _pipeline

APPSYNC_MODULE_DIR = Path(__file__).resolve().parents[2] / "tofu" / "application" / "modules" / "appsync"
FUNCTIONS_ORDERS = APPSYNC_MODULE_DIR / "functions_orders.tf"
CREATE_PUBLIC_ORDER_JS = APPSYNC_MODULE_DIR.parent.parent / "appsync" / "js-resolvers" / "create_public_order_fn.js"

TOKEN = "aws_appsync_function.validate_public_token"
TOKEN_STEP2 = "aws_appsync_function.validate_public_token_step2"
THROTTLE = "aws_appsync_function.throttle_public_order_create"
PROFILE = "aws_appsync_function.get_profile_for_public_order"
PROFILE_STEP2 = "aws_appsync_function.get_profile_for_public_order_step2"
CATALOG = "aws_appsync_function.get_catalog"
PAYMENT = "aws_appsync_function.validate_payment_method_public"
INCREMENT = "aws_appsync_function.increment_public_order_count"
WRITE = "aws_appsync_function.create_public_order"
EMAIL = "aws_appsync_function.send_public_order_emails"


def test_public_create_order_pipeline_order() -> None:
    pipeline = _pipeline(MUTATION_RESOLVERS, "public_create_order")
    assert pipeline == [
        TOKEN,
        TOKEN_STEP2,
        # SEC-6: the per-token fixed-window throttle gates everything after it.
        THROTTLE,
        # SEC-4: GSI locator, then the strong ownership confirmation; the owner
        # id is not trusted until PROFILE_STEP2.
        PROFILE,
        PROFILE_STEP2,
        CATALOG,
        PAYMENT,
        INCREMENT,
        WRITE,
        # The best-effort email step runs AFTER the order write: it must never
        # abort the committed order, and its own failure is swallowed by design.
        EMAIL,
    ], "publicCreateOrder's step order is the cap-burn contract; do not reorder"


def test_write_step_uses_real_table_names_via_templatefile() -> None:
    """The write is a TransactWriteItems spanning two tables, and each
    transact item's ``table`` field is the LITERAL AWS table name at runtime
    (AppSync does not default it to the datasource's table). Hardcoding the
    logical names 'Orders'/'Campaigns' there made the deployed pipeline target
    table/Orders and fail with AccessDenied, taking down every dependent
    integration test (receipt link split, updateOrder input coercion). This
    pins the real names to the injected ``var.dynamodb_table_names`` map."""
    tf = FUNCTIONS_ORDERS.read_text()
    block = tf.split('resource "aws_appsync_function" "create_public_order"', 1)[1]
    block = block.split("\n}", 1)[0]
    assert "templatefile(" in block, "create_public_order must be templatefile()'d, not file()"
    assert "orders_table_name" in block and "var.dynamodb_table_names.orders" in block
    assert "campaigns_table_name" in block and "var.dynamodb_table_names.campaigns" in block

    js = CREATE_PUBLIC_ORDER_JS.read_text()
    assert "table: ordersTableName" in js
    assert "table: campaignsTableName" in js
    assert "table: 'Orders'" not in js
    assert "table: 'Campaigns'" not in js


def test_throttle_runs_immediately_after_authorization() -> None:
    pipeline = _pipeline(MUTATION_RESOLVERS, "public_create_order")
    assert pipeline.index(THROTTLE) == pipeline.index(TOKEN_STEP2) + 1, (
        "the abuse throttle must gate the pipeline right after authorization, "
        "before any further reads do work for a flooding token"
    )


def test_ownership_confirmation_precedes_payment_and_email() -> None:
    pipeline = _pipeline(MUTATION_RESOLVERS, "public_create_order")
    assert pipeline.index(PROFILE) + 1 == pipeline.index(PROFILE_STEP2), (
        "the strong ownership read must directly follow the GSI locator (#438 pair)"
    )
    assert pipeline.index(PROFILE_STEP2) < pipeline.index(PAYMENT), (
        "buyer PII must not reach a stale owner id: the base-table confirmation must precede the payment-method read"
    )
    assert pipeline.index(PROFILE_STEP2) < pipeline.index(EMAIL), "the mailer must only ever see a confirmed owner id"


def test_payment_validation_precedes_the_cap_increment() -> None:
    pipeline = _pipeline(MUTATION_RESOLVERS, "public_create_order")
    assert pipeline.index(PAYMENT) < pipeline.index(INCREMENT), (
        "a caller-input rejection (unknown product id, soft-deleted catalog) must be "
        "decided BEFORE the cap's atomic ADD or rejected orders burn the lifetime cap"
    )


def test_cap_increment_precedes_the_order_write() -> None:
    pipeline = _pipeline(MUTATION_RESOLVERS, "public_create_order")
    assert pipeline.index(INCREMENT) < pipeline.index(WRITE), (
        "the increment's ConditionExpression is the authoritative cap bound and must gate the PutItem, not trail it"
    )
