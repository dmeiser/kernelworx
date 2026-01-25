/**
 * EditProfileDialog component - Dialog for editing a scout profile name
 *
 * Note: Unit fields (unitType, unitNumber) have been moved to Campaign level
 * as part of the Shared Campaign refactor. Unit information is now attached
 * to individual campaigns rather than profiles.
 */

import React, { useState, useEffect } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, Box } from '@mui/material';
import { useFormState } from '../hooks/useFormState';

interface EditProfileDialogProps {
  open: boolean;
  profileId: string;
  currentName: string;
  onClose: () => void;
  onSubmit: (profileId: string, newName: string) => Promise<void>;
}

interface ProfileFormValues {
  sellerName: string;
}

export const EditProfileDialog: React.FC<EditProfileDialogProps> = ({
  open,
  profileId,
  currentName,
  onClose,
  onSubmit,
}) => {
  const form = useFormState<ProfileFormValues>({
    initialValues: { sellerName: currentName },
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    form.resetTo({ sellerName: currentName });
  }, [currentName, open, form]);

  const handleSubmit = async () => {
    if (!form.values.sellerName.trim() || !form.isDirty) return;

    setLoading(true);
    try {
      await onSubmit(profileId, form.values.sellerName.trim());
      onClose();
    } catch (error) {
      /* v8 ignore next -- Error logging, tested via integration */
      console.error('Failed to update profile:', error);
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
      <DialogTitle>Edit Scout</DialogTitle>
      <DialogContent>
        <Box pt={1} display="flex" flexDirection="column" gap={2}>
          <TextField
            autoFocus
            fullWidth
            label="Scout Name"
            value={form.values.sellerName}
            onChange={(e) => form.setValue('sellerName', e.target.value)}
            onKeyPress={(e) => {
              if (e.key === 'Enter' && form.values.sellerName.trim() && form.isDirty) {
                handleSubmit();
              }
            }}
            disabled={loading}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={!form.values.sellerName.trim() || !form.isDirty || loading}
        >
          {loading ? 'Saving...' : 'Save Changes'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
