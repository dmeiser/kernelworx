/**
 * Tests for lib/qrDecode.ts.
 *
 * The decoded QR bytes are seller-controlled content rendered on our trusted
 * origin, so both the decode guard (bounded canvas, tainted-canvas swallow)
 * and the scheme allowlist (https/mailto only) are pinned here.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import jsQR from 'jsqr';
import QRCode from 'qrcode';
import {
  decodeQrLink,
  decodeDimensions,
  sanitizeQrLink,
  QR_DECODE_MAX_DIMENSION,
  QR_DECODE_TARGET_DIMENSION,
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
    expect(context.drawImage).toHaveBeenCalledWith(image, 0, 0, IMAGE_SIZE, IMAGE_SIZE);
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

  it('sizes the canvas at the decode target, not at the natural image size', () => {
    mockedJsQR.mockReturnValue({ data: 'https://venmo.com/u/seller' } as never);
    const context = makeContext(validImageData);
    const canvas = makeCanvas(context);
    const image = makeImageElement(canvas, 2048, 2048);
    decodeQrLink(image);
    expect(canvas.width).toBe(QR_DECODE_TARGET_DIMENSION);
    expect(canvas.height).toBe(QR_DECODE_TARGET_DIMENSION);
    expect(context.drawImage).toHaveBeenCalledWith(image, 0, 0, 640, 640);
    expect(context.getImageData).toHaveBeenCalledWith(0, 0, 640, 640);
    expect(mockedJsQR).toHaveBeenCalledWith(validImageData.data, 640, 640);
  });

  it('scales a non-square image on its long edge only', () => {
    mockedJsQR.mockReturnValue({ data: 'https://venmo.com/u/seller' } as never);
    const context = makeContext(validImageData);
    const canvas = makeCanvas(context);
    decodeQrLink(makeImageElement(canvas, 1600, 800));
    expect(canvas.width).toBe(640);
    expect(canvas.height).toBe(320);
    expect(mockedJsQR).toHaveBeenCalledWith(validImageData.data, 640, 320);
  });
});

describe('decodeDimensions', () => {
  it('leaves an image at or under the target untouched', () => {
    expect(decodeDimensions(300, 300)).toEqual({ width: 300, height: 300 });
    expect(decodeDimensions(640, 200)).toEqual({ width: 640, height: 200 });
  });

  it('shrinks the long edge to the target and keeps the aspect ratio', () => {
    expect(decodeDimensions(2048, 2048)).toEqual({ width: 640, height: 640 });
    expect(decodeDimensions(1200, 400)).toEqual({ width: 640, height: 213 });
  });

  it('never collapses a thin image to zero width', () => {
    const scaled = decodeDimensions(40, 2048);
    expect(scaled.width).toBeGreaterThanOrEqual(1);
    expect(scaled.height).toBe(640);
  });
});

describe('decodeQrLink with a real QR symbol', () => {
  /**
   * Downscaling must not cost decode accuracy, and only a real symbol proves
   * that. jsdom has no canvas rasterizer, so the canvas stand-in here does the
   * nearest-neighbour sampling a browser would: the QR is rasterized at a
   * natural size above the decode target, sampled down to the canvas size the
   * code asks for, and handed to the real jsQR.
   */
  const rasterizeQr = (value: string, moduleSize: number) => {
    const qr = QRCode.create(value, { errorCorrectionLevel: 'M' });
    const modules = qr.modules.size;
    const data = qr.modules.data as Uint8Array;
    const width = modules * moduleSize;
    const rgba = new Uint8ClampedArray(width * width * 4);
    for (let y = 0; y < width; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const moduleIndex = Math.floor(y / moduleSize) * modules + Math.floor(x / moduleSize);
        const dark = data[moduleIndex] ? 0 : 255;
        const offset = (y * width + x) * 4;
        rgba[offset] = dark;
        rgba[offset + 1] = dark;
        rgba[offset + 2] = dark;
        rgba[offset + 3] = 255;
      }
    }
    return { width, rgba };
  };

  const makeRasterizingCanvas = (source: { width: number; rgba: Uint8ClampedArray }) => {
    let buffer: Uint8ClampedArray | null = null;
    const context = {
      drawImage: vi.fn((_element: unknown, _x: number, _y: number, targetWidth: number, targetHeight: number) => {
        buffer = new Uint8ClampedArray(targetWidth * targetHeight * 4);
        for (let y = 0; y < targetHeight; y += 1) {
          const sourceY = Math.floor((y * source.width) / targetHeight);
          for (let x = 0; x < targetWidth; x += 1) {
            const sourceX = Math.floor((x * source.width) / targetWidth);
            const from = (sourceY * source.width + sourceX) * 4;
            const to = (y * targetWidth + x) * 4;
            buffer[to] = source.rgba[from];
            buffer[to + 1] = source.rgba[from + 1];
            buffer[to + 2] = source.rgba[from + 2];
            buffer[to + 3] = source.rgba[from + 3];
          }
        }
      }),
      getImageData: vi.fn((_x: number, _y: number, targetWidth: number, targetHeight: number) => ({
        data: buffer as Uint8ClampedArray,
        width: targetWidth,
        height: targetHeight,
      })),
    };
    return { canvas: { width: 0, height: 0, getContext: vi.fn(() => context) }, context };
  };

  it('still decodes a link from an image scaled down to the decode target', async () => {
    // The file-level mock keeps the other cases deterministic; this one hands
    // the pixels to the real decoder.
    const actual = await vi.importActual<typeof import('jsqr')>('jsqr');
    mockedJsQR.mockImplementation(((data: Uint8ClampedArray, width: number, height: number) =>
      actual.default(data, width, height)) as never);

    const link = 'https://venmo.com/u/seller';
    // A 25-module symbol at 40 px per module: 1000x1000, above the 640 target.
    const source = rasterizeQr(link, 40);
    expect(source.width).toBeGreaterThan(QR_DECODE_TARGET_DIMENSION);
    const { canvas, context } = makeRasterizingCanvas(source);
    const image = makeImageElement(canvas, source.width, source.width);

    expect(decodeQrLink(image)).toBe(link);
    expect(context.drawImage).toHaveBeenCalledWith(image, 0, 0, QR_DECODE_TARGET_DIMENSION, QR_DECODE_TARGET_DIMENSION);
  });
});
