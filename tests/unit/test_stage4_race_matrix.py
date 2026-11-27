"""Leaf 4.6.4 — the races Stage 4 has to lose correctly.

Every Stage 4 mutation reads, decides, then writes with a version pin. Two requests that
overlap in the window between the read and the commit are therefore not a bug to be found
later: they are a transaction that DynamoDB cancels. §4.6.4 asks for that to be automated for
the four pairs where a lost race would corrupt money or stock:

- **the last box, sold twice.** Both plans are staged from ONE read of one box. One commits;
  the other's pins are already false and its whole transaction — sale row, obligation, stock
  deltas, movement and idempotency marker — is cancelled together. One sale, one movement,
  physical never negative.
- **a method retired mid-flight.** The sale pinned the method row it read; the Unit deactivated
  it before the commit, and the sale does not land. This is the pair that cannot be caught by
  validation, because at read time the method really was active.
- **reservation against reservation, and fulfillment against release.** Each write is legal
  against the state it read and illegal against the state the other one left. Both orders leave
  exactly one committed, and either way the obligation and the stock moved together or not at all.
- **a fulfillment racing itself.** Two fulfillments of the same two boxes: the obligation never
  ends up owing fewer than nothing and never holds more fulfillment than it owed.

The idempotency half is measured across the same races rather than on its own: the cancelled
attempt left **no** marker, so its key re-runs and is refused by the stock bound instead of
replaying a sale that never happened; the committed attempt's marker is ``IN_FLIGHT`` — the
insert rode inside the transaction — so its retry is answered from the stored ``resultId`` and
writes nothing; and the same key with a different body is refused by fingerprint.

The plans are captured, not hand-built: the resolver runs for real, and the hook stops it at
its own ``TransactWriteItems``, which is the only way to know that what raced is the transaction
the deployed code would have issued — marker included.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Sequence

import botocore.client
import pytest
from botocore.exceptions import ClientError

from src.handlers.unit_operations import (
    CREATE_SALE_FIELD,
    FULFILL_WE_OWE_FIELD,
    SET_WE_OWE_RESERVATION_FIELD,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from src.utils import unit_payment_models as upm
from src.utils.dynamodb import get_dynamodb_client
from tests.unit.show_sell_fixtures import account_id, assert_is_error, seed_show_sell_fixtures
from tests.unit.test_show_and_sell_sales import (
    ACTIVE_EVENT,
    CAMPAIGN,
    PRODUCT,
    _call,
    _create,
    _line,
    _marker_rows,
    _method,
    _movements,
    _obligation_rows,
    _offer_products,
    _ok,
    _sale_rows,
    _seed_event,
    _seed_stock,
    _stored_allocation,
    _stored_balance,
    _stored_event,
)
from tests.unit.test_unit_payment_methods import _deactivate as _deactivate_method

AVERY = account_id("Avery")

#: One custom method this module names, so a sale can pin it and a deactivation can retire it.
WISE_METHOD_ID = "pm-wise-race"

#: The captured wire shape: a list of ``TransactWriteItems`` entries, each one keyed by its
#: action type. Captured plans are committed with the real client, exactly as the resolver
#: would have committed them.
Plan = List[Dict[str, Any]]


@pytest.fixture
def world(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 personas plus one running event and the two tables Stage 4 writes.

    Stock is seeded per case, because every case here is about a specific number of boxes:
    the last one, the last unassigned one, the two a fulfillment is holding.
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _offer_products(catalogs_table, 4)
    _seed_event(show_and_sells_table, ACTIVE_EVENT, product_ids=[PRODUCT])
    return {
        "units": units_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
    }


# --- The race harness -------------------------------------------------------------


class OneReadTwoPlans:
    """Stage two mutations against one state, then commit their plans in a chosen order.

    ``stage`` runs the real resolver and intercepts its ``TransactWriteItems``: the transaction
    is recorded in wire form and the call fails, so nothing lands and the next resolver reads
    exactly the same rows. That is the state two concurrent requests share — both have read,
    neither has written — and it is the state no sequential test can reach any other way.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._armed = False
        self._captured: Optional[Plan] = None
        original = botocore.client.BaseClient._make_api_call
        harness = self

        def intercept(client: Any, operation_name: str, params: Any) -> Any:
            if harness._armed and operation_name == "TransactWriteItems":
                harness._captured = deepcopy(list(params.get("TransactItems", [])))
                raise ClientError(
                    {
                        "Error": {
                            "Code": "TransactionCanceledException",
                            "Message": "captured for the race matrix; nothing committed",
                        }
                    },
                    operation_name,
                )
            return original(client, operation_name, params)

        monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", intercept)

    def stage(self, turn: Callable[[], Any]) -> Plan:
        """Run one resolver turn and keep the transaction it staged instead of committing."""
        self._captured = None
        self._armed = True
        try:
            turn()
        finally:
            self._armed = False
        assert self._captured is not None, "the turn staged no transaction, so it has no race to run"
        return self._captured

    def race(self, plans: Sequence[Plan]) -> Dict[str, Any]:
        """Commit each captured plan in order and report what DynamoDB answered."""
        client = get_dynamodb_client()
        verdicts: List[Dict[str, Any]] = []
        for attempt, plan in enumerate(plans):
            try:
                client.transact_write_items(TransactItems=deepcopy(list(plan)))
                verdicts.append({"attempt": attempt, "committed": True, "code": None, "reasons": None})
            except ClientError as exc:
                verdicts.append(
                    {
                        "attempt": attempt,
                        "committed": False,
                        "code": str(exc.response.get("Error", {}).get("Code")),
                        "reasons": list(exc.response.get("CancellationReasons") or []),
                    }
                )
        return {"verdicts": verdicts, "committed": sum(1 for verdict in verdicts if verdict["committed"])}


