/**
 * EditProfileDialog component - Dialog for editing a seller profile name
 */

import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
} from "@mui/material";

interface EditProfileDialogProps {
  open: boolean;
  profileId: string;
  currentName: string;
  onClose: () => void;
  onSubmit: (profileId: string, newName: string) => Promise<void>;
}

export const EditProfileDialog: React.FC<EditProfileDialogProps> = ({
  open,
  profileId,
  currentName,
  onClose,
  onSubmit,
}) => {
  const [sellerName, setSellerName] = useState(currentName);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setSellerName(currentName);
  }, [currentName, open]);

  const handleSubmit = async () => {
    if (!sellerName.trim() || sellerName === currentName) return;

    setLoading(true);
    try {
      await onSubmit(profileId, sellerName.trim());
      onClose();
    } catch (error) {
      console.error("Failed to update profile:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      setSellerName(currentName);
      onClose();
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit Seller Profile</DialogTitle>
      <DialogContent>
        <Box pt={1}>
          <TextField
            autoFocus
            fullWidth
            label="Seller Name"
            value={sellerName}
            onChange={(e) => setSellerName(e.target.value)}
            onKeyPress={(e) => {
              if (
                e.key === "Enter" &&
                sellerName.trim() &&
                sellerName !== currentName
              ) {
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
          disabled={!sellerName.trim() || sellerName === currentName || loading}
        >
          {loading ? "Saving..." : "Save Changes"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
