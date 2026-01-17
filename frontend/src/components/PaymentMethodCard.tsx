/**
 * PaymentMethodCard - Display a single payment method with actions
 *
 * Shows:
 * - Payment method name
 * - QR code preview (if available)
 * - Edit, Delete, Upload QR, Delete QR buttons (for custom methods only)
 * - Reserved methods (Cash, Check) are displayed but cannot be edited/deleted
 */

import React, { useState } from 'react';
import {
  Card,
  CardContent,
  Box,
  Typography,
  IconButton,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Chip,
  CircularProgress,
} from '@mui/material';
import {
  Edit as EditIcon,
  Delete as DeleteIcon,
  QrCode as QrCodeIcon,
  CloudUpload as UploadIcon,
  DeleteForever as DeleteQRIcon,
} from '@mui/icons-material';
import { QrCodeImage } from './QrCodeImage';

interface PaymentMethod {
  name: string;
  qrCodeUrl: string | null;
}

interface PaymentMethodCardProps {
  method: PaymentMethod;
  isReserved: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onUploadQR: () => void;
  onDeleteQR: () => void;
  isDeleting?: boolean;
  isUploadingQR?: boolean;
}

/* eslint-disable complexity -- Card component with many conditional UI elements */
export const PaymentMethodCard: React.FC<PaymentMethodCardProps> = ({
  method,
  isReserved,
  onEdit,
  onDelete,
  onUploadQR,
  onDeleteQR,
  isDeleting = false,
  isUploadingQR = false,
}) => {
  const [qrPreviewOpen, setQrPreviewOpen] = useState(false);

  const hasQrCode = Boolean(method.qrCodeUrl);

  return (
    <>
      <Card variant="outlined">
        <CardContent>
          <Box display="flex" alignItems="center" justifyContent="space-between">
            {/* Left side: Name and badges */}
            <Box display="flex" alignItems="center" gap={1}>
              <Typography variant="h6" component="span">
                {method.name}
              </Typography>
              {isReserved && <Chip label="Built-in" size="small" color="default" variant="outlined" />}
              {hasQrCode && (
                <Tooltip title="Click to view QR code">
                  <IconButton
                    size="small"
                    color="primary"
                    onClick={() => setQrPreviewOpen(true)}
                    aria-label={`View QR code for ${method.name}`}
                  >
                    <QrCodeIcon />
                  </IconButton>
                </Tooltip>
              )}
            </Box>

            {/* Right side: Actions (only for non-reserved methods) */}
            {!isReserved && (
              <Box display="flex" gap={0.5}>
                {!hasQrCode && (
                  <Tooltip title={isUploadingQR ? 'Uploading...' : 'Upload QR code'}>
                    <IconButton
                      size="small"
                      onClick={onUploadQR}
                      disabled={isUploadingQR}
                      aria-label={`Upload QR code for ${method.name}`}
                    >
                      {isUploadingQR ? <CircularProgress size={20} /> : <UploadIcon />}
                    </IconButton>
                  </Tooltip>
                )}
                {hasQrCode && (
                  <Tooltip title={isDeleting ? 'Deleting...' : 'Delete QR code'}>
                    <IconButton
                      size="small"
                      color="warning"
                      onClick={onDeleteQR}
                      disabled={isDeleting}
                      aria-label={`Delete QR code for ${method.name}`}
                    >
                      {isDeleting ? <CircularProgress size={20} /> : <DeleteQRIcon />}
                    </IconButton>
                  </Tooltip>
                )}
                <Tooltip title="Edit name">
                  <IconButton size="small" onClick={onEdit} aria-label={`Edit ${method.name}`}>
                    <EditIcon />
                  </IconButton>
                </Tooltip>
                <Tooltip title="Delete payment method">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={onDelete}
                    disabled={isDeleting}
                    aria-label={`Delete ${method.name}`}
                  >
                    <DeleteIcon />
                  </IconButton>
                </Tooltip>
              </Box>
            )}
          </Box>
        </CardContent>
      </Card>

      {/* QR Code Preview Dialog */}
      <Dialog open={qrPreviewOpen} onClose={() => setQrPreviewOpen(false)} maxWidth="sm">
        <DialogTitle>QR Code for {method.name}</DialogTitle>
        <DialogContent>
          <QrCodeImage qrCodeUrl={method.qrCodeUrl} methodName={method.name} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setQrPreviewOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  );
};
/* eslint-enable complexity */
