/**
 * Account Deletion Dialog Component
 *
 * Provides a stepped confirmation and progress dialog for client-driven
 * account deletion. Offers real-time per-profile feedback and allows resuming
 * if an error occurs.
 */

import React, { useState, useEffect } from 'react';
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
  PersonOff as PersonOffIcon,
  RadioButtonUnchecked as PendingIcon,
  Replay as ResumeIcon,
  Warning as WarningIcon,
} from '@mui/icons-material';
import type { UseAccountDeletionReturn, ProfileDeletionItem, DeletionStep } from '../../hooks/useAccountDeletion';

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

interface ProfilesPreviewListProps {
  isLoading: boolean;
  error: string | null;
  profiles: ProfileDeletionItem[];
  isDiscovered: boolean;
}

function ProfilesPreviewListContent({ profiles }: { profiles: ProfileDeletionItem[] }) {
  if (profiles.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ my: 1, fontStyle: 'italic' }}>
        No seller profiles found.
      </Typography>
    );
  }

  return (
    <Box sx={{ my: 1.5, p: 1.5, bgcolor: 'action.hover', borderRadius: 1 }}>
      <Typography variant="subtitle2" gutterBottom>
        Seller profiles to be deleted ({profiles.length}):
      </Typography>
      <List dense disablePadding>
        {profiles.map((p) => (
          <ListItem key={p.profileId} disableGutters sx={{ py: 0.25 }}>
            <ListItemIcon sx={{ minWidth: 28 }}>
              <PersonOffIcon fontSize="small" color="action" />
            </ListItemIcon>
            <ListItemText
              primary={p.sellerName}
              secondary="Campaigns, orders, and shares will also be deleted"
              primaryTypographyProps={{ variant: 'body2', fontWeight: 500 }}
              secondaryTypographyProps={{ variant: 'caption' }}
            />
          </ListItem>
        ))}
      </List>
    </Box>
  );
}

function ProfilesPreviewList({ isLoading, error, profiles, isDiscovered }: ProfilesPreviewListProps) {
  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, my: 1.5 }}>
        <CircularProgress size={16} />
        <Typography variant="body2" color="text.secondary">
          Finding associated seller profiles...
        </Typography>
      </Box>
    );
  }

  if (!isDiscovered) {
    if (error) {
      return (
        <Alert severity="error" sx={{ my: 1.5 }}>
          Failed to load seller profiles: {error}. Please try again or check your connection before deleting your
          account.
        </Alert>
      );
    }
    return null;
  }

  return <ProfilesPreviewListContent profiles={profiles} />;
}

