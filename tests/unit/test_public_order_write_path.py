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

Parsed with python-hcl2 via the harness in test_public_settings_pipeline_wiring.py.
"""

from tests.unit.test_public_settings_pipeline_wiring import MUTATION_RESOLVERS, _pipeline

TOKEN = "aws_appsync_function.validate_public_token"
TOKEN_STEP2 = "aws_appsync_function.validate_public_token_step2"
PROFILE = "aws_appsync_function.get_profile_for_public_order"
CATALOG = "aws_appsync_function.get_catalog"
PAYMENT = "aws_appsync_function.validate_payment_method_public"
INCREMENT = "aws_appsync_function.increment_public_order_count"
WRITE = "aws_appsync_function.create_public_order"


def test_public_create_order_pipeline_order() -> None:
    pipeline = _pipeline(MUTATION_RESOLVERS, "public_create_order")
    assert pipeline == [
        TOKEN,
        TOKEN_STEP2,
        PROFILE,
        CATALOG,
        PAYMENT,
        INCREMENT,
        WRITE,
    ], "publicCreateOrder's step order is the cap-burn contract; do not reorder"


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
