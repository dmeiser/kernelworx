"""Behavioral scope check for the Unit tenant execution role (Wave 2 §1.7 / SCOPE-1).

The Stage 1 Unit/Unit Campaign fields and the Stage 2 inventory fields run in the
``unit-operations`` Lambda under the scoped role in ``tofu/application/modules/iam/main.tf``.
``test_unit_tenant_wiring.py`` pins what that policy declares; this file pins the
other half of the contract — what the handler actually asks DynamoDB for. moto
never evaluates IAM, so a handler that stages an action the role omits stays
green in every other test and fails on ``dev`` with ``AccessDeniedException``,
with the whole ``TransactWriteItems`` cancelled. That is exactly how the join's
legacy Campaign link (§8.2) escaped the first cut of the role.

The grant map is read out of the shipped policy rather than copied by hand, so
drift in either direction fails here: a write the handler starts that the role
does not grant, and a grant the policy drops that the handler still needs.
``TransactWriteItems`` is expanded into the item actions it carries and checked
against every item's table, because DynamoDB authorizes a transaction per table
and the item actions are not permission to invoke the API (§4.2 of
``SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md``). Index-level grants are not
modelled: every DynamoDB API call names its base table, so the pair set is the
right unit of comparison.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Set, Tuple

import botocore.client
import pytest

from src.handlers.unit_operations import (
    ADJUST_COUNCIL_FIELD,
    ADJUST_INVENTORY_FIELD,
    CREATE_INVITE_FIELD,
    CREATE_UNIT_CAMPAIGN_FIELD,
    CREATE_UNIT_FIELD,
    INVENTORY_MOVEMENTS_FIELD,
    INVENTORY_POSITIONS_FIELD,
    JOIN_PREVIEW_FIELD,
    JOIN_UNIT_CAMPAIGN_FIELD,
    MY_UNITS_FIELD,
    RECORD_RECEIPT_FIELD,
    REDEEM_INVITE_FIELD,
    REMOVE_MEMBERSHIP_FIELD,
    REVOKE_GRANT_FIELD,
    REVOKE_INVITE_FIELD,
    UNIT_ADMINS_FIELD,
    UNIT_CAMPAIGN_CATALOG_FIELD,
    UNIT_CAMPAIGN_FIELD,
    UNIT_CAMPAIGN_ROSTER_FIELD,
    UNIT_CAMPAIGNS_FIELD,
    UNIT_FIELD,
    UNIT_INVITES_FIELD,
    UPDATE_UNIT_CAMPAIGN_FIELD,
    UPDATE_UNIT_FIELD,
    handle_unit_operation,
)
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    UNIT_CAMPAIGNS,
    account_id,
    grant_item,
    seed_show_sell_fixtures,
    unit_operation_event,
)
from tests.unit.test_edge_security import TF_APP, block, load_hcl

# The joinable Pack 3149 campaign, and the catalog its admins may build on.
FALL_CODE = str(UNIT_CAMPAIGNS[PACK_3149_FALL]["joinCode"])
DEFAULT_CATALOG = str(UNIT_CAMPAIGNS[PACK_3149_FALL]["catalogId"])

IAM_MODULE = TF_APP / "modules" / "iam" / "main.tf"
POLICY_NAME = "lambda_unit_tenant_dynamodb"

# The legacy tables Stage 1 may read. The only one it may write is the joined-
# scope link §8.2 puts in the join's own transaction.
LEGACY_TABLE_KEYS = {"accounts", "campaigns", "catalogs", "profiles", "shares"}
WRITE_ACTIONS = {"PutItem", "UpdateItem", "DeleteItem", "ConditionCheckItem"}

# The transaction API carries item operations; IAM names them per item.
ITEM_ACTIONS = {"Put": "PutItem", "Update": "UpdateItem", "Delete": "DeleteItem", "ConditionCheck": "ConditionCheckItem"}

_ARN_KEYS = re.compile(r'dynamodb_table_arns\["([a-z_]+)"\]')
_FOR_KEYS = re.compile(r"for k in \[([^\]]*)\]")
_ACTION_NAMES = re.compile(r'"dynamodb:([A-Za-z]+)"')


def _policy_statements() -> List[Dict[str, Any]]:
    """The shipped Unit tenant DynamoDB policy, statement by statement."""
    doc = load_hcl(IAM_MODULE)
    for entry in doc.get("data", []):
        bodies = entry.get("aws_iam_policy_document")
        if isinstance(bodies, dict) and POLICY_NAME in bodies:
            return [block(statement) for statement in bodies[POLICY_NAME]["statement"]]
    raise AssertionError(f"data.aws_iam_policy_document.{POLICY_NAME} is not declared")


def table_keys(statement: Dict[str, Any]) -> Set[str]:
    """The ``dynamodb_table_arns`` keys one statement's resources name."""
    text = str(statement["resources"]).replace("\\", "")
    keys = set(_ARN_KEYS.findall(text))
    for group in _FOR_KEYS.findall(text):
        keys |= {item.strip().strip('"') for item in group.split(",") if item.strip()}
    return keys


