/**
 * CreateProfileDialog component - Dialog for creating a new scout profile
 *
 * Note: Unit fields (unitType, unitNumber) have been moved to Campaign level
 * as part of the Shared Campaign refactor. Unit information is now attached
 * to individual campaigns rather than profiles.
 */

import React, { useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, Box } from '@mui/material';
import { useFormState } from '../hooks/useFormState';

interface CreateProfileDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (sellerName: string) => Promise<void>;
}

interface ProfileFormValues {
  sellerName: string;
}

export const CreateProfileDialog: React.FC<CreateProfileDialogProps> = ({ open, onClose, onSubmit }) => {
  const form = useFormState<ProfileFormValues>({
    initialValues: { sellerName: '' },
  });
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    /* v8 ignore start -- Defensive guard; unreachable because the submit button is disabled and Enter key handler checks the same condition */
    if (!form.values.sellerName.trim()) return;
    /* v8 ignore end */

    setLoading(true);
    try {
      await onSubmit(form.values.sellerName.trim());
      form.reset();
      onClose();
    } catch (error) {
      /* v8 ignore next -- Error logging, tested via integration */
      console.error('Failed to create profile:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      form.reset();
      onClose();
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create New Scout</DialogTitle>
      <DialogContent>
        <Box pt={1} display="flex" flexDirection="column" gap={2}>
          <TextField
            autoFocus
            fullWidth
            label="Scout Name"
            placeholder="e.g., Scout's First and Last Name"
            value={form.values.sellerName}
            onChange={(e) => form.setValue('sellerName', e.target.value)}
            onKeyPress={(e) => {
              if (e.key === 'Enter' && form.values.sellerName.trim()) {
                handleSubmit();
              }
            }}
            disabled={loading}
            helperText="Enter the name of the Scout"
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} variant="contained" disabled={!form.values.sellerName.trim() || loading}>
          {loading ? 'Creating...' : 'Create Scout'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
