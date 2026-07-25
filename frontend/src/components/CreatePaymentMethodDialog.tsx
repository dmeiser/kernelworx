/**
 * CreatePaymentMethodDialog - Dialog for creating a new custom payment method
 *
 * Features:
 * - Name input with validation
 * - Reserved name checking (cash, check)
 * - Duplicate name prevention
 * - Loading state during creation
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

interface CreatePaymentMethodDialogProps {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
  existingNames: string[];
  isLoading?: boolean;
}

/* eslint-disable complexity -- Complex dialog component with validation */
export const CreatePaymentMethodDialog: React.FC<CreatePaymentMethodDialogProps> = ({
  open,
  onClose,
  onCreate,
  existingNames,
  isLoading = false,
}) => {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Reset state when dialog opens/closes
  useEffect(() => {
    if (open) {
      setName('');
      setError(null);
    }
  }, [open]);

  const validateName = (value: string): string | null => {
    // Use shared validation from paymentMethodValidation.ts
    const result = validatePaymentMethodName(value, existingNames);
    return result.error;
  };

  const handleSubmit = async () => {
    const validationError = validateName(name);
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      await onCreate(name.trim());
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

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create Payment Method</DialogTitle>
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
          placeholder="e.g., Venmo, Zelle, PayPal"
          helperText="Enter a unique name for this payment method"
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
          onClick={() => { void handleSubmit(); }}
          variant="contained"
          disabled={isLoading || !name.trim()}
          startIcon={isLoading ? <CircularProgress size={16} /> : undefined}
        >
          {isLoading ? 'Creating...' : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
/* eslint-enable complexity */
