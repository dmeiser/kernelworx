"""The shared sale payment validator (delivery checklist §4.1.3, data model §5.14).

A sale names its payment method by code and keeps one immutable snapshot, so the
questions this suite settles are the ones every pooled-sale write path will ask:

- what a sale may name — a built-in, or ``CUSTOM:<paymentMethodId>`` resolved
  inside the event's own Unit, which makes another Unit's method simply not there
  (AUTH-U-05);
- what it records — the display name read from the server's row and never the
  caller's text (PAY-06), plus the Other explanation when the method is Other
  (AC-19, AC-20);
- what the write must carry — the method row's identity, version and active state as
  a transaction condition, so a deactivation landing after the read that filled the
  picker fails the whole sale rather than recording it against a retired method
  (PAY-M-02-03), and so a name that a rename freed and a create reused cannot answer
  for a sale made under the method that held it first; and
- that money is classified by the code alone, which is why a custom method named
  ``Cash`` never reaches the cash column (AC-31).
"""

from __future__ import annotations

from typing import Any, Dict, List, cast

import pytest
from botocore.exceptions import ClientError

from src.handlers.unit_operations import DEACTIVATE_PAYMENT_METHOD_FIELD, handle_unit_operation
from src.utils.dynamodb import get_dynamodb_client
from src.utils.errors import AppError, ErrorCode
from src.utils.sale_payment_models import (
    CUSTOM_METHOD_CODE_PREFIX,
    OTHER_DETAILS_MAX_CHARS,
    build_payment_method_snapshot,
    builtin_payment_method_snapshot,
    custom_method_id,
    expected_cash_cents,
    normalize_method_code,
    normalize_other_details,
    payment_method_condition_action,
    resolve_sale_payment,
    sale_payment_decision,
)
from src.utils.unit_payment_models import build_payment_item, payment_key
from tests.unit.show_sell_fixtures import account_id, grant_item, unit_item, unit_operation_event

AVERY = account_id("Avery")

PACK_ID = "unit-pack-3149-aurora"
TROOP_ID = "unit-troop-7150-boulder"

WISE_ID = "9f0d7c31-6b1e-4f0a-9e2c-2a7c4f1b8d30"
CASH_BOX_ID = "4b2a1c98-77e5-4d0f-9b31-6d5a0e8c2f14"
NO_SUCH_ID = "00000000-0000-4000-8000-000000000000"


def _seed_units(units_table: Any) -> None:
    """Two Units, each with Avery as an admin, so a method can belong to only one."""
    for unit_id, label, number in ((PACK_ID, "Pack", 3149), (TROOP_ID, "Troop", 7150)):
        units_table.put_item(Item=unit_item(unit_id, label, number, "Aurora", "CO", created_by=AVERY, admin_count=1))
        units_table.put_item(Item=grant_item(unit_id, AVERY, created_by=AVERY))


def _method(
    units_table: Any, unit_id: str, *, payment_method_id: str, display_name: str, is_active: bool = True
) -> Dict[str, Any]:
    """Write one custom-method row the way ``createUnitPaymentMethod`` does."""
    item = build_payment_item(
        payment_method_id=payment_method_id,
        unit_id=unit_id,
        display_name=display_name,
        created_by_account_id=AVERY,
        now_iso="2026-11-21T18:00:00+00:00",
        is_active=is_active,
    )
    units_table.put_item(Item=item)
    return item


def _decision(units_table: Any, unit_id: str, method_code: Any, **kwargs: Any) -> Dict[str, Any]:
    """``sale_payment_decision`` with the Unit wiring every call needs anyway."""
    return sale_payment_decision(unit_id=unit_id, method_code=method_code, **kwargs)


def _retire_method(units_table: Any, *, unit_id: str = PACK_ID, payment_method_id: str = WISE_ID) -> None:
    """Retire a method through ``deactivateUnitPaymentMethod`` itself.

    The version bump and the active flag come from the production path, so what the
    sale's condition meets afterwards is the state a real deactivation leaves behind.
    """
    payload = handle_unit_operation(
        unit_operation_event(
            DEACTIVATE_PAYMENT_METHOD_FIELD,
            "Avery",
            input={
                "unitId": unit_id,
                "paymentMethodId": payment_method_id,
                "version": {"expectedVersion": 1},
                "idempotency": {"idempotencyKey": f"retire-{payment_method_id}"},
            },
        ),
        None,
    )
    assert not (isinstance(payload, dict) and payload.get("__isError")), payload


