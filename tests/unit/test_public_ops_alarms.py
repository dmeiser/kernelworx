"""Static contract for the public-orders operational alarms (spec §9, slice 10).

The app tofu had zero ``aws_cloudwatch_metric_alarm`` resources before this
slice, so every claim below is pinned against the metric names and dimensions
that were verified against the live account's CloudWatch metric list
(``aws cloudwatch list-metrics``), not against recollection:

- ``AWS/AppSync`` ``4XXError`` is emitted with the ``GraphQLAPIId`` dimension
  only — there is no auth-mode dimension, so the public-surface 4xx/throttle
  alarm is API-wide by construction and the test pins that shape rather than
  pretending it is key-scoped;
- ``AWS/SES`` ``Reputation.BounceRate`` / ``Reputation.ComplaintRate`` are
  published with **no** dimensions, so those alarms must carry no ``dimensions``
  block at all (a bogus dimension would create an alarm that never sees data);
- AWS publishes **no** ``ExpiredAPIKeys`` metric, so the spec's named
  ExpiredAPIKeys alarm ships as a scheduled EventBridge reminder derived from
  the key's own ``expires`` value — the test pins the derivation (no hardcoded
  cron date anywhere) and the loud precondition that refuses a reminder with no
  date.

Also pinned: the SES reputation alarms and the expiry reminder are prod-only,
dev still runs the 4xx alarm (the feature's dev-first posture), ephemeral
instantiates the module not at all, every alarm notifies the module's own ops
SNS topic, and the renewal runbook names the SES production-access request for
``kernelworx.app`` as the pre-launch gate. CloudTrail and X-Ray stay absent.
"""

from pathlib import Path
from typing import Any, Dict, List

from tests.unit.test_edge_security import REPO_ROOT, TF_APP, load_hcl, resources

ALARMS_DIR = TF_APP / "modules" / "alarms"
ALARMS_MAIN = ALARMS_DIR / "main.tf"
ALARMS_VARIABLES = ALARMS_DIR / "variables.tf"
DEV_MAIN = TF_APP / "environments" / "dev" / "main.tf"
PROD_MAIN = TF_APP / "environments" / "prod" / "main.tf"
EPHEMERAL_MAIN = TF_APP / "environments" / "ephemeral" / "main.tf"
APP_SYNC_API = TF_APP / "modules" / "appsync" / "api.tf"
APP_SYNC_OUTPUTS = TF_APP / "modules" / "appsync" / "outputs.tf"
RUNBOOK = REPO_ROOT / "docs" / "PUBLIC_API_KEY_RUNBOOK.md"
TOFU_ROOT = TF_APP.parent


def _module_blocks(env_main: Path) -> Dict[str, Any]:
    doc = load_hcl(env_main)
    modules: Dict[str, Any] = {}
    for entry in doc.get("module", []):
        for name, attributes in entry.items():
            modules[str(name)] = attributes
    return modules


def _alarms_doc() -> Dict[str, Any]:
    return load_hcl(ALARMS_MAIN)


def _alarms_of_type(resource_type: str) -> List[tuple[str, Dict[str, Any]]]:
    return resources(_alarms_doc(), resource_type)


def _variable_defaults() -> Dict[str, Any]:
    doc = load_hcl(ALARMS_VARIABLES)
    defaults: Dict[str, Any] = {}
    for entry in doc.get("variable", []):
        for name, body in entry.items():
            if "default" in body:
                defaults[str(name)] = body["default"]
    return defaults


def _flag(value: Any) -> bool:
    return str(value).strip().lower() == "true"


# ---------------------------------------------------------------------------
# The module is the single owning stack, and it is the repo's alarm precedent
# ---------------------------------------------------------------------------


def test_alarms_module_exists_and_owns_every_alarm() -> None:
    for filename in ("main.tf", "variables.tf", "outputs.tf", "terraform.tf"):
        assert (ALARMS_DIR / filename).is_file(), f"the alarms module is missing {filename}"

    alarms = _alarms_of_type("aws_cloudwatch_metric_alarm")
    assert len(alarms) == 3, f"expected exactly three alarms, found {[a for a, _ in alarms]}"

    # No alarm defined anywhere else in the application stack: one owning stack
    # is what the spec's "every alarm below is new precedent with an owning
    # stack named" asks for.
    for tf in TOFU_ROOT.rglob("*.tf"):
        if ALARMS_DIR in tf.parents:
            continue
        assert "aws_cloudwatch_metric_alarm" not in tf.read_text(), f"{tf} declares an alarm outside the alarms module"


