/**
 * EditPaymentMethodDialog - Dialog for renaming an existing custom payment method
 *
 * Features:
 * - Pre-filled name input
 * - Validation against reserved and existing names
 * - Loading state during update
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

interface EditPaymentMethodDialogProps {
  open: boolean;
  onClose: () => void;
  onUpdate: (oldName: string, newName: string) => Promise<void>;
  currentName: string;
  existingNames: string[];
  isLoading?: boolean;
}

/* eslint-disable complexity -- Complex dialog component with validation */
export const EditPaymentMethodDialog: React.FC<EditPaymentMethodDialogProps> = ({
  open,
  onClose,
  onUpdate,
  currentName,
  existingNames,
  isLoading = false,
}) => {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Reset state when dialog opens/closes or currentName changes
  useEffect(() => {
    if (open) {
      setName(currentName);
      setError(null);
    }
  }, [open, currentName]);

  const validateName = (value: string): string | null => {
    // Use shared validation from paymentMethodValidation.ts
    const result = validatePaymentMethodName(value, existingNames, currentName);
    return result.error;
  };

  const handleSubmit = async () => {
    const validationError = validateName(name);
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      await onUpdate(currentName, name.trim());
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

  const hasChanged = name.trim().toLowerCase() !== currentName.toLowerCase();

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit Payment Method</DialogTitle>
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
          helperText={hasChanged ? 'This will update the name for all orders using this payment method' : ''}
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
          {isLoading ? 'Updating...' : 'Update'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
/* eslint-enable complexity */
