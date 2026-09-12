/**
 * Full-screen / container degraded state component shown when MFA is required for admin actions
 */
import React, { useState } from 'react';
import { Box, Paper, Typography, Button, Alert, Stack } from '@mui/material';
import { Security as SecurityIcon, QrCode2 as QrCodeIcon } from '@mui/icons-material';
import { MfaSetupDialog } from './MfaSetupDialog';

export interface MfaSetupRequiredStateProps {
  title?: string;
  message?: string;
  onSuccess?: () => void;
  autoOpenDialog?: boolean;
}

export const MfaSetupRequiredState: React.FC<MfaSetupRequiredStateProps> = ({
  title = 'MFA Setup Required',
  message = 'Multi-Factor Authentication (MFA) is required to access administrator features and perform administrative operations. Please set up TOTP MFA on your account to continue.',
  onSuccess,
  autoOpenDialog = false,
}) => {
  const [dialogOpen, setDialogOpen] = useState(autoOpenDialog);

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
        {title}
      </Typography>

      <Alert severity="warning" sx={{ mb: 3, textAlign: 'left' }}>
        <strong>Administrator Security Policy:</strong> Admin operations require Multi-Factor Authentication (MFA).
      </Alert>

      <Typography variant="body1" color="text.secondary" paragraph>
        {message}
      </Typography>

      <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 3 }}>
        <Button
          variant="contained"
          color="primary"
          size="large"
          startIcon={<QrCodeIcon />}
          onClick={() => setDialogOpen(true)}
        >
          Set Up MFA
        </Button>
      </Stack>

      <MfaSetupDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSuccess={onSuccess}
      />
    </Paper>
  );
};