def test_no_cloudtrail_and_no_xray_anywhere_in_the_module() -> None:
    for tf in ALARMS_DIR.glob("*.tf"):
        text = tf.read_text()
        assert 'resource "aws_cloudtrail' not in text, f"{tf} introduces CloudTrail, which is forbidden"
        assert "xray_enabled = true" not in text, f"{tf} enables X-Ray, which is forbidden"


# ---------------------------------------------------------------------------
# Metric shapes verified against the live account
# ---------------------------------------------------------------------------


def test_appsync_4xx_alarm_uses_the_only_real_dimension_set() -> None:
    alarms = {label: body for label, body in _alarms_of_type("aws_cloudwatch_metric_alarm")}
    body = alarms["appsync_4xx"]

    assert body["namespace"] == "AWS/AppSync"
    assert body["metric_name"] == "4XXError"
    dimensions = body["dimensions"]
    assert list(dimensions) == ["GraphQLAPIId"], (
        "AWS/AppSync 4XXError is emitted with the GraphQLAPIId dimension only; "
        "any other key would alarm on a metric series that never receives data"
    )
    assert "appsync_api_id" in str(dimensions["GraphQLAPIId"])

    # A throttle flood and an expired key both show up as 4xx; missing data must
    # not alarm (an idle environment is not an incident).
    assert body["treat_missing_data"] == "notBreaching"
    assert body["statistic"] == "Sum"
    assert body["comparison_operator"] == "GreaterThanOrEqualToThreshold"


def test_ses_reputation_alarms_carry_no_dimensions() -> None:
    alarms = {label: body for label, body in _alarms_of_type("aws_cloudwatch_metric_alarm")}
    bounce = alarms["ses_bounce_rate"]
    complaint = alarms["ses_complaint_rate"]

    assert bounce["namespace"] == "AWS/SES" and complaint["namespace"] == "AWS/SES"
    assert bounce["metric_name"] == "Reputation.BounceRate"
    assert complaint["metric_name"] == "Reputation.ComplaintRate"

    # Verified against the live metric list: both metrics are published with an
    # empty dimension set. An alarm that names a dimension would watch a series
    # that never exists and sit silently green.
    for label, body in (("ses_bounce_rate", bounce), ("ses_complaint_rate", complaint)):
        assert "dimensions" not in body, f"{label} must not name any dimension"
        assert body["treat_missing_data"] == "notBreaching", (
            "an account that has sent nothing publishes nothing; missing data must not alarm"
        )

    # SES restricts sending above these account-level bands; the thresholds are
    # variables so the alarms can be tuned without touching the resource block.
    defaults = _variable_defaults()
    assert float(defaults["ses_bounce_rate_threshold"]) <= 5.0
    assert float(defaults["ses_complaint_rate_threshold"]) <= 0.1
    assert float(defaults["appsync_4xx_threshold"]) <= 100


# ---------------------------------------------------------------------------
# Scope: which environment gets which alarm
# ---------------------------------------------------------------------------


def test_ephemeral_does_not_instantiate_the_alarms_module() -> None:
    assert "alarms" not in _module_blocks(EPHEMERAL_MAIN), (
        "ephemeral must create zero alarm/SNS objects (the #665 WAF and SES pattern)"
    )


def test_prod_carries_the_full_set_and_dev_only_the_4xx_alarm() -> None:
    dev = _module_blocks(DEV_MAIN)["alarms"]
    prod = _module_blocks(PROD_MAIN)["alarms"]

    assert dev["source"].endswith("modules/alarms")
    assert prod["source"].endswith("modules/alarms")

    assert _flag(prod["ses_reputation_enabled"]), "SES reputation alarms are prod only (Q3)"
    assert not _flag(dev["ses_reputation_enabled"]), (
        "reputation is account-level; the dev account's reputation is not the buyer-facing signal"
    )

    assert _flag(prod["api_key_expiry_reminder_enabled"])
    assert not _flag(dev["api_key_expiry_reminder_enabled"]), (
        "`expires` is one module-level literal shared by every environment, so one named reminder covers the fleet"
    )