interface ConfirmationViewProps {
  userEmail?: string;
  confirmText: string;
  onConfirmTextChange: (text: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  isLoadingProfiles: boolean;
  error: string | null;
  profiles: ProfileDeletionItem[];
  isDiscovered: boolean;
}

function ConfirmationView({
  userEmail,
  confirmText,
  onConfirmTextChange,
  onConfirm,
  onCancel,
  isLoadingProfiles,
  error,
  profiles,
  isDiscovered,
}: ConfirmationViewProps) {
  const isConfirmed = confirmText === 'DELETE' && !isLoadingProfiles;

  return (
    <>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <WarningIcon color="error" />
        Confirm Account Deletion
      </DialogTitle>
      <DialogContent>
        <DialogContentText>
          This will permanently delete your account (<strong>{userEmail}</strong>), associated profiles, custom payment
          methods &amp; QR codes, campaigns, and orders.
        </DialogContentText>

        <ProfilesPreviewList
          isLoading={isLoadingProfiles}
          error={error}
          profiles={profiles}
          isDiscovered={isDiscovered}
        />

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
        <Button onClick={onConfirm} color="error" variant="contained" disabled={!isConfirmed}>
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

function DiscoveryListItem({
  isDiscovered,
  count,
  isError,
}: {
  isDiscovered: boolean;
  count: number;
  isError?: boolean;
}) {
  if (isError && !isDiscovered) {
    return (
      <ListItem>
        <ListItemIcon>
          <ErrorIcon color="error" fontSize="small" />
        </ListItemIcon>
        <ListItemText primary="Discover account profiles" secondary="Failed to discover profiles" />
      </ListItem>
    );
  }
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
    return `Failed: ${profile.error}`;
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
    <ListItem dense disableGutters sx={{ py: 0.5 }}>
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
  isAccountFailed: boolean,
): string {
  if (step === 'completed') {
    return 'Deleted';
  }
  if (step === 'deleting-account') {
    return 'Deleting account, payment methods & QR codes...';
  }
  if (isAccountFailed) {
    return `Failed: ${error}`;
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
        primary="Account, payment methods & credentials"
        secondary={getAccountSecondaryText(step, error, isAccountFailed)}
      />
    </ListItem>
  );
}

function ProgressList({ deletion }: { deletion: UseAccountDeletionReturn }) {
  const isDiscovered = deletion.isDiscovered;
  const isAccountFailed =
    deletion.step === 'error' &&
    deletion.profiles.length > 0 &&
    deletion.profiles.every((p) => p.status === 'completed');

  return (
    <List dense sx={{ my: 1 }}>
      <DiscoveryListItem
        isDiscovered={isDiscovered}
        count={deletion.profiles.length}
        isError={deletion.step === 'error'}
      />
      {deletion.profiles.map((profile, idx) => (
        <ProfileListItem key={profile.profileId} profile={profile} index={idx} />
      ))}
      <AccountListItem step={deletion.step} error={deletion.error} isAccountFailed={isAccountFailed} />
    </List>
  );
}

function DeletionStatusAlert({ step, error }: { step: DeletionStep; error: string | null }) {
  if (step === 'error') {
    return (
      <Alert severity="error" sx={{ mb: 2 }}>
        Deletion encountered an error: {error}. You can resume to continue deleting remaining data.
      </Alert>
    );
  }
  if (step === 'completed') {
    return (
      <Alert severity="success" sx={{ mb: 2 }}>
        Account successfully deleted. You will be signed out momentarily.
      </Alert>
    );
  }
  return (
    <Box sx={{ mb: 2 }}>
      <Alert severity="info" sx={{ mb: 1.5 }}>
        Please keep this window open while your data is being deleted.
      </Alert>
      <LinearProgress color="error" />
    </Box>
  );
}

function DeletionProgressView({ deletion, onCancel }: { deletion: UseAccountDeletionReturn; onCancel: () => void }) {
  return (
    <>
      <ProgressHeader step={deletion.step} />
      <DialogContent>
        <DeletionStatusAlert step={deletion.step} error={deletion.error} />
        <ProgressList deletion={deletion} />
      </DialogContent>
      <DialogActions>
        {deletion.step === 'error' && (
          <>
            <Button onClick={onCancel}>Close</Button>
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
  );
}

function canTriggerProfileLoad(
  open: boolean,
  step: DeletionStep,
  isDiscovered: boolean,
  isLoading: boolean,
  hasError: boolean,
): boolean {
  if (!open || step !== 'idle') {
    return false;
  }
  if (isDiscovered || isLoading) {
    return false;
  }
  return !hasError;
}

export const AccountDeletionDialog: React.FC<AccountDeletionDialogProps> = ({ open, onClose, userEmail, deletion }) => {
  const [confirmText, setConfirmText] = useState('');
  const { step, error, isDiscovered, isLoadingProfiles, loadProfiles } = deletion;

  const shouldLoad = canTriggerProfileLoad(open, step, isDiscovered, isLoadingProfiles, Boolean(error));

  useEffect(() => {
    if (shouldLoad) {
      void loadProfiles();
    }
  }, [shouldLoad, loadProfiles]);

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

  return (
    <Dialog open={open} onClose={handleCancel} maxWidth="sm" fullWidth>
      {deletion.step === 'idle' ? (
        <ConfirmationView
          userEmail={userEmail}
          confirmText={confirmText}
          onConfirmTextChange={setConfirmText}
          onConfirm={handleStart}
          onCancel={handleCancel}
          isLoadingProfiles={deletion.isLoadingProfiles}
          error={deletion.error}
          profiles={deletion.profiles}
          isDiscovered={deletion.isDiscovered}
        />
      ) : (
        <DeletionProgressView deletion={deletion} onCancel={handleCancel} />
      )}
    </Dialog>
  );
};
