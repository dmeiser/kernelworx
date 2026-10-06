/**
 * Id and URL helpers for the public order pages.
 *
 * Order ids are `ORDER#<campaignId>#<orderSuffix>`. A raw `#` cannot live in a
 * path segment (it is the fragment delimiter), so the receipt URL always
 * carries the id split across two path segments and the server meaning of a
 * receipt link is fixed there - this module only renders it.
 */

/** The buyer-facing share path for a profile's public order page. */
export function buildSharePath(profileId: string, token: string): string {
  return `/o/${encodeURIComponent(profileId)}/${encodeURIComponent(token)}`;
}

/** Absolute share URL, as shown in the seller's settings share view. */
export function buildShareUrl(profileId: string, token: string): string {
  return `${window.location.origin}${buildSharePath(profileId, token)}`;
}

/**
 * The absolute receipt URL to render on the success screen, or null when no
 * usable link exists. The contract with the backend slice is a composed
 * ABSOLUTE url (an `r/<campaignId>/<orderSuffix>/<receiptToken>` path on the
 * site origin); a relative path is still resolved against the site origin so a
 * receipt link can never silently disappear. The `#` of a raw order id must
 * never reach an href, because the browser would truncate it at the fragment
 * delimiter and the link would be dead.
 */
export function resolveReceiptUrl(url: string | null | undefined): string | null {
  if (!url || url.includes('#')) return null;
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith('/')) return `${window.location.origin}${url}`;
  return null;
}
