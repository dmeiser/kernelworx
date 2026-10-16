/**
 * QR code decoding utilities for the public buyer page.
 *
 * Payment QR images are seller-uploaded PNGs of arbitrary content, so the
 * decoded bytes are attacker-influenced text rendered on our trusted origin.
 * Two guards keep that safe:
 *
 * - `decodeQrLink` only reads the image through a bounded canvas (the natural
 *   dimensions are checked before `getImageData`, so an anonymous page never
 *   allocates an unbounded canvas on image content).
 * - `sanitizeQrLink` allowlists `https:`/`mailto:` schemes only — no `http:`,
 *   because a downgrade from the trusted origin is not needed for payment
 *   links. Anything else decodes to "no link" and the page falls back to the
 *   "scan from another device" hint.
 */
import jsQR from 'jsqr';

/** Upper bound on either canvas dimension before decoding (decode-side guard). */
export const QR_DECODE_MAX_DIMENSION = 2048;

const ALLOWED_LINK_SCHEMES = new Set(['https', 'mailto']);

/**
 * Returns the link only when its scheme is in the https/mailto allowlist.
 * The scheme check is case-insensitive; surrounding whitespace is trimmed.
 */
export function sanitizeQrLink(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const schemeMatch = /^([a-z][a-z0-9+.-]*):/i.exec(trimmed);
  if (!schemeMatch) return null;
  return ALLOWED_LINK_SCHEMES.has(schemeMatch[1].toLowerCase()) ? trimmed : null;
}

/** The image's natural dimensions, or null when absent or above the decode bound. */
function naturalDimensionsWithinBound(
  element: HTMLImageElement,
): { width: number; height: number } | null {
  const width = element.naturalWidth;
  const height = element.naturalHeight;
  if (!width || !height) return null;
  if (width > QR_DECODE_MAX_DIMENSION || height > QR_DECODE_MAX_DIMENSION) return null;
  return { width, height };
}

/** Decode the image pixels; the canvas read can throw on a tainted canvas. */
function decodePixels(
  context: CanvasRenderingContext2D,
  element: HTMLImageElement,
  width: number,
  height: number,
): string | null {
  try {
    context.drawImage(element, 0, 0);
    const imageData = context.getImageData(0, 0, width, height);
    const decoded = jsQR(imageData.data, width, height);
    return sanitizeQrLink(decoded?.data);
  } catch {
    // Tainted canvas (missing crossOrigin) or a canvas read failure: no link.
    return null;
  }
}

/**
 * Attempts to decode a QR code from an image element.
 * Returns the decoded link (scheme-allowlisted) if successful, null otherwise.
 *
 * @param element - HTMLImageElement containing a QR code
 * @returns Decoded link string or null if decoding failed
 */
export function decodeQrLink(element: HTMLImageElement | null): string | null {
  if (!element) return null;
  const dimensions = naturalDimensionsWithinBound(element);
  if (!dimensions) return null;
  const { width, height } = dimensions;

  const canvas = element.ownerDocument.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) return null;

  return decodePixels(context, element, width, height);
}
