/**
 * Account Security Page
 * 
 * Allows users to:
 * - Change password
 * - Set up multi-factor authentication (TOTP)
 * - Register and manage passkeys (WebAuthn)
 */

import { useState, useEffect } from 'react';
import {
  Box,
  Button,
  TextField,
  Typography,
  Paper,
  Stack,
  Alert,
  CircularProgress,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
} from '@mui/material';
import {
  ArrowBack as BackIcon,
  VpnKey as PasswordIcon,
  Security as SecurityIcon,
  QrCode2 as QrCodeIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckIcon,
  Fingerprint as PasskeyIcon,
  Add as AddIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { 
  updatePassword, 
  setUpTOTP, 
  verifyTOTPSetup, 
  updateMFAPreference,
  fetchMFAPreference,
  associateWebAuthnCredential,
  listWebAuthnCredentials,
  deleteWebAuthnCredential,
  type AuthWebAuthnCredential,
} from 'aws-amplify/auth';
import QRCode from 'qrcode';

export const AccountSecurityPage: React.FC = () => {
  const navigate = useNavigate();
  
  // Password change state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);

  // MFA state
  const [mfaSetupCode, setMfaSetupCode] = useState<string | null>(null);
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [verificationCode, setVerificationCode] = useState('');
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [mfaSuccess, setMfaSuccess] = useState(false);
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaEnabled, setMfaEnabled] = useState(false);

  // Passkey state
  const [passkeys, setPasskeys] = useState<AuthWebAuthnCredential[]>([]);
  const [passkeyName, setPasskeyName] = useState('');
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const [passkeySuccess, setPasskeySuccess] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);

  // Load MFA and passkey status on mount
  useEffect(() => {
    loadMFAStatus();
    loadPasskeys();
  }, []);

  const loadMFAStatus = async () => {
    try {
      const mfaPreference = await fetchMFAPreference();
      // Check if TOTP is enabled
      setMfaEnabled(mfaPreference.enabled?.includes('TOTP') || mfaPreference.preferred === 'TOTP');
    } catch (err: any) {
      console.error('Failed to load MFA status:', err);
    }
  };

  const loadPasskeys = async () => {
    try {
      const result = await listWebAuthnCredentials();
      setPasskeys(result.credentials || []);
    } catch (err: any) {
      console.error('Failed to load passkeys:', err);
      // Passkeys might not be configured yet - don't show error to user
    }
  };

  // Handle password change
  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(false);

    // Validation
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match');
      return;
    }

    if (newPassword.length < 8) {
      setPasswordError('Password must be at least 8 characters');
      return;
    }

    setPasswordLoading(true);

    try {
      await updatePassword({ oldPassword: currentPassword, newPassword });
      setPasswordSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      console.error('Password change failed:', err);
      setPasswordError(err.message || 'Failed to change password. Please check your current password.');
    } finally {
      setPasswordLoading(false);
    }
  };

  // Set up MFA
  const handleSetupMFA = async () => {
    // Check if passkeys are enabled - MFA and passkeys cannot be used together
    if (passkeys.length > 0) {
      if (!window.confirm('TOTP MFA and Passkeys cannot be used together. Do you want to delete all passkeys and enable MFA?')) {
        return;
      }
      
      // Delete all passkeys first
      try {
        for (const passkey of passkeys) {
          if (passkey.credentialId) {
            await deleteWebAuthnCredential({ credentialId: passkey.credentialId });
          }
        }
        await loadPasskeys();
      } catch (err: any) {
        setMfaError('Failed to remove passkeys: ' + err.message);
        return;
      }
    }

    setMfaError(null);
    setMfaLoading(true);

    try {
      const totpSetupDetails = await setUpTOTP();
      const setupUri = totpSetupDetails.getSetupUri('PopcornManager');
      
      // Generate QR code
      const qrDataUrl = await QRCode.toDataURL(setupUri.href);
      
      setMfaSetupCode(totpSetupDetails.sharedSecret);
      setQrCodeUrl(qrDataUrl);
    } catch (err: any) {
      console.error('MFA setup failed:', err);
      setMfaError(err.message || 'Failed to set up MFA');
    } finally {
      setMfaLoading(false);
    }
  };

  // Verify and enable MFA
  const handleVerifyMFA = async (e: React.FormEvent) => {
    e.preventDefault();
    setMfaError(null);
    setMfaLoading(true);

    try {
      await verifyTOTPSetup({ code: verificationCode });
      await updateMFAPreference({ totp: 'PREFERRED' });
      
      setMfaSuccess(true);
      setMfaEnabled(true);
      setMfaSetupCode(null);
      setQrCodeUrl(null);
      setVerificationCode('');
    } catch (err: any) {
      console.error('MFA verification failed:', err);
      setMfaError(err.message || 'Invalid verification code. Please try again.');
    } finally {
      setMfaLoading(false);
    }
  };

  // Disable MFA
  const handleDisableMFA = async () => {
    if (!window.confirm('Are you sure you want to disable multi-factor authentication? This will make your account less secure.')) {
      return;
    }

    setMfaError(null);
    setMfaLoading(true);

    try {
      await updateMFAPreference({ totp: 'DISABLED' });
      setMfaEnabled(false);
      setMfaSuccess(false);
    } catch (err: any) {
      console.error('Disable MFA failed:', err);
      setMfaError(err.message || 'Failed to disable MFA');
    } finally {
      setMfaLoading(false);
    }
  };

  // Register a new passkey
  const handleRegisterPasskey = async () => {
    if (!passkeyName.trim()) {
      setPasskeyError('Please enter a name for this passkey');
      return;
    }

    // Check if MFA is enabled - passkeys and TOTP MFA cannot be used together
    if (mfaEnabled) {
      if (!window.confirm('Passkeys and TOTP MFA cannot be used together. Do you want to disable MFA and register this passkey?')) {
        return;
      }
      
      // Disable MFA first
      try {
        await updateMFAPreference({ totp: 'DISABLED' });
        setMfaEnabled(false);
      } catch (err: any) {
        setPasskeyError('Failed to disable MFA: ' + err.message);
        return;
      }
    }

    setPasskeyError(null);
    setPasskeySuccess(false);
    setPasskeyLoading(true);

    try {
      await associateWebAuthnCredential();
      setPasskeySuccess(true);
      setPasskeyName('');
      await loadPasskeys(); // Reload the list
    } catch (err: any) {
      console.error('Passkey registration failed:', err);
      setPasskeyError(err.message || 'Failed to register passkey. Make sure your browser supports passkeys and you have a compatible authenticator.');
    } finally {
      setPasskeyLoading(false);
    }
  };

  // Delete a passkey
  const handleDeletePasskey = async (credentialId: string) => {
    if (!window.confirm('Are you sure you want to delete this passkey?')) {
      return;
    }

    setPasskeyError(null);
    setPasskeyLoading(true);

    try {
      await deleteWebAuthnCredential({ credentialId });
      await loadPasskeys(); // Reload the list
    } catch (err: any) {
      console.error('Delete passkey failed:', err);
      setPasskeyError(err.message || 'Failed to delete passkey');
    } finally {
      setPasskeyLoading(false);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 3 }}>
        <IconButton onClick={() => navigate('/settings')} edge="start">
          <BackIcon />
        </IconButton>
        <Typography variant="h4" component="h1">
          Account Security
        </Typography>
      </Stack>

      {/* Change Password Section */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <PasswordIcon color="primary" />
          <Typography variant="h6">Change Password</Typography>
        </Stack>
        
        <Typography variant="body2" color="text.secondary" paragraph>
          Update your password to keep your account secure. Use a strong password with at least 8 characters.
        </Typography>

        {passwordSuccess && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setPasswordSuccess(false)}>
            Password changed successfully!
          </Alert>
        )}

        {passwordError && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setPasswordError(null)}>
            {passwordError}
          </Alert>
        )}

        <form onSubmit={handlePasswordChange}>
          <Stack spacing={2}>
            <TextField
              label="Current Password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              fullWidth
              disabled={passwordLoading}
              autoComplete="current-password"
            />
            <TextField
              label="New Password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              fullWidth
              disabled={passwordLoading}
              autoComplete="new-password"
              helperText="At least 8 characters with uppercase, lowercase, numbers, and symbols"
            />
            <TextField
              label="Confirm New Password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              fullWidth
              disabled={passwordLoading}
              autoComplete="new-password"
            />
            <Button
              type="submit"
              variant="contained"
              disabled={passwordLoading}
              sx={{ alignSelf: 'flex-start' }}
            >
              {passwordLoading ? <CircularProgress size={24} /> : 'Change Password'}
            </Button>
          </Stack>
        </form>
      </Paper>

      {/* Multi-Factor Authentication Section */}
      <Paper sx={{ p: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <SecurityIcon color="primary" />
          <Typography variant="h6">Multi-Factor Authentication (MFA)</Typography>
        </Stack>

        <Typography variant="body2" color="text.secondary" paragraph>
          Add an extra layer of security to your account by requiring a verification code from your phone.
        </Typography>

        {/* Passkey Conflict Warning */}
        {passkeys.length > 0 && !mfaEnabled && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <strong>Note:</strong> You have {passkeys.length} passkey{passkeys.length > 1 ? 's' : ''} registered. 
            TOTP MFA and Passkeys cannot be used together. Enabling MFA will delete all your passkeys.
          </Alert>
        )}

        {mfaSuccess && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMfaSuccess(false)}>
            MFA has been successfully enabled!
          </Alert>
        )}

        {mfaError && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setMfaError(null)}>
            {mfaError}
          </Alert>
        )}

        {mfaEnabled && !mfaSetupCode && (
          <Alert severity="success" icon={<CheckIcon />} sx={{ mb: 2 }}>
            <Typography variant="body2" fontWeight={600}>
              MFA is currently enabled
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Your account is protected with multi-factor authentication
            </Typography>
          </Alert>
        )}

        {!mfaSetupCode && !mfaEnabled && (
          <Button
            variant="contained"
            startIcon={<QrCodeIcon />}
            onClick={handleSetupMFA}
            disabled={mfaLoading}
          >
            {mfaLoading ? <CircularProgress size={24} /> : 'Set Up MFA'}
          </Button>
        )}

        {mfaEnabled && (
          <Button
            variant="outlined"
            color="error"
            startIcon={<DeleteIcon />}
            onClick={handleDisableMFA}
            disabled={mfaLoading}
            sx={{ mt: 2 }}
          >
            Disable MFA
          </Button>
        )}

        {/* MFA Setup Flow */}
        {mfaSetupCode && qrCodeUrl && (
          <Box sx={{ mt: 3 }}>
            <Divider sx={{ mb: 3 }} />
            
            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Step 1: Scan QR Code
            </Typography>
            <Typography variant="body2" color="text.secondary" paragraph>
              Use an authenticator app (Google Authenticator, Authy, 1Password, etc.) to scan this QR code:
            </Typography>
            
            <Box sx={{ textAlign: 'center', my: 3 }}>
              <img src={qrCodeUrl} alt="MFA QR Code" style={{ maxWidth: '256px' }} />
            </Box>

            <Typography variant="subtitle2" gutterBottom>
              Or enter this code manually:
            </Typography>
            <Paper variant="outlined" sx={{ p: 2, mb: 3, bgcolor: 'grey.50' }}>
              <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: 'break-all' }}>
                {mfaSetupCode}
              </Typography>
            </Paper>

            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Step 2: Verify Code
            </Typography>
            <Typography variant="body2" color="text.secondary" paragraph>
              Enter the 6-digit code from your authenticator app to complete setup:
            </Typography>

            <form onSubmit={handleVerifyMFA}>
              <Stack direction="row" spacing={2} alignItems="flex-start">
                <TextField
                  label="Verification Code"
                  value={verificationCode}
                  onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, '').substring(0, 6))}
                  required
                  disabled={mfaLoading}
                  inputProps={{ maxLength: 6, pattern: '[0-9]*' }}
                  helperText="Enter the 6-digit code"
                />
                <Button
                  type="submit"
                  variant="contained"
                  disabled={mfaLoading || verificationCode.length !== 6}
                >
                  {mfaLoading ? <CircularProgress size={24} /> : 'Verify & Enable'}
                </Button>
                <Button
                  variant="outlined"
                  onClick={() => {
                    setMfaSetupCode(null);
                    setQrCodeUrl(null);
                    setVerificationCode('');
                  }}
                  disabled={mfaLoading}
                >
                  Cancel
                </Button>
              </Stack>
            </form>
          </Box>
        )}
      </Paper>

      {/* Passkeys Section */}
      <Paper sx={{ p: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <PasskeyIcon color="primary" />
          <Typography variant="h6">Passkeys (Passwordless Login)</Typography>
        </Stack>

        <Typography variant="body2" color="text.secondary" paragraph>
          Passkeys let you sign in securely without a password - using your fingerprint, face, or device PIN.
        </Typography>

        {/* MFA Conflict Warning */}
        {mfaEnabled && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <strong>Note:</strong> Passkeys and TOTP MFA cannot be used together. 
            Registering a passkey will disable your current MFA setup. Passkeys provide 
            strong authentication without requiring a separate MFA app.
          </Alert>
        )}

        {passkeySuccess && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setPasskeySuccess(false)}>
            Passkey registered successfully!
          </Alert>
        )}

        {passkeyError && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setPasskeyError(null)}>
            {passkeyError}
          </Alert>
        )}

        {/* Registered Passkeys List */}
        {passkeys.length > 0 && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle2" gutterBottom>
              Registered Passkeys
            </Typography>
            <List>
              {passkeys.map((pk) => (
                <ListItem
                  key={pk.credentialId || Math.random()}
                  secondaryAction={
                    <IconButton
                      edge="end"
                      onClick={() => pk.credentialId && handleDeletePasskey(pk.credentialId)}
                      disabled={passkeyLoading || !pk.credentialId}
                    >
                      <DeleteIcon />
                    </IconButton>
                  }
                >
                  <ListItemIcon>
                    <PasskeyIcon />
                  </ListItemIcon>
                  <ListItemText
                    primary={pk.friendlyCredentialName || 'Unnamed Passkey'}
                    secondary={pk.createdAt ? `Created: ${new Date(pk.createdAt).toLocaleDateString()}` : 'Unknown date'}
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        {/* Register New Passkey */}
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Register a New Passkey
          </Typography>
          <Stack direction="row" spacing={2} alignItems="flex-start">
            <TextField
              label="Passkey Name"
              value={passkeyName}
              onChange={(e) => setPasskeyName(e.target.value)}
              placeholder="e.g., My iPhone, Work Laptop"
              disabled={passkeyLoading}
              sx={{ flex: 1 }}
              helperText="Give this passkey a name to remember which device it's for"
            />
            <Button
              variant="contained"
              startIcon={passkeyLoading ? <CircularProgress size={20} /> : <AddIcon />}
              onClick={handleRegisterPasskey}
              disabled={passkeyLoading || !passkeyName.trim()}
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
      </Paper>
    </Box>
  );
};
