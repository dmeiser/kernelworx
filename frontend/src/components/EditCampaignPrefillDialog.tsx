/**
 * EditCampaignPrefillDialog - Dialog for editing an existing campaign prefill
 *
 * Only allows editing: description, creatorMessage, isActive
 * Cannot modify: catalogId, seasonName, seasonYear, unit info (locked after creation)
 */

import React, { useState, useEffect } from "react";
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
} from "@mui/material";

interface CampaignPrefill {
  prefillCode: string;
  catalogId: string;
  catalog?: {
    catalogId: string;
    catalogName: string;
  };
  seasonName: string;
  seasonYear: number;
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

interface EditCampaignPrefillDialogProps {
  open: boolean;
  prefill: CampaignPrefill;
  onClose: () => void;
  onSave: (
    prefillCode: string,
    updates: {
      description?: string;
      creatorMessage?: string;
      isActive?: boolean;
    },
  ) => Promise<void>;
}

const MAX_CREATOR_MESSAGE_LENGTH = 300;
const BASE_URL = window.location.origin;

export const EditCampaignPrefillDialog: React.FC<
  EditCampaignPrefillDialogProps
> = ({ open, prefill, onClose, onSave }) => {
  const [description, setDescription] = useState(prefill.description || "");
  const [creatorMessage, setCreatorMessage] = useState(
    prefill.creatorMessage || "",
  );
  const [isActive, setIsActive] = useState(prefill.isActive);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when prefill changes
  useEffect(() => {
    setDescription(prefill.description || "");
    setCreatorMessage(prefill.creatorMessage || "");
    setIsActive(prefill.isActive);
    setError(null);
  }, [prefill]);

  const hasChanges =
    description !== (prefill.description || "") ||
    creatorMessage !== (prefill.creatorMessage || "") ||
    isActive !== prefill.isActive;

  const handleSubmit = async () => {
    if (creatorMessage.length > MAX_CREATOR_MESSAGE_LENGTH) {
      setError(
        `Creator message must be ${MAX_CREATOR_MESSAGE_LENGTH} characters or less`,
      );
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await onSave(prefill.prefillCode, {
        description: description.trim() || undefined,
        creatorMessage: creatorMessage.trim() || undefined,
        isActive,
      });
    } catch (err) {
      const errorMessage =
        err instanceof Error
          ? err.message
          : "Failed to update campaign prefill";
      setError(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Edit Campaign Prefill</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}

          {/* Read-only Info */}
          <Box sx={{ bgcolor: "grey.50", p: 2, borderRadius: 1 }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Campaign Details (Read-Only)
            </Typography>
            <Stack spacing={1}>
              <Box display="flex" alignItems="center" gap={1}>
                <Typography variant="body2" fontWeight="medium">
                  Code:
                </Typography>
                <Typography variant="body2" fontFamily="monospace">
                  {prefill.prefillCode}
                </Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={1}>
                <Typography variant="body2" fontWeight="medium">
                  Link:
                </Typography>
                <Typography
                  variant="body2"
                  fontFamily="monospace"
                  sx={{ wordBreak: "break-all" }}
                >
                  {`${BASE_URL}/c/${prefill.prefillCode}`}
                </Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={1}>
                <Typography variant="body2" fontWeight="medium">
                  Catalog:
                </Typography>
                <Typography variant="body2">
                  {prefill.catalog?.catalogName || "Unknown Catalog"}
                </Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={1}>
                <Typography variant="body2" fontWeight="medium">
                  Season:
                </Typography>
                <Typography variant="body2">
                  {prefill.seasonName} {prefill.seasonYear}
                </Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={1}>
                <Typography variant="body2" fontWeight="medium">
                  Unit:
                </Typography>
                <Typography variant="body2">
                  {prefill.unitType} {prefill.unitNumber}, {prefill.city},{" "}
                  {prefill.state}
                </Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={1}>
                <Typography variant="body2" fontWeight="medium">
                  Status:
                </Typography>
                <Chip
                  label={prefill.isActive ? "Active" : "Inactive"}
                  color={prefill.isActive ? "success" : "default"}
                  size="small"
                />
              </Box>
            </Stack>
          </Box>

          {/* Editable Fields */}
          <Typography variant="subtitle2" color="text.secondary">
            Editable Fields
          </Typography>

          {/* Active Status */}
          <FormControlLabel
            control={
              <Switch
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
              />
            }
            label={
              <Stack>
                <Typography>Active</Typography>
                <Typography variant="caption" color="text.secondary">
                  When inactive, the link will no longer work for new season
                  creation
                </Typography>
              </Stack>
            }
          />

          {/* Creator Message */}
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

          {/* Description (for internal use) */}
          <TextField
            label="Description (For Your Reference)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Internal description to help you manage your campaign prefills"
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={!hasChanges || isSubmitting}
          startIcon={isSubmitting ? <CircularProgress size={16} /> : undefined}
        >
          {isSubmitting ? "Saving..." : "Save Changes"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
