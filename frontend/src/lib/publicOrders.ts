/**
 * Utilities for public order URLs and links.
 */
import { toUrlId } from './ids';


/**
 * Root-relative receipt path: exactly `/r/<campaignId>/<orderSuffix>/<receiptToken>`.
 *
 * `[^#/]+` excludes both `/` and `#` from every segment, so an anchored match
 * also rejects any fragment anywhere in the string.
 */
const RECEIPT_PATH_PATTERN = /^\/r\/[^#/]+\/[^#/]+\/[^#/]+$/;

/**
 * Resolves a receipt URL for use in links.
 * Returns the URL if it's valid and safe to use, null otherwise.
 *
 * Accepts exactly two shapes and returns the root-relative receipt path in
 * both cases:
 *
 * - a root-relative receipt path matching `/r/<campaignId>/<orderSuffix>/<receiptToken>`;
 * - a strict same-origin `https:` URL on the app's own host (its path must
 *   still match the receipt pattern; query string and fragment are dropped).
 *
 * Everything else is rejected with null — in particular `javascript:`, `data:`,
 * `http:`, protocol-relative (`//host/...`) and relative paths, any other
 * origin, and any input carrying a fragment.
 *
 * @param url - The receipt URL to resolve
 * @returns Resolved root-relative receipt path or null if invalid
 */
function httpsReceiptPath(candidate: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }
  // Strict same-origin: https: scheme on the app's own host:port.
  // The pathname excludes the query string and fragment.
  if (parsed.protocol !== 'https:' || parsed.host !== window.location.host) {
    return null;
  }
  return parsed.pathname;
}

function receiptPathOf(candidate: string): string | null {
  if (candidate.startsWith('https://')) {
    return httpsReceiptPath(candidate);
  }
  // Reject everything but root-relative paths: bare paths and every scheme
  // other than https: (javascript:, data:, http:, ...), plus
  // protocol-relative URLs (which would silently resolve against a foreign
  // host).
  return candidate.startsWith('//') || !candidate.startsWith('/') ? null : candidate;
}

export function resolveReceiptUrl(url: string | null | undefined): string | null {
  if (typeof url !== 'string') return null;
  const path = receiptPathOf(url.trim());
  return path !== null && RECEIPT_PATH_PATTERN.test(path) ? path : null;
}

/**
 * Builds a share path for public orders.
 * @param campaignId - The campaign ID
 * @param token - The public order share token
 * @returns A path like "/o/campaignId/token"
 */
export function buildSharePath(campaignId: string, token: string): string {
  return `/o/${toUrlId(campaignId)}/${token}`;
}
