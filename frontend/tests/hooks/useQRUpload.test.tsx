import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import type { ReactNode } from 'react';
import { useQRUpload } from '../../src/hooks/useQRUpload';
import {
  REQUEST_PAYMENT_METHOD_QR_UPLOAD,
  CONFIRM_PAYMENT_METHOD_QR_UPLOAD,
  DELETE_PAYMENT_METHOD_QR_CODE,
} from '../../src/lib/graphql';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('useQRUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const createWrapper =
    (mocks: Parameters<typeof MockedProvider>[0]['mocks'] = []) =>
    ({ children }: { children: ReactNode }) => (
      <MockedProvider mocks={mocks} addTypename={false}>
        {children}
      </MockedProvider>
    );

  describe('initial state', () => {
    it('starts with isUploading false', () => {
      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(),
      });

      expect(result.current.isUploading).toBe(false);
    });

    it('starts with no upload error', () => {
      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(),
      });

      expect(result.current.uploadError).toBeNull();
    });

    it('starts with isDeleting false', () => {
      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(),
      });

      expect(result.current.isDeleting).toBe(false);
    });

    it('starts with deletingMethodName null', () => {
      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(),
      });

      expect(result.current.deletingMethodName).toBeNull();
    });
  });

  describe('uploadQRCode', () => {
    const mockFile = new File(['test'], 'test.png', { type: 'image/png' });

    const successfulUploadMocks = [
      {
        request: {
          query: REQUEST_PAYMENT_METHOD_QR_UPLOAD,
          variables: { paymentMethodName: 'Venmo' },
        },
        result: {
          data: {
            requestPaymentMethodQRCodeUpload: {
              uploadUrl: 'https://s3.amazonaws.com/bucket',
              fields: '{"key":"test-key","policy":"policy"}',
              s3Key: 'payment-qr-codes/123/abc.png',
            },
          },
        },
      },
      {
        request: {
          query: CONFIRM_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            paymentMethodName: 'Venmo',
            s3Key: 'payment-qr-codes/123/abc.png',
          },
        },
        result: {
          data: {
            confirmPaymentMethodQRCodeUpload: {
              success: true,
              qrCodeUrl: 'https://example.com/qr.png',
            },
          },
        },
      },
    ];

    it('sets isUploading to true during upload', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(successfulUploadMocks),
      });

      let uploadPromise: Promise<void>;
      act(() => {
        uploadPromise = result.current.uploadQRCode('Venmo', mockFile);
      });

      expect(result.current.isUploading).toBe(true);

      await act(async () => {
        await uploadPromise;
      });

      expect(result.current.isUploading).toBe(false);
    });

    it('calls onSuccess after successful upload', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true });
      const onSuccess = vi.fn();

      const { result } = renderHook(() => useQRUpload({ onSuccess }), {
        wrapper: createWrapper(successfulUploadMocks),
      });

      await act(async () => {
        await result.current.uploadQRCode('Venmo', mockFile);
      });

      expect(onSuccess).toHaveBeenCalledTimes(1);
    });

    it('calls refetch after successful upload', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true });
      const refetch = vi.fn().mockResolvedValue({});

      const { result } = renderHook(() => useQRUpload({ refetch }), {
        wrapper: createWrapper(successfulUploadMocks),
      });

      await act(async () => {
        await result.current.uploadQRCode('Venmo', mockFile);
      });

      expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('sets uploadError when request fails', async () => {
      const errorMocks = [
        {
          request: {
            query: REQUEST_PAYMENT_METHOD_QR_UPLOAD,
            variables: { paymentMethodName: 'Venmo' },
          },
          error: new Error('Network error'),
        },
      ];

      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(errorMocks),
      });

      await act(async () => {
        try {
          await result.current.uploadQRCode('Venmo', mockFile);
        } catch {
          // Expected error
        }
      });

      await waitFor(() => {
        expect(result.current.uploadError).toBe('Network error');
      });
    });

    it('sets uploadError when S3 upload fails', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(successfulUploadMocks),
      });

      await act(async () => {
        try {
          await result.current.uploadQRCode('Venmo', mockFile);
        } catch {
          // Expected error
        }
      });

      await waitFor(() => {
        expect(result.current.uploadError).toBe('Failed to upload file to S3');
      });
    });
  });

  describe('deleteQRCode', () => {
    const deleteSuccessMocks = [
      {
        request: {
          query: DELETE_PAYMENT_METHOD_QR_CODE,
          variables: { paymentMethodName: 'Venmo' },
        },
        result: {
          data: {
            deletePaymentMethodQRCode: {
              success: true,
            },
          },
        },
      },
    ];

    it('sets deletingMethodName during deletion', async () => {
      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(deleteSuccessMocks),
      });

      let deletePromise: Promise<void>;
      act(() => {
        deletePromise = result.current.deleteQRCode('Venmo');
      });

      expect(result.current.deletingMethodName).toBe('Venmo');
      expect(result.current.isDeleting).toBe(true);

      await act(async () => {
        await deletePromise;
      });

      expect(result.current.deletingMethodName).toBeNull();
      expect(result.current.isDeleting).toBe(false);
    });

    it('calls onDeleteSuccess after successful deletion', async () => {
      const onDeleteSuccess = vi.fn();

      const { result } = renderHook(() => useQRUpload({ onDeleteSuccess }), {
        wrapper: createWrapper(deleteSuccessMocks),
      });

      await act(async () => {
        await result.current.deleteQRCode('Venmo');
      });

      expect(onDeleteSuccess).toHaveBeenCalledTimes(1);
    });

    it('calls refetch after successful deletion', async () => {
      const refetch = vi.fn().mockResolvedValue({});

      const { result } = renderHook(() => useQRUpload({ refetch }), {
        wrapper: createWrapper(deleteSuccessMocks),
      });

      await act(async () => {
        await result.current.deleteQRCode('Venmo');
      });

      expect(refetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('clearError', () => {
    it('clears the upload error', async () => {
      const errorMocks = [
        {
          request: {
            query: REQUEST_PAYMENT_METHOD_QR_UPLOAD,
            variables: { paymentMethodName: 'Venmo' },
          },
          error: new Error('Test error'),
        },
      ];

      const { result } = renderHook(() => useQRUpload(), {
        wrapper: createWrapper(errorMocks),
      });

      // Trigger an error
      await act(async () => {
        try {
          await result.current.uploadQRCode('Venmo', new File(['test'], 'test.png'));
        } catch {
          // Expected
        }
      });

      await waitFor(() => {
        expect(result.current.uploadError).toBe('Test error');
      });

      // Clear the error
      act(() => {
        result.current.clearError();
      });

      expect(result.current.uploadError).toBeNull();
    });
  });
});
