"""Deployed wiring for the Unit tenant Lambda (Wave 2 §1.7 / SCOPE-1).

The Stage 1 SDL declares 19 Unit/Unit Campaign operations and the handler
(``src/handlers/unit_operations.py``) routes exactly those field names -- but a
resolver that exists only in schema and source answers nothing on
``dev.kernelworx.app``. This file pins the deployed path end to end, because
every link is one a plausible-looking wiring pass drops:

- the Lambda function itself, with the handler entry point and an env var for
  every table its ``TableAccessor`` reads. Not just the two Unit aggregate
  tables: the §6.6 invite-redemption counter lives on the shared
  ``public_order_throttles`` table, and a table the handler reaches without a
  deployed ``<TABLE>_TABLE_NAME`` fails at the accessor's
  ``get_required_env`` — the domain answer (``NOT_FOUND`` for an unusable
  invite) is replaced by ``INTERNAL_ERROR`` and the throttle stops counting.
  The unit suite cannot see that hole because ``conftest`` injects every table
  name into the test process; QA found it live on ``dev`` at ``2f457c5e``. So
  the env pin below is derived from the handler's own table closure, and the
  role grant and the three environments' ``table_names`` maps are checked
  against the same closure — env var, IAM grant and plan-time wiring are one
  chain, and a missing link at any of the three makes the table unreachable;
- a scoped execution role (the #326 domain-role split: no function falls back
  to a broad role, and the Unit role's only write outside its own tables is the
  §8.2 join link on the legacy campaigns table -- named, not implied);
- the AppSync AWS_LAMBDA data source;
- a resolver for every Unit-tenant SDL field, all bound to that one data
  source, so tenant isolation stays in the single handler that enforces it.

Parsed with python-hcl2 through the harness in ``test_edge_security.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_edge_security import TF_APP, block, load_hcl
from tests.unit.test_lambda_table_env_closure import SRC, closure_table_keys, workload_env

MODULES = TF_APP / "modules"
ENVIRONMENTS = TF_APP / "environments"
UNIT_HANDLER = SRC / "handlers" / "unit_operations.py"

LAMBDA_MODULE = MODULES / "lambda" / "main.tf"
IAM_MODULE = MODULES / "iam" / "main.tf"
APPSYNC_DIR = MODULES / "appsync"

QUERY_FIELDS = {
    "myUnits",
    "unit",
    "unitAdmins",
    "unitInvites",
    "unitCampaignJoinInfo",
    "unitCampaign",
    "unitCampaignCatalog",
    "unitCampaigns",
    "unitCampaignRoster",
    "inventoryPositions",
    "inventoryMovements",
    "scoutCustodyBalances",
    "myScoutCustody",
    "orderFulfillments",
    "unitScoutCampaignOrders",
    "showAndSell",
    "showAndSells",
    "unitCampaignOpportunities",
    "showAndSellOpportunity",
    "eventInventoryAllocations",
    "showAndSellSignups",
    "myScoutCommitments",
    "showAndSellSignupCalendarData",
    "weOweObligation",
    "weOweObligations",
    "showAndSellSales",
    "showAndSellFinalizationPreview",
    "showAndSellFinalizations",
    "showAndSellFinalization",
    "showAndSellFinalizationSaleSnapshots",
    "showAndSellFinalizationWorkSnapshots",
    "showAndSellFinalizationReturnLines",
    "showAndSellFinalizationCredits",
    "unitPaymentMethods",
    "unitPaymentMethodQrDownloadUrl",
}
MUTATION_FIELDS = {
    "createUnit",
    "updateUnit",
    "createUnitInvite",
    "revokeUnitInvite",
    "redeemUnitInvite",
    "revokeUnitAccessGrant",
    "createUnitCampaign",
    "updateUnitCampaign",
    "joinUnitCampaign",
    "removeUnitCampaignMembership",
    "recordInventoryReceipt",
    "adjustInventory",
    "adjustCouncilOnOrder",
    "issueStockToScout",
    "returnStockFromScout",
    "fulfillIndividualOrderLine",
    "reverseIndividualOrderFulfillment",
    "createShowAndSell",
    "updateShowAndSell",
    "updateShowAndSellRoundingDraft",
    "finalizeShowAndSell",
    "cancelShowAndSell",
    "assignShowAndSellInventory",
    "upsertShowAndSellSlot",
    "deleteShowAndSellSlot",
    "signupScoutForShowAndSellSlot",
    "cancelShowAndSellSignup",
    "confirmShowAndSellWork",
    "createShowAndSellSale",
    "correctShowAndSellSale",
    "voidShowAndSellSale",
    "setWeOweReservation",
    "fulfillWeOwe",
    "createUnitPaymentMethod",
    "updateUnitPaymentMethod",
    "deactivateUnitPaymentMethod",
    "requestUnitPaymentMethodQrUpload",
    "confirmUnitPaymentMethodQrUpload",
    "deleteUnitPaymentMethodQrCode",
}


def _hcl(path: Path) -> dict:
    return load_hcl(path)


_ARN_KEYS = re.compile(r'dynamodb_table_arns\["([a-z_]+)"\]')
_FOR_KEYS = re.compile(r"for k in \[([^\]]*)\]")


def _table_keys(statement: dict) -> set[str]:
    """The ``dynamodb_table_arns`` keys one policy statement's resources name.

    Both spellings in this policy: the direct ``arns["units"]`` lookup and the
    ``for k in [...]`` comprehension the read statement builds.
    """
    text = str(statement["resources"]).replace("\\", "")
    keys = set(_ARN_KEYS.findall(text))
    for group in _FOR_KEYS.findall(text):
        keys |= {item.strip().strip('"') for item in group.split(",") if item.strip()}
    return keys


def _resource(doc: dict, rtype: str, name: str, section: str = "resource") -> dict:
    """The body of one named resource (or data source), or a loud failure."""
    for entry in doc.get(section, []):
        for rtype_key, bodies in entry.items():
            if rtype_key != rtype:
                continue
            if isinstance(bodies, dict) and name in bodies:
                return bodies[name]
    raise AssertionError(f"{section}.{rtype}.{name} is not declared")


def _function_configs() -> dict:
    """The lambda module's `functions` locals map, as a raw dict."""
    doc = _hcl(LAMBDA_MODULE)
    for local_block in doc.get("locals", []):
        if "functions" in local_block:
            return local_block["functions"]
    raise AssertionError("the lambda module declares no `functions` locals map")


