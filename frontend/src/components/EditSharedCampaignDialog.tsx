/**
 * EditSharedCampaignDialog - Dialog for editing an existing shared campaign
 *
 * Only allows editing: description, creatorMessage, isActive
 * Cannot modify: catalogId, campaignName, campaignYear, unit info (locked after creation)
 */

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Stack,
  Alert,
  FormControlLabel,
  Switch,
  Typography,
  Box,
  Chip,
  CircularProgress,
} from '@mui/material';

interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  catalog?: {
    catalogId: string;
    catalogName: string;
  };
  campaignName: string;
  campaignYear: number;
  startDate?: string;
  endDate?: string;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  creatorMessage?: string;
  description?: string;
  isActive: boolean;
  createdAt: string;
}

interface EditSharedCampaignDialogProps {
  open: boolean;
  sharedCampaign: SharedCampaign;
  onClose: () => void;
  onSave: (
    sharedCampaignCode: string,
    updates: {
      description?: string;
      creatorMessage?: string;
      isActive?: boolean;
    },
  ) => Promise<void>;
}

const MAX_CREATOR_MESSAGE_LENGTH = 300;
const BASE_URL = window.location.origin;

const DetailRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Box display="flex" alignItems="center" gap={1}>
    <Typography variant="body2" fontWeight="medium">
      {label}:
    </Typography>
    {children}
  </Box>
);

const ReadOnlyInfo: React.FC<{ sharedCampaign: SharedCampaign }> = ({ sharedCampaign }) => (
  <Box sx={{ bgcolor: 'grey.50', p: 2, borderRadius: 1 }}>
    <Typography variant="subtitle2" color="text.secondary" gutterBottom>
      Campaign Details (Read-Only)
    </Typography>
    <Stack spacing={1}>
      <DetailRow label="Code">
        <Typography variant="body2" fontFamily="monospace">
          {sharedCampaign.sharedCampaignCode}
        </Typography>
      </DetailRow>
      <DetailRow label="Link">
        <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: 'break-all' }}>
          {`${BASE_URL}/c/${sharedCampaign.sharedCampaignCode}`}
        </Typography>
      </DetailRow>
      <DetailRow label="Catalog">
        <Typography variant="body2">{sharedCampaign.catalog?.catalogName || 'Unknown Catalog'}</Typography>
      </DetailRow>
      <DetailRow label="Campaign">
        <Typography variant="body2">
          {sharedCampaign.campaignName} {sharedCampaign.campaignYear}
        </Typography>
      </DetailRow>
      <DetailRow label="Unit">
        <Typography variant="body2">
          {sharedCampaign.unitType} {sharedCampaign.unitNumber}, {sharedCampaign.city}, {sharedCampaign.state}
        </Typography>
      </DetailRow>
      <DetailRow label="Status">
        <Chip
          label={sharedCampaign.isActive ? 'Active' : 'Inactive'}
          color={sharedCampaign.isActive ? 'success' : 'default'}
          size="small"
        />
      </DetailRow>
    </Stack>
  </Box>
);

interface EditableFieldsProps {
  isActive: boolean;
  setIsActive: (v: boolean) => void;
  creatorMessage: string;
  setCreatorMessage: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
}

const EditableFields: React.FC<EditableFieldsProps> = ({
  isActive,
  setIsActive,
  creatorMessage,
  setCreatorMessage,
  description,
  setDescription,
}) => (
  <>
    <Typography variant="subtitle2" color="text.secondary">
      Editable Fields
    </Typography>

    <FormControlLabel
      control={<Switch checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />}
      label={
        <Stack>
          <Typography>Active</Typography>
          <Typography variant="caption" color="text.secondary">
            When inactive, the link will no longer work for new campaign creation
          </Typography>
        </Stack>
      }
    />

    <TextField
      label="Message to Scouts"
      value={creatorMessage}
      onChange={(e) => setCreatorMessage(e.target.value)}
      placeholder="Enter a message that will be shown to scouts when they use this link"
      multiline
      rows={2}
      fullWidth
      inputProps={{ maxLength: MAX_CREATOR_MESSAGE_LENGTH }}
      helperText={`${creatorMessage.length}/${MAX_CREATOR_MESSAGE_LENGTH} characters`}
      error={creatorMessage.length > MAX_CREATOR_MESSAGE_LENGTH}
    />

    <TextField
      label="Description (For Your Reference)"
      value={description}
      onChange={(e) => setDescription(e.target.value)}
      placeholder="Internal description to help you manage your campaign shared campaigns"
      fullWidth
    />
  </>
);

