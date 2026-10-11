/**
 * Payment method radio plus the seller's QR image and its decoded link.
 *
 * Two attributes on the `<img>` are load-bearing security plumbing, not
 * styling:
 *
 * - `crossOrigin="anonymous"`: without it the canvas read in `lib/qrDecode.ts`
 *   is a tainted-canvas read and `getImageData` throws, so no link can ever be
 *   decoded.
 * - `referrerPolicy="no-referrer"`: the image request is cross-origin to the
 *   exports bucket, and the managed SecurityHeadersPolicy sets
 *   `Referrer-Policy: same-origin`, so without this the capability-bearing
 *   `/o/<profileId>/<token>` path would be sent as `Referer` into S3 access
 *   logs.
 *
 * The decoded link is rendered only through `sanitizeQrLink` (https/mailto
 * only) and only with `rel="noopener noreferrer"` — without `noreferrer` a
 * click leaks the same capability URL to the payment site.
 */

import { useRef, useState } from 'react';
import { Alert, Box, Link, Stack, Typography } from '@mui/material';
import { decodeQrLink } from '../../lib/qrDecode';
import type { PublicPaymentMethodView } from './publicOrderTypes';

export const QR_NO_LINK_HINT = 'Scan this code from another device, or ask the seller how to pay.';

interface QrImageBlockProps {
  method: PublicPaymentMethodView;
  onQrExpired?: () => void;
}

/** The image plus whatever the client-side decode found in it. */
const QrImageBlock: React.FC<QrImageBlockProps> = ({ method, onQrExpired }) => {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [decodedLink, setDecodedLink] = useState<string | null>(null);

  const handleImageLoad = () => {
    const element = imageRef.current;
    setDecodedLink(element ? decodeQrLink(element) : null);
  };

  return (
    <Box sx={{ pl: 3 }}>
      <Box
        ref={imageRef}
        component="img"
        src={method.qrCodeUrl ?? undefined}
        alt={`Payment QR code for ${method.name}`}
        crossOrigin="anonymous"
        referrerPolicy="no-referrer"
        onLoad={handleImageLoad}
        onError={onQrExpired}
        sx={{ maxWidth: 220, maxHeight: 220, display: 'block', mb: 1 }}
      />
      {decodedLink ? (
        <Link
          href={decodedLink}
          target="_blank"
          rel="noopener noreferrer"
          underline="always"
          data-testid="decoded-payment-link"
        >
          {decodedLink}
        </Link>
      ) : (
        <Typography variant="body2" color="text.secondary" data-testid="qr-no-link-hint">
          {QR_NO_LINK_HINT}
        </Typography>
      )}
    </Box>
  );
};

interface PaymentMethodChoiceProps {
  method: PublicPaymentMethodView;
  selected: boolean;
  onSelect: (name: string) => void;
  /** Called when the pre-signed QR image fails to load (it expires after 15 minutes). */
  onQrExpired?: () => void;
}

export const PaymentMethodChoice: React.FC<PaymentMethodChoiceProps> = ({
  method,
  selected,
  onSelect,
  onQrExpired,
}) => (
  <Stack spacing={1} data-testid={`payment-method-${method.name}`}>
    <Box
      component="label"
      sx={{ display: 'flex', alignItems: 'center', gap: 1, cursor: 'pointer' }}
      data-testid={`payment-label-${method.name}`}
      onClick={() => onSelect(method.name)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') onSelect(method.name);
      }}
    >
      <Box
        component="input"
        type="radio"
        name="paymentMethod"
        checked={selected}
        onChange={() => onSelect(method.name)}
      />
      <Typography variant="body1">{method.name}</Typography>
    </Box>

    {selected && method.qrCodeUrl ? <QrImageBlock method={method} onQrExpired={onQrExpired} /> : null}

    {selected && !method.qrCodeUrl ? (
      <Alert severity="info" sx={{ ml: 3 }} data-testid="payment-no-qr">
        No QR code was uploaded for this method. The seller will tell you how to pay.
      </Alert>
    ) : null}
  </Stack>
);

export default PaymentMethodChoice;
