/**
 * Tests for lib/qrDecode.ts.
 *
 * The decoded QR bytes are seller-controlled content rendered on our trusted
 * origin, so both the decode guard (bounded canvas, tainted-canvas swallow)
 * and the scheme allowlist (https/mailto only) are pinned here.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import jsQR from 'jsqr';
import {
  decodeQrLink,
  sanitizeQrLink,
  QR_DECODE_MAX_DIMENSION,
} from '../../src/lib/qrDecode';

vi.mock('jsqr', () => ({
  default: vi.fn(),
}));

const mockedJsQR = vi.mocked(jsQR);

const IMAGE_SIZE = 100;

/** Build a minimal image + canvas stand-in; override pieces per case. */
const makeImageElement = (
  canvas: { width: number; height: number; getContext: ReturnType<typeof vi.fn> } | null,
  naturalWidth = IMAGE_SIZE,
  naturalHeight = IMAGE_SIZE,
): HTMLImageElement => {
  const element = {
    naturalWidth,
    naturalHeight,
    ownerDocument: {
      createElement: vi.fn(() => canvas),
    },
  };
  return element as unknown as HTMLImageElement;
};

const makeCanvas = (context: unknown) => ({
  width: 0,
  height: 0,
  getContext: vi.fn(() => context),
});

const makeContext = (imageData: unknown) => ({
  drawImage: vi.fn(),
  getImageData: vi.fn(() => imageData),
});

const validImageData = { data: new Uint8ClampedArray(IMAGE_SIZE * IMAGE_SIZE * 4) };

describe('sanitizeQrLink', () => {
  it('accepts https and mailto links', () => {
    expect(sanitizeQrLink('https://venmo.com/u/seller')).toBe('https://venmo.com/u/seller');
    expect(sanitizeQrLink('mailto:pay@example.com')).toBe('mailto:pay@example.com');
    expect(sanitizeQrLink('HTTPS://EXAMPLE.COM/PAY')).toBe('HTTPS://EXAMPLE.COM/PAY');
  });

  it('rejects http and other schemes', () => {
    expect(sanitizeQrLink('http://example.com')).toBeNull();
    expect(sanitizeQrLink('javascript:alert(1)')).toBeNull();
    expect(sanitizeQrLink('ftp://example.com')).toBeNull();
    expect(sanitizeQrLink('data:text/html,<script>')).toBeNull();
  });

  it('rejects empty, missing, or scheme-less input', () => {
    expect(sanitizeQrLink(null)).toBeNull();
    expect(sanitizeQrLink(undefined)).toBeNull();
    expect(sanitizeQrLink('')).toBeNull();
    expect(sanitizeQrLink('   ')).toBeNull();
    expect(sanitizeQrLink('example.com/pay')).toBeNull();
  });

  it('trims surrounding whitespace', () => {
    expect(sanitizeQrLink('  https://venmo.com/u/seller\n')).toBe('https://venmo.com/u/seller');
  });
});

describe('decodeQrLink', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('decodes an https link from the image pixels', () => {
    mockedJsQR.mockReturnValue({ data: 'https://venmo.com/u/seller' } as never);
    const context = makeContext(validImageData);
    const image = makeImageElement(makeCanvas(context));
    expect(decodeQrLink(image)).toBe('https://venmo.com/u/seller');
    expect(context.drawImage).toHaveBeenCalledWith(image, 0, 0);
    expect(mockedJsQR).toHaveBeenCalledWith(validImageData.data, IMAGE_SIZE, IMAGE_SIZE);
  });

  it('returns null for a null element', () => {
    expect(decodeQrLink(null)).toBeNull();
    expect(mockedJsQR).not.toHaveBeenCalled();
  });

  it('returns null when the image has no natural dimensions', () => {
    expect(decodeQrLink(makeImageElement(makeCanvas(makeContext(validImageData)), 0, 0))).toBeNull();
    expect(mockedJsQR).not.toHaveBeenCalled();
  });

  it('refuses images above the decode dimension bound', () => {
    const context = makeContext(validImageData);
    expect(
      decodeQrLink(
        makeImageElement(makeCanvas(context), QR_DECODE_MAX_DIMENSION + 1, IMAGE_SIZE),
      ),
    ).toBeNull();
    expect(
      decodeQrLink(
        makeImageElement(makeCanvas(context), IMAGE_SIZE, QR_DECODE_MAX_DIMENSION + 1),
      ),
    ).toBeNull();
    expect(mockedJsQR).not.toHaveBeenCalled();
  });

  it('returns null when no 2d context is available', () => {
    const image = makeImageElement(makeCanvas(null));
    expect(decodeQrLink(image)).toBeNull();
    expect(mockedJsQR).not.toHaveBeenCalled();
  });

  it('returns null when the canvas read throws (tainted canvas)', () => {
    const context = makeContext(null);
    context.getImageData.mockImplementation(() => {
      throw new Error('SecurityError: tainted canvas');
    });
    const image = makeImageElement(makeCanvas(context));
    expect(decodeQrLink(image)).toBeNull();
  });

  it('returns null when no QR code is found', () => {
    mockedJsQR.mockReturnValue(null);
    const image = makeImageElement(makeCanvas(makeContext(validImageData)));
    expect(decodeQrLink(image)).toBeNull();
  });

  it('returns null when the decoded data is not an allowed link', () => {
    mockedJsQR.mockReturnValue({ data: 'http://evil.example/cap' } as never);
    const image = makeImageElement(makeCanvas(makeContext(validImageData)));
    expect(decodeQrLink(image)).toBeNull();
  });

  it('keeps a decoded mailto link', () => {
    mockedJsQR.mockReturnValue({ data: 'mailto:pay@example.com' } as never);
    const image = makeImageElement(makeCanvas(makeContext(validImageData)));
    expect(decodeQrLink(image)).toBe('mailto:pay@example.com');
  });
});
