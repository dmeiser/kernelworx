/**
 * QR Code URL utilities
 * 
 * Handles conversion of S3 keys to presigned URLs for QR code display.
 * QR codes may be returned as either:
 * - Full presigned URLs (from queries that include URL generation)
 * - S3 keys (from queries that don't)
 * 
 * This utility ensures consistent handling across all pages.
 */

/**
 * Check if a value is a presigned URL (starts with http/https) or an S3 key
 */
export function isPresignedUrl(value: string | null): boolean {
  if (!value) return false;
  return value.startsWith('http://') || value.startsWith('https://');
}

/**
 * Generate a presigned GET URL for a QR code S3 key
 * 
 * This uses the CloudFront vanity domain endpoint for QR code downloads.
 * CloudFront is configured to serve from the exports bucket with proper
 * CORS and caching headers.
 */
export function generateQrCodePresignedUrl(s3Key: string): string {
  // If it's already a presigned URL, return as-is
  if (isPresignedUrl(s3Key)) {
    return s3Key;
  }
  
  // If it's an S3 key, construct CloudFront URL
  // Format: https://qr-codes.dev.kernelworx.app/{s3Key}
  // The S3 key includes the full path like: qr-codes/account123/payment-method-name/...
  const cdnDomain = getCdnDomain();
  return `${cdnDomain}/${s3Key}`;
}

/**
 * Get the appropriate CDN domain based on environment
 */
function getCdnDomain(): string {
  const hostname = window.location.hostname;
  
  if (hostname === 'localhost' || hostname.startsWith('localhost:')) {
    // Local development - use direct S3 endpoint or LocalStack
    return 'http://localhost:9000/kernelworx-exports-ue1-dev';
  }
  
  if (hostname.includes('dev.')) {
    return 'https://qr-codes.dev.kernelworx.app';
  }
  
  if (hostname.includes('staging.')) {
    return 'https://qr-codes.staging.kernelworx.app';
  }
  
  // Production
  return 'https://qr-codes.kernelworx.app';
}

/**
 * Ensure a QR code URL is usable by converting S3 keys to presigned URLs
 * Safe to call on URLs that are already presigned.
 */
export function ensureQrCodeUrl(qrCodeUrlOrKey: string | null): string | null {
  if (!qrCodeUrlOrKey) {
    return null;
  }
  
  return generateQrCodePresignedUrl(qrCodeUrlOrKey);
}
