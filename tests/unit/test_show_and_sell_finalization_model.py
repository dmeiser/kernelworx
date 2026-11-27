"""Wave 6.1 (§5.1.1) — the finalization model: exact cash, complete snapshots, credit arithmetic.

The pure half of the Wave 6.1 surface. The resolver-level half — the preview read, the
rounding-draft write, the history queries — arrives with §5.1.2–§5.1.4; what is proved
here is the model itself, per the checklist's named model tests:

- **exact cash equations** (CASH-01..04): the adjustment/adjusted/discrepancy chain is
  derived, the two explanations are required at exactly the nonzero boundary, and a
  stored record is re-checked against its own arithmetic;
- **complete immutable inputs** (§5.16): a sale snapshot refuses a projection, a
  voided sale, an incomplete line, and a subtotal that does not sum to the total, and
  the deep copy survives a later rename of the source sale;
- **credit arithmetic** (SPLIT-02..SPLIT-10): one whole-event pool, floor shares,
  visible unassigned cents, Kernel-assigned rounding, and the exact-once pool
  invariant at approval;
- **projection scope** (§5.18): the total is keyed per Scout Campaign per Unit
  Campaign, moves only with credits of its own scope, and never underflows;
- **detail-to-total reconciliation** (DM-AC-08): the projection and its currently
  approved allocation detail must agree, row for row.

The later-state rows these tests seed (APPROVED, SUSPENDED, SUPERSEDED) are written
through this model layer only — the resolvers that transition them are §5.2 and §5.3.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.utils import show_and_sell_finalization_models as fm
from src.utils.errors import AppError, ErrorCode

EVENT = "SSE#fin-model"
UNIT_CAMPAIGN = "uc-fin-model"
OTHER_UNIT_CAMPAIGN = "uc-fin-model-other"
CAMPAIGN = "CAMPAIGN#scout-fin"
PRODUCT = "CATALOG#fin#prod-1"
PROFILE_A = "PROFILE#avery-fin"
PROFILE_B = "PROFILE#bruce-fin"
PROFILE_C = "PROFILE#cara-fin"
SLOT = "slot-fin-1"
ACCOUNT = "ACCOUNT#kernel-fin"
NOW = "2026-11-27T20:00:00+00:00"
FID = "11111111-1111-4111-8111-111111111111"


def _subcode(exc: AppError) -> str:
    assert exc.details is not None
    return str(exc.details["subcode"])


def _cash(**overrides: Any) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "calculated_expected_cents": 2500,
        "manual_adjustment_cents": 0,
        "manual_adjustment_reason": None,
        "actual_cash_cents": 2500,
        "discrepancy_explanation": None,
    }
    args.update(overrides)
    return fm.cash_reconciliation(**args)


def _finalization_row(**overrides: Any) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "show_and_sell_id": EVENT,
        "unit_campaign_id": UNIT_CAMPAIGN,
        "finalization_id": FID,
        "version_number": 1,
        "whole_pool_cents": 10_000,
        "split_method": "EQUAL",
        "cash": _cash(),
        "previous_finalization_id": None,
        "approved_by_account_id": ACCOUNT,
        "approved_at": NOW,
        "source_event_version": 7,
    }
    args.update(overrides)
    return fm.build_finalization_row(**args)


def _sale_row(**overrides: Any) -> Dict[str, Any]:
    sale: Dict[str, Any] = {
        "saleId": "sale-fin-1",
        "saleAt": "2026-11-27T18:30:00+00:00",
        "buyerName": "Nora",
        "buyerPhone": None,
        "buyerEmail": None,
        "enteredByAccountId": ACCOUNT,
        "lineItems": [
            {
                "lineItemId": "line-fin-1",
                "productId": PRODUCT,
                "productNameSnapshot": "Caramel Cremes",
                "unitPriceCentsSnapshot": 500,
                "immediateQty": 3,
                "weOweQty": 2,
                "subtotalCents": 2500,
            }
        ],
        "totalCents": 2500,
        "paymentMethodSnapshot": {"methodCode": "CASH", "displayNameSnapshot": "Cash", "paymentMethodId": "pm-1"},
        "revision": 1,
        "status": "ACTIVE",
    }
    sale.update(overrides)
    return sale


# --- identity and vocabulary --------------------------------------------------------


def test_finalization_id_is_bare_and_stable() -> None:
    fresh = fm.new_finalization_id()
    assert fm.normalize_finalization_id(fresh) == fresh
    assert fm.new_allocation_id() != fm.new_allocation_id()
    # A finalization id always has child markers after it, so no '#' at all — stricter
    # than the sale id, which is always last in its key.
    with pytest.raises(AppError) as exc:
        fm.normalize_finalization_id("FINALIZATION#oops")
    assert exc.value.error_code == ErrorCode.INVALID_INPUT


def test_status_and_split_vocabularies_are_closed() -> None:
    assert fm.normalize_finalization_status("APPROVED") == "APPROVED"
    assert fm.normalize_allocation_status("SUPERSEDED") == "SUPERSEDED"
    with pytest.raises(AppError):
        fm.normalize_finalization_status("PENDING")
    with pytest.raises(AppError):
        fm.normalize_allocation_status("VOIDED")
    assert fm.normalize_split_method("TIME_WORKED") == "TIME_WORKED"
    with pytest.raises(AppError):
        fm.normalize_split_method("PER_SLOT")


def test_version_number_and_signed_cents_boundaries() -> None:
    assert fm.normalize_version_number(1) == 1
    for bad in (0, -1, True, "2"):
        with pytest.raises(AppError) as exc:
            fm.normalize_version_number(bad)
        assert _subcode(exc.value) == fm.VERSION_NUMBER_INVALID
    assert fm.normalize_signed_cents(-40, "manualAdjustmentCents") == -40
    with pytest.raises(AppError):
        fm.normalize_signed_cents(True, "manualAdjustmentCents")
    with pytest.raises(AppError):
        fm.normalize_signed_cents(10**12, "manualAdjustmentCents")
    with pytest.raises(AppError):
        fm.normalize_signed_cents(-(10**12), "manualAdjustmentCents")


# --- key layout (§6.4) ---------------------------------------------------------------


def test_keys_place_every_child_under_one_partition() -> None:
    assert fm.finalization_sk(FID) == f"FINALIZATION#{FID}"
    assert fm.return_line_sk(FID, PRODUCT) == f"FINALIZATION#{FID}#RETURN#{PRODUCT}"
    assert fm.sale_snapshot_sk(FID, "sale-fin-1") == f"FINALIZATION#{FID}#SALE#sale-fin-1"
    assert fm.work_snapshot_sk(FID, SLOT, PROFILE_A) == f"FINALIZATION#{FID}#WORK#{SLOT}#{PROFILE_A}"
    assert fm.credit_sk(FID, PROFILE_A) == f"CREDIT#{FID}#{PROFILE_A}"
    assert fm.finalization_key(EVENT, FID) == {"pk": f"SHOW_AND_SELL#{EVENT}", "sk": f"FINALIZATION#{FID}"}
    assert fm.return_line_key(EVENT, FID, PRODUCT)["sk"].startswith("FINALIZATION#")
    assert fm.sale_snapshot_key(EVENT, FID, "sale-fin-1")["pk"] == f"SHOW_AND_SELL#{EVENT}"
    assert fm.work_snapshot_key(EVENT, FID, SLOT, PROFILE_A)["pk"] == f"SHOW_AND_SELL#{EVENT}"
    assert fm.credit_key(EVENT, FID, PROFILE_A)["pk"] == f"SHOW_AND_SELL#{EVENT}"


def test_total_key_is_unit_campaign_then_scout_campaign() -> None:
    key = fm.total_key(UNIT_CAMPAIGN, CAMPAIGN)
    # §6.2: the composite partition key is what makes §5.18's scope physical — there is
    # no key under which a cross-Unit-Campaign total could even be written.
    assert key == {
        "pk": f"UNIT_CAMPAIGN#{UNIT_CAMPAIGN}#SCOUT_CAMPAIGN#{CAMPAIGN}",
        "sk": "SHOW_AND_SELL_TOTAL",
    }
    with pytest.raises(AppError):
        fm.total_key("", CAMPAIGN)


# --- cash reconciliation (CASH-01..04) ----------------------------------------------


def test_cash_chain_is_computed_not_supplied() -> None:
    cash = fm.cash_reconciliation(
        calculated_expected_cents=2500,
        manual_adjustment_cents=1000,
        manual_adjustment_reason="Quinn's Other check held $10 in cash; plus a $10 split",
        actual_cash_cents=3400,
        discrepancy_explanation="one $1 candy bar paid cash was entered as Other",
    )
    assert cash[fm.CALCULATED_EXPECTED_CENTS_ATTRIBUTE] == 2500
    assert cash[fm.ADJUSTED_EXPECTED_CENTS_ATTRIBUTE] == 3500
    assert cash[fm.DISCREPANCY_CENTS_ATTRIBUTE] == -100


def test_zero_cash_path_needs_no_prose() -> None:
    cash = _cash()
    assert cash[fm.MANUAL_ADJUSTMENT_REASON_ATTRIBUTE] is None
    assert cash[fm.DISCREPANCY_EXPLANATION_ATTRIBUTE] is None
    assert cash[fm.DISCREPANCY_CENTS_ATTRIBUTE] == 0


def test_nonzero_adjustment_without_reason_is_refused() -> None:
    with pytest.raises(AppError) as exc:
        _cash(manual_adjustment_cents=1000)
    assert _subcode(exc.value) == fm.CASH_ADJUSTMENT_REASON_REQUIRED


def test_reason_without_adjustment_is_refused() -> None:
    with pytest.raises(AppError) as exc:
        _cash(manual_adjustment_reason="explains nothing")
    assert _subcode(exc.value) == fm.CASH_REASON_WITHOUT_ADJUSTMENT


def test_nonzero_discrepancy_without_explanation_is_refused() -> None:
    with pytest.raises(AppError) as exc:
        _cash(actual_cash_cents=2400)
    assert _subcode(exc.value) == fm.CASH_DISCREPANCY_EXPLANATION_REQUIRED


def test_explanation_without_discrepancy_is_refused() -> None:
    with pytest.raises(AppError) as exc:
        _cash(discrepancy_explanation="explains nothing")
    assert _subcode(exc.value) == fm.CASH_EXPLANATION_WITHOUT_DISCREPANCY


def test_adjusted_expected_cannot_go_negative() -> None:
    with pytest.raises(AppError) as exc:
        _cash(manual_adjustment_cents=-2501, manual_adjustment_reason="more than was collected")
    assert _subcode(exc.value) == fm.ADJUSTED_EXPECTED_NEGATIVE


def test_cash_inputs_are_money() -> None:
    with pytest.raises(AppError):
        _cash(calculated_expected_cents=-1)
    with pytest.raises(AppError):
        _cash(actual_cash_cents="25.00")


def test_stored_cash_map_is_rechecked_against_its_own_arithmetic() -> None:
    good = _cash()
    assert fm.validate_cash_reconciliation(good) == good
    broken = dict(good)
    broken[fm.DISCREPANCY_CENTS_ATTRIBUTE] = 999
    with pytest.raises(AppError) as exc:
        fm.validate_cash_reconciliation(broken)
    assert _subcode(exc.value) == fm.CASH_ARITHMETIC_BROKEN
    with pytest.raises(AppError):
        fm.validate_cash_reconciliation({**good, "extra": 1})
    with pytest.raises(AppError):
        fm.validate_cash_reconciliation({k: v for k, v in good.items() if k != fm.ACTUAL_CASH_CENTS_ATTRIBUTE})


# --- return reconciliation line (FIN-02..FIN-04) -------------------------------------


def test_expected_return_is_assigned_minus_recorded_sales() -> None:
    assert fm.expected_return_qty(5, 3) == 2
    assert fm.expected_return_qty(4, 4) == 0
    with pytest.raises(AppError) as exc:
        fm.expected_return_qty(2, 3)
    assert _subcode(exc.value) == "SOLD_ABOVE_ALLOCATED"


def test_return_line_derives_variance_and_net_effect() -> None:
    line = fm.build_return_line_row(
        show_and_sell_id=EVENT,
        finalization_id=FID,
        product_id=PRODUCT,
        allocated_qty=10,
        expected_qty=7,
        actual_qty=6,
        reconciliation_movement_id="mov-fin-1",
        reason="one box opened and squished at the table",
    )
    assert line["sk"] == f"FINALIZATION#{FID}#RETURN#{PRODUCT}"
    assert line[fm.VARIANCE_QTY_ATTRIBUTE] == -1
    assert line[fm.NET_STOCK_EFFECT_QTY_ATTRIBUTE] == -4
    assert line["entityType"] == fm.RETURN_LINE_ENTITY_TYPE
    zero = fm.build_return_line_row(
        show_and_sell_id=EVENT,
        finalization_id=FID,
        product_id=PRODUCT,
        allocated_qty=10,
        expected_qty=7,
        actual_qty=7,
    )
    assert zero[fm.VARIANCE_QTY_ATTRIBUTE] == 0
    assert zero[fm.RECONCILIATION_MOVEMENT_ID_ATTRIBUTE] is None


def test_first_version_variance_needs_its_adjustment_link() -> None:
    with pytest.raises(AppError) as exc:
        fm.build_return_line_row(
            show_and_sell_id=EVENT,
            finalization_id=FID,
            product_id=PRODUCT,
            allocated_qty=10,
            expected_qty=7,
            actual_qty=8,
        )
    assert _subcode(exc.value) == fm.RETURN_VARIANCE_UNADJUSTED
    # A re-finalization version (informational variance, §5.3) still needs a reason
    # whenever it links a stock-only adjustment, and an adjustment with no variance to
    # adjust is refused outright.
    informational = fm.build_return_line_row(
        show_and_sell_id=EVENT,
        finalization_id=FID,
        product_id=PRODUCT,
        allocated_qty=10,
        expected_qty=7,
        actual_qty=8,
        informational_variance=True,
    )
    assert informational[fm.VARIANCE_QTY_ATTRIBUTE] == 1
    with pytest.raises(AppError) as exc:
        fm.build_return_line_row(
            show_and_sell_id=EVENT,
            finalization_id=FID,
            product_id=PRODUCT,
            allocated_qty=10,
            expected_qty=7,
            actual_qty=7,
            reconciliation_movement_id="mov-fin-2",
            reason="moved something that did not move",
        )
    assert _subcode(exc.value) == fm.STOCK_ADJUSTMENT_WITHOUT_VARIANCE
    with pytest.raises(AppError) as exc:
        fm.build_return_line_row(
            show_and_sell_id=EVENT,
            finalization_id=FID,
            product_id=PRODUCT,
            allocated_qty=10,
            expected_qty=7,
            actual_qty=6,
            reconciliation_movement_id="mov-fin-3",
        )
    assert exc.value.error_code == ErrorCode.INVALID_INPUT


# --- immutable sale-input snapshot (§5.16) -------------------------------------------


def test_sale_snapshot_is_the_complete_sale_deep_copied() -> None:
    sale = _sale_row()
    snapshot = fm.build_sale_snapshot_row(FID, sale, show_and_sell_id=EVENT)
    assert snapshot["sk"] == f"FINALIZATION#{FID}#SALE#sale-fin-1"
    assert snapshot[fm.LINE_ITEMS_ATTRIBUTE] == sale["lineItems"]
    assert snapshot[fm.PAYMENT_SNAPSHOT_ATTRIBUTE] == sale["paymentMethodSnapshot"]
    # PAY-06 one level up: a later rename of the source sale — or of the catalog behind
    # it — cannot reach a version that already happened.
    sale["lineItems"][0]["productNameSnapshot"] = "Renamed Caramels"
    sale["paymentMethodSnapshot"]["displayNameSnapshot"] = "Renamed Cash"
    assert snapshot[fm.LINE_ITEMS_ATTRIBUTE][0]["productNameSnapshot"] == "Caramel Cremes"
    assert snapshot[fm.PAYMENT_SNAPSHOT_ATTRIBUTE]["displayNameSnapshot"] == "Cash"


def test_sale_snapshot_refuses_incomplete_projection_or_voided_source() -> None:
    with pytest.raises(AppError) as exc:
        fm.build_sale_snapshot_row(FID, {"saleId": "s", "status": "ACTIVE"}, show_and_sell_id=EVENT)
    assert _subcode(exc.value) == fm.SNAPSHOT_INPUT_INCOMPLETE
    assert exc.value.details is not None and "lineItems" in exc.value.details["missing"]
    with pytest.raises(AppError) as exc:
        fm.build_sale_snapshot_row(FID, _sale_row(status="VOIDED"), show_and_sell_id=EVENT)
    assert _subcode(exc.value) == fm.SNAPSHOT_INPUT_INCOMPLETE
    with pytest.raises(AppError) as exc:
        fm.build_sale_snapshot_row(FID, _sale_row(lineItems="not-a-list"), show_and_sell_id=EVENT)
    assert _subcode(exc.value) == fm.SNAPSHOT_INPUT_INCOMPLETE
    short_line = {"lineItemId": "line-x", "productId": PRODUCT}
    with pytest.raises(AppError) as exc:
        fm.build_sale_snapshot_row(FID, _sale_row(lineItems=[short_line]), show_and_sell_id=EVENT)
    assert exc.value.details is not None and "subtotalCents" in exc.value.details["missing"]
    # A snapshot whose parts do not sum to its whole is a second, disagreeing answer
    # about the pool.
    lying = _sale_row(totalCents=2400)
    with pytest.raises(AppError) as exc:
        fm.build_sale_snapshot_row(FID, lying, show_and_sell_id=EVENT)
    assert exc.value.details is not None and exc.value.details["subtotalSum"] == 2500


# --- immutable work-input snapshot (§5.16) -------------------------------------------


def test_work_snapshot_carries_exactly_the_five_inputs() -> None:
    row = fm.build_work_snapshot_row(
        finalization_id=FID,
        show_and_sell_id=EVENT,
        slot_id=SLOT,
        profile_id=PROFILE_A,
        campaign_id=CAMPAIGN,
        actual_minutes=150,
        source_signup_version=3,
    )
    assert row["sk"] == f"FINALIZATION#{FID}#WORK#{SLOT}#{PROFILE_A}"
    assert set(row) == fm.WORK_SNAPSHOT_ROW_ATTRIBUTES
    assert row[fm.ACTUAL_MINUTES_ATTRIBUTE] == 150
    # A snapshot exists only for confirmed work; zero would be an un-confirmed signup
    # taking a share of the pool.
    with pytest.raises(AppError):
        fm.build_work_snapshot_row(
            finalization_id=FID,
            show_and_sell_id=EVENT,
            slot_id=SLOT,
            profile_id=PROFILE_A,
            campaign_id=CAMPAIGN,
            actual_minutes=0,
            source_signup_version=3,
        )
    with pytest.raises(AppError):
        fm.build_work_snapshot_row(
            finalization_id=FID,
            show_and_sell_id=EVENT,
            slot_id=SLOT,
            profile_id=PROFILE_A,
            campaign_id=CAMPAIGN,
            actual_minutes=150,
            source_signup_version=0,
        )


# --- the finalization version row (§5.16) ---------------------------------------------


def test_finalization_row_is_born_approved_and_shaped() -> None:
    row = _finalization_row()
    assert set(row) == fm.FINALIZATION_ROW_ATTRIBUTES
    assert row[fm.STATUS_ATTRIBUTE] == "APPROVED"
    assert row[fm.PREVIOUS_FINALIZATION_ID_ATTRIBUTE] is None
    assert row[fm.SUSPENSION_REASON_ATTRIBUTE] is None
    chained = _finalization_row(version_number=2, previous_finalization_id=FID)
    assert chained[fm.PREVIOUS_FINALIZATION_ID_ATTRIBUTE] == FID
    with pytest.raises(AppError):
        _finalization_row(previous_finalization_id="FINALIZATION#oops")
    with pytest.raises(AppError):
        _finalization_row(whole_pool_cents=-1)


def test_suspend_transform_requires_approval_and_a_reason() -> None:
    suspended = fm.mark_finalization_suspended(
        _finalization_row(), suspended_by_account_id=ACCOUNT, suspended_at=NOW, suspension_reason="cash count was wrong"
    )
    assert suspended[fm.STATUS_ATTRIBUTE] == "SUSPENDED"
    assert suspended[fm.SUSPENSION_REASON_ATTRIBUTE] == "cash count was wrong"
    assert _finalization_row()[fm.STATUS_ATTRIBUTE] == "APPROVED"  # transform, not mutation
    with pytest.raises(AppError) as exc:
        fm.mark_finalization_suspended(
            suspended, suspended_by_account_id=ACCOUNT, suspended_at=NOW, suspension_reason="again"
        )
    assert _subcode(exc.value) == fm.FINALIZATION_STATE_INVALID
    with pytest.raises(AppError):
        fm.mark_finalization_suspended(
            _finalization_row(), suspended_by_account_id=ACCOUNT, suspended_at=NOW, suspension_reason="  "
        )


def test_supersede_transform_retires_only_an_approved_version() -> None:
    superseded = fm.mark_finalization_superseded(_finalization_row())
    assert superseded[fm.STATUS_ATTRIBUTE] == "SUPERSEDED"
    with pytest.raises(AppError) as exc:
        fm.mark_finalization_superseded(superseded)
    assert _subcode(exc.value) == fm.FINALIZATION_STATE_INVALID


def test_a_hand_written_row_missing_a_declared_attribute_is_refused() -> None:
    # The row-shape guard is the §5.10 discipline: a stored row that does not carry
    # every attribute the model declares is refused on the way back out, rather than
    # quietly propagated into a report that reads its gap as a null.
    malformed = _finalization_row()
    del malformed[fm.SOURCE_EVENT_VERSION_ATTRIBUTE]
    with pytest.raises(AppError) as exc:
        fm.mark_finalization_suspended(
            malformed, suspended_by_account_id=ACCOUNT, suspended_at=NOW, suspension_reason="count was wrong"
        )
    assert _subcode(exc.value) == fm.SNAPSHOT_INPUT_INCOMPLETE
    assert exc.value.details["missing"] == [fm.SOURCE_EVENT_VERSION_ATTRIBUTE]


# --- credit arithmetic (SPLIT-02..SPLIT-10) -------------------------------------------


def test_pool_is_one_whole_event_sum_over_active_sales() -> None:
    sales = [
        _sale_row(saleId="s1", totalCents=30_000),
        _sale_row(saleId="s2", totalCents=10_000),  # slot two of the same event
        _sale_row(saleId="s3", totalCents=5_00, status="VOIDED"),
    ]
    # SPLIT-02's example: $300 morning + $100 afternoon is one $400 pool, and a voided
    # sale is not part of it. A We Owe sale's total already carries the owed line.
    assert fm.whole_pool_cents(sales) == 40_000
    assert fm.whole_pool_cents([]) == 0


def test_equal_split_rounds_down_and_leaves_cents_visible() -> None:
    shares = fm.base_shares(
        whole_pool_cents=10_000,
        split_method="EQUAL",
        eligible_work=[(PROFILE_A, 60), (PROFILE_B, 60), (PROFILE_C, 60)],
    )
    # AC-55 / SPLIT-10: $100 three ways starts at $33.33 each, one cent unassigned.
    assert shares == {PROFILE_A: 3333, PROFILE_B: 3333, PROFILE_C: 3333}
    assert fm.unassigned_cents(10_000, shares) == 1


def test_time_worked_split_weights_by_confirmed_minutes() -> None:
    # $60 with 240 + 120 confirmed minutes: $40 and $20 exactly.
    shares = fm.base_shares(
        whole_pool_cents=6_000,
        split_method="TIME_WORKED",
        eligible_work=[(PROFILE_A, 240), (PROFILE_B, 120)],
    )
    assert shares == {PROFILE_A: 4_000, PROFILE_B: 2_000}
    assert fm.unassigned_cents(6_000, shares) == 0
    # EQUAL ignores minutes entirely (SPLIT-03); TIME_WORKED refuses zero minutes.
    equal = fm.base_shares(whole_pool_cents=1_000, split_method="EQUAL", eligible_work=[(PROFILE_A, 0)])
    assert equal == {PROFILE_A: 1_000}
    with pytest.raises(AppError) as exc:
        fm.base_shares(whole_pool_cents=1_000, split_method="TIME_WORKED", eligible_work=[(PROFILE_A, 0)])
    assert _subcode(exc.value) == fm.TIME_WORKED_MINUTES_REQUIRED
    with pytest.raises(AppError) as exc:
        fm.base_shares(whole_pool_cents=1_000, split_method="EQUAL", eligible_work=[(PROFILE_A, 60), (PROFILE_A, 30)])
    assert _subcode(exc.value) == fm.DUPLICATE_ROUNDING_PARTICIPANT
    assert fm.base_shares(whole_pool_cents=500, split_method="EQUAL", eligible_work=[]) == {}


def test_rounding_assignments_are_unique_nonnegative_and_bounded() -> None:
    assignments = fm.normalize_rounding_assignments(
        [{"profileId": PROFILE_A, "cents": 1}, {"profileId": PROFILE_B, "cents": 0}]
    )
    assert assignments == {PROFILE_A: 1, PROFILE_B: 0}
    with pytest.raises(AppError) as exc:
        fm.normalize_rounding_assignments([{"profileId": PROFILE_A, "cents": 1}, {"profileId": PROFILE_A, "cents": 1}])
    assert _subcode(exc.value) == fm.DUPLICATE_ROUNDING_PARTICIPANT
    with pytest.raises(AppError):
        fm.normalize_rounding_assignments([{"profileId": PROFILE_A, "cents": -1}])

    fm.validate_rounding_draft(assignments, eligible_profile_ids=[PROFILE_A, PROFILE_B], unassigned=1)
    with pytest.raises(AppError) as exc:
        fm.validate_rounding_draft(assignments, eligible_profile_ids=[PROFILE_A], unassigned=1)
    assert _subcode(exc.value) == fm.ROUNDING_PARTICIPANT_INELIGIBLE
    with pytest.raises(AppError) as exc:
        fm.validate_rounding_draft(assignments, eligible_profile_ids=[PROFILE_A, PROFILE_B], unassigned=0)
    assert _subcode(exc.value) == fm.ROUNDING_OVERSUM


def test_credit_row_amount_is_base_plus_rounding_never_supplied() -> None:
    credit = fm.build_credit_row(
        finalization=_finalization_row(),
        campaign_id=CAMPAIGN,
        profile_id=PROFILE_A,
        actual_minutes=240,
        base_amount_cents=3_333,
        rounding_credit_cents=1,
        created_at=NOW,
        updated_at=NOW,
    )
    assert credit["sk"] == f"CREDIT#{FID}#{PROFILE_A}"
    assert set(credit) == fm.CREDIT_ROW_ATTRIBUTES
    assert credit[fm.AMOUNT_CENTS_ATTRIBUTE] == 3_334
    assert credit[fm.STATUS_ATTRIBUTE] == "APPROVED"
    with pytest.raises(AppError):
        fm.build_credit_row(
            finalization=_finalization_row(),
            campaign_id=CAMPAIGN,
            profile_id=PROFILE_A,
            actual_minutes=240,
            base_amount_cents=3_333,
            rounding_credit_cents=1,
            created_at=NOW,
            updated_at=NOW,
            status="PENDING",
        )


def test_approved_allocations_equal_the_pool_exactly_once() -> None:
    finalization = _finalization_row(whole_pool_cents=10_000)
    credits = [
        fm.build_credit_row(
            finalization=finalization,
            campaign_id=CAMPAIGN,
            profile_id=profile,
            actual_minutes=60,
            base_amount_cents=3_333,
            rounding_credit_cents=rounding,
            created_at=NOW,
            updated_at=NOW,
        )
        for profile, rounding in ((PROFILE_A, 1), (PROFILE_B, 0), (PROFILE_C, 0))
    ]
    fm.validate_credit_set(finalization, credits)
    # A short sum — the cent never assigned — is exactly as much a refusal (SPLIT-09).
    with pytest.raises(AppError) as exc:
        fm.validate_credit_set(finalization, credits[:2])
    assert _subcode(exc.value) == fm.CREDIT_POOL_MISMATCH
    broken = dict(credits[0])
    broken[fm.AMOUNT_CENTS_ATTRIBUTE] = 9_999
    with pytest.raises(AppError) as exc:
        fm.validate_credit_set(finalization, [broken, credits[1], credits[2]])
    assert _subcode(exc.value) == fm.CREDIT_POOL_MISMATCH
    suspended = dict(credits[2])
    suspended[fm.STATUS_ATTRIBUTE] = "SUSPENDED"
    with pytest.raises(AppError) as exc:
        fm.validate_credit_set(finalization, [credits[0], credits[1], suspended])
    assert _subcode(exc.value) == fm.CREDIT_POOL_MISMATCH


# --- the Unit-Campaign-scoped total (§5.18, DM-AC-08) ---------------------------------


def _credit_row(**overrides: Any) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "finalization": _finalization_row(),
        "campaign_id": CAMPAIGN,
        "profile_id": PROFILE_A,
        "actual_minutes": 240,
        "base_amount_cents": 3_333,
        "rounding_credit_cents": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    args.update(overrides)
    return fm.build_credit_row(**args)


def test_total_row_is_built_in_its_composite_scope() -> None:
    row = fm.build_total_row(
        campaign_id=CAMPAIGN,
        profile_id=PROFILE_A,
        unit_campaign_id=UNIT_CAMPAIGN,
        approved_amount_cents=0,
        version=1,
        updated_at=NOW,
    )
    assert set(row) == fm.TOTAL_ROW_ATTRIBUTES
    assert row["pk"] == f"UNIT_CAMPAIGN#{UNIT_CAMPAIGN}#SCOUT_CAMPAIGN#{CAMPAIGN}"
    with pytest.raises(AppError):
        fm.build_total_row(
            campaign_id=CAMPAIGN,
            profile_id=PROFILE_A,
            unit_campaign_id=UNIT_CAMPAIGN,
            approved_amount_cents=-1,
            version=1,
            updated_at=NOW,
        )


def test_total_moves_only_with_credits_of_its_own_scope(unit_campaigns_table: Any) -> None:
    credit = _credit_row()
    created = fm.apply_approved_credit(None, credit=credit, updated_at=NOW)
    assert created[fm.APPROVED_AMOUNT_CENTS_ATTRIBUTE] == 3_334
    assert created[fm.VERSION_ATTRIBUTE] == 1
    twice = fm.apply_approved_credit(created, credit=credit, updated_at=NOW)
    assert twice[fm.APPROVED_AMOUNT_CENTS_ATTRIBUTE] == 6_668
    assert twice[fm.VERSION_ATTRIBUTE] == 2
    # §5.18: "never shared across Unit Campaigns" — enforced at the arithmetic.
    other = dict(created)
    other[fm.UNIT_CAMPAIGN_ID_ATTRIBUTE] = OTHER_UNIT_CAMPAIGN
    other["pk"] = fm.total_key(OTHER_UNIT_CAMPAIGN, CAMPAIGN)["pk"]
    with pytest.raises(AppError) as exc:
        fm.apply_approved_credit(other, credit=credit, updated_at=NOW)
    assert _subcode(exc.value) == fm.TOTAL_SCOPE_MISMATCH
    # The projection is a real row in the unit_campaigns table, readable by its key.
    unit_campaigns_table.put_item(Item=created)
    loaded = fm.load_campaign_total(UNIT_CAMPAIGN, CAMPAIGN)
    assert loaded is not None
    assert int(loaded[fm.APPROVED_AMOUNT_CENTS_ATTRIBUTE]) == 3_334
    assert fm.load_campaign_total("uc-never-written", CAMPAIGN) is None


def test_reversal_never_underflows() -> None:
    total = fm.apply_approved_credit(None, credit=_credit_row(), updated_at=NOW)
    backed = fm.reverse_approved_credit(total, amount_cents=3_334, updated_at=NOW)
    assert backed[fm.APPROVED_AMOUNT_CENTS_ATTRIBUTE] == 0
    assert backed[fm.VERSION_ATTRIBUTE] == 2
    with pytest.raises(AppError) as exc:
        fm.reverse_approved_credit(backed, amount_cents=1, updated_at=NOW)
    assert _subcode(exc.value) == fm.TOTAL_CREDIT_UNDERFLOW


def test_detail_to_total_reconciliation_proves_the_pair(unit_campaigns_table: Any) -> None:
    total = fm.apply_approved_credit(None, credit=_credit_row(), updated_at=NOW)
    other_finalization = _finalization_row(
        finalization_id="22222222-2222-4222-8222-222222222222",
        version_number=2,
        previous_finalization_id=FID,
    )
    second = _credit_row(finalization=other_finalization, base_amount_cents=3_000, rounding_credit_cents=0)
    credits = [_credit_row(), second]
    # 3334 + 3000 approved detail vs the running total.
    total = fm.apply_approved_credit(total, credit=second, updated_at=NOW)
    fm.reconcile_total_with_credits(total, credits)
    with pytest.raises(AppError) as exc:
        fm.reconcile_total_with_credits(total, credits[:1])
    assert _subcode(exc.value) == fm.DETAIL_TOTAL_MISMATCH
    # A row from another scope is refused, not silently excluded — a reconciliation
    # that quietly ignores rows proves nothing.
    foreign = _credit_row()
    foreign[fm.UNIT_CAMPAIGN_ID_ATTRIBUTE] = OTHER_UNIT_CAMPAIGN
    with pytest.raises(AppError) as exc:
        fm.reconcile_total_with_credits(total, credits + [foreign])
    assert _subcode(exc.value) == fm.TOTAL_SCOPE_MISMATCH
    # Inactive rows from another scope are simply not part of this reconciliation —
    # and one in the middle, so the sweep continues past the skipped row.
    foreign_suspended = dict(foreign)
    foreign_suspended[fm.STATUS_ATTRIBUTE] = "SUSPENDED"
    fm.reconcile_total_with_credits(total, credits[:1] + [foreign_suspended] + credits[1:])
    # A suspended credit in this very scope is excluded too — the projection carries
    # currently approved detail only, and the reopened version's replacement is the
    # separate row that §5.3.3 publishes.
    own_suspended = dict(credits[0])
    own_suspended[fm.STATUS_ATTRIBUTE] = "SUSPENDED"
    fm.reconcile_total_with_credits(total, credits + [own_suspended])


# --- partition reads (§6.4) -----------------------------------------------------------


def test_reads_answer_versions_children_and_credits_separately(show_and_sells_table: Any) -> None:
    version = _finalization_row()
    fid2 = "22222222-2222-4222-8222-222222222222"
    second = _finalization_row(finalization_id=fid2, version_number=2, previous_finalization_id=FID)
    suspended = fm.mark_finalization_suspended(
        second, suspended_by_account_id=ACCOUNT, suspended_at=NOW, suspension_reason="reopen"
    )
    line = fm.build_return_line_row(
        show_and_sell_id=EVENT,
        finalization_id=FID,
        product_id=PRODUCT,
        allocated_qty=5,
        expected_qty=2,
        actual_qty=2,
    )
    snapshot = fm.build_sale_snapshot_row(FID, _sale_row(), show_and_sell_id=EVENT)
    work = fm.build_work_snapshot_row(
        finalization_id=FID,
        show_and_sell_id=EVENT,
        slot_id=SLOT,
        profile_id=PROFILE_A,
        campaign_id=CAMPAIGN,
        actual_minutes=60,
        source_signup_version=2,
    )
    credit = _credit_row()
    for row in (version, line, snapshot, work, credit):
        show_and_sells_table.put_item(Item=row)
    show_and_sells_table.put_item(Item=suspended)

    versions = fm.finalization_rows(EVENT)
    assert len(versions) == 2  # children excluded; both lifecycle states are versions
    assert {v[fm.STATUS_ATTRIBUTE] for v in versions} == {"APPROVED", "SUSPENDED"}
    assert fm.finalization_rows("SSE#no-events-here") == []

    loaded = fm.read_finalization(EVENT, FID)
    assert loaded is not None and loaded[fm.STATUS_ATTRIBUTE] == "APPROVED"
    assert fm.read_finalization(EVENT, "33333333-3333-4333-8333-333333333333") is None

    assert [r[fm.PRODUCT_ID_ATTRIBUTE] for r in fm.finalization_return_line_rows(EVENT, FID)] == [PRODUCT]
    assert [r[fm.SALE_ID_ATTRIBUTE] for r in fm.finalization_sale_snapshot_rows(EVENT, FID)] == ["sale-fin-1"]
    assert [r[fm.PROFILE_ID_ATTRIBUTE] for r in fm.finalization_work_snapshot_rows(EVENT, FID)] == [PROFILE_A]
    assert [r[fm.PROFILE_ID_ATTRIBUTE] for r in fm.finalization_credit_rows(EVENT, FID)] == [PROFILE_A]
    assert fm.finalization_credit_rows(EVENT, "44444444-4444-4444-8444-444444444444") == []
    assert fm.finalization_return_line_rows(EVENT, "44444444-4444-4444-8444-444444444444") == []
    assert fm.finalization_sale_snapshot_rows(EVENT, "44444444-4444-4444-8444-444444444444") == []
    assert fm.finalization_work_snapshot_rows(EVENT, "44444444-4444-4444-8444-444444444444") == []
