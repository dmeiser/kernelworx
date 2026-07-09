/**
 * Tests for useQRUpload hook
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const mockRequestUpload = vi.fn();
const mockConfirmUpload = vi.fn();
const mockDeleteQR = vi.fn();

const mutationMocks = [mockRequestUpload, mockConfirmUpload, mockDeleteQR];
let mutationCallIndex = 0;

vi.mock('@apollo/client/react', () => ({
  useMutation: () => {
    const mockFn = mutationMocks[mutationCallIndex] ?? vi.fn();
    mutationCallIndex += 1;
    return [mockFn, { loading: false }];
  },
}));

vi.mock('../../src/lib/graphql', () => ({
  REQUEST_PAYMENT_METHOD_QR_UPLOAD: { kind: 'Document', definitions: [] },
  CONFIRM_PAYMENT_METHOD_QR_UPLOAD: { kind: 'Document', definitions: [] },
  DELETE_PAYMENT_METHOD_QR_CODE: { kind: 'Document', definitions: [] },
}));

import { useQRUpload } from '../../src/hooks/useQRUpload';

const createMockFile = (name = 'qr.png', type = 'image/png'): File =>
  new File(['qr-content'], name, { type });

describe('useQRUpload', () => {
  beforeEach(() => {
    mutationCallIndex = 0;
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns initial state', () => {
    const { result } = renderHook(() => useQRUpload());

    expect(result.current.isUploading).toBe(false);
    expect(result.current.isDeleting).toBe(false);
    expect(result.current.uploadError).toBeNull();
    expect(result.current.deletingMethodName).toBeNull();
    expect(typeof result.current.uploadQRCode).toBe('function');
    expect(typeof result.current.deleteQRCode).toBe('function');
    expect(typeof result.current.clearError).toBe('function');
  });

  it('clearError resets uploadError', () => {
    const { result } = renderHook(() => useQRUpload());

    act(() => {
      result.current.clearError();
    });

    expect(result.current.uploadError).toBeNull();
  });

  describe('uploadQRCode', () => {
    it('completes a full upload flow with string fields', async () => {
      const onSuccess = vi.fn();
      const refetch = vi.fn().mockResolvedValue({ data: {} });
      mockRequestUpload.mockResolvedValue({
        data: {
          requestPaymentMethodQRCodeUpload: {
            uploadUrl: 'https://s3.example.com/upload',
            fields: JSON.stringify({ key: 'qr-codes/venmo.png', Policy: 'policy' }),
            s3Key: 'qr-codes/venmo.png',
          },
        },
      });
      const mockFetch = vi.fn().mockResolvedValue({ ok: true });
      vi.stubGlobal('fetch', mockFetch);
      mockConfirmUpload.mockResolvedValue({ data: { confirmPaymentMethodQRCodeUpload: {} } });

      const { result } = renderHook(() => useQRUpload({ onSuccess, refetch }));
      const file = createMockFile();

      await act(async () => {
        await result.current.uploadQRCode('Venmo', file);
      });

      expect(mockRequestUpload).toHaveBeenCalledWith({ variables: { paymentMethodName: 'Venmo' } });
      expect(mockFetch).toHaveBeenCalledTimes(1);
      const fetchCall = mockFetch.mock.calls[0];
      expect(fetchCall[0]).toBe('https://s3.example.com/upload');
      expect(fetchCall[1].method).toBe('POST');
      expect(fetchCall[1].body).toBeInstanceOf(FormData);
      expect(mockConfirmUpload).toHaveBeenCalledWith({
        variables: { paymentMethodName: 'Venmo', s3Key: 'qr-codes/venmo.png' },
      });
      expect(refetch).toHaveBeenCalledTimes(1);
      expect(onSuccess).toHaveBeenCalledTimes(1);
      expect(result.current.isUploading).toBe(false);
      expect(result.current.uploadError).toBeNull();
    });

    it('completes upload flow with pre-parsed object fields', async () => {
      mockRequestUpload.mockResolvedValue({
        data: {
          requestPaymentMethodQRCodeUpload: {
            uploadUrl: 'https://s3.example.com/upload',
            fields: { key: 'qr-codes/paypal.png', Policy: 'policy' },
            s3Key: 'qr-codes/paypal.png',
          },
        },
      });
      const mockFetch = vi.fn().mockResolvedValue({ ok: true });
      vi.stubGlobal('fetch', mockFetch);
      mockConfirmUpload.mockResolvedValue({ data: { confirmPaymentMethodQRCodeUpload: {} } });

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await result.current.uploadQRCode('PayPal', createMockFile('paypal.png'));
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(result.current.uploadError).toBeNull();
    });

    it('works without optional callbacks', async () => {
      mockRequestUpload.mockResolvedValue({
        data: {
          requestPaymentMethodQRCodeUpload: {
            uploadUrl: 'https://s3.example.com/upload',
            fields: '{}',
            s3Key: 'key',
          },
        },
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
      mockConfirmUpload.mockResolvedValue({ data: {} });

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await result.current.uploadQRCode('Cash', createMockFile());
      });

      expect(result.current.isUploading).toBe(false);
    });

    it('throws when requestUpload returns no data', async () => {
      mockRequestUpload.mockResolvedValue({ data: null });

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await expect(result.current.uploadQRCode('Venmo', createMockFile())).rejects.toThrow(
          'Failed to get upload URL',
        );
      });

      expect(result.current.isUploading).toBe(false);
      expect(result.current.uploadError).toBe('Failed to get upload URL');
    });

    it('throws and sets error when requestUpload fails', async () => {
      mockRequestUpload.mockRejectedValue(new Error('Network error'));

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await expect(result.current.uploadQRCode('Venmo', createMockFile())).rejects.toThrow(
          'Network error',
        );
      });

      expect(result.current.uploadError).toBe('Network error');
      expect(result.current.isUploading).toBe(false);
    });

    it('throws and sets error when S3 upload response is not ok', async () => {
      mockRequestUpload.mockResolvedValue({
        data: {
          requestPaymentMethodQRCodeUpload: {
            uploadUrl: 'https://s3.example.com/upload',
            fields: '{}',
            s3Key: 'key',
          },
        },
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await expect(result.current.uploadQRCode('Venmo', createMockFile())).rejects.toThrow(
          'Failed to upload file to S3',
        );
      });

      expect(result.current.uploadError).toBe('Failed to upload file to S3');
      expect(result.current.isUploading).toBe(false);
    });

    it('throws and sets error when confirmUpload fails', async () => {
      mockRequestUpload.mockResolvedValue({
        data: {
          requestPaymentMethodQRCodeUpload: {
            uploadUrl: 'https://s3.example.com/upload',
            fields: '{}',
            s3Key: 'key',
          },
        },
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
      mockConfirmUpload.mockRejectedValue(new Error('Confirm failed'));

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await expect(result.current.uploadQRCode('Venmo', createMockFile())).rejects.toThrow(
          'Confirm failed',
        );
      });

      expect(result.current.uploadError).toBe('Confirm failed');
      expect(result.current.isUploading).toBe(false);
    });

    it('falls back to generic error message for non-Error throws', async () => {
      mockRequestUpload.mockRejectedValue('string-error');

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await expect(result.current.uploadQRCode('Venmo', createMockFile())).rejects.toBe(
          'string-error',
        );
      });

      expect(result.current.uploadError).toBe('Failed to upload QR code');
      expect(result.current.isUploading).toBe(false);
    });

    it('still calls onSuccess when refetch is not provided', async () => {
      const onSuccess = vi.fn();
      mockRequestUpload.mockResolvedValue({
        data: {
          requestPaymentMethodQRCodeUpload: {
            uploadUrl: 'https://s3.example.com/upload',
            fields: '{}',
            s3Key: 'key',
          },
        },
      });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
      mockConfirmUpload.mockResolvedValue({ data: {} });

      const { result } = renderHook(() => useQRUpload({ onSuccess }));

      await act(async () => {
        await result.current.uploadQRCode('Venmo', createMockFile());
      });

      expect(onSuccess).toHaveBeenCalledTimes(1);
    });
  });

  describe('deleteQRCode', () => {
    it('deletes QR code and calls callbacks', async () => {
      const onDeleteSuccess = vi.fn();
      const refetch = vi.fn().mockResolvedValue({ data: {} });
      mockDeleteQR.mockResolvedValue({ data: { deletePaymentMethodQRCode: true } });

      const { result } = renderHook(() => useQRUpload({ onDeleteSuccess, refetch }));

      let promise: Promise<void>;
      act(() => {
        promise = result.current.deleteQRCode('Venmo');
      });

      expect(result.current.deletingMethodName).toBe('Venmo');
      expect(result.current.isDeleting).toBe(true);

      await act(async () => {
        await promise;
      });

      expect(mockDeleteQR).toHaveBeenCalledWith({ variables: { paymentMethodName: 'Venmo' } });
      expect(refetch).toHaveBeenCalledTimes(1);
      expect(onDeleteSuccess).toHaveBeenCalledTimes(1);
      expect(result.current.deletingMethodName).toBeNull();
      expect(result.current.isDeleting).toBe(false);
    });

    it('works without optional callbacks', async () => {
      mockDeleteQR.mockResolvedValue({ data: { deletePaymentMethodQRCode: true } });

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await result.current.deleteQRCode('Zelle');
      });

      expect(mockDeleteQR).toHaveBeenCalledWith({ variables: { paymentMethodName: 'Zelle' } });
      expect(result.current.deletingMethodName).toBeNull();
    });

    it('resets deletingMethodName even when delete fails', async () => {
      mockDeleteQR.mockRejectedValue(new Error('Delete failed'));

      const { result } = renderHook(() => useQRUpload());

      await act(async () => {
        await expect(result.current.deleteQRCode('Venmo')).rejects.toThrow('Delete failed');
      });

      expect(result.current.deletingMethodName).toBeNull();
      expect(result.current.isDeleting).toBe(false);
    });

    it('resets deletingMethodName when refetch fails', async () => {
      const refetch = vi.fn().mockRejectedValue(new Error('Refetch failed'));
      mockDeleteQR.mockResolvedValue({ data: { deletePaymentMethodQRCode: true } });

      const { result } = renderHook(() => useQRUpload({ refetch }));

      await act(async () => {
        await expect(result.current.deleteQRCode('Venmo')).rejects.toThrow('Refetch failed');
      });

      expect(result.current.deletingMethodName).toBeNull();
    });
  });
});
