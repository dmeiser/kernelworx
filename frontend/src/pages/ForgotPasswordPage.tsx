/**
 * Forgot Password Page
 *
 * Two-step password reset flow using Cognito:
 * 1. Enter email and request a reset code.
 * 2. Enter the code and a new password to confirm the reset.
 */

import { useState } from 'react';
import {
  Box,
  Button,
  TextField,
  Typography,
  Card,
  CardContent,
  Stack,
  Alert,
  CircularProgress,
  Link as MuiLink,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { resetPassword, confirmResetPassword } from 'aws-amplify/auth';

const PASSWORD_REGEX = /^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/;

const RESET_ERROR_MESSAGES: Record<string, string> = {
  LimitExceededException: 'Too many attempts. Please try again later.',
};

const SENSITIVE_RESET_ERROR_NAMES = new Set(['UserNotFoundException', 'InvalidParameterException']);

const CONFIRM_ERROR_MESSAGES: Record<string, string> = {
  CodeMismatchException: 'Invalid verification code. Please check and try again.',
  UserNotFoundException: 'Invalid verification code. Please check and try again.',
  ExpiredCodeException: 'Verification code expired. Please request a new code.',
  InvalidPasswordException:
    'Password does not meet requirements: minimum 8 characters with uppercase, lowercase, numbers, and symbols.',
};

function getErrorFromTable(
  table: Record<string, string>,
  errorName: string | undefined,
  fallbackMessage: string,
): string {
  if (errorName && table[errorName]) {
    return table[errorName];
  }
  return fallbackMessage;
}

interface AlertMessagesProps {
  error: string | null;
  success: string | null;
}

const AlertMessages: React.FC<AlertMessagesProps> = ({ error, success }) => (
  <>
    {error && (
      <Alert severity="error" sx={{ mb: 2 }}>
        {error}
      </Alert>
    )}
    {success && (
      <Alert severity="success" sx={{ mb: 2 }}>
        {success}
      </Alert>
    )}
  </>
);

export const ForgotPasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [codeSent, setCodeSent] = useState(false);

  const validatePassword = (): string | null => {
    if (!password || !confirmPassword) {
      return 'Password and confirmation are required';
    }
    if (!PASSWORD_REGEX.test(password)) {
      return 'Password must be at least 8 characters and include uppercase, lowercase, number, and symbol';
    }
    if (password !== confirmPassword) {
      return 'Passwords do not match';
    }
    return null;
  };

  const handleRequestCode = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setError(null);
    setSuccess(null);

    if (!email) {
      setError('Email is required');
      return;
    }

    setLoading(true);
    try {
      await resetPassword({ username: email });
    } catch (err: unknown) {
      const typedError = err as { name?: string; message?: string };
      if (!SENSITIVE_RESET_ERROR_NAMES.has(typedError.name ?? '')) {
        console.error('Reset password request failed:', err);
        setError(getErrorFromTable(RESET_ERROR_MESSAGES, typedError.name, 'Unable to send reset code. Please try again later.'));
        setLoading(false);
        return;
      }
    }
    setCodeSent(true);
    setSuccess(`Reset code sent to ${email}`);
    setLoading(false);
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    const validationError = validatePassword();
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      await confirmResetPassword({
        username: email,
        confirmationCode: code,
        newPassword: password,
      });
      setSuccess('Password reset successfully. Redirecting to login...');
      setTimeout(() => {
        void navigate('/login');
      }, 1500);
    } catch (err: unknown) {
      const typedError = err as { name?: string; message?: string };
      if (typedError.name !== 'UserNotFoundException') {
        console.error('Confirm reset password failed:', err);
      }
      setError(getErrorFromTable(CONFIRM_ERROR_MESSAGES, typedError.name, 'Unable to reset password. Please try again later.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
        p: 2,
      }}
    >
      <Card sx={{ width: '100%', maxWidth: 450 }}>
        <CardContent sx={{ p: 4 }}>
          <Box sx={{ textAlign: 'center', mb: 4 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5, mb: 2, flexWrap: 'wrap' }}>
              <Box component="img" src="/logo.svg" alt="KernelWorx mark" sx={{ width: 32, height: 32 }} />
              <Typography
                variant="h5"
                component="h1"
                sx={{
                  fontFamily: '"Bricolage Grotesque", "Atkinson Hyperlegible", sans-serif',
                  fontWeight: 700,
                  lineHeight: 1,
                }}
              >
                <Box component="span" sx={{ color: 'text.primary' }}>Kernel</Box>
                <Box component="span" sx={{ color: 'primary.main' }}>Worx</Box>
              </Typography>
            </Box>
            <Typography variant="body2" color="text.secondary">
              Reset your password
            </Typography>
          </Box>

          <AlertMessages error={error} success={success} />

          {!codeSent ? (
            <Box component="form" onSubmit={(e) => { void handleRequestCode(e); }}>
              <TextField
                fullWidth
                label="Email Address"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                margin="normal"
                required
                autoComplete="email"
                autoFocus
              />
              <Button type="submit" fullWidth variant="contained" sx={{ mt: 3, mb: 2 }} disabled={loading}>
                {loading ? <CircularProgress size={24} /> : 'Send Reset Code'}
              </Button>
              <Typography variant="body2" align="center" color="text.secondary">
                Remember your password?{' '}
                <MuiLink component="button" type="button" onClick={() => { void navigate('/login'); }} sx={{ cursor: 'pointer' }}>
                  Sign In
                </MuiLink>
              </Typography>
            </Box>
          ) : (
            <Box component="form" onSubmit={(e) => { void handleResetPassword(e); }}>
              <Typography variant="body2" color="text.secondary" paragraph>
                Enter the reset code sent to <strong>{email}</strong> and choose a new password.
              </Typography>
              <TextField
                fullWidth
                label="Reset Code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                margin="normal"
                required
                autoFocus
              />
              <TextField
                fullWidth
                label="New Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                margin="normal"
                required
                autoComplete="new-password"
                helperText="Minimum 8 characters with uppercase, lowercase, numbers, and symbols"
              />
              <TextField
                fullWidth
                label="Confirm New Password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                margin="normal"
                required
                autoComplete="new-password"
              />
              <Stack spacing={1} sx={{ mt: 3 }}>
                <Button type="submit" fullWidth variant="contained" disabled={loading}>
                  {loading ? <CircularProgress size={24} /> : 'Reset Password'}
                </Button>
                <Button fullWidth variant="text" onClick={() => { void handleRequestCode(); }} disabled={loading}>
                  Resend Code
                </Button>
                <Button fullWidth variant="text" onClick={() => { void navigate('/login'); }}>
                  Back to Login
                </Button>
              </Stack>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
};

export default ForgotPasswordPage;
