/**
 * A dialog that hosts a form, not a yes/no question.
 *
 * `ConfirmDialog` closes itself once its action resolves, which is right for a
 * confirmation and wrong for a form: a validation failure would dismiss the form
 * the user was filling in, taking their typing with it. This host keeps the dialog
 * open until the caller says the write actually finished — so an inline field error
 * is still on screen when it is read.
 *
 * It also keeps the confirm button's pending state in one place, so a slow write
 * cannot be clicked twice into two separate intents.
 */

import React, { useState, type ReactNode } from 'react';
import {
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from '@mui/material';
import { ErrorNote } from './ErrorAlert';

interface FormDialogProps {
  title: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
  children: ReactNode;
  error?: string | null;
  onDismissError?: () => void;
  confirmColor?: React.ComponentProps<typeof Button>['color'];
}

export const FormDialog: React.FC<FormDialogProps> = (props) => {
  const { title, confirmLabel, onCancel, onConfirm, children, confirmColor } = props;
  const [pending, setPending] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  // A form that refuses its own input — or a write the server turned down — stays
  // open with the reason shown. Only the caller closing it ends the dialog, so the
  // person never loses what they typed to a validation miss.
  const run = async () => {
    setPending(true);
    setRefusal(null);
    try {
      await onConfirm();
    } catch (confirmFailure) {
      setRefusal((confirmFailure as Error).message || 'Could not complete this action.');
    } finally {
      setPending(false);
    }
  };

  const problem = props.error ?? refusal;
  return (
    <Dialog open onClose={pending ? undefined : onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {children}
        <ErrorNote message={problem} onDismiss={props.onDismissError} sx={{ mt: 2 }} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          color={confirmColor}
          onClick={() => void run()}
          disabled={pending}
          startIcon={pending ? <CircularProgress size={16} /> : undefined}
          data-testid="form-dialog-confirm"
        >
          {pending ? 'Working…' : confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