def _commit_sale(units_table: Any, decision: Dict[str, Any]) -> None:
    """The sale write a pooled-sale resolver issues: the method's condition and the sale row.

    The plain client is the one the resolvers use (:func:`src.utils.dynamodb.get_dynamodb_client`),
    and the two actions are one ``TransactWriteItems``, so DynamoDB — not a check the
    handler ran a read earlier — decides whether the sale exists.
    """
    snapshot = decision["snapshot"]
    transact_items: List[Dict[str, Any]] = [
        {
            "Put": {
                "TableName": units_table.table_name,
                "Item": {
                    "pk": {"S": f"UNIT#{PACK_ID}"},
                    "sk": {"S": "SALE#sale-1"},
                    "paymentMethodSnapshot": {
                        "M": {
                            "methodCode": {"S": snapshot["methodCode"]},
                            "displayName": {"S": snapshot["displayName"]},
                            **(
                                {"otherDetails": {"NULL": True}}
                                if snapshot["otherDetails"] is None
                                else {"otherDetails": {"S": snapshot["otherDetails"]}}
                            ),
                        }
                    },
                },
            }
        }
    ]
    if decision["condition"] is not None:
        transact_items.insert(0, {"ConditionCheck": decision["condition"]})
    get_dynamodb_client().transact_write_items(TransactItems=cast(Any, transact_items))


def _sale_rows(units_table: Any) -> Any:
    """Every sale row on the Unit — what a refused commit must not have written."""
    return [row for row in units_table.scan()["Items"] if str(row["sk"]).startswith("SALE#")]


# --- what a sale is allowed to name ----------------------------------------------


def test_a_sale_names_a_builtin_by_code_however_the_picker_caps_it() -> None:
    """Cash/Check/Other are codes, and the snapshot carries the canonical name."""
    for sent, code in (("cash", "CASH"), ("CHECK", "CHECK"), (" Other ", "OTHER")):
        assert normalize_method_code(sent) == code

    assert builtin_payment_method_snapshot("CASH", None) == {
        "methodCode": "CASH",
        "displayName": "Cash",
        "otherDetails": None,
    }
    assert builtin_payment_method_snapshot("OTHER", "a card")["displayName"] == "Other"


def test_a_code_that_names_no_method_is_refused_before_anything_is_read() -> None:
    """A caller that invents a method code is a client bug, not a missing method."""
    for bad in ("paypal", "cash app", "custom", "", "   ", None, 7):
        with pytest.raises(AppError) as raised:
            normalize_method_code(bad)
        assert raised.value.error_code == ErrorCode.INVALID_INPUT
        assert raised.value.details["subcode"] in {"PAYMENT_METHOD_REQUIRED", "UNKNOWN_PAYMENT_METHOD_CODE"}


def test_a_custom_code_keeps_the_id_it_was_given() -> None:
    """``CUSTOM:<id>`` addresses a row, so that id is not re-cased on the way in."""
    code = normalize_method_code(f"  {CUSTOM_METHOD_CODE_PREFIX}{WISE_ID} ")
    assert code == f"{CUSTOM_METHOD_CODE_PREFIX}{WISE_ID}"
    assert custom_method_id(code) == WISE_ID
    assert custom_method_id("CASH") is None

    for bad in (f"{CUSTOM_METHOD_CODE_PREFIX}   ", f"{CUSTOM_METHOD_CODE_PREFIX}{'x' * 101}"):
        with pytest.raises(AppError) as raised:
            normalize_method_code(bad)
        assert raised.value.error_code == ErrorCode.INVALID_INPUT


def test_a_sale_selects_a_custom_method_in_its_own_unit(units_table: Any) -> None:
    """The event's Unit decides which methods exist; that is tenant isolation."""
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise")

    resolved = resolve_sale_payment(PACK_ID, f"{CUSTOM_METHOD_CODE_PREFIX}{WISE_ID}")
    assert resolved is not None and resolved["paymentMethodId"] == WISE_ID
    assert resolve_sale_payment(TROOP_ID, f"{CUSTOM_METHOD_CODE_PREFIX}{WISE_ID}") is None
    assert resolve_sale_payment(PACK_ID, "CASH") is None
    assert resolve_sale_payment(PACK_ID, f"{CUSTOM_METHOD_CODE_PREFIX}{NO_SUCH_ID}") is None

    with pytest.raises(AppError) as raised:
        _decision(units_table, TROOP_ID, f"{CUSTOM_METHOD_CODE_PREFIX}{WISE_ID}")
    assert raised.value.error_code == ErrorCode.NOT_FOUND