def _actions_of(statement: Dict[str, Any]) -> Set[str]:
    """The DynamoDB actions one statement allows, without the ``dynamodb:`` prefix."""
    actions = statement.get("actions")
    if isinstance(actions, list):
        return {str(action).split(":")[-1] for action in actions}
    return set(_ACTION_NAMES.findall(str(actions).replace("\\", "")))


def role_grants() -> Dict[str, Set[str]]:
    """Physical table name to the DynamoDB actions the shipped role allows on it."""
    grants: Dict[str, Set[str]] = {}
    for statement in _policy_statements():
        actions = _actions_of(statement)
        assert actions, f"the {POLICY_NAME} policy has a statement with no DynamoDB action"
        keys = table_keys(statement)
        assert keys, f"the {POLICY_NAME} policy has a statement naming no table"
        for key in keys:
            grants.setdefault(_physical_table(key), set()).update(actions)
    assert grants, f"the {POLICY_NAME} policy grants nothing"
    return grants


def _physical_table(key: str) -> str:
    """The table name the test environment gives a policy's table key."""
    return os.environ[f"{key.upper()}_TABLE_NAME"]


def _table_key(physical: str) -> str:
    for key in {"units", "unit_campaigns", "public_order_throttles", "inventory"} | LEGACY_TABLE_KEYS:
        if _physical_table(key) == physical:
            return key
    return physical


class DynamoDbCallRecorder:
    """Records the ``(action, table)`` pairs one handler turn issues.

    Hooks botocore's ``BaseClient._make_api_call`` so resource-style and
    client-style calls are both captured with their real operation names, and
    expands the transaction APIs into the pairs DynamoDB authorizes. Seeding
    done before ``attach()`` is not recorded.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: List[Tuple[str, str]] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = botocore.client.BaseClient._make_api_call
        calls = self.calls

        def recording_call(client: Any, operation_name: str, params: Any) -> Any:
            if client.meta.service_model.service_name == "dynamodb" and isinstance(params, dict):
                calls.extend(_pairs_for(operation_name, params))
            return original(client, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)


def _pairs_for(operation: str, params: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Every ``(action, table)`` pair one DynamoDB API call is authorized against."""
    pairs: List[Tuple[str, str]] = []
    table = params.get("TableName")
    if isinstance(table, str):
        pairs.append((operation, table))
    request_items = params.get("RequestItems")
    if isinstance(request_items, dict):
        pairs.extend((operation, name) for name in request_items)
    for item in params.get("TransactItems") or []:
        if operation == "TransactWriteItems":
            for kind, body in item.items():
                target = body.get("TableName") if isinstance(body, dict) else None
                if kind in ITEM_ACTIONS and isinstance(target, str):
                    pairs.append((ITEM_ACTIONS[kind], target))
                    pairs.append(("TransactWriteItems", target))
            continue
        body = item.get("Get") if isinstance(item, dict) else None
        target = body.get("TableName") if isinstance(body, dict) else None
        if isinstance(target, str):
            pairs.append(("GetItem", target))
            pairs.append(("TransactGetItems", target))
    return pairs


