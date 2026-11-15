"""Deployed wiring for the Unit tenant Lambda (Wave 2 §1.7 / SCOPE-1).

The Stage 1 SDL declares 19 Unit/Unit Campaign operations and the handler
(``src/handlers/unit_operations.py``) routes exactly those field names -- but a
resolver that exists only in schema and source answers nothing on
``dev.kernelworx.app``. This file pins the deployed path end to end, because
every link is one a plausible-looking wiring pass drops:

- the Lambda function itself, with the handler entry point and the env vars
  the TableAccessor reads (UNITS_TABLE_NAME / UNIT_CAMPAIGNS_TABLE_NAME);
- a scoped execution role (the #326 domain-role split: no function falls back
  to a broad role, and the Unit role's only write outside its own tables is the
  §8.2 join link on the legacy campaigns table -- named, not implied);
- the AppSync AWS_LAMBDA data source;
- a resolver for every one of the 19 SDL fields -- nine queries and ten
  mutations -- all bound to that one data source, so tenant isolation stays
  in the single handler that enforces it.

Parsed with python-hcl2 through the harness in ``test_edge_security.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_edge_security import TF_APP, block, load_hcl

MODULES = TF_APP / "modules"
ENVIRONMENTS = TF_APP / "environments"

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
        assert keys <= {"units", "unit_campaigns", "public_order_throttles", "campaigns"}, (
            f"write actions outside the Unit tables, the counter and the join link: {keys}"
        )
        if "campaigns" in keys and "unit_campaigns" not in keys:
            assert set(statement["actions"]) == {"dynamodb:UpdateItem", "dynamodb:TransactWriteItems"}, (
                "the join link is one conditional update: no PutItem, DeleteItem or ConditionCheckItem on a legacy table"
            )
            assert "/index/" not in str(statement["resources"]), (
                "the joined-scope link is written on the base table; the campaignId-index GSI is a locator only"
            )
    assert writable == {"units", "unit_campaigns", "public_order_throttles", "campaigns"}, (
        f"unexpected legacy write surface: {writable - {'units', 'unit_campaigns', 'public_order_throttles'}}"
    )

    joined = " ".join(str(s["actions"]) for s in statements)
    assert "dynamodb:TransactWriteItems" in joined, "every Stage 1 mutation commits through a conditional transaction"
    assert "dynamodb:ConditionCheckItem" in joined, "the marker guards ride those transactions"


def test_unit_operations_datasource_is_lambda_backed() -> None:
    doc = _hcl(APPSYNC_DIR / "datasources_lambda.tf")
    datasource = _resource(doc, "aws_appsync_datasource", "unit_operations")
    assert "AWS_LAMBDA" in str(datasource["type"])
    config = block(datasource["lambda_config"][0])
    assert "unit-operations" in str(config["function_arn"]), "the data source must invoke the unit-operations Lambda"


def test_all_nineteen_stage_one_fields_are_resolved_on_that_datasource() -> None:
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
    assert len(bound) == 19, f"expected exactly the 19 Stage 1 resolvers, got {sorted(bound)}"
