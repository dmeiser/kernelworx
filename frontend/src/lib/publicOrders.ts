/**
 * Id and URL helpers for the public order pages.
 *
 * Order ids are `ORDER#<campaignId>#<orderSuffix>`. A raw `#` cannot live in a
 * path segment (it is the fragment delimiter) and `lib/ids.ts` cuts at the
 * FIRST `#`, so a single "bare" order id is impossible: the receipt URL carries
 * the id split across two segments and this module reassembles it for the
 * GraphQL argument.
 */

/** Prefix of a full order id in the orders table. */
export const ORDER_ID_PREFIX = 'ORDER';

const ID_SEPARATOR = '#';

/** The buyer-facing share path for a profile's public order page. */
export function buildSharePath(profileId: string, token: string): string {
  return `/o/${encodeURIComponent(profileId)}/${encodeURIComponent(token)}`;
}

/** Absolute share URL, as shown in the seller's settings share view. */
export function buildShareUrl(profileId: string, token: string): string {
  return `${window.location.origin}${buildSharePath(profileId, token)}`;
}

/** Reassemble the full order id from the two receipt URL segments. */
export function buildOrderIdFromSegments(campaignId: string, orderSuffix: string): string {
  return `${ORDER_ID_PREFIX}${ID_SEPARATOR}${campaignId}${ID_SEPARATOR}${orderSuffix}`;
}

/**
 * Split a full order id into its two URL segments, or null when the id is not
 * in the three-part form (a legacy `ORDER#<uuid>` id has no suffix to carry and
 * the server rejects it too, so there is no link to build).
 */
export function splitOrderIdForPath(orderId: string | null | undefined): { campaignId: string; orderSuffix: string } | null {
  if (!orderId) return null;
  const parts = orderId.split(ID_SEPARATOR);
  if (parts.length !== 3 || !parts[1] || !parts[2]) return null;
  return { campaignId: parts[1], orderSuffix: parts[2] };
}

/** The split-segment receipt path for an order plus its per-order receipt token. */
export function buildReceiptPath(orderId: string, receiptToken: string): string | null {
  const segments = splitOrderIdForPath(orderId);
  if (!segments) return null;
  return (
    `/r/${encodeURIComponent(segments.campaignId)}/${encodeURIComponent(segments.orderSuffix)}` +
    `/${encodeURIComponent(receiptToken)}`
  );
}

/**
 * True when a URL is safe to render as a receipt link on the success screen:
 * the `#` of a raw order id must never reach an href, because the browser would
 * truncate it at the fragment delimiter and the link would be dead.
 */
export function isSplitSegmentReceiptUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  return !url.includes(ID_SEPARATOR) && /^https?:\/\//.test(url);
}
