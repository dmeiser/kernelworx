/**
 * Account Security Page
 * 
 * Allows users to:
 * - Change password
 * - Set up multi-factor authentication (TOTP)
 * - Manage MFA devices
 */

import { useState } from 'react';
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
} from '@mui/material';
import {
  ArrowBack as BackIcon,
  VpnKey as PasswordIcon,
  Security as SecurityIcon,
  QrCode2 as QrCodeIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { updatePassword, setUpTOTP, verifyTOTPSetup, updateMFAPreference } from 'aws-amplify/auth';
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
    </Box>
  );
};
