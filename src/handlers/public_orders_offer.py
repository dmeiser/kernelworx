"""Public order offer read: ``publicGetOrderOffer`` (#679 public-orders offer slice).

The anonymous read behind the share URL ``/o/<profileId>/<token>``. There is no
caller identity on this path — AppSync admits the request with the public API
key and ``identity`` is null, so the URL token IS the authorization and this
handler must never call ``get_caller_id``.

Read order, each step narrowing the next (spec §5.3):

1. Locate the profile through the ``profileId-index`` GSI. The GSI is a locator
   only, never the authorization (#545 rule): a few seconds after a profile
   transfer it transiently projects both the old and the new owner row, so more
   than one projection is resolved with a strongly consistent read per candidate
   and an ambiguous owner is NOT_FOUND, never a best guess.
2. Strongly consistent GetItem on ``{ownerAccountId, profileId}`` to confirm the
   row behind that locator still exists under that owner.
3. Refuse unless the feature is enabled and the token matches. This is the one
   place a constant-time comparison is available (``hmac.compare_digest``, both
   sides encoded to bytes), so it is used here.
4. GetItem the stored anchor campaign by its canonical id — a strong GetItem, not
   the ``campaignId-index`` GSI the authenticated path uses — and refuse if it is
   missing or inactive, reproducing the repo's ``isActive == null -> true``
   back-compat default.
5. GetItem the catalog and refuse if it is missing or soft-deleted. Soft deletion
   is catalog-level only; products carry no per-item tombstone.
6. Intersect the seller's allowlist with the account's stored methods
   case-insensitively. ``Cash`` and ``Check`` are NOT force-added: they appear
   only if the seller allowlisted them.

An empty product list or an empty method list is a successful offer, not an
error: NOT_FOUND there would read to a buyer as a dead link, which is a different
and wrong thing.

Every negative branch raises the identical ``NOT_FOUND`` with one message, so
probing a profile id cannot distinguish "never enabled" from "bad token".

Logging hygiene is a contract here, not an aspiration (§9): the token, the stored
S3 key, and any buyer contact never reach a log line. Two surfaces make that
non-obvious — ``generate_presigned_get_url`` embeds ``s3_key`` in its own
success-path log line (suppressed for the duration of the call), and the
decorator's generic unexpected-exception line logs ``error=str(e)``, which is
where a library echoing a request argument would leak the token (scrubbed at the
handler boundary).
"""

import hmac
import logging
from contextlib import contextmanager
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Tuple, cast

from boto3.dynamodb.conditions import Key

try:  # pragma: no cover
    from utils import payment_methods as _payment_methods
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_campaign_id, ensure_catalog_id, ensure_profile_id, strip_prefix
    from utils.logging import get_logger
    from utils.payment_methods import RESERVED_NAMES, generate_presigned_get_url
except ModuleNotFoundError:  # pragma: no cover
    from ..utils import payment_methods as _payment_methods
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_campaign_id, ensure_catalog_id, ensure_profile_id, strip_prefix
    from ..utils.logging import get_logger
    from ..utils.payment_methods import RESERVED_NAMES, generate_presigned_get_url

# The decorator stays typed for mypy via the relative import below; at runtime
# the absolute import resolves in the Lambda zip (package `utils`) and the
# relative fallback resolves in unit tests (package `src.handlers`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

# Pre-signed QR image lifetime, matching the authenticated batch path (#330).
# A minted URL stays fetchable this long after a disable or a token rotation;
# that is stated behavior, not an immediate revocation.
QR_URL_EXPIRY_SECONDS = 900

# One message for every negative branch. Distinct messages per reason would turn
# the offer into an oracle over which profiles exist and which enabled the
# feature.
OFFER_UNAVAILABLE_MESSAGE = "Offer not available"

# The only field name this Lambda answers. The receipt read (a later slice)
# dispatches on its own field name through the same unit resolver.
OFFER_FIELD = "publicGetOrderOffer"


def _offer_unavailable() -> AppError:
    """Return the single NOT_FOUND every negative branch raises."""
    return AppError(ErrorCode.NOT_FOUND, OFFER_UNAVAILABLE_MESSAGE)


# ---------------------------------------------------------------------------
# Step 1-2: locate the profile, then confirm it consistently
# ---------------------------------------------------------------------------


def _profile_projections(db_profile_id: str) -> List[Dict[str, Any]]:
    """Query the ``profileId-index`` GSI for rows projecting this profile id."""
    response = tables.profiles.query(
        IndexName="profileId-index",
        KeyConditionExpression=Key("profileId").eq(db_profile_id),
    )
    items = response.get("Items", [])
    return [item for item in items if isinstance(item, dict)]


