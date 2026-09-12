/**
 * PaymentMethodDialog - Shared dialog for creating or editing a custom payment method
 *
 * Single form/dialog implementation parameterized by mode. The public
 * CreatePaymentMethodDialog and EditPaymentMethodDialog components are thin
 * wrappers over this dialog.
 *
 * Features:
 * - Name input with validation
 * - Reserved name checking (cash, check)
 * - Duplicate name prevention
 * - Loading state during submission
 */

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Alert,
  CircularProgress,
} from '@mui/material';
import { validatePaymentMethodName, MAX_NAME_LENGTH } from '../lib/paymentMethodValidation';

export interface PaymentMethodDialogProps {
  mode: 'create' | 'edit';
  open: boolean;
  onClose: () => void;
  onSubmit: (trimmedName: string) => Promise<void>;
  existingNames: string[];
  currentName?: string;
  isLoading?: boolean;
}

/* eslint-disable complexity -- Complex dialog component with validation */
export const PaymentMethodDialog: React.FC<PaymentMethodDialogProps> = ({
  mode,
  open,
  onClose,
  onSubmit,
  existingNames,
  currentName = '',
  isLoading = false,
}) => {
  const isEdit = mode === 'edit';
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Reset state when dialog opens/closes (or currentName changes in edit mode)
  useEffect(() => {
    if (open) {
      setName(isEdit ? currentName : '');
      setError(null);
    }
  }, [open, isEdit, currentName]);

  const validateName = (value: string): string | null => {
    // Use shared validation from paymentMethodValidation.ts
    const result = validatePaymentMethodName(value, existingNames, isEdit ? currentName : undefined);
    return result.error;
  };

  const handleSubmit = async () => {
    const validationError = validateName(name);
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      await onSubmit(name.trim());
      onClose();
    } catch {
      // Error handling is done in parent component
    }
  };

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value;
    setName(newValue);

    // Clear error when user types
    if (error) {
      setError(null);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !isLoading) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  const title = isEdit ? 'Edit Payment Method' : 'Create Payment Method';
  const actionLabel = isEdit ? 'Update' : 'Create';
  const loadingLabel = isEdit ? 'Updating...' : 'Creating...';
  const hasChanged = name.trim().toLowerCase() !== currentName.toLowerCase();
  const helperText = isEdit
    ? hasChanged
      ? 'This will update the name for all orders using this payment method'
      : ''
    : 'Enter a unique name for this payment method';

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <TextField
          autoFocus
          margin="dense"
          label="Payment Method Name"
          fullWidth
          value={name}
          onChange={handleNameChange}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          placeholder={isEdit ? undefined : 'e.g., Venmo, Zelle, PayPal'}
          helperText={helperText}
          inputProps={{
            maxLength: MAX_NAME_LENGTH,
            'aria-label': 'Payment method name',
          }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isLoading}>
          Cancel
        </Button>
        <Button
          onClick={() => {
            void handleSubmit();
          }}
          variant="contained"
          disabled={isLoading || !name.trim()}
          startIcon={isLoading ? <CircularProgress size={16} /> : undefined}
        >
          {isLoading ? loadingLabel : actionLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
/* eslint-enable complexity */
