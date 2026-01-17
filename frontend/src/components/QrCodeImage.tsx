import React from 'react';
import { Box, Typography } from '@mui/material';

interface QrCodeImageProps {
  qrCodeUrl: string | null;
  methodName: string;
  maxHeight?: number;
}

/**
 * QrCodeImage - shared component to display a payment method QR code.
 * - If qrCodeUrl is null, shows a friendly fallback message.
 * - Otherwise renders the QR image with sensible sizing.
 */
export const QrCodeImage: React.FC<QrCodeImageProps> = ({ qrCodeUrl, methodName, maxHeight = 400 }) => {
  if (!qrCodeUrl) {
    return (
      <Typography color="text.secondary" align="center">
        No QR code available for this payment method.
      </Typography>
    );
  }

  return (
    <Box display="flex" justifyContent="center" p={2}>
      <Box
        component="img"
        src={qrCodeUrl}
        alt={`QR code for ${methodName}`}
        sx={{ maxWidth: '100%', maxHeight }}
      />
    </Box>
  );
};

export default QrCodeImage;
