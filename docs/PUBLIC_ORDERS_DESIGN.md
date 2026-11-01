# Public orders design note

## PublicOrder item shape and key grammar

- Offers come from campaign + catalog: `publicGetOrderOffer(campaignId, token)`.
- Offer key: campaign lookup via `campaignId-index` GSI, then consistent GetItem `{profileId, campaignId}`.
- Profile located via `profileId-index` GSI then consistent read keyed `{ownerAccountId, profileId}`.
- Orders stored with PK `ORDER#<campaignId>#<orderSuffix>` (receipt segments split to avoid `#` in URLs).
- Status on receipt: `receiptStatusChip` etc. Capability URL: `/r/:campaignId/:orderSuffix/:receiptToken`.

## Share token format and rotation

- Per-campaign token in `campaign.publicOrders.token`.
- Compared with `hmac.compare_digest` (constant time); mismatch/disabled/inactive -> identical NOT_FOUND.
- Rotation: `updateCampaignPublicOrderSettings(..., rotateToken: true)` mints new token; old token dead immediately.
- Buyer-facing generic NOT_FOUND for all negative branches (no oracle).

## Cap counter and accepted drift

- Counter: `campaign.publicOrderCount`, enforced at 500 (`PUBLIC_ORDER_CAP`) in JS resolver before insert.
- Accepted trade-off: cap is checked without transactional locking; concurrent races can overshoot by a small amount. Accepted for cost/simplex; counter is eventually consistent-ish. Pre-signed URLs etc.
- Accepted drift documented; not fixed.

## Receipt capability URL

- `/r/:campaignId/:orderSuffix/:receiptToken` capability URL; token discloses one order only, never echoed.

## Email flow

- Buyer first (confirmation with receipt link), seller second (notification).
- SES gating: env contract; ephemeral lacks SES -> configured false.
- Prod pre-launch gates: docs/PUBLIC_ORDERS_PRELAUNCH.md.

## Known accepted gaps

- Ephemeral CSP img-src excludes ephemeral export host.
- Cap drift accepted.
