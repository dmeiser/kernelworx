"""Leaf 4.6.6 — every Stage 4 endpoint, and who is turned away from it.

Two halves, both driven through the deployed handler entrypoint with the raw AppSync
identity each caller class actually produces:

1. every documented payment / sale / We Owe field answers for the Unit Admins of the
   event's Unit — the eleven Stage 4 mutations and five queries, including the QR
   request → upload → confirm → download → delete chain against a real object, so each
   endpoint description is exercised rather than merely read;
2. the same fields against callers who must not reach them: a Scout-owning parent with no
   grant (SS-SM-07 step 1's Morgan, the fixture world's Taylor), the outsider who is sole
   admin of another Unit and holds only a read share here (READ-only Riley), a caller whose
   token carries the global ``ADMIN`` group and no grant at all (AUTH-U-03), a Unit Admin of
   this Unit aiming at another Unit's rows (cross-Unit), and the three session-less shapes —
   no identity, an empty identity, and the API-key identity with an ``apiKeyId`` and no
   ``sub``.

A denial is only worth recording if the row it wanted is still there and unchanged, so every
denied case snapshots the whole Stage 4 state — sales, sale revisions, obligations,
fulfilments, payment rows, the payment capacity counter, movements and idempotency markers —
and compares it afterwards. A denial that answers ``NOT_FOUND`` after writing something is
caught here, and so is one whose message repeats the private id it just refused to name.

The fixture world's role mapping, because the smoke plan's names are not fixture personas:
``Taylor`` is the plan's Morgan (owns Scout profiles, no Unit Admin grant), ``Riley`` is the
plan's Riley (sole admin of Crew 529, a read share on Avery's Scout, nothing on Pack 3149),
and the global ADMIN is a bare ``sub`` plus a ``cognito:groups`` claim, the way
``src.utils.auth.is_admin`` reads one.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pytest

from src.handlers.unit_operations import (
    CONFIRM_PAYMENT_QR_FIELD,
    CORRECT_SALE_FIELD,
    CREATE_PAYMENT_METHOD_FIELD,
    CREATE_SALE_FIELD,
    DEACTIVATE_PAYMENT_METHOD_FIELD,
    DELETE_PAYMENT_QR_FIELD,
    FULFILL_WE_OWE_FIELD,
    PAYMENT_QR_DOWNLOAD_FIELD,
    REQUEST_PAYMENT_QR_FIELD,
    SET_WE_OWE_RESERVATION_FIELD,
    SHOW_AND_SELL_SALES_FIELD,
    UNIT_PAYMENT_METHODS_FIELD,
    UPDATE_PAYMENT_METHOD_FIELD,
    VOID_SALE_FIELD,
    WE_OWE_OBLIGATION_FIELD,
    WE_OWE_OBLIGATIONS_FIELD,
    handle_unit_operation,
)
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from src.utils import unit_payment_models as upm
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    TROOP_7150,
    account_id,
    assert_is_error,
    grant_item,
    seed_show_sell_fixtures,
    unit_campaign_item,
)
from tests.unit.test_show_and_sell_sales import (
    ACTIVE_EVENT,
    CAMPAIGN,
    CATALOG_ID,
    PRODUCT,
    SALE_AT,
    _create,
    _line,
    _ok,
    _seed_event,
    _seed_stock,
)

#: The Pack's Unit Admin in this world — the smoke plan's Alex.
ALEX = "Avery"
#: A second equal Unit Admin, so the check is proved to be a grant and not a creator check.
CASEY = "Devon"
#: SS-SM-07 step 1's Morgan: owns the lane's Scouts, no grant on Pack 3149.
MORGAN = "Taylor"
#: READ-only Riley: sole admin of Troop 7150, a read share on this Unit's Scout, no grant here.
RILEY = "Riley"
#: A removed admin of Pack 3149 (AUTH-U-01's revoked grant).
REVOKED = "Blake"
#: The Owner analogue: a global application ADMIN with no grant on Pack 3149 (AUTH-U-03).
GLOBAL_ADMIN_SUB = "77777777-7777-4777-8777-777777777777"

#: Riley's Troop — the other Unit in this world, and the desk a Pack admin must not reach.
FOREIGN_UNIT = TROOP_7150
#: A real Unit Campaign and event on that Troop, so the cross-Unit half points a live grant at
#: rows that exist and belong to someone else. An id that never existed would only prove the
#: handler can answer NOT_FOUND for nothing.
FOREIGN_CAMPAIGN = "SUC#7150-fall-desk"
FOREIGN_EVENT = "SSE#7150-fall-desk"

#: The five fields the Stage 4 SDL exposes as queries.
STAGE4_QUERY_FIELDS = (
    SHOW_AND_SELL_SALES_FIELD,
    WE_OWE_OBLIGATIONS_FIELD,
    WE_OWE_OBLIGATION_FIELD,
    UNIT_PAYMENT_METHODS_FIELD,
    PAYMENT_QR_DOWNLOAD_FIELD,
)

#: The eleven Stage 4 mutations.
STAGE4_MUTATION_FIELDS = (
    CREATE_SALE_FIELD,
    CORRECT_SALE_FIELD,
    VOID_SALE_FIELD,
    SET_WE_OWE_RESERVATION_FIELD,
    FULFILL_WE_OWE_FIELD,
    CREATE_PAYMENT_METHOD_FIELD,
    UPDATE_PAYMENT_METHOD_FIELD,
    DEACTIVATE_PAYMENT_METHOD_FIELD,
    REQUEST_PAYMENT_QR_FIELD,
    CONFIRM_PAYMENT_QR_FIELD,
    DELETE_PAYMENT_QR_FIELD,
)

STAGE4_FIELDS: Tuple[str, ...] = STAGE4_QUERY_FIELDS + STAGE4_MUTATION_FIELDS

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _identity(name: str, *, groups: Optional[List[str]] = None) -> Dict[str, Any]:
    """The identity AppSync hands a signed-in caller, optionally with group claims."""
    identity: Dict[str, Any] = {"sub": account_id(name)}
    if groups is not None:
        identity["claims"] = {"sub": account_id(name), "cognito:groups": groups}
    return identity


def _event(
    field: str,
    identity: Optional[Mapping[str, Any]],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The raw invoke payload, with exactly the identity this case wants.

    Not the persona-shaped helper: the API-key and group-claim shapes below have no persona,
    and what is under test is the shape AppSync really sends.
    """
    block: Dict[str, Any] = dict(arguments) if arguments is not None else {"input": mutation}
    return {
        "arguments": block,
        "identity": identity,
        "requestContext": {"requestId": "stage4-auth-sweep"},
        "info": {"fieldName": field, "parentTypeName": "Query" if field in STAGE4_QUERY_FIELDS else "Mutation"},
    }


