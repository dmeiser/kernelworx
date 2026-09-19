/**
 * Dialog for setting up TOTP Multi-Factor Authentication (MFA) or showing federated admin restriction
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
} from 'aws-amplify/auth';
import QRCode from 'qrcode';
import {
  checkIsFederatedSession,
  attemptSignOut,
  handleSignOutAndRedirect,
} from '../lib/authUtils';

export interface MfaSetupDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  isFederated?: boolean;
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    return String((err as { message: unknown }).message);
  }
  return fallback;
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
    void handleSignOutAndRedirect();
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

const FederatedNoticeView: React.FC = () => (
  <Box sx={{ py: 1 }}>
    <Alert severity="warning" sx={{ mb: 2 }}>
      <strong>Administrator Security Policy:</strong> Admin operations require Multi-Factor Authentication (MFA).
    </Alert>
    <Typography variant="body1" color="text.secondary" paragraph>
      This account signs in through a social provider which cannot present MFA. Administrator functions require signing in with an email and password with Multi-Factor Authentication (MFA) enabled. Please sign out and sign in with your password.
    </Typography>
  </Box>
);

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

const getDialogTitleText = (isFederated: boolean, success: boolean): string => {
  if (isFederated) return 'Admin access requires a password sign-in';
  if (success) return 'MFA Enabled';
  return 'Set Up Multi-Factor Authentication';
};

const MfaDialogTitle: React.FC<{ isFederated: boolean; success: boolean }> = ({ isFederated, success }) => (
  <DialogTitle>{getDialogTitleText(isFederated, success)}</DialogTitle>
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
  isFederated: boolean;
  loading: boolean;
  success: boolean;
  formProps: MfaFormViewProps;
}

const MfaDialogBody: React.FC<MfaDialogBodyProps> = ({ isFederated, loading, success, formProps }) => {
  if (isFederated) {
    return <FederatedNoticeView />;
  }
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
  isFederated: boolean;
  success: boolean;
  verifying: boolean;
  loading: boolean;
  codeLength: number;
  onClose: () => void;
  onVerify: () => void;
}

const FederatedDialogActions: React.FC<{ onClose: () => void }> = ({ onClose }) => (
  <DialogActions>
    <Button onClick={onClose}>Back</Button>
    <Button variant="contained" color="primary" onClick={() => void handleSignOutAndRedirect()}>
      Sign Out
    </Button>
  </DialogActions>
);

const NativeDialogActions: React.FC<{
  verifying: boolean;
  loading: boolean;
  codeLength: number;
  onClose: () => void;
  onVerify: () => void;
}> = ({ verifying, loading, codeLength, onClose, onVerify }) => (
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

const MfaDialogActions: React.FC<MfaDialogActionsProps> = ({
  isFederated,
  success,
  verifying,
  loading,
  codeLength,
  onClose,
  onVerify,
}) => {
  if (isFederated) {
    return <FederatedDialogActions onClose={onClose} />;
  }
  if (success) return null;

  return (
    <NativeDialogActions
      verifying={verifying}
      loading={loading}
      codeLength={codeLength}
      onClose={onClose}
      onVerify={onVerify}
    />
  );
};

const useMfaSetupFlow = (open: boolean, isFederatedProp?: boolean, onSuccess?: () => void) => {
  const [isFederated, setIsFederated] = useState<boolean>(isFederatedProp ?? false);
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
    if (!open) {
      hasFetchedRef.current = false;
      return;
    }

    if (typeof isFederatedProp === 'boolean') {
      setIsFederated(isFederatedProp);
      if (!isFederatedProp && !hasFetchedRef.current) {
        hasFetchedRef.current = true;
        void fetchTotpSetup(setSharedSecret, setOtpauthUrl, setQrCodeUrl, setError, setLoading);
      }
      return;
    }

    void checkIsFederatedSession().then((federated) => {
      setIsFederated(federated);
      if (!federated && !hasFetchedRef.current) {
        hasFetchedRef.current = true;
        void fetchTotpSetup(setSharedSecret, setOtpauthUrl, setQrCodeUrl, setError, setLoading);
      }
    });
  }, [open, isFederatedProp]);

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
    isFederated,
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

export const MfaSetupDialog: React.FC<MfaSetupDialogProps> = ({
  open,
  onClose,
  onSuccess,
  isFederated: isFederatedProp,
}) => {
  const flow = useMfaSetupFlow(open, isFederatedProp, onSuccess);

  return (
    <Dialog open={open} onClose={flow.success ? undefined : onClose} maxWidth="sm" fullWidth>
      <MfaDialogTitle isFederated={flow.isFederated} success={flow.success} />
      <DialogContent>
        <MfaErrorAlert error={flow.error} />
        <MfaDialogBody
          isFederated={flow.isFederated}
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
        isFederated={flow.isFederated}
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
