/**
 * ConfirmDialog - Reusable confirmation dialog with title, message, and action buttons
 *
 * Use for destructive or irreversible actions like delete, deactivate, or remove.
 */

import React, { useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography, CircularProgress, Alert } from '@mui/material';

interface ConfirmButtonProps {
  onClick: () => void;
  label: string;
  color: React.ComponentProps<typeof Button>['color'];
  isLoading: boolean;
  loadingLabel: string;
}

const ConfirmButton: React.FC<ConfirmButtonProps> = ({ onClick, label, color, isLoading, loadingLabel }) => (
  <Button
    onClick={onClick}
    variant="contained"
    color={color}
    disabled={isLoading}
    startIcon={isLoading ? <CircularProgress size={16} /> : undefined}
  >
    {isLoading ? loadingLabel : label}
  </Button>
);

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  confirmLabel?: string;
  confirmColor?: React.ComponentProps<typeof Button>['color'];
  isLoading?: boolean;
  loadingLabel?: string;
  children?: React.ReactNode;
  error?: string | null;
  onDismissError?: () => void;
  maxWidth?: React.ComponentProps<typeof Dialog>['maxWidth'];
}

/* eslint-disable complexity -- wrapper component: destructuring + conditional default props are not real complexity */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = (props) => {
  const {
    open,
    title,
    onClose,
    onConfirm,
    confirmLabel = 'Confirm',
    confirmColor = 'primary',
    isLoading = false,
    loadingLabel = 'Processing...',
    children,
    error,
    onDismissError,
    maxWidth = 'sm',
  } = props;

  const [internalError, setInternalError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const combinedLoading = isLoading || isPending;

  const handleConfirm = async () => {
    setInternalError(null);
    setIsPending(true);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setInternalError(err instanceof Error ? err.message : 'An unexpected error occurred');
    } finally {
      setIsPending(false);
    }
  };

  const displayError = error ?? internalError;

  return (
    <Dialog open={open} onClose={combinedLoading ? undefined : onClose} maxWidth={maxWidth} fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {children || <Typography>Are you sure you want to {confirmLabel.toLowerCase()}?</Typography>}
        {displayError && (
          <Alert severity="error" sx={{ mt: 2 }} onClose={onDismissError}>
            {displayError}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={combinedLoading}>
          Cancel
        </Button>
        <ConfirmButton
          onClick={handleConfirm}
          label={confirmLabel}
          color={confirmColor}
          isLoading={combinedLoading}
          loadingLabel={loadingLabel}
        />
      </DialogActions>
    </Dialog>
  );
};
