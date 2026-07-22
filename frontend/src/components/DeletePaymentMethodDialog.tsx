/**
 * DeletePaymentMethodDialog - Confirmation dialog for deleting a payment method
 *
 * Features:
 * - Clear warning message
 * - Requires confirmation before deletion
 * - Loading state during deletion
 */

import React from 'react';
import { Typography, Alert } from '@mui/material';
import { ConfirmDialog } from './ConfirmDialog';

interface DeletePaymentMethodDialogProps {
  open: boolean;
  onClose: () => void;
  onDelete: () => Promise<void>;
  methodName: string;
  isLoading?: boolean;
}

export const DeletePaymentMethodDialog: React.FC<DeletePaymentMethodDialogProps> = ({
  open,
  onClose,
  onDelete,
  methodName,
  isLoading = false,
}) => (
  <ConfirmDialog
    open={open}
    title="Delete Payment Method"
    onClose={onClose}
    onConfirm={onDelete}
    confirmLabel="Delete"
    confirmColor="error"
    isLoading={isLoading}
    loadingLabel="Deleting..."
  >
    <Alert severity="warning" sx={{ mb: 2 }}>
      This action cannot be undone.
    </Alert>
    <Typography>
      Are you sure you want to delete the payment method <strong>&quot;{methodName}&quot;</strong>?
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
      Existing orders using this payment method will keep their payment type unchanged.
    </Typography>
  </ConfirmDialog>
);