def _cancel_codes(reasons: Sequence[Dict[str, Any]]) -> List[str]:
    """The per-item verdicts DynamoDB reports for a cancelled transaction.

    Items that were fine answer ``None``, so a cancelled transaction is named by the one verdict
    that is not: the pin that had already gone false.
    """
    return [str(reason.get("Code") or reason.get("code") or "None") for reason in reasons]


def _failed_rows(plan: Plan, reasons: Sequence[Dict[str, Any]]) -> List[str]:
    """Which stored rows the cancelled plan was refused, named by sort key.

    A cancellation verdict comes back in the plan's own order, so the captured plan says what
    each verdict is about. ``Update`` reasons echo the row and a ``ConditionCheck`` reason does
    not, which is why the pairing has to come from the plan rather than the reply.
    """
    rows: List[str] = []
    for index, reason in enumerate(reasons):
        if "ConditionalCheckFailed" not in str(reason.get("Code") or ""):
            continue
        action = plan[index]
        for shape in ("ConditionCheck", "Update", "Delete"):
            if shape in action:
                rows.append(str(action[shape]["Key"]["sk"]["S"]))
                break
        else:
            rows.append(str(action["Put"]["Item"]["sk"]["S"]))
    return rows


def _condition_checks(plan: Plan) -> List[Dict[str, Any]]:
    """The rows a staged transaction refuses to write unless they are still what it read."""
    return [action["ConditionCheck"] for action in plan if "ConditionCheck" in action]