def _lambda_body() -> dict:
    return _resource(_hcl(LAMBDA_MODULE), "aws_lambda_function", "functions")


def _resolver_docs() -> list[dict]:
    return [_hcl(APPSYNC_DIR / "resolvers_queries.tf"), _hcl(APPSYNC_DIR / "resolvers_mutations.tf")]


def test_unit_operations_lambda_declares_the_handler_and_table_env() -> None:
    functions = _function_configs()
    assert "unit-operations" in functions, (
        "the 19 Unit operations have no Lambda: the SDL and the handler exist, but nothing deploys them to dev"
    )
    config = block(functions["unit-operations"])
    assert "handlers.unit_operations.handle_unit_operation" in str(config["handler"]), (
        "the deployed entry point must be the routed handler, not a raw resolver"
    )
    extra_env = block(config["extra_env"])
    assert "UNITS_TABLE_NAME" in extra_env and "units" in str(extra_env["UNITS_TABLE_NAME"]), (
        "the TableAccessor reads <TABLE>_TABLE_NAME from the environment"
    )
    assert "UNIT_CAMPAIGNS_TABLE_NAME" in extra_env and "unit_campaigns" in str(
        extra_env["UNIT_CAMPAIGNS_TABLE_NAME"]
    ), "the Unit Campaign aggregate table must be in the environment too"


