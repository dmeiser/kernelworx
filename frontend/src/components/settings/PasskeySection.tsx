/**
 * Passkeys (WebAuthn) section for User Settings
 */
import {
  Paper,
  Stack,
  Box,
  Typography,
  TextField,
  Button,
  Alert,
  CircularProgress,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import { Fingerprint as PasskeyIcon, Delete as DeleteIcon, Add as AddIcon } from '@mui/icons-material';
import { formatDisplayDate } from '../../lib/date-utils';
import type { UsePasskeysReturn } from '../../hooks/usePasskeys';

interface PasskeySectionProps {
  passkeyHook: UsePasskeysReturn;
  mfaEnabled: boolean;
  onRegisterPasskey: () => void;
}

export const PasskeySection: React.FC<PasskeySectionProps> = ({ passkeyHook, mfaEnabled, onRegisterPasskey }) => {
  return (
    <Paper sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <PasskeyIcon color="primary" />
        <Typography variant="h6">Passkeys (Passwordless Login)</Typography>
      </Stack>

      <Typography variant="body2" color="text.secondary" paragraph>
        Passkeys let you sign in securely without a password - using your fingerprint, face, or device PIN.
      </Typography>
      <PasskeyConflictWarning show={mfaEnabled} />
      <PasskeyStatusAlerts hook={passkeyHook} />
      <RegisteredPasskeys hook={passkeyHook} />
      <RegisterPasskeyForm hook={passkeyHook} onRegisterPasskey={onRegisterPasskey} />
      <PasskeyConfirmDialog hook={passkeyHook} />
    </Paper>
  );
};

const PasskeyConflictWarning: React.FC<{ show: boolean }> = ({ show }) => {
  if (!show) return null;

  return (
    <Alert severity="warning" sx={{ mb: 2 }}>
      <strong>Note:</strong> Passkeys and TOTP MFA cannot be used together. Registering a passkey will disable your
      current MFA setup. Passkeys provide strong authentication without requiring a separate MFA app.
    </Alert>
  );
};

const PasskeyStatusAlerts: React.FC<{ hook: UsePasskeysReturn }> = ({ hook }) => (
  <>
    {hook.passkeySuccess ? (
      <Alert severity="success" sx={{ mb: 2 }} onClose={() => hook.setPasskeySuccess(false)}>
        Passkey registered successfully!
      </Alert>
    ) : null}

    {hook.passkeyError ? (
      <Alert severity="error" sx={{ mb: 2 }} onClose={() => hook.setPasskeyError(null)}>
        {hook.passkeyError}
      </Alert>
    ) : null}
  </>
);

const PasskeyItem: React.FC<{
  passkey: UsePasskeysReturn['passkeys'][number];
  loading: boolean;
  onDelete: (credentialId: string) => void;
}> = ({ passkey, loading, onDelete }) => {
  const handleDelete = () => {
    if (passkey.credentialId) {
      onDelete(passkey.credentialId);
    }
  };

  const secondaryText = passkey.createdAt
    ? `Created: ${formatDisplayDate(passkey.createdAt.toISOString()) || 'Unknown date'}`
    : 'Unknown date';

  return (
    <ListItem
      secondaryAction={
        <IconButton
          edge="end"
          onClick={handleDelete}
          disabled={loading || !passkey.credentialId}
          aria-label="Delete passkey"
        >
          <DeleteIcon />
        </IconButton>
      }
    >
      <ListItemIcon>
        <PasskeyIcon />
      </ListItemIcon>
      <ListItemText primary={passkey.friendlyCredentialName || 'Unnamed Passkey'} secondary={secondaryText} />
    </ListItem>
  );
};

const RegisteredPasskeys: React.FC<{ hook: UsePasskeysReturn }> = ({ hook }) => {
  if (!hook.passkeys.length) return null;

  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle2" gutterBottom>
        Registered Passkeys
      </Typography>
      <List>
        {hook.passkeys.map((pk, index) => (
          <PasskeyItem
            key={`passkey-${index}`}
            passkey={pk}
            loading={hook.passkeyLoading}
            onDelete={hook.handleDeletePasskey}
          />
        ))}
      </List>
    </Box>
  );
};

const RegisterPasskeyForm: React.FC<{
  hook: UsePasskeysReturn;
  onRegisterPasskey: () => void;
}> = ({ hook, onRegisterPasskey }) => (
  <Box>
    <Typography variant="subtitle2" gutterBottom>
      Register a New Passkey
    </Typography>
    <Stack direction="row" spacing={2} alignItems="flex-start" flexWrap="wrap">
      <TextField
        label="Passkey Name"
        value={hook.passkeyName}
        onChange={(event) => hook.setPasskeyName(event.target.value)}
        placeholder="e.g., My iPhone, Work Laptop"
        disabled={hook.passkeyLoading}
        sx={{ flex: 1, minWidth: 0 }}
        helperText="Give this passkey a name to remember which device it's for"
      />
      <Button
        variant="contained"
        startIcon={hook.passkeyLoading ? <CircularProgress size={20} /> : <AddIcon />}
        onClick={onRegisterPasskey}
        disabled={hook.passkeyLoading || !hook.passkeyName.trim()}
      >
        Register
      </Button>
    </Stack>
    <Alert severity="info" sx={{ mt: 2 }}>
      <Typography variant="caption">
        <strong>Note:</strong> Passkeys use your device's built-in security (Touch ID, Face ID, Windows Hello, etc.).
        You'll be prompted to authenticate with your device when registering.
      </Typography>
    </Alert>
  </Box>
);

const PasskeyConfirmDialog: React.FC<{ hook: UsePasskeysReturn }> = ({ hook }) => {
  if (!hook.pendingConfirmation) return null;

  return (
    <Dialog open onClose={hook.cancelPasskeyConfirmation}>
      <DialogTitle>{hook.pendingConfirmation.type === 'delete' ? 'Delete Passkey?' : 'Disable MFA?'}</DialogTitle>
      <DialogContent>
        <Typography>{hook.pendingConfirmation.message}</Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={hook.cancelPasskeyConfirmation}>Cancel</Button>
        <Button onClick={() => void hook.confirmPasskeyAction()} color="error" variant="contained">
          {hook.pendingConfirmation.type === 'delete' ? 'Delete' : 'Continue'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
