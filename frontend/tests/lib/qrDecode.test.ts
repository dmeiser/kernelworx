/**
 * Unit tests for the QR decode plumbing.
 *
 * The scheme allowlist itself is pinned in `tests/lib/qrLinkSafety.test.ts`;
 * these tests cover what surrounds it: the pixel budget that bounds the
 * `getImageData` allocation on an anonymous page, the "nothing decodable"
 * paths, and the payload length bound.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MAX_QR_EDGE_PX, MAX_QR_PIXELS, decodeQrLink, decodeQrPayload, qrImageWithinBounds } from '../../src/lib/qrDecode';

vi.mock('jsqr', () => ({
  default: vi.fn(() => ({ data: 'https://pay.example.com/invoice' })),
}));

import jsQR from 'jsqr';

interface FakeContext {
  drawImage: ReturnType<typeof vi.fn>;
  getImageData: ReturnType<typeof vi.fn>;
}

function makeImage(width: number, height: number): HTMLImageElement {
  const image = document.createElement('img');
  Object.defineProperty(image, 'naturalWidth', { value: width });
  Object.defineProperty(image, 'naturalHeight', { value: height });
  return image;
}

let originalGetContext: typeof HTMLCanvasElement.prototype.getContext;
let context: FakeContext;

beforeEach(() => {
  originalGetContext = HTMLCanvasElement.prototype.getContext;
  context = {
    drawImage: vi.fn(),
    getImageData: vi.fn(() => ({ data: new Uint8ClampedArray(4), width: 10, height: 10 })),
  };
  vi.mocked(jsQR).mockReturnValue({ data: 'https://pay.example.com/invoice' } as never);
});

afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
  vi.restoreAllMocks();
});

describe('qrImageWithinBounds', () => {
  it('accepts an image inside both bounds', () => {
    expect(qrImageWithinBounds(makeImage(300, 300))).toBe(true);
  });

  it('rejects an image with no decoded dimensions', () => {
    expect(qrImageWithinBounds(makeImage(0, 0))).toBe(false);
  });

  it('rejects an edge over the per-edge bound', () => {
    expect(qrImageWithinBounds(makeImage(MAX_QR_EDGE_PX + 1, 10))).toBe(false);
  });

  it('rejects an image over the pixel budget even when each edge fits', () => {
    const edge = Math.min(MAX_QR_EDGE_PX, Math.ceil(Math.sqrt(MAX_QR_PIXELS)) + 1);
    expect(qrImageWithinBounds(makeImage(edge, edge))).toBe(false);
  });
});

describe('decodeQrPayload', () => {
  it('never reads pixels from an oversized image', () => {
    HTMLCanvasElement.prototype.getContext = vi.fn() as never;
    const result = decodeQrPayload(makeImage(MAX_QR_EDGE_PX + 1, MAX_QR_EDGE_PX + 1));
    expect(result).toBeNull();
    expect(HTMLCanvasElement.prototype.getContext).not.toHaveBeenCalled();
  });

  it('decodes the payload from the canvas pixels', () => {
    HTMLCanvasElement.prototype.getContext = (() => context) as never;
    const image = makeImage(10, 10);

    expect(decodeQrPayload(image)).toBe('https://pay.example.com/invoice');
    expect(context.drawImage).toHaveBeenCalledWith(image, 0, 0);
    expect(jsQR).toHaveBeenCalled();
  });

  it('returns null when the canvas has no 2d context', () => {
    HTMLCanvasElement.prototype.getContext = (() => null) as never;
    expect(decodeQrPayload(makeImage(10, 10))).toBeNull();
  });

  it('returns null when the canvas read throws (a tainted canvas)', () => {
    HTMLCanvasElement.prototype.getContext = (() => ({
      ...context,
      drawImage: vi.fn(() => {
        throw new Error('tainted canvas');
      }),
    })) as never;
    expect(decodeQrPayload(makeImage(10, 10))).toBeNull();
  });

  it('returns null when no QR is found', () => {
    HTMLCanvasElement.prototype.getContext = (() => context) as never;
    vi.mocked(jsQR).mockReturnValueOnce(null as never);
    expect(decodeQrPayload(makeImage(10, 10))).toBeNull();
  });

  it('drops a decoded payload over the output bound', () => {
    HTMLCanvasElement.prototype.getContext = (() => context) as never;
    vi.mocked(jsQR).mockReturnValueOnce({ data: 'x'.repeat(5000) } as never);
    expect(decodeQrPayload(makeImage(10, 10))).toBeNull();
  });
});

describe('decodeQrLink', () => {
  it('returns the decoded payload only when it is an allowed link', () => {
    HTMLCanvasElement.prototype.getContext = (() => context) as never;
    vi.mocked(jsQR).mockReturnValue({ data: 'javascript:alert(1)' } as never);
    expect(decodeQrLink(makeImage(10, 10))).toBeNull();

    vi.mocked(jsQR).mockReturnValue({ data: 'https://pay.example.com/ok' } as never);
    expect(decodeQrLink(makeImage(10, 10))).toBe('https://pay.example.com/ok');
  });
});
