/**
 * Full-screen / container degraded state component shown when MFA is required for admin actions
 */
import React, { useState, useEffect } from 'react';
import { Box, Paper, Typography, Button, Alert, Stack } from '@mui/material';
import { Security as SecurityIcon, QrCode2 as QrCodeIcon } from '@mui/icons-material';
import { MfaSetupDialog } from './MfaSetupDialog';
import { checkIsFederatedSession, handleSignOutAndRedirect } from '../lib/authUtils';

export interface MfaSetupRequiredStateProps {
  title?: string;
  message?: string;
  onSuccess?: () => void;
  autoOpenDialog?: boolean;
  isFederated?: boolean;
}

const DEFAULT_NATIVE_TITLE = 'MFA Setup Required';
const DEFAULT_NATIVE_MESSAGE =
  'Multi-Factor Authentication (MFA) is required to access administrator features and perform administrative operations. Please set up TOTP MFA on your account to continue.';

const DEFAULT_FEDERATED_TITLE = 'Admin access requires a password sign-in';
const DEFAULT_FEDERATED_MESSAGE =
  'This account signs in through a social provider which cannot present MFA. Administrator functions require signing in with an email and password with Multi-Factor Authentication (MFA) enabled. Please sign out and sign in with your password to continue.';

const computeDisplayTitle = (title?: string, isFederated?: boolean): string => {
  if (title) return title;
  return isFederated ? DEFAULT_FEDERATED_TITLE : DEFAULT_NATIVE_TITLE;
};

const computeDisplayMessage = (message?: string, isFederated?: boolean): string => {
  if (message) return message;
  return isFederated ? DEFAULT_FEDERATED_MESSAGE : DEFAULT_NATIVE_MESSAGE;
};

const FederatedButtons: React.FC<{ onBack: () => void }> = ({ onBack }) => (
  <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 3 }}>
    <Button
      variant="contained"
      color="primary"
      size="large"
      onClick={() => void handleSignOutAndRedirect()}
    >
      Sign Out
    </Button>
    <Button variant="outlined" color="inherit" size="large" onClick={onBack}>
      Back
    </Button>
  </Stack>
);

const NativeButtons: React.FC<{ onOpenDialog: () => void }> = ({ onOpenDialog }) => (
  <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 3 }}>
    <Button
      variant="contained"
      color="primary"
      size="large"
      startIcon={<QrCodeIcon />}
      onClick={onOpenDialog}
    >
      Set Up MFA
    </Button>
  </Stack>
);

const handleBack = () => {
  if (typeof window !== 'undefined' && window.history.length > 1) {
    window.history.back();
  }
};

const useFederatedStatus = (isFederatedProp?: boolean) => {
  const [isFederated, setIsFederated] = useState<boolean | undefined>(isFederatedProp);

  useEffect(() => {
    if (typeof isFederatedProp === 'boolean') {
      setIsFederated(isFederatedProp);
      return;
    }
    let mounted = true;
    void checkIsFederatedSession().then((federated) => {
      if (mounted) setIsFederated(federated);
    });
    return () => {
      mounted = false;
    };
  }, [isFederatedProp]);

  return isFederated ?? false;
};

export const MfaSetupRequiredState: React.FC<MfaSetupRequiredStateProps> = ({
  title,
  message,
  onSuccess,
  autoOpenDialog = false,
  isFederated: isFederatedProp,
}) => {
  const [dialogOpen, setDialogOpen] = useState(autoOpenDialog);
  const isFed = useFederatedStatus(isFederatedProp);
  const displayTitle = computeDisplayTitle(title, isFed);
  const displayMessage = computeDisplayMessage(message, isFed);
  const handleClose = () => setDialogOpen(false);
  const handleOpen = () => setDialogOpen(true);

  return (
    <Paper
      data-testid="mfa-setup-required-state"
      sx={{
        p: { xs: 3, sm: 4 },
        textAlign: 'center',
        maxWidth: 600,
        mx: 'auto',
        my: 4,
        borderRadius: 2,
      }}
    >
      <Box display="flex" justifyContent="center" mb={2}>
        <SecurityIcon color="warning" sx={{ fontSize: 56 }} />
      </Box>

      <Typography variant="h5" component="h2" fontWeight="bold" gutterBottom>
        {displayTitle}
      </Typography>

      <Alert severity="warning" sx={{ mb: 3, textAlign: 'left' }}>
        <strong>Administrator Security Policy:</strong> Admin operations require Multi-Factor Authentication (MFA).
      </Alert>

      <Typography variant="body1" color="text.secondary" paragraph>
        {displayMessage}
      </Typography>

      {isFed ? (
        <FederatedButtons onBack={handleBack} />
      ) : (
        <NativeButtons onOpenDialog={handleOpen} />
      )}

      <MfaSetupDialog
        open={dialogOpen}
        onClose={handleClose}
        onSuccess={onSuccess}
        isFederated={isFed}
      />
    </Paper>
  );
};