const validateMessage = (message: string): string | null =>
  message.length > MAX_CREATOR_MESSAGE_LENGTH
    ? `Creator message must be ${MAX_CREATOR_MESSAGE_LENGTH} characters or less`
    : null;

const checkHasChanges = (
  description: string,
  creatorMessage: string,
  isActive: boolean,
  sharedCampaign: SharedCampaign,
): boolean =>
  description !== (sharedCampaign.description || '') ||
  creatorMessage !== (sharedCampaign.creatorMessage || '') ||
  isActive !== sharedCampaign.isActive;

const useEditFormState = (sharedCampaign: SharedCampaign) => {
  const [description, setDescription] = useState(sharedCampaign.description || '');
  const [creatorMessage, setCreatorMessage] = useState(sharedCampaign.creatorMessage || '');
  const [isActive, setIsActive] = useState(sharedCampaign.isActive);

  useEffect(() => {
    setDescription(sharedCampaign.description || '');
    setCreatorMessage(sharedCampaign.creatorMessage || '');
    setIsActive(sharedCampaign.isActive);
  }, [sharedCampaign]);

  const hasChanges = checkHasChanges(description, creatorMessage, isActive, sharedCampaign);

  return {
    description,
    setDescription,
    creatorMessage,
    setCreatorMessage,
    isActive,
    setIsActive,
    hasChanges,
  };
};

const useSubmitHandler = (
  sharedCampaign: SharedCampaign,
  creatorMessage: string,
  description: string,
  isActive: boolean,
  onSave: EditSharedCampaignDialogProps['onSave'],
) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const executeSave = async () => {
    await onSave(sharedCampaign.sharedCampaignCode, {
      description: description.trim() || undefined,
      creatorMessage: creatorMessage.trim() || undefined,
      isActive,
    });
  };

  const handleSubmit = async () => {
    const validationError = validateMessage(creatorMessage);
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await executeSave();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update campaign sharedCampaign');
    } finally {
      setIsSubmitting(false);
    }
  };

  return { isSubmitting, error, handleSubmit };
};

interface DialogViewProps {
  open: boolean;
  onClose: () => void;
  sharedCampaign: SharedCampaign;
  formState: ReturnType<typeof useEditFormState>;
  submitState: ReturnType<typeof useSubmitHandler>;
}

const DialogView: React.FC<DialogViewProps> = ({ open, onClose, sharedCampaign, formState, submitState }) => (
  <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
    <DialogTitle>Edit Campaign SharedCampaign</DialogTitle>
    <DialogContent>
      <Stack spacing={3} sx={{ mt: 1 }}>
        {submitState.error && <Alert severity="error">{submitState.error}</Alert>}
        <ReadOnlyInfo sharedCampaign={sharedCampaign} />
        <EditableFields
          isActive={formState.isActive}
          setIsActive={formState.setIsActive}
          creatorMessage={formState.creatorMessage}
          setCreatorMessage={formState.setCreatorMessage}
          description={formState.description}
          setDescription={formState.setDescription}
        />
      </Stack>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={submitState.isSubmitting}>
        Cancel
      </Button>
      <Button
        onClick={submitState.handleSubmit}
        variant="contained"
        disabled={!formState.hasChanges || submitState.isSubmitting}
        startIcon={submitState.isSubmitting ? <CircularProgress size={16} /> : undefined}
      >
        {submitState.isSubmitting ? 'Saving...' : 'Save Changes'}
      </Button>
    </DialogActions>
  </Dialog>
);

export const EditSharedCampaignDialog: React.FC<EditSharedCampaignDialogProps> = ({
  open,
  sharedCampaign,
  onClose,
  onSave,
}) => {
  const formState = useEditFormState(sharedCampaign);
  const submitState = useSubmitHandler(
    sharedCampaign,
    formState.creatorMessage,
    formState.description,
    formState.isActive,
    onSave,
  );

  return (
    <DialogView
      open={open}
      onClose={onClose}
      sharedCampaign={sharedCampaign}
      formState={formState}
      submitState={submitState}
    />
  );
};
