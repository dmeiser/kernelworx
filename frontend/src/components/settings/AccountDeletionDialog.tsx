/**
 * Account Deletion Dialog Component
 *
 * Provides a stepped confirmation and progress dialog for client-driven
 * account deletion. Offers real-time per-profile feedback and allows resuming
 * if an error occurs.
 */

import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  RadioButtonUnchecked as PendingIcon,
  Replay as ResumeIcon,
  Warning as WarningIcon,
} from '@mui/icons-material';
import type { UseAccountDeletionReturn, ProfileDeletionItem } from '../../hooks/useAccountDeletion';

interface AccountDeletionDialogProps {
  open: boolean;
  onClose: () => void;
  userEmail?: string;
  deletion: UseAccountDeletionReturn;
}

function StatusIcon({ status }: { status: ProfileDeletionItem['status'] }) {
  if (status === 'completed') {
    return <CheckCircleIcon color="success" fontSize="small" />;
  }
  if (status === 'in-progress') {
    return <CircularProgress size={18} color="inherit" />;
  }
  if (status === 'failed') {
    return <ErrorIcon color="error" fontSize="small" />;
  }
  return <PendingIcon color="disabled" fontSize="small" />;
}

interface ConfirmationViewProps {
  userEmail?: string;
  confirmText: string;
  onConfirmTextChange: (text: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmationView({
  userEmail,
  confirmText,
  onConfirmTextChange,
  onConfirm,
  onCancel,
}: ConfirmationViewProps) {
  const isConfirmed = confirmText === 'DELETE';

  return (
    <>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <WarningIcon color="error" />
        Confirm Account Deletion
      </DialogTitle>
      <DialogContent>
        <DialogContentText>
          This will permanently delete your account (<strong>{userEmail}</strong>) and associated profiles,
          campaigns, and orders.
        </DialogContentText>

        <Alert severity="warning" sx={{ my: 2 }}>
          <strong>Warning:</strong> This action is permanent and cannot be undone.
        </Alert>

        <Alert severity="info" sx={{ mb: 2 }}>
          <strong>Note:</strong> Custom catalogs you created are preserved and will not be deleted.
        </Alert>

        <Typography variant="body2" gutterBottom sx={{ mt: 2 }}>
          To confirm, please type <strong>DELETE</strong> in the box below:
        </Typography>

        <TextField
          autoFocus
          fullWidth
          value={confirmText}
          onChange={(e) => onConfirmTextChange(e.target.value)}
          placeholder="Type DELETE to confirm"
          sx={{ mt: 1 }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button
          onClick={onConfirm}
          color="error"
          variant="contained"
          disabled={!isConfirmed}
        >
          Delete Account
        </Button>
      </DialogActions>
    </>
  );
}

function ProgressHeader({ step }: { step: UseAccountDeletionReturn['step'] }) {
  if (step === 'completed') {
    return (
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <CheckCircleIcon color="success" />
        Account Deleted
      </DialogTitle>
    );
  }
  if (step === 'error') {
    return (
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <ErrorIcon color="error" />
        Deletion Interrupted
      </DialogTitle>
    );
  }
  return (
    <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <CircularProgress size={22} color="error" />
      Deleting Account...
    </DialogTitle>
  );
}

function DiscoveryListItem({ isDiscovered, count }: { isDiscovered: boolean; count: number }) {
  const icon = isDiscovered ? (
    <CheckCircleIcon color="success" fontSize="small" />
  ) : (
    <CircularProgress size={18} color="inherit" />
  );
  const text = isDiscovered ? `Found ${count} seller profile(s)` : 'Searching...';

  return (
    <ListItem>
      <ListItemIcon>{icon}</ListItemIcon>
      <ListItemText primary="Discover account profiles" secondary={text} />
    </ListItem>
  );
}

function getProfileSecondaryText(profile: ProfileDeletionItem): string {
  if (profile.status === 'failed') {
    return `Failed: ${profile.error || 'Unknown error'}`;
  }
  if (profile.status === 'completed') {
    return 'Deleted';
  }
  if (profile.status === 'in-progress') {
    return 'Deleting profile & orders...';
  }
  return 'Pending';
}

function ProfileListItem({ profile, index }: { profile: ProfileDeletionItem; index: number }) {
  return (
    <ListItem sx={{ pl: 4 }}>
      <ListItemIcon>
        <StatusIcon status={profile.status} />
      </ListItemIcon>
      <ListItemText
        primary={`Profile ${index + 1}: ${profile.sellerName}`}
        secondary={getProfileSecondaryText(profile)}
      />
    </ListItem>
  );
}

function getAccountSecondaryText(
  step: UseAccountDeletionReturn['step'],
  error: string | null,
  isAccountFailed: boolean
): string {
  if (step === 'completed') {
    return 'Deleted';
  }
  if (step === 'deleting-account') {
    return 'Deleting account and signing out...';
  }
  if (isAccountFailed) {
    return `Failed: ${error || 'Unknown error'}`;
  }
  return 'Pending';
}

function AccountStatusIcon({
  step,
  isAccountFailed,
}: {
  step: UseAccountDeletionReturn['step'];
  isAccountFailed: boolean;
}) {
  if (step === 'completed') {
    return <CheckCircleIcon color="success" fontSize="small" />;
  }
  if (step === 'deleting-account') {
    return <CircularProgress size={18} color="inherit" />;
  }
  if (isAccountFailed) {
    return <ErrorIcon color="error" fontSize="small" />;
  }
  return <PendingIcon color="disabled" fontSize="small" />;
}

function AccountListItem({
  step,
  error,
  isAccountFailed,
}: {
  step: UseAccountDeletionReturn['step'];
  error: string | null;
  isAccountFailed: boolean;
}) {
  return (
    <ListItem>
      <ListItemIcon>
        <AccountStatusIcon step={step} isAccountFailed={isAccountFailed} />
      </ListItemIcon>
      <ListItemText
        primary="Account & credentials"
        secondary={getAccountSecondaryText(step, error, isAccountFailed)}
      />
    </ListItem>
  );
}

function ProgressList({ deletion }: { deletion: UseAccountDeletionReturn }) {
  const isDiscovered = deletion.step !== 'discovering';
  const isAccountFailed =
    deletion.step === 'error' &&
    deletion.profiles.every((p) => p.status === 'completed');

  return (
    <List dense sx={{ my: 1 }}>
      <DiscoveryListItem isDiscovered={isDiscovered} count={deletion.profiles.length} />
      {deletion.profiles.map((profile, idx) => (
        <ProfileListItem key={profile.profileId} profile={profile} index={idx} />
      ))}
      <AccountListItem
        step={deletion.step}
        error={deletion.error}
        isAccountFailed={isAccountFailed}
      />
    </List>
  );
}

export const AccountDeletionDialog: React.FC<AccountDeletionDialogProps> = ({
  open,
  onClose,
  userEmail,
  deletion,
}) => {
  const [confirmText, setConfirmText] = useState('');

  const handleStart = () => {
    void deletion.startDeletion();
  };

  const handleCancel = () => {
    if (!deletion.isProcessing) {
      deletion.reset();
      setConfirmText('');
      onClose();
    }
  };

  const isConfirmedView = deletion.step === 'idle';

  return (
    <Dialog open={open} onClose={handleCancel} maxWidth="sm" fullWidth>
      {isConfirmedView ? (
        <ConfirmationView
          userEmail={userEmail}
          confirmText={confirmText}
          onConfirmTextChange={setConfirmText}
          onConfirm={handleStart}
          onCancel={handleCancel}
        />
      ) : (
        <>
          <ProgressHeader step={deletion.step} />
          <DialogContent>
            {deletion.step === 'error' ? (
              <Alert severity="error" sx={{ mb: 2 }}>
                Deletion encountered an error: {deletion.error}. You can resume to continue deleting remaining data.
              </Alert>
            ) : deletion.step === 'completed' ? (
              <Alert severity="success" sx={{ mb: 2 }}>
                Account successfully deleted. You will be signed out momentarily.
              </Alert>
            ) : (
              <Box sx={{ mb: 2 }}>
                <Alert severity="info" sx={{ mb: 1.5 }}>
                  Please keep this window open while your data is being deleted.
                </Alert>
                <LinearProgress color="error" />
              </Box>
            )}

            <ProgressList deletion={deletion} />
          </DialogContent>
          <DialogActions>
            {deletion.step === 'error' && (
              <>
                <Button onClick={handleCancel}>Close</Button>
                <Button
                  onClick={() => {
                    void deletion.resumeDeletion();
                  }}
                  color="error"
                  variant="contained"
                  startIcon={<ResumeIcon />}
                >
                  Resume Deletion
                </Button>
              </>
            )}
          </DialogActions>
        </>
      )}
    </Dialog>
  );
};