def assert_within_role_scope(calls: List[Tuple[str, str]]) -> None:
    """Assert every pair the handler asked for is inside the shipped policy."""
    assert calls, "expected the handler to issue DynamoDB calls"
    grants = role_grants()
    outside = sorted({(action, table) for action, table in calls if action not in grants.get(table, set())})
    refused = ", ".join(f"dynamodb:{action} on {table}" for action, table in outside)
    assert not outside, (
        f"the unit-tenant role grants none of these: {refused}. A DynamoDB write the role does not "
        "grant is an AccessDeniedException on dev, and a conditional transaction cancels the whole "
        "mutation with it."
    )


def assert_only_the_join_link_writes_a_legacy_table(calls: List[Tuple[str, str]]) -> None:
    """The §8.2 joined-scope link is the only legacy row Stage 1 writes."""
    legacy_writes = {
        (action, table)
        for action, table in calls
        if action in WRITE_ACTIONS and _table_key(table) in LEGACY_TABLE_KEYS
    }
    link = ("UpdateItem", _physical_table("campaigns"))
    assert legacy_writes <= {link}, f"unexpected legacy writes: {sorted(legacy_writes - {link})}"


def _call(
    field: str,
    caller: Any,
    *,
    mutation: Dict[str, Any] | None = None,
    arguments: Dict[str, Any] | None = None,
) -> Any:
    """One resolver turn through the deployed entry point."""
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _campaign_of(persona: str) -> str:
    """The Scout Campaign id the Stage 1 fixtures give a persona."""
    return str(PROFILES[persona]["campaignId"])


def _ok(payload: Any) -> Any:
    """A mutation that errored exercises none of its writes, so fail loudly."""
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload


