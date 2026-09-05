/**
 * Delete Account Section Component
 *
 * Allows users to permanently delete their account and all associated data.
 * Orchestrates stepped deletion on the frontend with user feedback and
 * resumption support. Catalogs are never deleted.
 */

import React, { useState } from 'react';
import {
  Box,
  Button,
  Typography,
  Paper,
  Alert,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import {
  Delete as DeleteIcon,
  PersonOff as PersonOffIcon,
  Campaign as CampaignIcon,
  Receipt as ReceiptIcon,
  Share as ShareIcon,
  MenuBook as CatalogIcon,
  Payment as PaymentIcon,
} from '@mui/icons-material';
import { useAccountDeletion } from '../../hooks/useAccountDeletion';
import { AccountDeletionDialog } from './AccountDeletionDialog';

interface DeleteAccountSectionProps {
  onAccountDeleted?: () => Promise<void>;
  onDeleteAccount?: () => Promise<void>;
  userEmail?: string;
}

export const DeleteAccountSection: React.FC<DeleteAccountSectionProps> = ({
  onAccountDeleted,
  onDeleteAccount,
  userEmail,
}) => {
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleSuccess = async () => {
    if (onAccountDeleted) {
      await onAccountDeleted();
    } else if (onDeleteAccount) {
      await onDeleteAccount();
    }
  };

  const deletion = useAccountDeletion({
    onSuccess: handleSuccess,
  });

  const handleOpenDialog = () => {
    deletion.reset();
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    if (!deletion.isProcessing) {
      setDialogOpen(false);
      deletion.reset();
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
            <PaymentIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary="Custom payment methods & QR codes"
            secondary="All payment preferences and uploaded QR code images stored in S3"
          />
        </ListItem>
        <ListItem>
          <ListItemIcon>
            <CatalogIcon fontSize="small" color="primary" />
          </ListItemIcon>
          <ListItemText
            primary="Custom catalogs"
            secondary="Catalogs you created will be preserved and never deleted"
          />
        </ListItem>
      </List>

      <Typography variant="body2" color="text.secondary" paragraph sx={{ mt: 2 }}>
        Please export any reports you need before proceeding.
      </Typography>

      <Button
        variant="outlined"
        color="error"
        startIcon={<DeleteIcon />}
        onClick={handleOpenDialog}
        size="large"
      >
        Delete My Account
      </Button>

      <AccountDeletionDialog
        open={dialogOpen}
        onClose={handleCloseDialog}
        userEmail={userEmail}
        deletion={deletion}
      />
    </Paper>
  );
};