def test_unit_operations_env_names_every_table_its_closure_reaches() -> None:
    """An env var for each table the Unit handler can ask the accessor for.

    ``TableAccessor._get_table`` calls ``get_required_env("<TABLE>_TABLE_NAME")``, so
    an un-wired table is not a degraded feature: it raises inside the request, the
    generic decorator answers ``INTERNAL_ERROR``, and on ``redeemUnitInvite`` that
    replaced the documented ``NOT_FOUND`` for every unusable code while the §6.6
    counter stopped counting (QA, ``2f457c5e``). The closure derivation itself lives
    in ``test_lambda_table_env_closure.py``, which applies the same rule to every
    deployed Lambda and to the environments' ``table_names`` maps; this pin stays
    because it names the contract Stage 1 broke.
    """
    env = workload_env("unit-operations")
    for key in sorted(closure_table_keys(UNIT_HANDLER)):
        var = f"{key.upper()}_TABLE_NAME"
        assert var in env, (
            f"the unit-operations closure reads tables.{key}, but the deployed Lambda carries no {var}: "
            "get_required_env raises and the caller is answered INTERNAL_ERROR"
        )
        assert f"table_names.{key}" in env[var], f"{var} must come from var.table_names.{key}, not a literal name"


def test_unit_tenant_role_grants_every_table_the_closure_reaches() -> None:
    """The last link: an env var the role cannot use is still an unreachable table.

    moto never evaluates IAM, so a table the handler reads and the role omits shows
    up only as ``AccessDeniedException`` on ``dev`` — the same failure shape as the
    missing env var this file's other pins catch.
    """
    policy = _resource(_hcl(IAM_MODULE), "aws_iam_policy_document", "lambda_unit_tenant_dynamodb", section="data")
    granted: set[str] = set()
    for statement in [block(s) for s in policy["statement"]]:
        granted |= _table_keys(statement)
    missing = closure_table_keys(UNIT_HANDLER) - granted
    assert not missing, f"the unit-tenant role grants no access to {sorted(missing)}, which the handler reads"


def test_every_environment_assigns_the_scoped_unit_tenant_role() -> None:
    for env in ("dev", "prod", "ephemeral"):
        doc = _hcl(ENVIRONMENTS / env / "main.tf")
        for entry in doc.get("module", []):
            for name, bodies in entry.items():
                if name != "lambda":
                    continue
                body = block(bodies)
                roles = body["lambda_domain_role_arns"]
                assert "unit-operations" in roles, f"{env}: unit-operations has no execution role entry"
                assert "lambda_unit_tenant_execution_role_arn" in str(roles["unit-operations"]), (
                    f"{env}: unit-operations must run on the scoped unit-tenant role (#326 split)"
                )
                table_names = body["table_names"]
                assert "units" in table_names and "unit_campaigns" in table_names, (
                    f"{env}: the lambda module cannot inject table env it was not given"
                )