@pytest.fixture
def seeded(
    units_table: Any,
    unit_campaigns_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    catalogs_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 persona world: Units, grants, rosters, guards, catalogs."""
    return seed_show_sell_fixtures(
        units_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
    )


@pytest.fixture
def dynamodb_calls(monkeypatch: pytest.MonkeyPatch) -> DynamoDbCallRecorder:
    """A DynamoDB call recorder; call ``attach()`` after seeding the world."""
    return DynamoDbCallRecorder(monkeypatch)


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _join_scout(caller: str, join_code: str, campaign_id: str, key: str) -> Any:
    return _call(
        JOIN_UNIT_CAMPAIGN_FIELD,
        caller,
        mutation={"joinCode": join_code, "campaignId": campaign_id, **_idem(key)},
    )


# --- the join is the write the first cut of the role could not perform ---------


def test_join_writes_the_legacy_campaign_link_the_role_must_grant(
    seeded: Dict[str, Any], dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """§8.2 / CAMP-M-03: membership, guard and the Campaign link commit together.

    The link is an ``UpdateItem`` on the legacy ``campaigns`` table inside the
    same transaction as the roster and the guard, so the role has to grant it or
    every ``joinUnitCampaign`` on dev is refused and nothing at all is written.
    """
    dynamodb_calls.attach()

    result = _ok(_join_scout("Blake", FALL_CODE, _campaign_of("Blake"), "join-1"))
    assert result["unitCampaignId"] == PACK_3149_FALL

    link = ("UpdateItem", _physical_table("campaigns"))
    assert link in dynamodb_calls.calls, "the join no longer writes the §8.2 Campaign link it is contractually owed"
    assert ("TransactWriteItems", _physical_table("campaigns")) in dynamodb_calls.calls, (
        "the link rides the same transaction as the membership and the guard"
    )
    assert_only_the_join_link_writes_a_legacy_table(dynamodb_calls.calls)
    assert_within_role_scope(dynamodb_calls.calls)


# --- all nineteen operations, audited against the same policy ------------------


def test_every_stage_one_mutation_stays_inside_the_shipped_role(
    seeded: Dict[str, Any], units_table: Any, dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """Ten mutations, one audit: no write may ask for an action the role omits."""
    # A second grant to revoke, seeded before recording starts so the revoke
    # takes the real path instead of erroring out of its own write.
    units_table.put_item(Item=grant_item(PACK_3149, account_id("Blake"), created_by=account_id("Avery")))
    units_table.update_item(
        Key={"pk": f"UNIT#{PACK_3149}", "sk": "METADATA"},
        UpdateExpression="SET adminCount = :two",
        ExpressionAttributeValues={":two": 2},
    )

    dynamodb_calls.attach()

    created_unit = _ok(
        _call(
            CREATE_UNIT_FIELD,
            "Avery",
            mutation={
                "unitType": "Pack",
                "unitNumber": 4404,
                "city": "Boulder",
                "state": "CO",
                "timezone": "America/Denver",
                **_idem("create-unit"),
            },
        )
    )
    _ok(
        _call(
            UPDATE_UNIT_FIELD,
            "Avery",
            mutation={
                "unitId": created_unit["unit"]["unitId"],
                "city": "Denver",
                "version": {"expectedVersion": 1},
                **_idem("update-unit"),
            },
        )
    )
    invite = _ok(_call(CREATE_INVITE_FIELD, "Avery", mutation={"unitId": PACK_3149, **_idem("create-invite")}))
    _ok(
        _call(
            REVOKE_INVITE_FIELD,
            "Avery",
            mutation={"unitId": PACK_3149, "inviteCode": invite["inviteCode"], **_idem("revoke-invite")},
        )
    )
    second_invite = _ok(
        _call(CREATE_INVITE_FIELD, "Avery", mutation={"unitId": PACK_3149, **_idem("create-invite-2")})
    )
    _ok(
        _call(
            REDEEM_INVITE_FIELD,
            "Blake",
            mutation={"inviteCode": second_invite["inviteCode"], **_idem("redeem-invite")},
        )
    )
    _ok(
        _call(
            REVOKE_GRANT_FIELD,
            "Avery",
            mutation={
                "unitId": PACK_3149,
                "accountId": account_id("Blake"),
                "version": {"expectedVersion": 1},
                **_idem("revoke-grant"),
            },
        )
    )
    _ok(
        _call(
            CREATE_UNIT_CAMPAIGN_FIELD,
            "Avery",
            mutation={
                "unitId": PACK_3149,
                "campaignName": "Pack 3149 Winter Show & Sell",
                "campaignYear": 2027,
                "catalogId": DEFAULT_CATALOG,
                **_idem("create-campaign"),
            },
        )
    )
    _ok(
        _call(
            UPDATE_UNIT_CAMPAIGN_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": PACK_3149_FALL,
                "campaignName": "Pack 3149 Fall Show & Sell",
                "version": {"expectedVersion": 1},
                **_idem("update-campaign"),
            },
        )
    )
    _ok(_join_scout("Blake", FALL_CODE, _campaign_of("Blake"), "join-campaign"))
    _ok(
        _call(
            REMOVE_MEMBERSHIP_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": PACK_3149_FALL,
                "campaignId": _campaign_of("Devon"),
                "expectedMembershipVersion": 1,
                "expectedGuardVersion": 1,
                **_idem("remove-member"),
            },
        )
    )

    assert_only_the_join_link_writes_a_legacy_table(dynamodb_calls.calls)
    assert_within_role_scope(dynamodb_calls.calls)


def test_a_failed_redemption_increments_the_counter_the_role_grants(
    seeded: Dict[str, Any], dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """§6.6: the failure counter rides a table outside the Unit aggregates."""
    dynamodb_calls.attach()

    _call(REDEEM_INVITE_FIELD, "Blake", mutation={"inviteCode": "ABCDEFGH23456789", **_idem("bad-redeem")})

    counter = ("UpdateItem", _physical_table("public_order_throttles"))
    assert counter in dynamodb_calls.calls, "the redemption throttle counter is no longer incremented"
    assert_only_the_join_link_writes_a_legacy_table(dynamodb_calls.calls)
    assert_within_role_scope(dynamodb_calls.calls)


def test_every_stage_one_query_stays_inside_the_shipped_role(
    seeded: Dict[str, Any], dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """Nine queries: the reads the role grants are the reads the handler needs."""
    dynamodb_calls.attach()

    _ok(_call(MY_UNITS_FIELD, "Avery", arguments={}))
    _ok(_call(UNIT_FIELD, "Avery", arguments={"unitId": PACK_3149}))
    _ok(_call(UNIT_ADMINS_FIELD, "Avery", arguments={"unitId": PACK_3149}))
    _ok(_call(UNIT_INVITES_FIELD, "Avery", arguments={"unitId": PACK_3149}))
    _ok(_call(JOIN_PREVIEW_FIELD, "Blake", arguments={"joinCode": FALL_CODE}))
    _ok(_call(UNIT_CAMPAIGN_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL}))
    _ok(_call(UNIT_CAMPAIGNS_FIELD, "Avery", arguments={"unitId": PACK_3149}))
    _ok(_call(UNIT_CAMPAIGN_CATALOG_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL}))
    roster = _ok(_call(UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL}))
    assert roster["items"], "the roster read needs a joined Scout to exercise the Account batch read"

    assert not [pair for pair in dynamodb_calls.calls if pair[0] in WRITE_ACTIONS], (
        "a Stage 1 query wrote something: the read audit stops being a read audit"
    )
    assert_within_role_scope(dynamodb_calls.calls)


# --- Stage 2: the inventory balance writes and the reads that answer from them ---

INVENTORY_PRODUCT = f"{DEFAULT_CATALOG}#prod-1"


@pytest.fixture
def stocked(
    units_table: Any,
    unit_campaigns_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 world plus the empty inventory table Stage 2 writes into."""
    return seed_show_sell_fixtures(
        units_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
    )


def test_the_three_balance_mutations_touch_only_the_inventory_table(
    stocked: Dict[str, Any], dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """§2.2.1-03: balance, movement, and marker are inventory rows, and nothing else is.

    Stage 2's promise is that a stock count moves without touching money. A write
    that reached the Order, payment, or We Owe tables here is an
    AccessDeniedException on `dev` today, and a reconciliation hole the day the role
    grew that grant.
    """
    dynamodb_calls.attach()

    _ok(
        _call(
            RECORD_RECEIPT_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": PACK_3149_FALL,
                "productId": INVENTORY_PRODUCT,
                "quantity": 10,
                **_idem("scope-receipt"),
            },
        )
    )
    _ok(
        _call(
            ADJUST_INVENTORY_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": PACK_3149_FALL,
                "productId": INVENTORY_PRODUCT,
                "quantityDelta": -3,
                "reason": "gifted a case to the fire company",
                **_idem("scope-adjust"),
            },
        )
    )
    _ok(
        _call(
            ADJUST_COUNCIL_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": PACK_3149_FALL,
                "productId": INVENTORY_PRODUCT,
                "quantityDelta": 4,
                **_idem("scope-council"),
            },
        )
    )

    inventory = _physical_table("inventory")
    writes = {pair for pair in dynamodb_calls.calls if pair[0] in WRITE_ACTIONS}
    assert writes, "a balance mutation issued no write at all"
    assert {table for _, table in writes} == {inventory}, f"a balance mutation wrote outside inventory: {sorted(writes)}"
    assert ("TransactWriteItems", inventory) in dynamodb_calls.calls, (
        "the balance write no longer rides one conditional transaction"
    )
    assert_only_the_join_link_writes_a_legacy_table(dynamodb_calls.calls)
    assert_within_role_scope(dynamodb_calls.calls)


def test_every_stage_two_query_stays_inside_the_shipped_role(
    stocked: Dict[str, Any], dynamodb_calls: DynamoDbCallRecorder
) -> None:
    """§2.2.4: the position and history reads ask only for what the role grants."""
    _ok(
        _call(
            RECORD_RECEIPT_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": PACK_3149_FALL,
                "productId": INVENTORY_PRODUCT,
                "quantity": 10,
                **_idem("scope-read-seed"),
            },
        )
    )
    dynamodb_calls.attach()

    positions = _ok(_call(INVENTORY_POSITIONS_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL}))
    movements = _ok(_call(INVENTORY_MOVEMENTS_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL}))
    assert positions["items"] and movements["items"], "a read of an empty table audits nothing"

    assert not [pair for pair in dynamodb_calls.calls if pair[0] in WRITE_ACTIONS], (
        "a Stage 2 query wrote something: the audit trail stops being a record of mutations"
    )
    assert_within_role_scope(dynamodb_calls.calls)
