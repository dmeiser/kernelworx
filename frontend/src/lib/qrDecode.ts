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

/**
 * Long-edge size the pixels are actually decoded at.
 *
 * jsQR's cost is per pixel, while a QR symbol carries far fewer modules than a
 * seller-uploaded PNG carries pixels: decoding a 2048x2048 read synchronously
 * on the main thread freezes the page for hundreds of milliseconds to read the
 * same ~100 modules. Scaling the long edge to 640 keeps roughly six pixels per
 * module for any payment QR — comfortably above what the decoder needs — while
 * cutting the pixel count ~10x.
 */
export const QR_DECODE_TARGET_DIMENSION = 640;

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
function naturalDimensionsWithinBound(element: HTMLImageElement): { width: number; height: number } | null {
  const width = element.naturalWidth;
  const height = element.naturalHeight;
  if (!width || !height) return null;
  if (width > QR_DECODE_MAX_DIMENSION || height > QR_DECODE_MAX_DIMENSION) return null;
  return { width, height };
}

/**
 * Canvas dimensions to decode at: the natural size when it already fits the
 * target, otherwise the same aspect ratio scaled so the long edge is the
 * target. Aspect ratio is preserved because jsQR reads square modules.
 */
export function decodeDimensions(width: number, height: number): { width: number; height: number } {
  const longEdge = Math.max(width, height);
  if (longEdge <= QR_DECODE_TARGET_DIMENSION) return { width, height };
  const scale = QR_DECODE_TARGET_DIMENSION / longEdge;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

/** Decode the image pixels at the scaled size; the canvas read can throw on a tainted canvas. */
function decodePixels(
  context: CanvasRenderingContext2D,
  element: HTMLImageElement,
  width: number,
  height: number,
): string | null {
  try {
    context.drawImage(element, 0, 0, width, height);
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
  const natural = naturalDimensionsWithinBound(element);
  if (!natural) return null;
  const { width, height } = decodeDimensions(natural.width, natural.height);

  const canvas = element.ownerDocument.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) return null;

  return decodePixels(context, element, width, height);
}