# ---------------------------------------------------------------------------
# The arranged desk: an event with stock, one sale with an obligation, and a
# payment method the endpoints can address.
# ---------------------------------------------------------------------------


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
    """The Stage 1 personas, with Devon added as a second equal admin of Pack 3149."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    units_table.put_item(Item=grant_item(PACK_3149, CASEY, created_by=ALEX))
    units_table.put_item(
        Item=unit_campaign_item(
            FOREIGN_CAMPAIGN,
            unit_id=FOREIGN_UNIT,
            campaign_name="Troop 7150 Fall Show & Sell",
            campaign_year=2026,
            catalog_id=CATALOG_ID,
            join_code="JOINTR7150FALL01",
            created_by="Riley",
        )
    )
    return {
        "units": units_table,
        "unit_campaigns": unit_campaigns_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
    }


def _state(world: Dict[str, Any]) -> List[Tuple[str, str, str, str]]:
    """Every row in every table Stage 4 writes, as an address plus a payload digest.

    Snapshotting the whole surface rather than one row is what turns "the denial was polite"
    into "the denial changed nothing": a resolver that authorized after writing moves this
    list, whatever row it happened to touch.
    """
    rows: List[Tuple[str, str, str, str]] = []
    for name in ("units", "inventory", "show_and_sells"):
        for row in world[name].scan()["Items"]:
            payload = str(sorted((key, str(value)) for key, value in row.items() if key not in ("pk", "sk")))
            rows.append((name, str(row["pk"]), str(row["sk"]), payload))
    return rows


def _arrange(world: Dict[str, Any]) -> Dict[str, str]:
    """The stock, event, payment method, sale and obligation the endpoints address."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT, product_ids=[PRODUCT], we_owe_enabled=True)
    # Riley's Troop has a real event of its own, so the cross-Unit cases aim at a row that
    # exists in another tenant rather than at a made-up id.
    _seed_event(
        world["show_and_sells"],
        FOREIGN_EVENT,
        product_ids=[PRODUCT],
        we_owe_enabled=True,
        **{ssm.UNIT_ID_ATTRIBUTE: FOREIGN_UNIT, ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: FOREIGN_CAMPAIGN},
    )
    #: Six boxes in Kernel stock, four assigned to the event: the two unassigned ones are
    #: what a reservation may claim, so the reservation endpoint has something to answer.
    _seed_stock(world, product_id=PRODUCT, physical=6, allocated=4)
    venmo = _ok(
        handle_unit_operation(
            _event(
                CREATE_PAYMENT_METHOD_FIELD,
                _identity("Avery"),
                mutation={"unitId": PACK_3149, "displayName": "Venmo", "idempotency": {"idempotencyKey": "auth-venmo"}},
            ),
            None,
        )
    )
    sale = _ok(
        _create(
            "Avery",
            lines=[_line(PRODUCT, immediate=1, we_owe=1)],
            buyerName="Quinn Buyer",
            otherDetails="Apple Pay; Kernel reimbursed the unit by Venmo",
            paymentMethodCode="OTHER",
            key="auth-sale",
        )
    )
    obligations = sm.sale_obligations(ACTIVE_EVENT, str(sale["sale"]["saleId"]))
    assert obligations, "the arranged sale is meant to owe a unit of stock"
    return {
        "paymentMethodId": str(venmo["paymentMethodId"]),
        "saleId": str(sale["sale"]["saleId"]),
        "weOweId": str(obligations[0][sm.WE_OWE_ID_ATTRIBUTE]),
    }