def test_both_environments_wire_the_api_id_and_the_key_expiry() -> None:
    for env_main in (DEV_MAIN, PROD_MAIN):
        alarms = _module_blocks(env_main)["alarms"]
        assert "module.appsync.api_id" in str(alarms["appsync_api_id"])
        # Single source of truth: the reminder date is the key's own expiry, so
        # renewing api.tf moves the reminder automatically.
        assert "module.appsync.api_key_expires" in str(alarms["api_key_expiry"]), (
            "the reminder must read the key's own expires value, never restate a date"
        )
        assert "alert_email" in alarms


def test_appsync_module_exports_the_key_expiry() -> None:
    outputs = load_hcl(APP_SYNC_OUTPUTS).get("output", [])
    names = {name for entry in outputs for name in entry}
    assert "api_key_expires" in names, "the appsync module must export the key expiry for the reminder"

    # The expiry stays a literal in api.tf: a computed value would rotate the
    # key (and break every open tab) on every plan.
    key_blocks = {label: body for label, body in resources(load_hcl(APP_SYNC_API), "aws_appsync_api_key")}
    expires = str(key_blocks["public_orders"]["expires"])
    assert "${" not in expires and "timestamp(" not in expires


def test_no_environment_hardcodes_a_reminder_date() -> None:
    for env_main in (DEV_MAIN, PROD_MAIN, EPHEMERAL_MAIN):
        assert "cron(" not in env_main.read_text(), (
            "the reminder schedule is derived from the key's expires; a literal cron date would drift"
        )


def test_reminder_schedule_is_derived_from_the_key_expiry() -> None:
    text = ALARMS_MAIN.read_text()
    assert '"-720h"' in text, "the reminder must sit 30 days before the key's own expires value"
    assert 'api_key_expiry == ""' in text, "the derivation must not run on an empty expiry"
    assert "schedule_expression = local.api_key_expiry_reminder_schedule" in text
    assert 'error_message = "api_key_expiry_reminder_enabled requires api_key_expiry' in text, (
        "a reminder with no date must fail the plan loudly, not create an invalid rule"
    )


# ---------------------------------------------------------------------------
# Notification path
# ---------------------------------------------------------------------------


def test_every_alarm_notifies_the_modules_own_ops_topic() -> None:
    for label, body in _alarms_of_type("aws_cloudwatch_metric_alarm"):
        actions = body.get("alarm_actions")
        assert actions, f"{label} has no alarm_actions: an alarm nobody is told about is decoration"
        assert "aws_sns_topic.ops_alerts" in str(actions), f"{label} must notify the ops alert topic"


def test_ops_topic_notifies_the_environment_alert_email() -> None:
    subscriptions = _alarms_of_type("aws_sns_topic_subscription")
    assert len(subscriptions) == 1
    subscription = subscriptions[0][1]
    assert subscription["protocol"] == "email"
    assert "var.alert_email" in str(subscription["endpoint"])

    topic_policies = _alarms_of_type("aws_sns_topic_policy")
    assert topic_policies, "the ops topic needs a policy: EventBridge must be allowed to publish"


def test_expiry_reminder_publishes_to_the_same_ops_topic() -> None:
    targets = _alarms_of_type("aws_cloudwatch_event_target")
    assert len(targets) == 1
    assert "aws_sns_topic.ops_alerts" in str(targets[0][1]["arn"])
    assert "PUBLIC_API_KEY_RUNBOOK" in str(targets[0][1]["input"]), (
        "the reminder email must point at the runbook, not just at the date"
    )


# ---------------------------------------------------------------------------
# The runbook half of the slice
# ---------------------------------------------------------------------------


def test_runbook_exists_and_names_the_pre_launch_gate() -> None:
    assert RUNBOOK.is_file(), "docs/PUBLIC_API_KEY_RUNBOOK.md is the runbook the spec names"
    text = RUNBOOK.read_text()

    assert "production access" in text, "the SES production-access request must be named as a gate"
    assert "kernelworx.app" in text
    assert "sandbox" in text
    assert "cutover" in text, "the renewal runbook must state the hard-cutover gap"
    assert "expires" in text
    assert "CloudTrail" in text and "X-Ray" in text, "the non-goals must be stated"


def test_runbook_is_reachable_from_the_infrastructure_it_documents() -> None:
    assert "PUBLIC_API_KEY_RUNBOOK" in ALARMS_MAIN.read_text()
    assert "PUBLIC_API_KEY_RUNBOOK" in APP_SYNC_API.read_text(), (
        "api.tf's `expires` comment is where a renewer starts; it must point at the runbook"
    )