def test_the_snapshot_takes_the_servers_name_not_the_callers(units_table: Any) -> None:
    """PAY-06: a later rename or retirement never rewrites what a sale recorded."""
    _seed_units(units_table)
    stored = _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise")

    decision = _decision(units_table, PACK_ID, f"{CUSTOM_METHOD_CODE_PREFIX}{WISE_ID}")
    assert decision["snapshot"] == {"methodCode": f"CUSTOM:{WISE_ID}", "displayName": "Wise", "otherDetails": None}

    units_table.update_item(
        Key=payment_key(PACK_ID, "wise"),
        UpdateExpression="SET #name = :name, #version = #version + :one",
        ExpressionAttributeNames={"#name": "displayName", "#version": "version"},
        ExpressionAttributeValues={":name": "Wise Wallet", ":one": 1},
    )

    assert decision["snapshot"]["displayName"] == "Wise"
    assert build_payment_method_snapshot(stored, "a note")["displayName"] == "Wise"


# --- the Other explanation (AC-19, AC-20) -----------------------------------------


def test_other_requires_an_explanation_and_no_other_method_carries_one() -> None:
    """Other is how a split payment is recorded, so its note is the whole record."""
    note = "cash plus a check; the balance at the next meeting"
    assert normalize_other_details("OTHER", f"  {note}  ") == note
    assert normalize_other_details("CASH", None) is None
    assert normalize_other_details("CASH", "   ") is None

    for missing in (None, "", "   ", 7):
        with pytest.raises(AppError) as raised:
            normalize_other_details("OTHER", missing)
        assert raised.value.error_code == ErrorCode.INVALID_INPUT

    with pytest.raises(AppError) as raised:
        normalize_other_details("OTHER", "x" * (OTHER_DETAILS_MAX_CHARS + 1))
    assert raised.value.error_code == ErrorCode.INVALID_INPUT
    assert f"at most {OTHER_DETAILS_MAX_CHARS}" in raised.value.message

    for sent in ("cash now, check later", 7):
        with pytest.raises(AppError) as raised:
            normalize_other_details("CASH", sent)
        assert raised.value.error_code == ErrorCode.INVALID_INPUT
        assert raised.value.details["subcode"] == "OTHER_DETAILS_NOT_ALLOWED"


def test_a_sale_for_other_carries_its_note_into_the_snapshot(units_table: Any) -> None:
    """The decision is what a sale writes, so the explanation has to be inside it."""
    _seed_units(units_table)
    decision = _decision(units_table, PACK_ID, "OTHER", other_details="half cash, half a check")

    assert decision["snapshot"] == {
        "methodCode": "OTHER",
        "displayName": "Other",
        "otherDetails": "half cash, half a check",
    }
    assert decision["condition"] is None


# --- the method has to still be available (PAY-M-02-03) ---------------------------


def test_a_retired_method_refuses_a_new_sale(units_table: Any) -> None:
    """A method retired since the picker was filled is a reload, not a bad sale."""
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise", is_active=False)

    with pytest.raises(AppError) as raised:
        _decision(units_table, PACK_ID, f"{CUSTOM_METHOD_CODE_PREFIX}{WISE_ID}")
    assert raised.value.error_code == ErrorCode.CONFLICT
    assert raised.value.details["subcode"] == "PAYMENT_METHOD_NOT_ACTIVE"
    assert raised.value.details["paymentMethodId"] == WISE_ID


def test_a_correction_may_keep_the_method_a_sale_was_made_under(units_table: Any) -> None:
    """An unchanged historical correction is allowed to name a retired method."""
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise", is_active=False)

    decision = _decision(units_table, PACK_ID, f"CUSTOM:{WISE_ID}", require_active=False)

    assert decision["snapshot"]["displayName"] == "Wise"
    assert decision["condition"] is not None


def test_the_condition_names_the_method_row_the_snapshot_read(units_table: Any) -> None:
    """The write carries the method's identity, version and active state, on that row's key."""
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise")
    row = resolve_sale_payment(PACK_ID, f"CUSTOM:{WISE_ID}")
    assert row is not None

    condition = payment_method_condition_action(row)

    assert condition["TableName"] == units_table.table_name
    assert condition["Key"] == {"pk": {"S": f"UNIT#{PACK_ID}"}, "sk": {"S": "PAYMENT#wise"}}
    assert (
        condition["ConditionExpression"]
        == "#version = :expectedVersion AND #paymentMethodId = :paymentMethodId AND #isActive = :isActive"
    )
    assert condition["ExpressionAttributeNames"] == {
        "#version": "version",
        "#paymentMethodId": "paymentMethodId",
        "#isActive": "isActive",
    }
    assert condition["ExpressionAttributeValues"] == {
        ":expectedVersion": {"N": "1"},
        ":paymentMethodId": {"S": WISE_ID},
        ":isActive": {"BOOL": True},
    }