@pytest.fixture
def desk(world: Dict[str, Any]) -> Dict[str, Any]:
    """The arranged rows, plus the state that arrangement left behind."""
    ids = _arrange(world)
    return {"world": world, "ids": ids, "state": _state(world)}


def _arguments(field: str, ids: Mapping[str, str]) -> Dict[str, Any]:
    """The argument block one query needs, addressed at the arranged rows."""
    if field == SHOW_AND_SELL_SALES_FIELD:
        return {"showAndSellId": ACTIVE_EVENT}
    if field == WE_OWE_OBLIGATIONS_FIELD:
        return {"unitCampaignId": CAMPAIGN}
    if field == WE_OWE_OBLIGATION_FIELD:
        return {"weOweId": ids["weOweId"]}
    if field == UNIT_PAYMENT_METHODS_FIELD:
        return {"unitId": PACK_3149}
    if field == PAYMENT_QR_DOWNLOAD_FIELD:
        return {"unitId": PACK_3149, "paymentMethodId": ids["paymentMethodId"]}
    raise AssertionError(f"{field} is a mutation and takes an input block")


def _input(field: str, ids: Mapping[str, str], *, key: str, s3_key: Optional[str] = None) -> Dict[str, Any]:
    """The input block one mutation needs, addressed at the arranged rows.

    Every block is one a real browser sends, so a caller who is turned away was turned away
    from a request that would otherwise have been accepted, not from a malformed one.
    """
    idem = {"idempotency": {"idempotencyKey": key}}
    if field == CREATE_SALE_FIELD:
        return {
            "showAndSellId": ACTIVE_EVENT,
            "saleAt": SALE_AT,
            "lineItems": [_line(PRODUCT, immediate=1)],
            "paymentMethodCode": "CASH",
            "version": {"expectedVersion": 2},
            **idem,
        }
    if field == CORRECT_SALE_FIELD:
        return {
            "showAndSellId": ACTIVE_EVENT,
            "saleId": ids["saleId"],
            "reason": "the buyer took one box back",
            "lineItems": [_line(PRODUCT, immediate=0, we_owe=1)],
            "saleVersion": {"expectedVersion": 1},
            "version": {"expectedVersion": 2},
            **idem,
        }
    if field == VOID_SALE_FIELD:
        return {
            "showAndSellId": ACTIVE_EVENT,
            "saleId": ids["saleId"],
            "reason": "the buyer changed their mind",
            "saleVersion": {"expectedVersion": 1},
            "version": {"expectedVersion": 2},
            **idem,
        }
    if field == SET_WE_OWE_RESERVATION_FIELD:
        return {"weOweId": ids["weOweId"], "targetReservedQty": 1, "version": {"expectedVersion": 1}, **idem}
    if field == FULFILL_WE_OWE_FIELD:
        return {
            "weOweId": ids["weOweId"],
            "quantity": 1,
            "source": "EXTERNAL_COUNCIL",
            "version": {"expectedVersion": 1},
            **idem,
        }
    if field == CREATE_PAYMENT_METHOD_FIELD:
        return {"unitId": PACK_3149, "displayName": "Zelle", **idem}
    if field == UPDATE_PAYMENT_METHOD_FIELD:
        return {
            "unitId": PACK_3149,
            "paymentMethodId": ids["paymentMethodId"],
            "displayName": "Venmo Quick",
            "version": {"expectedVersion": int(ids.get("paymentVersion", 1))},
            **idem,
        }
    if field == DEACTIVATE_PAYMENT_METHOD_FIELD:
        return {
            "unitId": PACK_3149,
            "paymentMethodId": ids["paymentMethodId"],
            "version": {"expectedVersion": int(ids.get("paymentVersion", 1))},
            **idem,
        }
    if field == REQUEST_PAYMENT_QR_FIELD:
        return {
            "unitId": PACK_3149,
            "paymentMethodId": ids["paymentMethodId"],
            "contentType": "image/png",
            "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
            **idem,
        }
    if field == CONFIRM_PAYMENT_QR_FIELD:
        return {
            "unitId": PACK_3149,
            "paymentMethodId": ids["paymentMethodId"],
            "s3Key": s3_key or "payment-qr-codes/unit/unit-pack-3149-aurora/venmo/upload.png",
            "version": {"expectedVersion": int(ids.get("paymentVersion", 1))},
            **idem,
        }
    if field == DELETE_PAYMENT_QR_FIELD:
        return {
            "unitId": PACK_3149,
            "paymentMethodId": ids["paymentMethodId"],
            "version": {"expectedVersion": int(ids.get("paymentVersion", 1))},
            **idem,
        }
    raise AssertionError(f"no input block for {field}")


