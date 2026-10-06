/**
 * Client-side decode of a seller-uploaded payment QR image.
 *
 * The image is an arbitrary PNG the seller uploaded, fetched from a pre-signed
 * S3 GET on an anonymous page, so the read is bounded in both directions:
 *
 * - IN: the image's natural dimensions are checked before a single pixel is
 *   read. `getImageData` allocates a width*height*4 byte buffer, so an
 *   unbounded image is a memory attack on a page anyone can open. (The source
 *   bytes themselves are bounded by the QR upload path's content-length
 *   ceiling; the pixel budget is what the browser actually allocates.)
 * - OUT: the decoded payload length is capped before it is rendered.
 *
 * The `<img>` element passed in must carry `crossOrigin="anonymous"`, or the
 * canvas is tainted and `getImageData` throws (caught here, so a missing
 * attribute degrades to "no link found" rather than an exception).
 */

import jsQR from 'jsqr';
import { MAX_QR_LINK_LENGTH, sanitizeQrLink } from './qrLinkSafety';

/** Longest single edge accepted for a decode. */
export const MAX_QR_EDGE_PX = 2000;

/** Largest pixel count accepted for a decode (bounds the RGBA buffer). */
export const MAX_QR_PIXELS = 1_000_000;

/** True when the loaded image is small enough to read pixels from. */
export function qrImageWithinBounds(image: HTMLImageElement): boolean {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  if (!width || !height) return false;
  return width <= MAX_QR_EDGE_PX && height <= MAX_QR_EDGE_PX && width * height <= MAX_QR_PIXELS;
}

/** Read the image's pixels into an ImageData, or null when the read is refused. */
function readImagePixels(image: HTMLImageElement): ImageData | null {
  try {
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;

    const context = canvas.getContext('2d');
    if (!context) return null;

    context.drawImage(image, 0, 0);
    return context.getImageData(0, 0, canvas.width, canvas.height);
  } catch {
    // Tainted canvas (no crossOrigin on the img), a canvas-less environment,
    // or a decoder failure all mean the same thing to the buyer: no link.
    return null;
  }
}

/** Bound the decoded payload before anything renders it. */
function boundedPayload(decoded: { data: string } | null): string | null {
  if (!decoded) return null;
  if (!decoded.data || decoded.data.length > MAX_QR_LINK_LENGTH) return null;
  return decoded.data;
}

/**
 * Decode the QR payload from an already-loaded image element.
 * Returns null for "nothing decodable" — which is NOT an error: the page shows
 * the image with a "scan from another device" hint instead.
 */
export function decodeQrPayload(image: HTMLImageElement): string | null {
  if (!qrImageWithinBounds(image)) return null;

  const pixels = readImagePixels(image);
  if (!pixels) return null;

  return boundedPayload(jsQR(pixels.data, pixels.width, pixels.height));
}

/**
 * Decode the QR and return only a link that is safe to render. The allowlist
 * lives in `qrLinkSafety.sanitizeQrLink`; keeping it a pure function is what
 * makes the scheme rules unit-testable without injecting a QR into a browser.
 */
export function decodeQrLink(image: HTMLImageElement): string | null {
  return sanitizeQrLink(decodeQrPayload(image));
}