def test_a_renamed_method_frees_the_name_for_another_methods_sale(units_table: Any) -> None:
    """The identity half of the condition is what makes it about a method, not a name.

    A payment row's sort key is a normalized display name, so a rename followed by a
    create puts a DIFFERENT method at the key an earlier read saw — and at the same
    version number that read recorded, because the new row starts at 1. A condition on
    the version alone would let that sale commit, snapshotting a method the picker
    never offered. The interleaving is a real one: both writes are ordinary admin
    mutations, and the sale's read is not part of either transaction.
    """
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise")
    decision = _decision(units_table, PACK_ID, f"CUSTOM:{WISE_ID}")
    assert decision["condition"] is not None
    assert decision["snapshot"]["displayName"] == "Wise"

    # The rename moved Wise to another key and this create took the name back up, so
    # PAYMENT#wise is now a different method — at the version the sale's read saw.
    _method(units_table, PACK_ID, payment_method_id=CASH_BOX_ID, display_name="Wise")

    with pytest.raises(ClientError) as cancelled:
        _commit_sale(units_table, decision)
    reasons = cancelled.value.response["CancellationReasons"]
    assert [reason["Code"] for reason in reasons] == ["ConditionalCheckFailed", "None"]
    assert _sale_rows(units_table) == []


def test_a_deactivation_after_the_read_cancels_the_sale_transaction(units_table: Any) -> None:
    """The race the condition exists for: the read is not the guard, the write is.

    The picker read sees Wise at version 1 and active; the Unit retires it before the
    sale is committed. The sale's ``TransactWriteItems`` carries that row's key with
    the version and active flag as the read saw them, so DynamoDB cancels the whole
    transaction — the sale row never exists, and the retry that follows is refused as
    an inactive method rather than recorded.
    """
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise")
    decision = _decision(units_table, PACK_ID, f"CUSTOM:{WISE_ID}")
    assert decision["condition"] is not None
    assert decision["snapshot"]["displayName"] == "Wise"

    _retire_method(units_table)

    with pytest.raises(ClientError) as cancelled:
        _commit_sale(units_table, decision)
    reasons = cancelled.value.response["CancellationReasons"]
    assert [reason["Code"] for reason in reasons] == ["ConditionalCheckFailed", "None"]
    assert _sale_rows(units_table) == []

    with pytest.raises(AppError) as late:
        _decision(units_table, PACK_ID, f"CUSTOM:{WISE_ID}")
    assert late.value.error_code == ErrorCode.CONFLICT


def test_the_sale_transaction_commits_while_the_method_stays_as_read(units_table: Any) -> None:
    """The control that keeps the condition above from being vacuous: nothing moved, so it writes."""
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=WISE_ID, display_name="Wise")
    decision = _decision(units_table, PACK_ID, f"CUSTOM:{WISE_ID}")

    _commit_sale(units_table, decision)

    sale = _sale_rows(units_table)[0]
    assert sale["paymentMethodSnapshot"] == {
        "methodCode": f"CUSTOM:{WISE_ID}",
        "displayName": "Wise",
        "otherDetails": None,
    }
    method = units_table.get_item(Key=payment_key(PACK_ID, "wise"))["Item"]
    assert (method["version"], method["isActive"]) == (1, True)


def test_a_sale_on_a_builtin_needs_no_condition_to_hold(units_table: Any) -> None:
    """A built-in has no row, so there is nothing to pin and the write is ordinary."""
    _seed_units(units_table)
    decision = _decision(units_table, PACK_ID, "OTHER", other_details="a twenty and a five")
    assert decision["condition"] is None

    _commit_sale(units_table, decision)

    assert _sale_rows(units_table)[0]["paymentMethodSnapshot"] == {
        "methodCode": "OTHER",
        "displayName": "Other",
        "otherDetails": "a twenty and a five",
    }


# --- money is classified by the code alone (AC-31) --------------------------------


def test_expected_cash_never_reads_the_display_text(units_table: Any) -> None:
    """AC-31: a method someone named Cash is a name; a cash sale is a code."""
    _seed_units(units_table)
    _method(units_table, PACK_ID, payment_method_id=CASH_BOX_ID, display_name="Cash")

    named_cash = _decision(units_table, PACK_ID, f"CUSTOM:{CASH_BOX_ID}")["snapshot"]
    assert named_cash["displayName"] == "Cash"
    assert expected_cash_cents(named_cash, 12_000) == 0

    assert expected_cash_cents(builtin_payment_method_snapshot("CASH", None), 12_000) == 12_000
    assert expected_cash_cents(builtin_payment_method_snapshot("CASH", None), "4500") == 4500
    assert expected_cash_cents(builtin_payment_method_snapshot("CHECK", None), 12_000) == 0
    other = builtin_payment_method_snapshot("OTHER", "half cash, half check; expected cash adjusted")
    assert expected_cash_cents(other, 12_000) == 0