def _call(
    field: str,
    identity: Optional[Mapping[str, Any]],
    ids: Mapping[str, str],
    *,
    key: str = "sweep",
    s3_key: Optional[str] = None,
) -> Any:
    """One Stage 4 field, one identity, one request that would otherwise be accepted."""
    if field in STAGE4_QUERY_FIELDS:
        return handle_unit_operation(_event(field, identity, arguments=_arguments(field, ids)), None)
    return handle_unit_operation(_event(field, identity, mutation=_input(field, ids, key=key, s3_key=s3_key)), None)


def _payment_key(payment_method_id: str) -> Dict[str, str]:
    """The stored row for the arranged method, whose sort key is its normalized name."""
    return {"pk": f"UNIT#{PACK_3149}", "sk": f"{upm.PAYMENT_SK_PREFIX}#venmo"}


def _keys(s3_bucket: Any) -> List[str]:
    """Every object key left in the exports bucket."""
    listed = s3_bucket.list_objects_v2(Bucket=os.environ["EXPORTS_BUCKET"])
    return [str(item["Key"]) for item in listed.get("Contents", [])]


def _upload_target(world: Dict[str, Any], ids: Mapping[str, str], s3_bucket: Any, *, tag: str) -> str:
    """Ask for an upload target and write the browser's bytes there: returns the key."""
    request = _ok(_call(REQUEST_PAYMENT_QR_FIELD, _identity("Avery"), ids, key=f"attach-{tag}-req"))
    upload_key = str(request["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=upload_key, Body=PNG_BYTES)
    return upload_key


def _attach_qr(world: Dict[str, Any], ids: Mapping[str, str], s3_bucket: Any, *, tag: str) -> str:
    """Publish a real QR image on the arranged method, and return the key the row now serves."""
    upload_key = _upload_target(world, ids, s3_bucket, tag=tag)
    stored_version = int(
        world["units"].get_item(Key=_payment_key(ids["paymentMethodId"])).get("Item", {}).get("version", 1)
    )
    confirmed = _ok(
        handle_unit_operation(
            _event(
                CONFIRM_PAYMENT_QR_FIELD,
                _identity("Avery"),
                mutation={
                    "unitId": PACK_3149,
                    "paymentMethodId": ids["paymentMethodId"],
                    "s3Key": upload_key,
                    "version": {"expectedVersion": stored_version},
                    "idempotency": {"idempotencyKey": f"attach-{tag}-confirm"},
                },
            ),
            None,
        )
    )
    attachment = str(confirmed["qrCodeS3Key"])
    assert attachment and attachment != upload_key, confirmed
    ids["paymentVersion"] = stored_version + 1
    return attachment


# ---------------------------------------------------------------------------
# 1. The endpoint descriptions: every field answers its Unit Admins.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", STAGE4_FIELDS)
@pytest.mark.parametrize("admin", ["Avery", "Devon"])
def test_every_stage4_field_answers_a_units_admin(desk: Dict[str, Any], s3_bucket: Any, admin: str, field: str) -> None:
    """4.6.6: the Unit Admins of the event's Unit reach all sixteen Stage 4 fields."""
    world, ids = desk["world"], desk["ids"]
    s3_key: Optional[str] = None
    if field == CONFIRM_PAYMENT_QR_FIELD:
        # The confirm publishes bytes the browser already posted, so post them first.
        s3_key = _upload_target(world, ids, s3_bucket, tag=f"confirm-{admin}")
    elif field in (PAYMENT_QR_DOWNLOAD_FIELD, DELETE_PAYMENT_QR_FIELD):
        # A download or a delete needs an image to name, so publish one first the way 4.1.2 does.
        _attach_qr(world, ids, s3_bucket, tag=f"{field}-{admin}")

    answer = _call(field, _identity(admin), ids, key=f"ok-{field}-{admin}", s3_key=s3_key)

    assert not (isinstance(answer, dict) and answer.get("__isError")), f"{field} refused its own Unit Admin: {answer}"


def test_the_qr_chain_runs_end_to_end_for_a_unit_admin(desk: Dict[str, Any], s3_bucket: Any) -> None:
    """4.6.6: request, upload, confirm, download and delete all run against a real object."""
    world, ids = desk["world"], desk["ids"]
    upload_key = _upload_target(world, ids, s3_bucket, tag="chain")
    stored_version = int(
        world["units"].get_item(Key=_payment_key(ids["paymentMethodId"])).get("Item", {}).get("version", 1)
    )

    confirmed = _ok(
        handle_unit_operation(
            _event(
                CONFIRM_PAYMENT_QR_FIELD,
                _identity("Avery"),
                mutation={
                    "unitId": PACK_3149,
                    "paymentMethodId": ids["paymentMethodId"],
                    "s3Key": upload_key,
                    "version": {"expectedVersion": stored_version},
                    "idempotency": {"idempotencyKey": "qr-confirm"},
                },
            ),
            None,
        )
    )
    assert confirmed["paymentMethodId"] == ids["paymentMethodId"]
    attachment = str(confirmed["qrCodeS3Key"])
    assert attachment and attachment != upload_key, "the published object is the mutable POST key"
    ids["paymentVersion"] = stored_version + 1

    download = _ok(_call(PAYMENT_QR_DOWNLOAD_FIELD, _identity("Avery"), ids))
    assert download["downloadUrl"] and download["expiresAt"]

    _ok(_call(DELETE_PAYMENT_QR_FIELD, _identity("Avery"), ids, key="qr-delete"))
    history = _ok(
        handle_unit_operation(
            _event(
                UNIT_PAYMENT_METHODS_FIELD,
                _identity("Avery"),
                arguments={"unitId": PACK_3149, "includeInactive": True},
            ),
            None,
        )
    )
    venmo = [method for method in history if method["paymentMethodId"] == ids["paymentMethodId"]]
    assert venmo and venmo[0]["qrCodeS3Key"] is None, "the delete left a reference behind"
    remaining = _keys(s3_bucket)
    assert upload_key not in remaining, "the delete left the upload target in the bucket"
    assert attachment not in remaining, "the delete left the published object in the bucket"


# ---------------------------------------------------------------------------
# 2. The denials: nothing is answered, and nothing is written.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "caller,label",
    [(MORGAN, "scout-parent"), (RILEY, "outsider-admin"), (REVOKED, "revoked-admin")],
    ids=["morgan-no-grant", "riley-read-only", "revoked-admin"],
)
@pytest.mark.parametrize("field", STAGE4_FIELDS)
def test_a_caller_without_a_grant_is_denied_every_stage4_field(
    desk: Dict[str, Any], field: str, caller: str, label: str
) -> None:
    """4.6.6: the Scout parent, the outsider admin and the revoked admin reach nothing."""
    world, ids, before = desk["world"], desk["ids"], desk["state"]

    denied = assert_is_error(_call(field, _identity(caller), ids, key=f"deny-{label}-{field}"), "NOT_FOUND")
    assert denied["message"] == "Unit not found", denied["message"]
    for private in (ids["saleId"], ids["weOweId"], ACTIVE_EVENT):
        assert private not in denied["message"], f"{field} named a private id it refused to answer for"
    assert _state(world) == before, f"{label} was denied but the {field} write still landed"


@pytest.mark.parametrize("field", STAGE4_FIELDS)
def test_a_global_application_admin_without_a_grant_is_denied_every_stage4_field(
    desk: Dict[str, Any], field: str
) -> None:
    """4.6.6 AUTH-U-03: the global ``ADMIN`` group confers no Unit access on any Stage 4 field."""
    world, ids, before = desk["world"], desk["ids"], desk["state"]
    identity = {"sub": GLOBAL_ADMIN_SUB, "claims": {"sub": GLOBAL_ADMIN_SUB, "cognito:groups": ["ADMIN"]}}

    denied = assert_is_error(_call(field, identity, ids, key=f"deny-admin-{field}"), "NOT_FOUND")
    assert denied["message"] == "Unit not found", denied["message"]
    assert _state(world) == before


@pytest.mark.parametrize(
    "shape",
    [None, {}, {"apiKeyId": "0f8e7c1a", "sourceIp": ["198.51.100.7"], "user": False}],
    ids=["no-identity", "empty-identity", "api-key"],
)
@pytest.mark.parametrize("field", STAGE4_FIELDS)
def test_a_session_less_or_api_key_caller_is_denied_every_stage4_field(
    desk: Dict[str, Any], field: str, shape: Any
) -> None:
    """4.6.6: no session, an empty identity and the API-key identity are all ``UNAUTHORIZED``.

    The API-key shape is what AppSync sends for key mode — an ``apiKeyId`` and a source
    address, and no ``sub`` at all. No Stage 4 field is exposed in key mode, so the only
    correct answer is that there is nobody to authorize.
    """
    world, ids, before = desk["world"], desk["ids"], desk["state"]

    denied = assert_is_error(_call(field, shape, ids, key=f"deny-anon-{field}"), "UNAUTHORIZED")
    assert denied["message"] == "A signed-in account is required"
    assert _state(world) == before


#: The fields whose request carries an address that can be re-pointed at another tenant: a
#: Unit id, or the event / Unit Campaign whose own row names its Unit. An obligation or sale
#: id carries no address, so those three fields are proved from the other side — Riley, admin
#: of Troop 7150, reaching the Pack's desk — in the denial sweep above.
CROSS_UNIT_FIELDS: Tuple[str, ...] = tuple(
    field
    for field in STAGE4_FIELDS
    if field not in (WE_OWE_OBLIGATION_FIELD, SET_WE_OWE_RESERVATION_FIELD, FULFILL_WE_OWE_FIELD)
)

#: The fields whose tenancy comes from the event row, not from a Unit id in the request.
EVENT_ADDRESSED_FIELDS: Tuple[str, ...] = (
    SHOW_AND_SELL_SALES_FIELD,
    CREATE_SALE_FIELD,
    CORRECT_SALE_FIELD,
    VOID_SALE_FIELD,
)


def _readdressed(field: str, ids: Mapping[str, str]) -> Dict[str, Any]:
    """The same request this field would otherwise send, aimed at Troop 7150's rows.

    A real event and a real Unit Campaign, both owned by Riley's Unit: the point is that the
    caller is refused on a row that exists and belongs to someone else, which is the case an
    existence-oracle bug would answer.
    """
    block: Dict[str, Any] = (
        dict(_arguments(field, ids)) if field in STAGE4_QUERY_FIELDS else _input(field, ids, key=f"cross-{field}")
    )
    if field in EVENT_ADDRESSED_FIELDS:
        block["showAndSellId"] = FOREIGN_EVENT
    elif field == WE_OWE_OBLIGATIONS_FIELD:
        block["unitCampaignId"] = FOREIGN_CAMPAIGN
    else:
        block["unitId"] = FOREIGN_UNIT
    return block


@pytest.mark.parametrize("field", CROSS_UNIT_FIELDS)
def test_a_pack_admin_reaching_another_units_desk_is_denied(desk: Dict[str, Any], field: str) -> None:
    """4.6.6 cross-Unit: an admin of Pack 3149 has no answer for Troop 7150's rows."""
    world, ids, before = desk["world"], desk["ids"], desk["state"]
    block = _readdressed(field, ids)

    if field in STAGE4_QUERY_FIELDS:
        answer = handle_unit_operation(_event(field, _identity(ALEX), arguments=block), None)
    else:
        answer = handle_unit_operation(_event(field, _identity(ALEX), mutation=block), None)

    denied = assert_is_error(answer, "NOT_FOUND")
    assert denied["message"] in {"Unit not found", "Show & Sell not found", "Unit Campaign not found"}, denied[
        "message"
    ]
    for private in (FOREIGN_EVENT, FOREIGN_CAMPAIGN, FOREIGN_UNIT):
        assert private not in denied["message"], f"{field} confirmed the foreign row it refused to answer for"
    assert _state(world) == before, f"{field} was denied against another Unit but the write still landed"
