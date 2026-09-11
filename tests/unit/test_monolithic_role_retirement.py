"""Wiring contract for the #355 retirement of the monolithic Lambda role.

#326 split the monolithic shared Lambda execution role into scoped per-domain
roles (campaign #351, profile/sharing #352, payment #353, account/reporting
#354) plus a dedicated role for the Cognito post-auth trigger (#355). #355
(chunk 5, final) removes the monolithic role entirely:

- the iam module declares no ``aws_iam_role.lambda_execution``, its retired
  inline policies, or a ``lambda_execution_role_arn`` output;
- the post-auth replacement role's inline policy grants exactly
  GetItem/PutItem/UpdateItem on the accounts table — no S3, CloudFront, or
  Cognito grants anywhere in its attached policies;
- the lambda module has no ``lambda_role_arn`` variable and its role-resolution
  locals index ``var.lambda_domain_role_arns`` directly (no shared fallback —
  a missing entry fails the plan loudly);
- the cognito module attaches its admin policy to the dedicated admin-role
  variable, with no legacy ``lambda_execution_role_arn`` fallback;
- every non-admin Lambda function key (app and trigger) has an entry in the
  ``lambda_domain_role_arns`` map of ALL THREE environments (dev, prod,
  ephemeral), so tofu plan can never hit the loud missing-entry failure.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2, the pattern established by test_cloudfront_oac.py,
test_admin_resolver_wiring.py, and test_edge_security.py) and assert the
meaning of the retirement contract. The recovery script's import list is
covered behaviorally by test_ephemeral_reliability.py, which executes the
script with stubbed aws/tofu executables and asserts the recorded ``tofu
import`` addresses: the retired monolithic role is absent and the post-auth
role plus its basic-execution attachment and DynamoDB policy are present.
"""

from __future__ import annotations

from tests.unit.test_edge_security import (
    TF_APP,
    block,
    first_resource,
    load_hcl,
    modules,
    resources,
)

IAM_DOC = load_hcl(TF_APP / "modules" / "iam" / "main.tf")
LAMBDA_DOC = load_hcl(TF_APP / "modules" / "lambda" / "main.tf")
COGNITO_DOC = load_hcl(TF_APP / "modules" / "cognito" / "main.tf")
ENVIRONMENTS = ("dev", "prod", "ephemeral")


def _variables(doc: dict) -> set[str]:
    return {name for entry in doc.get("variable", []) for name in entry}


def _variable_attrs(doc: dict, name: str) -> dict:
    for entry in doc.get("variable", []):
        if name in entry:
            return entry[name]
    raise AssertionError(f"variable {name} not found")


def _outputs(doc: dict) -> set[str]:
    return {name for entry in doc.get("output", []) for name in entry}


def _locals(doc: dict) -> dict:
    merged = {}
    for entry in doc.get("locals", []):
        merged.update(entry)
    return merged


def _policy_document(doc: dict, name: str) -> dict:
    for entry in doc.get("data", []):
        bodies = entry.get("aws_iam_policy_document", {})
        if name in bodies:
            return block(bodies[name])
    raise AssertionError(f"data.aws_iam_policy_document.{name} not found")


def _inline_policy_statements(doc: dict, role_label: str) -> list[tuple[str, list[dict]]]:
    """(policy label, statements) for every inline policy attached to the role."""
    attached = []
    for label, body in resources(doc, "aws_iam_role_policy"):
        if body.get("role") != f"${{aws_iam_role.{role_label}.id}}":
            continue
        ref = body.get("policy", "")
        prefix, suffix = "${data.aws_iam_policy_document.", ".json}"
        assert ref.startswith(prefix) and ref.endswith(suffix), (
            f"{label}: policy must be rendered from a data.aws_iam_policy_document"
        )
        attached.append((label, _policy_document(doc, ref[len(prefix) : -len(suffix)]).get("statement", [])))
    return attached


def _lambda_module_block(env: str) -> dict:
    found = modules(load_hcl(TF_APP / "environments" / env / "main.tf"), "lambda")
    assert len(found) == 1, f"{env}: exactly one lambda module block expected"
    return found[0]


def _all_function_keys() -> list[str]:
    merged = _locals(LAMBDA_DOC)
    admin = set(merged["admin_function_keys"]) | set(merged["admin_trigger_keys"])
    keys = sorted(set(merged["functions"]) | set(merged["trigger_functions"]))
    return [k for k in keys if k not in admin]