def test_unit_tenant_role_writes_the_unit_tables_and_the_join_link_only() -> None:
    """The write surface is the two aggregate tables, the counter, and one link.

    The §8.2 join writes the Scout Campaign's joined-scope link on the legacy
    ``campaigns`` table in the same transaction as the membership and the guard,
    so the role must grant that one write — a join without it cancels with
    ``AccessDeniedException`` against real DynamoDB, which moto never shows.
    ``test_unit_tenant_role_scope.py`` proves the grant matches what the handler
    actually issues; this test proves nothing else is writable.
    """
    doc = _hcl(IAM_MODULE)
    _resource(doc, "aws_iam_role", "lambda_unit_tenant_execution")
    policy = _resource(doc, "aws_iam_policy_document", "lambda_unit_tenant_dynamodb", section="data")
    statements = [block(s) for s in policy["statement"]]

    write_actions = {"dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"}
    writable: set[str] = set()
    for statement in statements:
        if not write_actions & set(statement["actions"]):
            continue
        keys = _table_keys(statement)
        writable |= keys
        assert keys <= {
            "units",
            "unit_campaigns",
            "inventory",
            "public_order_throttles",
            "campaigns",
            "order_fulfillments",
            "orders",
            "show_and_sells",
        }, (
            f"write actions outside the Unit tables, the inventory, fulfillment and event tables, the counter and the links: {keys}"
        )
        if "orders" in keys and "order_fulfillments" not in keys:
            assert set(statement["actions"]) <= {
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:UpdateItem",
                "dynamodb:ConditionCheckItem",
                "dynamodb:TransactWriteItems",
            }, (
                "a fulfillment moves lineItems and fulfillmentVersion on an Order that already exists: "
                "no PutItem or DeleteItem on the legacy orders table — its create and delete owners stay "
                "createOrder/publicCreateOrder and the delete cascades"
            )
            assert "/index/" not in str(statement["resources"]), (
                "the Order row a fulfillment conditions on is read and written by its base-table key"
            )
        if "campaigns" in keys and "unit_campaigns" not in keys:
            assert set(statement["actions"]) == {"dynamodb:UpdateItem", "dynamodb:TransactWriteItems"}, (
                "the join link is one conditional update: no PutItem, DeleteItem or ConditionCheckItem on a legacy table"
            )
            assert "/index/" not in str(statement["resources"]), (
                "the joined-scope link is written on the base table; the campaignId-index GSI is a locator only"
            )
    assert writable == {
        "units",
        "unit_campaigns",
        "inventory",
        "public_order_throttles",
        "campaigns",
        "order_fulfillments",
        "orders",
        "show_and_sells",
    }, f"unexpected write surface: {writable}"

    joined = " ".join(str(s["actions"]) for s in statements)
    assert "dynamodb:TransactWriteItems" in joined, "every Stage 1 mutation commits through a conditional transaction"
    assert "dynamodb:ConditionCheckItem" in joined, "the marker guards ride those transactions"


def test_unit_operations_datasource_is_lambda_backed() -> None:
    doc = _hcl(APPSYNC_DIR / "datasources_lambda.tf")
    datasource = _resource(doc, "aws_appsync_datasource", "unit_operations")
    assert "AWS_LAMBDA" in str(datasource["type"])
    config = block(datasource["lambda_config"][0])
    assert "unit-operations" in str(config["function_arn"]), "the data source must invoke the unit-operations Lambda"


def test_all_sixty_unit_fields_are_resolved_on_that_datasource() -> None:
    """Twenty-six queries and thirty-five mutations, Stage 1 through Stage 5 alike.

    Stage 2 adds the inventory and custody reads and the balance and custody writes to
    the same data source, Stage 3 §2.4 adds the two Order-fulfillment mutations, the
    fulfillment audit query, and the Order list a Unit Admin fulfills from, §3.1
    adds the three event mutations with the admin and participant event reads, §3.2
    adds the stock-assignment mutation with the raw allocation read, §3.3 adds the
    two slot mutations, §3.4 adds the signup, cancellation and work-confirmation
    mutations with the admin signup board, the Scout's own commitment list and the
    calendar data a browser needs, and §4.1.1 adds the payment-method read with its
    three write mutations, and §4.2/§4.3 add pooled sale entry, correction and voiding: tenant isolation, the Unit Admin check, and the
    Profile share check all live in the one handler, so a new field is a new name in
    its router, and an unbound SDL field answers nothing on ``dev``.
    """
    bound: dict[str, str] = {}
    for doc in _resolver_docs():
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type != "aws_appsync_resolver":
                    continue
                for _, attrs in instances.items():
                    field = attrs.get("field")
                    datasource = attrs.get("data_source")
                    kind = attrs.get("type")
                    if isinstance(field, str) and "unit_operations" in str(datasource):
                        bound[f"{kind}:{field}"] = str(datasource)

    for field in sorted(QUERY_FIELDS):
        assert f"Query:{field}" in bound, f"Query.{field} has no resolver on UnitOperationsDS"
    for field in sorted(MUTATION_FIELDS):
        assert f"Mutation:{field}" in bound, f"Mutation.{field} has no resolver on UnitOperationsDS"
    assert len(bound) == 74, f"expected exactly the 74 Unit-tenant resolvers, got {sorted(bound)}"
