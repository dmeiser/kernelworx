/**
 * Shared hook for QR code data URL generation.
 */
import { useCallback, useEffect, useState } from 'react';
import QRCode from 'qrcode';

export interface UseQrDataUrlOptions {
  width?: number;
  margin?: number;
  color?: {
    dark?: string;
    light?: string;
  };
  onError?: (err: unknown) => void;
}

export interface UseQrDataUrlReturn {
  qrDataUrl: string | null;
  loading: boolean;
  error: unknown | null;
  generateQrCode: (url: string, overrideOptions?: UseQrDataUrlOptions) => Promise<string | null>;
}

const DEFAULT_OPTIONS = {
  width: 400,
  margin: 2,
};

function buildQrOptions(options?: UseQrDataUrlOptions, override?: UseQrDataUrlOptions) {
  const merged: UseQrDataUrlOptions = {
    width: DEFAULT_OPTIONS.width,
    margin: DEFAULT_OPTIONS.margin,
  };
  if (options) Object.assign(merged, options);
  if (override) Object.assign(merged, override);
  return merged;
}

function isUrlEmpty(url: string | null | undefined): boolean {
  return !url || url.trim() === '';
}

function resolveErrorHandler(override?: UseQrDataUrlOptions, base?: UseQrDataUrlOptions) {
  return override?.onError || base?.onError;
}

function reportQrError(
  err: unknown,
  onError?: (err: unknown) => void,
  setError?: (err: unknown) => void,
  setQrDataUrl?: (url: string | null) => void,
) {
  if (import.meta.env.DEV) {
    console.error('Failed to generate QR code:', err);
  }
  setError?.(err);
  setQrDataUrl?.(null);
  onError?.(err);
}

export function useQrDataUrl(url?: string | null, options?: UseQrDataUrlOptions): UseQrDataUrlReturn {
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<unknown | null>(null);

  const generateQrCode = useCallback(
    async (targetUrl: string, overrideOptions?: UseQrDataUrlOptions): Promise<string | null> => {
      if (isUrlEmpty(targetUrl)) {
        setQrDataUrl(null);
        setError(null);
        return null;
      }

      setLoading(true);
      setError(null);

      const qrOptions = buildQrOptions(options, overrideOptions);
      const errorHandler = resolveErrorHandler(overrideOptions, options);

      try {
        const dataUrl = await QRCode.toDataURL(targetUrl, qrOptions);
        setQrDataUrl(dataUrl);
        return dataUrl;
      } catch (err) {
        reportQrError(err, errorHandler, setError, setQrDataUrl);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [options],
  );

  useEffect(() => {
    if (isUrlEmpty(url)) {
      setQrDataUrl(null);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    const qrOptions = buildQrOptions(options);

    QRCode.toDataURL(url!, qrOptions)
      .then((dataUrl) => {
        if (!cancelled) {
          setQrDataUrl(dataUrl);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          reportQrError(err, options?.onError, setError, setQrDataUrl);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [url, options]);

  return {
    qrDataUrl,
    loading,
    error,
    generateQrCode,
  };
}