class TestMonolithicRoleRemoved:
    """The monolithic role, its policies, and its plumbing are gone."""

    def test_iam_module_declares_no_monolithic_role(self) -> None:
        assert all(label != "lambda_execution" for label, _ in resources(IAM_DOC, "aws_iam_role"))
        assert all(label != "lambda_basic" for label, _ in resources(IAM_DOC, "aws_iam_role_policy_attachment"))
        retired_policies = {"lambda_dynamodb", "lambda_s3", "lambda_cloudfront"}
        policy_labels = {label for label, _ in resources(IAM_DOC, "aws_iam_role_policy")}
        assert retired_policies.isdisjoint(policy_labels), (
            f"retired monolithic inline policies still declared: {retired_policies & policy_labels}"
        )
        assert "lambda_execution_role_arn" not in _outputs(IAM_DOC)
        assert "lambda_execution_role_name" not in _outputs(IAM_DOC)
        assert "lambda_execution_role_arn" not in _variables(IAM_DOC)

    def test_iam_module_declares_post_auth_role(self) -> None:
        role = first_resource(IAM_DOC, "aws_iam_role", "lambda_post_auth_execution")
        assert role["assume_role_policy"] == "${data.aws_iam_policy_document.lambda_assume_role.json}"
        assert "lambda_post_auth_execution_role_arn" in _outputs(IAM_DOC)
        attachment = first_resource(IAM_DOC, "aws_iam_role_policy_attachment", "lambda_post_auth_basic")
        assert attachment["role"] == "${aws_iam_role.lambda_post_auth_execution.name}"

    def test_post_auth_role_scoped_to_accounts_table(self) -> None:
        """The post-auth role's inline policies grant DynamoDB access to the
        accounts table only: exactly GetItem/PutItem/UpdateItem, no S3,
        CloudFront, or Cognito grants."""
        attached = _inline_policy_statements(IAM_DOC, "lambda_post_auth_execution")
        assert [label for label, _ in attached] == ["lambda_post_auth_dynamodb"], (
            "post-auth role must carry exactly its DynamoDB inline policy "
            "(plus the managed AWSLambdaBasicExecutionRole attachment)"
        )
        [(_, statements)] = attached
        assert len(statements) == 1
        statement = statements[0]
        assert statement.get("effect") == "Allow"
        assert sorted(statement.get("actions", [])) == [
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
        ]
        assert statement.get("resources") == ['${var.dynamodb_table_arns["accounts"]}']


class TestLambdaModuleHasNoSharedFallback:
    def test_no_shared_role_variable(self) -> None:
        assert "lambda_role_arn" not in _variables(LAMBDA_DOC)

    def test_role_resolution_indexes_domain_map_directly(self) -> None:
        merged = _locals(LAMBDA_DOC)
        for local_name in ("app_role_arn", "trigger_role_arn"):
            expr = merged[local_name]
            assert "var.lambda_domain_role_arns" in expr, (
                f"local.{local_name} must resolve non-admin functions through the domain-role map"
            )
            assert "var.lambda_role_arn" not in expr, f"local.{local_name} must not fall back to a shared role"
            assert "coalesce" not in expr, f"local.{local_name} must not coalesce a shared-role fallback"


class TestCognitoModuleHasNoLegacyFallback:
    def test_admin_policy_targets_admin_role_variable(self) -> None:
        assert "lambda_execution_role_arn" not in _variables(COGNITO_DOC)
        admin_var = _variable_attrs(COGNITO_DOC, "lambda_admin_execution_role_arn")
        assert "default" not in admin_var, "admin role ARN must be required (no fallback default)"
        policy = first_resource(COGNITO_DOC, "aws_iam_role_policy", "lambda_cognito_admin")
        assert "var.lambda_admin_execution_role_arn" in policy["role"], (
            "the Cognito admin policy must attach to the dedicated admin role (#121); "
            "the monolithic shared role was retired in #355"
        )


class TestEveryFunctionHasScopedRole:
    """Every non-admin function key resolves via lambda_domain_role_arns in all envs."""

    def test_all_non_admin_functions_have_domain_entries(self) -> None:
        function_keys = _all_function_keys()
        assert function_keys
        for env in ENVIRONMENTS:
            domain_map = _lambda_module_block(env)["lambda_domain_role_arns"]
            missing = [k for k in function_keys if k not in domain_map]
            assert not missing, f"{env}: functions missing a lambda_domain_role_arns entry: {missing}"
            assert domain_map["post-auth"] == "${module.iam.lambda_post_auth_execution_role_arn}", (
                f"{env}: post-auth trigger must map to the scoped post-auth role"
            )

    def test_environments_pass_no_monolithic_wiring(self) -> None:
        for env in ENVIRONMENTS:
            attrs = _lambda_module_block(env)
            legacy = {"lambda_role_arn", "lambda_execution_role_arn"} & {k for k in attrs if not k.startswith("__")}
            assert not legacy, f"{env}: legacy monolithic/shared role wiring remains: {sorted(legacy)}"