def _one_lost_race(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """The shared verdict of every race here: one committed, the other cancelled whole."""
    assert outcome["committed"] == 1, outcome["verdicts"]
    loser = next(verdict for verdict in outcome["verdicts"] if not verdict["committed"])
    assert loser["code"] == "TransactionCanceledException", loser
    assert any("ConditionalCheckFailed" in code for code in _cancel_codes(loser["reasons"])), loser["reasons"]
    return loser


# --- Readers ----------------------------------------------------------------------


def _balance(world: Dict[str, Any]) -> Dict[str, int]:
    row = _stored_balance(world["inventory"])
    assert row is not None
    return {
        "physical": int(row[inv.KERNEL_PHYSICAL_QTY]),
        "possession": int(row[inv.SOLD_IN_POSSESSION_QTY]),
        "version": int(row[inv.VERSION_ATTRIBUTE]),
    }


def _allocation(world: Dict[str, Any]) -> Dict[str, int]:
    row = _stored_allocation(world["inventory"], ACTIVE_EVENT)
    assert row is not None
    return {
        "allocated": int(row[inv.ALLOCATED_QTY]),
        "sold": int(row[inv.SOLD_QTY]),
        "released": int(row[inv.RELEASED_QTY]),
        "version": int(row[inv.VERSION_ATTRIBUTE]),
    }


def _obligation(world: Dict[str, Any], we_owe_id: str) -> Dict[str, int]:
    row = sm.load_we_owe_by_id_or_not_found(we_owe_id)
    return {
        "original": int(row[sm.ORIGINAL_QTY_ATTRIBUTE]),
        "fulfilled": int(row[sm.FULFILLED_QTY_ATTRIBUTE]),
        "reserved": int(row[sm.RESERVED_QTY_ATTRIBUTE]),
        "remaining": int(row[sm.REMAINING_QTY_ATTRIBUTE]),
        "uncovered": int(row[sm.UNCOVERED_QTY_ATTRIBUTE]),
        "version": int(row[sm.VERSION_ATTRIBUTE]),
    }


def _movement_types(world: Dict[str, Any]) -> List[str]:
    return sorted(str(row[inv.MOVEMENT_TYPE_ATTRIBUTE]) for row in _movements(world["inventory"]))


def _markers(world: Dict[str, Any], operation: str) -> List[Dict[str, Any]]:
    """One operation's markers.

    The sale that created an obligation writes its own marker in the same table, so counting
    every marker would charge this race for a row another resolver committed.
    """
    return [row for row in _marker_rows(world["show_and_sells"]) if f"#{operation}#" in str(row.get("pk", ""))]


def _owed(world: Dict[str, Any], *, immediate: int, we_owe: int, key: str = "race-sale") -> str:
    """One sale that owes, returning its obligation id — the row both racers act on."""
    answer = _ok(_create(lines=[_line(PRODUCT, immediate=immediate, we_owe=we_owe)], buyerName="Buyer Cy", key=key))
    assert len(answer["obligations"]) == 1
    return str(answer["obligations"][0][sm.WE_OWE_ID_ATTRIBUTE])


def _reserve(we_owe_id: str, target: int, key: str) -> Any:
    version = int(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.VERSION_ATTRIBUTE])
    return _call(
        SET_WE_OWE_RESERVATION_FIELD,
        "Avery",
        mutation={
            "weOweId": we_owe_id,
            "targetReservedQty": target,
            "version": {"expectedVersion": version},
            "idempotency": {"idempotencyKey": key},
        },
    )


def _fulfill(we_owe_id: str, quantity: int, key: str) -> Any:
    version = int(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.VERSION_ATTRIBUTE])
    return _call(
        FULFILL_WE_OWE_FIELD,
        "Avery",
        mutation={
            "weOweId": we_owe_id,
            "quantity": quantity,
            "source": sm.WE_OWE_SOURCE_KERNEL,
            "version": {"expectedVersion": version},
            "idempotency": {"idempotencyKey": key},
        },
    )


# --- The last box, sold twice ------------------------------------------------------


