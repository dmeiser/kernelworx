/**
 * MFA (Multi-Factor Authentication) section for User Settings
 */
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import {
  CheckCircle as CheckIcon,
  Delete as DeleteIcon,
  QrCode2 as QrCodeIcon,
  Security as SecurityIcon,
} from '@mui/icons-material';
import type { UseMfaReturn } from '../../hooks/useMfa';

interface MfaSectionProps {
  mfaHook: UseMfaReturn;
  passkeyCount?: number;
  onSetupMFA: () => void;
  isAdmin?: boolean;
}

interface MfaStatusAlertsProps {
  hook: UseMfaReturn;
}

const MfaStatusAlerts: React.FC<MfaStatusAlertsProps> = ({ hook }) => (
  <>
    {hook.mfaSuccess && (
      <Alert severity="success" sx={{ mb: 2 }} onClose={() => hook.setMfaSuccess(false)}>
        MFA has been successfully enabled!
      </Alert>
    )}

    {hook.mfaError && (
      <Alert severity="error" sx={{ mb: 2 }} onClose={() => hook.setMfaError(null)}>
        {hook.mfaError}
      </Alert>
    )}

    {hook.mfaEnabled && !hook.mfaSetupCode && (
      <Alert severity="success" icon={<CheckIcon />} sx={{ mb: 2 }}>
        <Typography variant="body2" fontWeight={600}>
          MFA is currently enabled
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Your account is protected with multi-factor authentication
        </Typography>
      </Alert>
    )}
  </>
);

interface MfaPrimaryActionsProps {
  hook: UseMfaReturn;
  onSetup: () => void;
}

const MfaPrimaryActions: React.FC<MfaPrimaryActionsProps> = ({ hook, onSetup }) => (
  <>
    {!hook.mfaSetupCode && !hook.mfaEnabled && (
      <Button variant="contained" startIcon={<QrCodeIcon />} onClick={onSetup} disabled={hook.mfaLoading}>
        {hook.mfaLoading ? <CircularProgress size={24} /> : 'Set Up MFA'}
      </Button>
    )}

    {hook.mfaEnabled && (
      <Button
        variant="outlined"
        color="error"
        startIcon={<DeleteIcon />}
        onClick={hook.handleDisableMFA}
        disabled={hook.mfaLoading}
        sx={{ mt: 2 }}
      >
        Disable MFA
      </Button>
    )}
  </>
);

interface MfaSetupSectionProps {
  hook: UseMfaReturn;
}

const MfaSetupSection: React.FC<MfaSetupSectionProps> = ({ hook }) => {
  if (!hook.mfaSetupCode || !hook.qrCodeUrl) return null;

  return (
    <Box sx={{ mt: 3 }}>
      <Divider sx={{ mb: 3 }} />

      <Typography variant="subtitle1" fontWeight={600} gutterBottom>
        Step 1: Scan QR Code
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Use an authenticator app (Google Authenticator, Authy, 1Password, etc.) to scan this QR code:
      </Typography>

      <Box sx={{ textAlign: 'center', my: 3 }}>
        <img src={hook.qrCodeUrl} alt="MFA QR Code" style={{ maxWidth: '256px' }} />
      </Box>

      <Typography variant="subtitle2" gutterBottom>
        Or enter this code manually:
      </Typography>
      <Paper variant="outlined" sx={{ p: 2, mb: 3, bgcolor: 'grey.50' }}>
        <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: 'break-all' }}>
          {hook.mfaSetupCode}
        </Typography>
      </Paper>

      <Typography variant="subtitle1" fontWeight={600} gutterBottom>
        Step 2: Verify Code
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Enter the 6-digit code from your authenticator app to complete setup:
      </Typography>

      <form
        onSubmit={(e) => {
          void hook.handleVerifyMFA(e);
        }}
      >
        <Stack direction="row" spacing={2} alignItems="flex-start" flexWrap="wrap">
          <TextField
            label="Verification Code"
            value={hook.mfaVerificationCode}
            onChange={(event) => hook.setMfaVerificationCode(event.target.value.replace(/\D/g, '').substring(0, 6))}
            required
            disabled={hook.mfaLoading}
            inputProps={{ maxLength: 6, pattern: '[0-9]*' }}
            helperText="Enter the 6-digit code"
            sx={{ minWidth: 0 }}
          />
          <Button type="submit" variant="contained" disabled={hook.mfaLoading || hook.mfaVerificationCode.length !== 6}>
            {hook.mfaLoading ? <CircularProgress size={24} /> : 'Verify & Enable'}
          </Button>
          <Button variant="outlined" onClick={hook.resetMfaSetup} disabled={hook.mfaLoading}>
            Cancel
          </Button>
        </Stack>
      </form>
    </Box>
  );
};

interface MfaConfirmDialogProps {
  hook: UseMfaReturn;
}

const MfaConfirmDialog: React.FC<MfaConfirmDialogProps> = ({ hook }) => {
  if (!hook.pendingConfirmation) return null;

  return (
    <Dialog open onClose={hook.cancelMfaConfirmation}>
      <DialogTitle>Disable MFA?</DialogTitle>
      <DialogContent>
        <Typography>{hook.pendingConfirmation.message}</Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={hook.cancelMfaConfirmation}>Cancel</Button>
        <Button onClick={() => void hook.confirmDisableMFA()} color="error" variant="contained">
          Disable
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export const MfaSection: React.FC<MfaSectionProps> = ({ mfaHook, onSetupMFA, isAdmin }) => (
  <Paper sx={{ p: 3, mb: 3 }}>
    <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
      <SecurityIcon color="primary" />
      <Typography variant="h6">Multi-Factor Authentication (MFA)</Typography>
    </Stack>

    <Typography variant="body2" color="text.secondary" paragraph>
      Add an extra layer of security to your account with TOTP multi-factor authentication. Both an authenticator app and passkeys are supported together.
    </Typography>

    {isAdmin && (
      <Alert severity="info" sx={{ mb: 2 }}>
        <strong>Administrator notice:</strong> Admin operations need an authenticator app (TOTP) enrolled; a passkey alone signs you in but does not grant admin.
      </Alert>
    )}

    <MfaStatusAlerts hook={mfaHook} />
    <MfaPrimaryActions hook={mfaHook} onSetup={onSetupMFA} />
    <MfaSetupSection hook={mfaHook} />
    <MfaConfirmDialog hook={mfaHook} />
  </Paper>
);
