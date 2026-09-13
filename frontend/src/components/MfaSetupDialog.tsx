/**
 * Dialog for setting up TOTP Multi-Factor Authentication (MFA)
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Typography,
  Alert,
  CircularProgress,
  Box,
  Paper,
  Stack,
} from '@mui/material';
import {
  setUpTOTP,
  verifyTOTPSetup,
  updateMFAPreference,
  signOut,
} from 'aws-amplify/auth';
import QRCode from 'qrcode';

export interface MfaSetupDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    return String((err as { message: unknown }).message);
  }
  return fallback;
};

const attemptSignOut = async (): Promise<void> => {
  try {
    await signOut({ global: true });
  } catch {
    try {
      await signOut();
    } catch {
      // Ignored: sign out attempt handled
    }
  }
};

const fetchTotpSetup = async (
  setSharedSecret: (val: string) => void,
  setOtpauthUrl: (val: string) => void,
  setQrCodeUrl: (val: string) => void,
  setError: (val: string | null) => void,
  setLoading: (val: boolean) => void,
): Promise<void> => {
  setLoading(true);
  setError(null);
  try {
    const totpDetails = await setUpTOTP();
    const uri = totpDetails.getSetupUri('KernelWorx');
    const qr = await QRCode.toDataURL(uri.href);
    setSharedSecret(totpDetails.sharedSecret);
    setOtpauthUrl(uri.href);
    setQrCodeUrl(qr);
  } catch (err: unknown) {
    setError(getErrorMessage(err, 'Failed to initialize MFA setup'));
  } finally {
    setLoading(false);
  }
};

const MfaSuccessView: React.FC = () => {
  const handleSignInAgain = () => {
    void attemptSignOut().finally(() => {
      window.location.href = '/login';
    });
  };

  return (
    <Box sx={{ py: 2, textAlign: 'center' }}>
      <Alert severity="success" sx={{ mb: 3 }}>
        MFA enabled — sign in again
      </Alert>
      <Typography variant="body1" color="text.secondary" paragraph>
        Multi-factor authentication is now configured. To apply your updated security credentials, please sign in again.
      </Typography>
      <Button variant="contained" color="primary" size="large" onClick={handleSignInAgain} sx={{ mt: 1 }}>
        Sign In Again
      </Button>
    </Box>
  );
};

const MfaQrSection: React.FC<{ qrCodeUrl: string | null }> = ({ qrCodeUrl }) => {
  if (!qrCodeUrl) return null;
  return (
    <Box sx={{ textAlign: 'center', my: 1 }}>
      <img src={qrCodeUrl} alt="MFA QR Code" style={{ maxWidth: '200px' }} />
    </Box>
  );
};

const MfaSecretSection: React.FC<{ sharedSecret: string | null }> = ({ sharedSecret }) => {
  if (!sharedSecret) return null;
  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Secret Key:
      </Typography>
      <Paper variant="outlined" sx={{ p: 1.5, bgcolor: 'grey.50' }}>
        <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: 'break-all' }}>
          {sharedSecret}
        </Typography>
      </Paper>
    </Box>
  );
};

const MfaUrlSection: React.FC<{ otpauthUrl: string | null }> = ({ otpauthUrl }) => {
  if (!otpauthUrl) return null;
  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Configuration URL:
      </Typography>
      <Typography
        variant="caption"
        fontFamily="monospace"
        color="text.secondary"
        sx={{ wordBreak: 'break-all', display: 'block' }}
      >
        {otpauthUrl}
      </Typography>
    </Box>
  );
};

interface MfaFormViewProps {
  qrCodeUrl: string | null;
  sharedSecret: string | null;
  otpauthUrl: string | null;
  verificationCode: string;
  verifying: boolean;
  onCodeChange: (code: string) => void;
}

const MfaFormView: React.FC<MfaFormViewProps> = ({
  qrCodeUrl,
  sharedSecret,
  otpauthUrl,
  verificationCode,
  verifying,
  onCodeChange,
}) => (
  <Stack spacing={2} sx={{ mt: 1 }}>
    <Typography variant="body2" color="text.secondary">
      Scan this QR code with your authenticator app (Google Authenticator, 1Password, Authy, etc.):
    </Typography>

    <MfaQrSection qrCodeUrl={qrCodeUrl} />
    <MfaSecretSection sharedSecret={sharedSecret} />
    <MfaUrlSection otpauthUrl={otpauthUrl} />

    <TextField
      label="Verification Code"
      value={verificationCode}
      onChange={(e) => onCodeChange(e.target.value.replace(/\D/g, '').substring(0, 6))}
      placeholder="000000"
      inputProps={{ maxLength: 6, pattern: '[0-9]*' }}
      fullWidth
      disabled={verifying}
      helperText="Enter the 6-digit code from your authenticator app"
      autoFocus
    />
  </Stack>
);

const MfaDialogTitle: React.FC<{ success: boolean }> = ({ success }) => (
  <DialogTitle>{success ? 'MFA Enabled' : 'Set Up Multi-Factor Authentication'}</DialogTitle>
);

const MfaErrorAlert: React.FC<{ error: string | null }> = ({ error }) => {
  if (!error) return null;
  return (
    <Alert severity="error" sx={{ mb: 2 }}>
      {error}
    </Alert>
  );
};

interface MfaDialogBodyProps {
  loading: boolean;
  success: boolean;
  formProps: MfaFormViewProps;
}

const MfaDialogBody: React.FC<MfaDialogBodyProps> = ({ loading, success, formProps }) => {
  if (loading) {
    return (
      <Box display="flex" justifyContent="center" py={4}>
        <CircularProgress />
      </Box>
    );
  }
  if (success) {
    return <MfaSuccessView />;
  }
  return <MfaFormView {...formProps} />;
};

interface MfaDialogActionsProps {
  success: boolean;
  verifying: boolean;
  loading: boolean;
  codeLength: number;
  onClose: () => void;
  onVerify: () => void;
}

const MfaDialogActions: React.FC<MfaDialogActionsProps> = ({
  success,
  verifying,
  loading,
  codeLength,
  onClose,
  onVerify,
}) => {
  if (success) return null;

  return (
    <DialogActions>
      <Button onClick={onClose} disabled={verifying}>
        Cancel
      </Button>
      <Button
        onClick={onVerify}
        variant="contained"
        disabled={verifying || loading || codeLength !== 6}
      >
        {verifying ? <CircularProgress size={24} /> : 'Verify & Enable'}
      </Button>
    </DialogActions>
  );
};

const useMfaSetupFlow = (open: boolean, onSuccess?: () => void) => {
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [sharedSecret, setSharedSecret] = useState<string | null>(null);
  const [otpauthUrl, setOtpauthUrl] = useState<string | null>(null);
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [verificationCode, setVerificationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const hasFetchedRef = useRef(false);

  useEffect(() => {
    if (open && !hasFetchedRef.current) {
      hasFetchedRef.current = true;
      void fetchTotpSetup(setSharedSecret, setOtpauthUrl, setQrCodeUrl, setError, setLoading);
    }
    if (!open) {
      hasFetchedRef.current = false;
    }
  }, [open]);

  const handleVerify = useCallback(async () => {
    if (verificationCode.length !== 6) return;
    setVerifying(true);
    setError(null);

    try {
      await verifyTOTPSetup({ code: verificationCode });
      await updateMFAPreference({ totp: 'PREFERRED' });
      setSuccess(true);
      await attemptSignOut();
      onSuccess?.();
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Invalid verification code. Please try again.'));
    } finally {
      setVerifying(false);
    }
  }, [verificationCode, onSuccess]);

  return {
    loading,
    verifying,
    sharedSecret,
    otpauthUrl,
    qrCodeUrl,
    verificationCode,
    setVerificationCode,
    error,
    success,
    handleVerify,
  };
};

export const MfaSetupDialog: React.FC<MfaSetupDialogProps> = ({ open, onClose, onSuccess }) => {
  const flow = useMfaSetupFlow(open, onSuccess);

  return (
    <Dialog open={open} onClose={flow.success ? undefined : onClose} maxWidth="sm" fullWidth>
      <MfaDialogTitle success={flow.success} />
      <DialogContent>
        <MfaErrorAlert error={flow.error} />
        <MfaDialogBody
          loading={flow.loading}
          success={flow.success}
          formProps={{
            qrCodeUrl: flow.qrCodeUrl,
            sharedSecret: flow.sharedSecret,
            otpauthUrl: flow.otpauthUrl,
            verificationCode: flow.verificationCode,
            verifying: flow.verifying,
            onCodeChange: flow.setVerificationCode,
          }}
        />
      </DialogContent>
      <MfaDialogActions
        success={flow.success}
        verifying={flow.verifying}
        loading={flow.loading}
        codeLength={flow.verificationCode.length}
        onClose={onClose}
        onVerify={() => {
          void flow.handleVerify();
        }}
      />
    </Dialog>
  );
};
