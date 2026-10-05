/**
 * Allowlist for links decoded out of a seller-uploaded payment QR.
 *
 * The QR bytes are arbitrary PNG content uploaded by the seller, so the decoded
 * string is attacker-influenced text rendered on the trusted KernelWorx origin
 * (the buyer page is same-origin with the signed-in app). Only two schemes are
 * ever rendered:
 *
 * - `https:`  — payment links. `http:` is deliberately NOT allowed: there is no
 *   reason to downgrade a payment link from a trusted origin, and a plain-http
 *   href is both spoofable and a mixed-content request.
 * - `mailto:` — the seller emailing themselves an invoice request.
 *
 * Everything else is dropped: `javascript:` (script execution in an href),
 * `data:` (inline content rendered from untrusted bytes), `file:`, `http:`, and
 * protocol-relative `//host` (which `URL` cannot even parse without a base, and
 * which would silently inherit whatever scheme the page is served over).
 */

/** The only protocols a decoded QR link may use. */
export const ALLOWED_QR_LINK_PROTOCOLS: readonly string[] = ['https:', 'mailto:'];

/** Upper bound on a rendered link; QR payloads are far shorter in practice. */
export const MAX_QR_LINK_LENGTH = 2048;

/** Normalize the raw payload to a candidate absolute URL string ('' = reject). */
function normalizeCandidate(raw: string | null | undefined): string {
  if (typeof raw !== 'string') return '';
  const candidate = raw.trim();
  if (candidate.length === 0 || candidate.length > MAX_QR_LINK_LENGTH) return '';
  return candidate;
}

/** Parse a candidate link without a base, or return null when it is not absolute. */
function parseAbsoluteUrl(candidate: string): URL | null {
  try {
    // No base URL: a protocol-relative `//host` or a relative path fails here
    // instead of silently resolving against the page.
    return new URL(candidate);
  } catch {
    return null;
  }
}

/**
 * Returns the safe, normalized href for a decoded QR payload, or null when the
 * payload must not be rendered as a link at all.
 *
 * The parsed `URL`'s `href` is returned rather than the raw string: parsing
 * strips tab/newline characters that browsers ignore inside URLs, so the
 * normalized form cannot smuggle a different target than the one checked.
 */
export function sanitizeQrLink(raw: string | null | undefined): string | null {
  const candidate = normalizeCandidate(raw);
  const parsed = candidate ? parseAbsoluteUrl(candidate) : null;
  if (!parsed) return null;
  return ALLOWED_QR_LINK_PROTOCOLS.includes(parsed.protocol) ? parsed.href : null;
}