def test_two_sales_of_the_last_box_from_one_read_commit_exactly_once(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-21, VER-01: the desk sells the last box twice and the books hold it once."""
    _seed_stock(world, physical=1, allocated=1)
    harness = OneReadTwoPlans(monkeypatch)

    first = harness.stage(lambda: _create(lines=[_line(PRODUCT, immediate=1)], version=1, key="race-a"))
    second = harness.stage(lambda: _create(lines=[_line(PRODUCT, immediate=1)], version=1, key="race-b"))
    outcome = harness.race([first, second])

    loser = _one_lost_race(outcome)
    # Every row the loser meant to move still carried the version the winner had just moved,
    # which is why the sale, the stock, the movement and the marker are all missing together.
    assert _failed_rows(second, loser["reasons"]) == [
        inv.balance_key(CAMPAIGN, PRODUCT)["sk"],
        ssm.event_allocation_key(CAMPAIGN, PRODUCT, ACTIVE_EVENT)["sk"],
        ssm.METADATA_SK,
    ]
    assert len(_sale_rows(world["show_and_sells"])) == 1, "one sale row, not one per attempt"
    assert _obligation_rows(world["show_and_sells"]) == []
    assert _movement_types(world) == ["EVENT_IMMEDIATE_SALE"]
    assert _balance(world) == {"physical": 0, "possession": 0, "version": 2}
    assert _allocation(world) == {"allocated": 1, "sold": 1, "released": 0, "version": 2}
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2
    assert len(_markers(world, CREATE_SALE_FIELD)) == 1, "the cancelled attempt left no marker behind"
    assert [row["status"] for row in _markers(world, CREATE_SALE_FIELD)] == ["IN_FLIGHT"]


def test_the_race_that_cancelled_is_refused_by_the_desk_on_the_next_attempt(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wire pin is the backstop; the desk itself says so when the buyer tries again."""
    _seed_stock(world, physical=1, allocated=1)
    harness = OneReadTwoPlans(monkeypatch)

    plans = [
        harness.stage(lambda: _create(lines=[_line(PRODUCT, immediate=1)], version=1, key=f"race-{letter}"))
        for letter in ("a", "b")
    ]
    assert harness.race(plans)["committed"] == 1

    refused = assert_is_error(_create(lines=[_line(PRODUCT, immediate=1)], version=2, key="race-c"), "CONFLICT")
    assert "0 to sell" in refused["message"], refused["message"]
    assert len(_sale_rows(world["show_and_sells"])) == 1, "the refusal wrote nothing"
    assert _movement_types(world) == ["EVENT_IMMEDIATE_SALE"]
    assert _balance(world)["physical"] == 0, "stock went to zero and stayed there — never below"


def test_a_retry_after_the_race_replays_the_committed_sale_and_the_cancelled_key_re_runs(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4.6.4's identical/changed retry pair, measured across a race rather than in isolation.

    The winner's marker was inserted inside the transaction, so an ``IN_FLIGHT`` marker is
    proof the business rows committed; its retry is answered from the stored ``resultId`` and
    stages no write. The loser's marker was cancelled with its transaction, so its key is not
    a phantom answer — it re-runs and meets the stock bound. And a key reused with different
    content is refused by fingerprint before anything is read for a write.
    """
    _seed_stock(world, physical=1, allocated=1)
    harness = OneReadTwoPlans(monkeypatch)

    plans = [
        harness.stage(lambda: _create(lines=[_line(PRODUCT, immediate=1)], version=1, key=f"race-{letter}"))
        for letter in ("a", "b")
    ]
    assert harness.race(plans)["committed"] == 1
    committed_sale = _sale_rows(world["show_and_sells"])[0]

    before = {
        "sales": len(_sale_rows(world["show_and_sells"])),
        "movements": len(_movements(world["inventory"])),
        "markers": len(_marker_rows(world["show_and_sells"])),
        "event_version": _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE],
    }

    replay = _ok(_create(lines=[_line(PRODUCT, immediate=1)], version=1, key="race-a"))
    assert replay["sale"][sm.SALE_ID_ATTRIBUTE] == committed_sale[sm.SALE_ID_ATTRIBUTE]
    assert int(replay["sale"][sm.TOTAL_CENTS_ATTRIBUTE]) == 500

    changed = assert_is_error(_create(lines=[_line(PRODUCT, immediate=1, we_owe=1)], key="race-a"), "INVALID_INPUT")
    assert "already used with different request content" in changed["message"], changed["message"]

    orphan = assert_is_error(_create(lines=[_line(PRODUCT, immediate=1)], version=2, key="race-b"), "CONFLICT")
    assert "0 to sell" in orphan["message"], "the cancelled key re-ran instead of replaying nothing"

    assert len(_sale_rows(world["show_and_sells"])) == before["sales"]
    assert len(_movements(world["inventory"])) == before["movements"]
    assert len(_marker_rows(world["show_and_sells"])) == before["markers"]
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == before["event_version"]
    assert _balance(world)["physical"] == 0


# --- A method retired between the read and the commit ------------------------------


def test_a_method_retired_between_the_read_and_the_commit_cancels_the_sale(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-18 at the wire: validation cannot see a deactivation that happens after it ran."""
    _seed_stock(world, physical=4, allocated=4)
    _method(world["units"], payment_method_id=WISE_METHOD_ID, display_name="Wise")
    harness = OneReadTwoPlans(monkeypatch)

    plan = harness.stage(
        lambda: _create(
            lines=[_line(PRODUCT, immediate=1)],
            version=1,
            key="race-wise",
            paymentMethodCode=f"CUSTOM:{WISE_METHOD_ID}",
        )
    )
    _ok(_deactivate_method(world["units"], AVERY, paymentMethodId=WISE_METHOD_ID, version=1))

    outcome = harness.race([plan])
    verdict = outcome["verdicts"][0]
    assert not verdict["committed"] and verdict["code"] == "TransactionCanceledException"
    assert any("ConditionalCheckFailed" in code for code in _cancel_codes(verdict["reasons"])), verdict["reasons"]

    # The pin that broke is the one the sale put on the method row it read: version, id and
    # isActive together. No validation could have seen the deactivation — at read time the
    # method really was active — so this condition is the only thing standing between a
    # retired method and a sale recorded against it.
    method_pins = [_condition_checks(plan)[0]]
    assert [pin["Key"]["sk"]["S"] for pin in method_pins] == [upm.payment_sk("wise")]
    assert "#isActive" in method_pins[0]["ConditionExpression"]
    assert method_pins[0]["ExpressionAttributeValues"][":isActive"] == {"BOOL": True}

    assert _sale_rows(world["show_and_sells"]) == [], "no sale against a method the Unit retired"
    assert _movement_types(world) == []
    assert _balance(world) == {"physical": 4, "possession": 0, "version": 1}
    assert _allocation(world) == {"allocated": 4, "sold": 0, "released": 0, "version": 1}
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1
    assert _markers(world, CREATE_SALE_FIELD) == []

    refused = assert_is_error(
        _create(
            lines=[_line(PRODUCT, immediate=1)],
            version=1,
            key="race-wise-2",
            paymentMethodCode=f"CUSTOM:{WISE_METHOD_ID}",
        ),
        "CONFLICT",
    )
    assert "no longer available" in refused["message"]


# --- Reservations and fulfillments -------------------------------------------------


def test_two_reservations_of_the_last_unassigned_box_move_stock_once(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """OWE-04 at the wire: two desks each hold one box, and the Unit has one to give."""
    _seed_stock(world, physical=5, allocated=4)
    we_owe_id = _owed(world, immediate=1, we_owe=2)
    harness = OneReadTwoPlans(monkeypatch)

    plans = [harness.stage(lambda: _reserve(we_owe_id, 1, f"reserve-{letter}")) for letter in ("a", "b")]
    outcome = harness.race(plans)

    loser = _one_lost_race(outcome)
    assert _failed_rows(plans[1], loser["reasons"]) == [
        sm.we_owe_key(ACTIVE_EVENT, we_owe_id)["sk"],
        inv.balance_key(CAMPAIGN, PRODUCT)["sk"],
    ], "the second desk pinned both the boxes it owed and the boxes it was holding"
    obligation = _obligation(world, we_owe_id)
    assert (obligation["reserved"], obligation["remaining"], obligation["uncovered"]) == (1, 2, 1)
    assert obligation["original"] == 2 and obligation["fulfilled"] == 0
    assert _balance(world) == {"physical": 4, "possession": 1, "version": 3}
    assert _movement_types(world) == ["EVENT_IMMEDIATE_SALE", "WE_OWE_RESERVE"]
    assert len(_markers(world, SET_WE_OWE_RESERVATION_FIELD)) == 1


@pytest.mark.parametrize("order", ["release-first", "deliver-first"])
def test_a_release_and_a_fulfillment_of_one_obligation_land_in_one_order_only(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch, order: str
) -> None:
    """The two legal writes for one obligation, committed in either order, move both rows together.

    Releasing a reservation and delivering it are each valid against the state they read and
    mutually exclusive in effect. Whichever commits first pins the other out, and in neither
    order does the obligation move without the stock moving with it.
    """
    _seed_stock(world, physical=7, allocated=4)
    we_owe_id = _owed(world, immediate=1, we_owe=2)
    _ok(_reserve(we_owe_id, 2, "reserve-setup"))

    harness = OneReadTwoPlans(monkeypatch)
    release = harness.stage(lambda: _reserve(we_owe_id, 0, "reserve-release"))
    deliver = harness.stage(lambda: _fulfill(we_owe_id, 2, "fulfill-both"))

    plans = [release, deliver] if order == "release-first" else [deliver, release]
    outcome = harness.race(plans)
    loser = _one_lost_race(outcome)
    loser_index = next(index for index, verdict in enumerate(outcome["verdicts"]) if not verdict["committed"])
    assert _failed_rows(plans[loser_index], loser["reasons"]) == [
        sm.we_owe_key(ACTIVE_EVENT, we_owe_id)["sk"],
        inv.balance_key(CAMPAIGN, PRODUCT)["sk"],
    ]
    winner = next(verdict["attempt"] for verdict in outcome["verdicts"] if verdict["committed"])

    obligation = _obligation(world, we_owe_id)
    balance = _balance(world)
    assert obligation["fulfilled"] + obligation["remaining"] == obligation["original"]
    assert obligation["reserved"] <= obligation["remaining"], "nothing is held against nothing owed"
    assert balance["possession"] <= obligation["reserved"], "nothing sits in possession beyond a reservation"
    assert balance["physical"] >= 0 and balance["possession"] >= 0

    if plans[winner] is deliver:
        assert (obligation["fulfilled"], obligation["reserved"], obligation["remaining"]) == (2, 0, 0)
        assert balance == {"physical": 4, "possession": 0, "version": 4}
        assert _movement_types(world) == ["EVENT_IMMEDIATE_SALE", "WE_OWE_FULFILL", "WE_OWE_RESERVE"]
        assert len(_markers(world, FULFILL_WE_OWE_FIELD)) == 1
        assert len(_markers(world, SET_WE_OWE_RESERVATION_FIELD)) == 1, "only the setup reservation has a marker"
    else:
        assert (obligation["fulfilled"], obligation["reserved"], obligation["remaining"]) == (0, 0, 2)
        assert balance == {"physical": 6, "possession": 0, "version": 4}
        assert _movement_types(world) == ["EVENT_IMMEDIATE_SALE", "WE_OWE_RELEASE", "WE_OWE_RESERVE"]


def test_two_fulfillments_of_one_obligation_never_overfill_it(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """OWE-07 at the wire: two desks deliver the same two boxes; the buyer owes nothing twice."""
    _seed_stock(world, physical=7, allocated=4)
    we_owe_id = _owed(world, immediate=1, we_owe=2)
    _ok(_reserve(we_owe_id, 2, "reserve-setup"))

    harness = OneReadTwoPlans(monkeypatch)
    plans = [harness.stage(lambda: _fulfill(we_owe_id, 2, f"fulfill-{letter}")) for letter in ("a", "b")]
    outcome = harness.race(plans)

    loser = _one_lost_race(outcome)
    assert _failed_rows(plans[1], loser["reasons"]) == [
        sm.we_owe_key(ACTIVE_EVENT, we_owe_id)["sk"],
        inv.balance_key(CAMPAIGN, PRODUCT)["sk"],
    ]
    obligation = _obligation(world, we_owe_id)
    assert (obligation["original"], obligation["fulfilled"], obligation["reserved"], obligation["remaining"]) == (
        2,
        2,
        0,
        0,
    )
    row = sm.load_we_owe_by_id_or_not_found(we_owe_id)
    assert (row[sm.STATUS_ATTRIBUTE], row[sm.CLOSE_REASON_ATTRIBUTE]) == (
        sm.WE_OWE_STATUS_CLOSED,
        sm.WE_OWE_CLOSE_FULFILLED,
    )
    assert _balance(world) == {"physical": 4, "possession": 0, "version": 4}
    assert _movement_types(world) == ["EVENT_IMMEDIATE_SALE", "WE_OWE_FULFILL", "WE_OWE_RESERVE"]
    fulfillment_rows = [
        loaded
        for loaded in (
            sm.we_owe_fulfillment_payload(stored) for stored in sm.we_owe_fulfillment_history(ACTIVE_EVENT, we_owe_id)
        )
    ]
    assert len(fulfillment_rows) == 1, "one fulfillment record for one obligation, not one per attempt"
    assert int(fulfillment_rows[0]["quantity"]) == 2
    assert len(_markers(world, FULFILL_WE_OWE_FIELD)) == 1
