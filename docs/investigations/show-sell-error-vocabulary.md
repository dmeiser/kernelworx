# Show & Sell error vocabulary — wave-1 decision record

Status: DECIDED (wave 1, integration plan section 5 step 3; review item
r1-1). Applies to the Unit/Unit Campaign/inventory/Show & Sell backend
landing on `src/handlers/*_operations.py`.

The spec's error vocabulary IS our vocabulary: the clean-room build was
written from the spec, so no renaming happens on landing. The decisions
below are the three places where the APPLICATION's existing vocabulary
differs from what the Show & Sell contract requires.

## D-1: `RATE_LIMIT_EXCEEDED` is a NEW code, distinct from the lifetime cap

The application has `PUBLIC_ORDER_LIMIT_EXCEEDED`, a per-campaign
LIFETIME cap for public orders: when it fires the buyer must not retry.

Spec 5.3 requires a different thing: a fixed-window redemption/write
THROTTLE (attempt 11 in the same UTC hour, persisted on
`public_order_throttles` with key `UNIT_INVITE_REDEMPTION#<accountId>#WINDOW#<yyyy-MM-ddTHH>`
per impact map 4.4). Semantics differ on every axis:

| | `PUBLIC_ORDER_LIMIT_EXCEEDED` | `RATE_LIMIT_EXCEEDED` |
| --- | --- | --- |
| Meaning | campaign lifetime cap spent | hourly window spent |
| Retry | never (client must stop) | after the window rolls |
| Counter scope | campaign | (account, UTC hour) |
| Storage | campaign row | `public_order_throttles` TTL rows |

DECISION: add `RATE_LIMIT_EXCEEDED` to `ErrorCode` (done, wave 1); the
throttle path raises it with a `retryAfterHint` detail (RFC 3339 window
boundary, an authorized detail per D-3). Reusing the lifetime-cap code
would tell clients to stop retrying a condition that expires in under an
hour.

## D-2: bidirectional narrowing — the Unit-invite path suppresses the legacy invite codes

The application surfaces `INVITE_EXPIRED` and `INVITE_ALREADY_USED` for
its PROFILE invites. Spec 5.3 forbids distinct codes for the Unit-invite
redemption outcome: expired, consumed, or revoked invites must be
indistinguishable from a never-existing code — NOT_FOUND, no existence
oracle (SEC-03).

DECISION: the legacy profile-invite handlers KEEP their codes (their
clients key on them; narrowing them is a breaking change to existing
surface and is out of scope). The Unit-invite redemption path
(`redeemUnitInvite`) MUST NOT raise `INVITE_EXPIRED`/`INVITE_ALREADY_USED`
— every non-success redemption outcome is NOT_FOUND. This is a
per-path suppression, recorded here so a later "tidy the vocabulary"
pass does not "fix" the apparent duplication and re-open the oracle.

## D-3: CONFLICT carries an authorized-details table, never internals

`CONFLICT` answers the spec section 11 deletion/edit guards. The
`AppError.details` dict is part of the wire contract, so only enumerated
reasons ship; handler internals (row keys, counts of other tenants'
data) never do. Initial authorized reasons (extended per wave, each
added here first):

| Reason | Raised when |
| --- | --- |
| `LAST_UNIT_ADMIN` | the Account is the final Unit Admin of a live Unit (spec 11: block until another admin is added or the Unit is deleted via its own governed flow) |
| `JOINED_CAMPAIGN_HAS_DEPENDENCIES` | joined Scout Campaign deletion while membership/commitment/custody/credit/fulfillment rows exist |
| `OUTSTANDING_CUSTODY` | profile deletion with with-Scout stock not returned/sold |
| `FULFILLMENT_INVALIDATED` | an Order edit that would invalidate existing fulfillment (spec 11 edit policy) |
| `ACTIVE_GUARD` | any operation blocked by an ACTIVE roster/finalization guard row |

Rules: reasons are UPPER_SNAKE strings in a `reason` detail key; new
reasons are added to this table in the same commit that introduces them;
messages stay human-readable and may change, reasons are contract.
