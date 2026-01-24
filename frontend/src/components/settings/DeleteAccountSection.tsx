/**
 * Delete Account Section Component
 *
 * Allows users to permanently delete their account and all associated data
 */

import React, { useState } from 'react';
import {
  Box,
  Button,
  Typography,
  Paper,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  TextField,
  Alert,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import {
  Delete as DeleteIcon,
  Warning as WarningIcon,
  PersonOff as PersonOffIcon,
  Campaign as CampaignIcon,
  Receipt as ReceiptIcon,
  Share as ShareIcon,
  Category as CategoryIcon,
} from '@mui/icons-material';

interface DeleteAccountSectionProps {
  onDeleteAccount: () => Promise<void>;
  userEmail?: string;
}

export const DeleteAccountSection: React.FC<DeleteAccountSectionProps> = ({ onDeleteAccount, userEmail }) => {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleOpenDialog = () => {
    setDialogOpen(true);
    setConfirmText('');
    setError(null);
  };

  const handleCloseDialog = () => {
    if (!deleting) {
      setDialogOpen(false);
      setConfirmText('');
      setError(null);
    }
  };

  const handleDelete = async () => {
    if (confirmText !== 'DELETE') {
      setError('Please type DELETE to confirm');
      return;
    }

    try {
      setDeleting(true);
      setError(null);
      await onDeleteAccount();
      // Don't close dialog - user will be logged out and redirected
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete account');
      setDeleting(false);
    }
  };

  return (
    <Paper elevation={1} sx={{ p: 3, mt: 3, border: '2px solid', borderColor: 'error.main' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <DeleteIcon color="error" sx={{ mr: 1 }} />
        <Typography variant="h6" color="error">
          Delete Account
        </Typography>
      </Box>

      <Alert severity="error" sx={{ mb: 2 }}>
        <strong>Warning:</strong> This action is permanent and cannot be undone!
      </Alert>

      <Typography variant="body2" color="text.secondary" paragraph>
        Deleting your account will permanently remove all of your data, including:
      </Typography>

      <List dense>
        <ListItem>
          <ListItemIcon>
            <PersonOffIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Your account and login credentials" />
        </ListItem>
        <ListItem>
          <ListItemIcon>
            <PersonOffIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="All seller profiles you created" />
        </ListItem>
        <ListItem>
          <ListItemIcon>
            <CampaignIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="All campaigns and campaign data" />
        </ListItem>
        <ListItem>
          <ListItemIcon>
            <ReceiptIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="All orders and customer information" />
        </ListItem>
        <ListItem>
          <ListItemIcon>
            <ShareIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="All shares and invitations" />
        </ListItem>
        <ListItem>
          <ListItemIcon>
            <CategoryIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="All custom catalogs" />
        </ListItem>
      </List>

      <Typography variant="body2" color="text.secondary" paragraph sx={{ mt: 2 }}>
        Please export any reports you need before proceeding.
      </Typography>

      <Button variant="outlined" color="error" startIcon={<DeleteIcon />} onClick={handleOpenDialog} size="large">
        Delete My Account
      </Button>

      {/* Confirmation Dialog */}
      <Dialog open={dialogOpen} onClose={handleCloseDialog} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <WarningIcon color="error" />
          Confirm Account Deletion
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will permanently delete your account (<strong>{userEmail}</strong>) and all associated data.
          </DialogContentText>

          <Alert severity="warning" sx={{ my: 2 }}>
            This action cannot be undone. All your data will be permanently deleted.
          </Alert>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          <Typography variant="body2" gutterBottom sx={{ mt: 2 }}>
            To confirm, please type <strong>DELETE</strong> in the box below:
          </Typography>

          <TextField
            autoFocus
            fullWidth
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="Type DELETE to confirm"
            disabled={deleting}
            sx={{ mt: 1 }}
            error={error !== null && confirmText !== 'DELETE'}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog} disabled={deleting}>
            Cancel
          </Button>
          <Button onClick={handleDelete} color="error" variant="contained" disabled={deleting || confirmText !== 'DELETE'}>
            {deleting ? 'Deleting...' : 'Delete Account'}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
};
