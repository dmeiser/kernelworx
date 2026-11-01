import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import QRCode from 'qrcode';
import { useQrDataUrl } from '../../src/hooks/useQrDataUrl';

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn(),
  },
}));

describe('useQrDataUrl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('initializes with null qrDataUrl when no url is provided', () => {
    const { result } = renderHook(() => useQrDataUrl());
    expect(result.current.qrDataUrl).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('generates a QR data URL automatically when url is provided', async () => {
    vi.mocked(QRCode.toDataURL).mockResolvedValue('data:image/png;base64,mockqr' as never);

    const { result } = renderHook(() => useQrDataUrl('https://example.com/c/123'));

    await waitFor(() => {
      expect(result.current.qrDataUrl).toBe('data:image/png;base64,mockqr');
    });
    expect(QRCode.toDataURL).toHaveBeenCalledWith('https://example.com/c/123', {
      width: 400,
      margin: 2,
      color: undefined,
    });
  });

  it('clears qrDataUrl when url becomes null', async () => {
    vi.mocked(QRCode.toDataURL).mockResolvedValue('data:image/png;base64,mockqr' as never);

    const { result, rerender } = renderHook(({ url }: { url?: string | null }) => useQrDataUrl(url), {
      initialProps: { url: 'https://example.com' as string | null },
    });

    await waitFor(() => {
      expect(result.current.qrDataUrl).toBe('data:image/png;base64,mockqr');
    });

    rerender({ url: null });

    await waitFor(() => {
      expect(result.current.qrDataUrl).toBeNull();
    });
  });

  it('handles generation error on url change', async () => {
    const onError = vi.fn();
    const err = new Error('QR failed');
    vi.mocked(QRCode.toDataURL).mockRejectedValue(err as never);

    const { result } = renderHook(() => useQrDataUrl('https://example.com', { onError }));

    await waitFor(() => {
      expect(result.current.error).toBe(err);
    });
    expect(result.current.qrDataUrl).toBeNull();
    expect(onError).toHaveBeenCalledWith(err);
  });

  it('supports imperative generateQrCode call', async () => {
    vi.mocked(QRCode.toDataURL).mockResolvedValue('data:image/png;base64,imperative' as never);

    const { result } = renderHook(() => useQrDataUrl());

    let output: string | null = null;
    await act(async () => {
      output = await result.current.generateQrCode('https://example.com/test');
    });

    expect(output).toBe('data:image/png;base64,imperative');
    expect(result.current.qrDataUrl).toBe('data:image/png;base64,imperative');
  });

  it('imperative generateQrCode handles error and calls override onError', async () => {
    const onError = vi.fn();
    const err = new Error('Imperative failed');
    vi.mocked(QRCode.toDataURL).mockRejectedValue(err as never);

    const { result } = renderHook(() => useQrDataUrl());

    let output: string | null = null;
    await act(async () => {
      output = await result.current.generateQrCode('https://example.com/test', { onError });
    });

    expect(output).toBeNull();
    expect(result.current.qrDataUrl).toBeNull();
    expect(result.current.error).toBe(err);
    expect(onError).toHaveBeenCalledWith(err);
  });

  it('imperative generateQrCode with an empty url clears the state and returns null', async () => {
    const { result } = renderHook(() => useQrDataUrl());

    let output: string | null = 'unset';
    await act(async () => {
      output = await result.current.generateQrCode('');
    });

    expect(output).toBeNull();
    expect(result.current.qrDataUrl).toBeNull();
    expect(result.current.error).toBeNull();
    expect(QRCode.toDataURL).not.toHaveBeenCalled();
  });
});