def _consistent_profile(owner_account_id: Optional[str], db_profile_id: str) -> Optional[Dict[str, Any]]:
    """Return the profile item iff a strongly consistent base-table read finds it.

    The base-table key ``{ownerAccountId, profileId}`` is what proves the owner:
    an item returned under that hash key belongs to that account right now,
    which the eventually consistent GSI projection cannot show (#438/#545).
    """
    if not owner_account_id:
        return None
    response = tables.profiles.get_item(
        Key={"ownerAccountId": owner_account_id, "profileId": db_profile_id},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return item if isinstance(item, dict) else None


def _resolve_ambiguous_projection(
    projections: List[Dict[str, Any]], db_profile_id: str, logger: Any
) -> Optional[Dict[str, Any]]:
    """Resolve a multi-projection GSI read with consistent reads per candidate.

    A profile transfer leaves both the old and the new owner's row projected for
    a few seconds. Exactly one candidate surviving a consistent read means the
    transfer finished and that row is current; zero or several is ambiguous and
    is reported as unavailable rather than guessed at.
    """
    owners = {str(item.get("ownerAccountId")) for item in projections if item.get("ownerAccountId")}
    confirmed = [profile for profile in (_consistent_profile(owner, db_profile_id) for owner in owners) if profile]
    if len(confirmed) != 1:
        logger.warning(
            "Ambiguous profileId-index projection",
            profile_id=db_profile_id,
            projections=len(projections),
            confirmed=len(confirmed),
        )
        return None
    return confirmed[0]


def _load_profile(db_profile_id: str, logger: Any) -> Dict[str, Any]:
    """Locate the profile through the GSI and confirm it with a consistent read."""
    projections = _profile_projections(db_profile_id)
    if not projections:
        raise _offer_unavailable()

    if len(projections) == 1:
        profile = _consistent_profile(projections[0].get("ownerAccountId"), db_profile_id)
    else:
        profile = _resolve_ambiguous_projection(projections, db_profile_id, logger)

    if profile is None:
        raise _offer_unavailable()
    return profile


# ---------------------------------------------------------------------------
# Step 3: the token is the authorization
# ---------------------------------------------------------------------------


def _settings_blob(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return the profile's ``publicOrders`` blob, or {} when it never enabled."""
    blob = profile.get("publicOrders")
    return blob if isinstance(blob, dict) else {}


def _token_matches(blob: Dict[str, Any], token: Any) -> bool:
    """Constant-time compare the request token against the stored share token.

    A non-string or empty token is a mismatch, not INVALID_INPUT: the schema
    marks the argument non-null, so a caller who strips it must land on the same
    NOT_FOUND as a wrong token instead of learning the profile exists.
    """
    if blob.get("enabled") is not True:
        return False
    stored = blob.get("token")
    if not isinstance(stored, str) or not stored or not isinstance(token, str) or not token:
        return False
    return hmac.compare_digest(token.encode("utf-8"), stored.encode("utf-8"))


# ---------------------------------------------------------------------------
# Steps 4-5: the anchor campaign and its catalog
# ---------------------------------------------------------------------------


def _campaign_is_active(campaign: Dict[str, Any]) -> bool:
    """Back-compat active check: campaigns written before ``isActive`` existed are active."""
    value = campaign.get("isActive")
    return True if value is None else value is True


def _load_campaign(profile: Dict[str, Any], blob: Dict[str, Any]) -> Dict[str, Any]:
    """GetItem the anchor campaign by canonical id under the profile's own key.

    A strong GetItem keyed by the confirmed profile — never the
    ``campaignId-index`` GSI the authenticated order path uses — so a dangling
    anchor pointing at another profile's campaign is a miss, not a cross-read.
    """
    campaign_id = ensure_campaign_id(blob.get("campaignId"))
    if not campaign_id:
        raise _offer_unavailable()

    response = tables.campaigns.get_item(
        Key={"profileId": profile.get("profileId"), "campaignId": campaign_id},
        ConsistentRead=True,
    )
    campaign = response.get("Item")
    if not isinstance(campaign, dict) or not _campaign_is_active(campaign):
        raise _offer_unavailable()
    return campaign


def _load_catalog(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """GetItem the campaign's catalog; missing or soft-deleted is unavailable.

    Soft deletion is catalog-level only: ``Product`` has no ``isDeleted`` field
    and ``updateCatalog`` replaces the products array wholesale, so there is no
    per-product tombstone to filter here.
    """
    catalog_id = ensure_catalog_id(campaign.get("catalogId"))
    if not catalog_id:
        raise _offer_unavailable()

    response = tables.catalogs.get_item(Key={"catalogId": catalog_id})
    catalog = response.get("Item")
    if not isinstance(catalog, dict) or catalog.get("isDeleted") is True:
        raise _offer_unavailable()
    return catalog


# ---------------------------------------------------------------------------
# Offer shaping: products in catalog order
# ---------------------------------------------------------------------------


def _as_float(value: Any) -> Optional[float]:
    """Coerce a stored DynamoDB number (Decimal, float, or numeric string) to float.

    Returns None for anything that is not a number rather than raising, so one
    malformed stored value cannot fail the whole offer.
    """
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_int(value: Any) -> Optional[int]:
    """Coerce a stored number to int, or None when it is not a number."""
    number = _as_float(value)
    return None if number is None else int(number)


def _sort_key(product: Dict[str, Any]) -> Tuple[int, float]:
    """Catalog order; a product without a usable ``sortOrder`` sorts last."""
    order = _as_float(product.get("sortOrder"))
    return (0, order) if order is not None else (1, 0.0)


def _public_product(product: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Shape one stored product for ``PublicProduct``, or None if unusable.

    ``price`` is a non-null Float, so a product whose price is not a number is
    dropped rather than served as a coercion error for the whole offer.
    """
    product_id = product.get("productId")
    name = product.get("productName")
    if not isinstance(product_id, str) or not product_id or not isinstance(name, str):
        return None
    price = _as_float(product.get("price"))
    if price is None:
        return None

    description = product.get("description")
    return {
        "productId": product_id,
        "productName": name,
        "price": price,
        "description": description if isinstance(description, str) else None,
        "sortOrder": _as_int(product.get("sortOrder")),
    }


def _public_products(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The catalog's products in catalog order. An empty list is a valid offer."""
    raw = catalog.get("products")
    products = [item for item in (raw or []) if isinstance(item, dict)]
    products.sort(key=_sort_key)
    return [shaped for shaped in (_public_product(product) for product in products) if shaped]


# ---------------------------------------------------------------------------
# Step 6: payment methods, and the pre-signed QR images
# ---------------------------------------------------------------------------


def _stored_methods(owner_account_id: Any) -> Dict[str, Dict[str, Any]]:
    """The account's stored payment methods keyed by lowercased name."""
    response = tables.accounts.get_item(Key={"accountId": owner_account_id})
    account = response.get("Item")
    preferences = account.get("preferences") if isinstance(account, dict) else None
    methods = preferences.get("paymentMethods") if isinstance(preferences, dict) else None

    by_name: Dict[str, Dict[str, Any]] = {}
    for method in methods or []:
        if isinstance(method, dict) and isinstance(method.get("name"), str):
            by_name.setdefault(method["name"].strip().lower(), method)
    return by_name


def _extract_s3_key(value: str) -> str:
    """Python equivalent of ``batch_qr_urls_fn.js``'s ``extractS3Key``.

    New rows store the raw S3 key; legacy rows can hold the full object URL, so
    the key is taken from the path after the host. Mirrors the JS exactly —
    including passing a non-URL value through untouched.
    """
    if not value.startswith("http"):
        return value
    path_start = value.find("/", 8)  # skip the scheme, then the host
    return value[path_start + 1 :] if path_start > 0 else value


@contextmanager
def _suppress_logged_value(value: str) -> Iterator[None]:
    """Drop log records that would echo ``value`` while the block runs.

    ``generate_presigned_get_url`` logs its own success line with ``s3_key``
    embedded. The public offer must never put a stored object key in a log, so a
    filter on that module's logger drops any record whose rendered text carries
    the key for the duration of the call. ``value`` is the extracted key, which
    the caller has already proven non-empty.
    """
    helper_logger = logging.getLogger(_payment_methods.__name__)

    def _drop(record: logging.LogRecord) -> bool:
        return value not in str(record.getMessage())

    helper_logger.addFilter(_drop)
    try:
        yield
    finally:
        helper_logger.removeFilter(_drop)


def _signed_qr_url(owner_account_id: Any, method: Dict[str, Any], logger: Any) -> Optional[str]:
    """Pre-sign one method's stored QR key, or None when it cannot be signed.

    The key is passed EXPLICITLY: the helper's no-key path probes deterministic
    slug-shaped keys that can never match the UUID-shaped keys actually stored,
    costing up to three ``head_object`` calls to fail. The helper also validates
    the key itself and raises FORBIDDEN on a mismatch, comparing the key's second
    path segment to the id it is given — so the bare account form goes in
    (``batch_qr_urls_fn.js`` precedent), and a foreign or malformed key yields a
    null URL and a warning instead of failing the whole offer. The warning never
    names the key.
    """
    stored = method.get("qrCodeUrl")
    if not isinstance(stored, str) or not stored:
        return None

    s3_key = _extract_s3_key(stored)
    if not s3_key:
        # A URL with no path (a truncated legacy value) has nothing to sign.
        # Falling through would hand the helper an empty key, which is falsy
        # and would take its no-key probe path.
        return None
    try:
        with _suppress_logged_value(s3_key):
            signed = generate_presigned_get_url(
                strip_prefix(owner_account_id),
                method.get("name") if isinstance(method.get("name"), str) else "",
                s3_key=s3_key,
                expiry_seconds=QR_URL_EXPIRY_SECONDS,
            )
            return cast(Optional[str], signed)
    except AppError as exc:
        if exc.error_code != ErrorCode.FORBIDDEN:
            raise
        logger.warning(
            "Skipping QR key that failed ownership validation",
            method=method.get("name"),
        )
        return None


def _public_payment_methods(profile: Dict[str, Any], blob: Dict[str, Any], logger: Any) -> List[Dict[str, Any]]:
    """Allowlist intersected with the account's still-existing methods.

    Case-insensitive, in allowlist order, de-duplicated. A method the seller
    allowlisted but has since deleted drops out; if that empties the list the
    offer still succeeds with an empty list.

    ``Cash`` and ``Check`` are global pseudo-methods that never live in
    ``preferences.paymentMethods``, so they count as existing without a stored
    entry — but they are NOT force-added: they appear only because the seller
    allowlisted them.
    """
    allowed = blob.get("allowedPaymentMethods")
    names = [name for name in allowed if isinstance(name, str)] if isinstance(allowed, list) else []
    stored = _stored_methods(profile.get("ownerAccountId"))

    methods: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        key = name.strip().lower()
        if key in seen:
            continue
        method = stored.get(key)
        if method:
            display_name = method["name"]
            qr_code_url = _signed_qr_url(profile.get("ownerAccountId"), method, logger)
        elif key in RESERVED_NAMES:
            display_name, qr_code_url = name, None
        else:
            continue
        seen.add(key)
        methods.append({"name": display_name, "qrCodeUrl": qr_code_url})
    return methods


# ---------------------------------------------------------------------------
# Offer assembly
# ---------------------------------------------------------------------------


def _build_offer(event: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the offer for one ``publicGetOrderOffer`` request."""
    logger = get_logger(__name__)
    arguments = event.get("arguments") or {}

    profile_id = arguments.get("profileId")
    db_profile_id = ensure_profile_id(profile_id) if isinstance(profile_id, str) else None
    if not db_profile_id:
        raise _offer_unavailable()

    profile = _load_profile(db_profile_id, logger)
    blob = _settings_blob(profile)
    if not _token_matches(blob, arguments.get("token")):
        raise _offer_unavailable()

    campaign = _load_campaign(profile, blob)
    catalog = _load_catalog(campaign)
    products = _public_products(catalog)
    payment_methods = _public_payment_methods(profile, blob, logger)

    logger.info(
        "Public order offer served",
        profile_id=db_profile_id,
        campaign_id=ensure_campaign_id(campaign.get("campaignId")),
        products=len(products),
        payment_methods=len(payment_methods),
    )

    return {
        "sellerName": profile.get("sellerName") if isinstance(profile.get("sellerName"), str) else "",
        "campaignId": strip_prefix(campaign.get("campaignId")),
        "campaignName": campaign.get("campaignName") if isinstance(campaign.get("campaignName"), str) else "",
        "products": products,
        "paymentMethods": payment_methods,
    }


def _redact_secrets(exc: Exception, secret: Optional[str]) -> Exception:
    """Strip the share token from an unexpected exception's message, in place.

    The decorator's generic path logs ``error=str(e)``. A library that echoes a
    request argument — a validation error, a service error carrying the request —
    would therefore put the capability token in the log, so the scrub happens at
    this boundary where the secret is known exactly and can be replaced literally
    rather than pattern-matched. A message that never carried it is left alone.
    """
    text = str(exc)
    if isinstance(secret, str) and secret and secret in text:
        exc.args = (text.replace(secret, "[redacted]"),)
    return exc


def _run_guarded(event: Dict[str, Any]) -> Dict[str, Any]:
    """Run the offer read with the share token scrubbed from unexpected errors."""
    token = (event.get("arguments") or {}).get("token")
    try:
        return _build_offer(event)
    except AppError:
        raise
    except Exception as exc:
        raise _redact_secrets(exc, token if isinstance(token, str) else None) from None


@with_error_handling(error_message=OFFER_UNAVAILABLE_MESSAGE)
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Unit-resolver entry point: dispatch on ``info.fieldName``.

    ``lambda_unit_resolver.js`` forwards the whole AppSync context, so the field
    name is the discriminator (the pipeline invoke's ``operation`` field does not
    exist here). Identity is null on this auth mode and is never read.
    """
    field_name = (event.get("info") or {}).get("fieldName", "")
    if field_name != OFFER_FIELD:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported operation: {field_name}")
    return _run_guarded(event)
