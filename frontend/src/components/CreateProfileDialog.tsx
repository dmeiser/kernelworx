/**
 * CreateProfileDialog component - Dialog for creating a new seller profile
 */

import React, { useState } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
} from "@mui/material";

interface CreateProfileDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (sellerName: string) => Promise<void>;
}

export const CreateProfileDialog: React.FC<CreateProfileDialogProps> = ({
  open,
  onClose,
  onSubmit,
}) => {
  const [sellerName, setSellerName] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!sellerName.trim()) return;

    setLoading(true);
    try {
      await onSubmit(sellerName.trim());
      setSellerName("");
      onClose();
    } catch (error) {
      console.error("Failed to create profile:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      setSellerName("");
      onClose();
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create New Seller Profile</DialogTitle>
      <DialogContent>
        <Box pt={1}>
          <TextField
            autoFocus
            fullWidth
            label="Seller Name"
            placeholder="e.g., Scout's First and Last Name"
            value={sellerName}
            onChange={(e) => setSellerName(e.target.value)}
            onKeyPress={(e) => {
              if (e.key === "Enter" && sellerName.trim()) {
                handleSubmit();
              }
            }}
            disabled={loading}
            helperText="Enter the name of the Scout or seller"
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
          disabled={!sellerName.trim() || loading}
        >
          {loading ? "Creating..." : "Create Seller"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
