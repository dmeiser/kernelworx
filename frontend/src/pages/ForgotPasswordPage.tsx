/**
 * Forgot Password Page
 *
 * Provides a branded password-reset flow:
 * - Request a reset code via email using AWS Amplify `resetPassword`
 * - Confirm the code and set a new password using `confirmResetPassword`
 * - Redirect to `/login` after a successful reset
 */

import { useState, useRef, useEffect } from 'react';
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
import { useNavigate, type NavigateFunction } from 'react-router-dom';
import { resetPassword, confirmResetPassword } from 'aws-amplify/auth';
import { useAuth } from '../contexts/AuthContext';

const PASSWORD_REGEX = /^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/;
const CONFIRM_CODE_REGEX = /^\d{6}$/;
const POST_RESET_REDIRECT_MS = 1500;
const RESEND_COOLDOWN_MS = 30000;

const RESET_ERROR_MESSAGES: Record<string, string> = {
  LimitExceededException:
    'Too many attempts. Please wait a while before trying again.',
};

const CONFIRM_ERROR_MESSAGES: Record<string, string> = {
  CodeMismatchException: 'Invalid confirmation code. Please check and try again.',
  ExpiredCodeException: 'This code has expired. Please request a new one.',
  InvalidPasswordException:
    'Password does not meet requirements: minimum 8 characters with uppercase, lowercase, numbers, and symbols.',
  // UserNotFoundException is handled separately to avoid account enumeration.
};

const SENSITIVE_RESET_ERROR_NAMES = new Set([
  'UserNotFoundException',
  'InvalidParameterException',
]);

function getErrorMessage(
  err: unknown,
  table: Record<string, string>,
  fallback: string,
): string {
  const typed = err as { name?: string };
  if (typed.name && table[typed.name]) {
    return table[typed.name];
  }
  return fallback;
}

function validatePassword(password: string, confirmPassword: string): string | null {
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
}

function validateConfirmationCode(code: string): string | null {
  const trimmed = code.trim();
  if (!trimmed) {
    return 'Confirmation code is required';
  }
  if (!CONFIRM_CODE_REGEX.test(trimmed)) {
    return 'Confirmation code must be 6 digits';
  }
  return null;
}

interface ForgotPasswordState {
  email: string;
  setEmail: (value: string) => void;
  code: string;
  setCode: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  confirmPassword: string;
  setConfirmPassword: (value: string) => void;
  error: string | null;
  success: string | null;
  loading: boolean;
  codeSent: boolean;
  resendCooldown: number;
  handleRequestCode: (e: React.FormEvent) => Promise<void>;
  handleConfirmReset: (e: React.FormEvent) => Promise<void>;
  handleResendCode: () => Promise<void>;
  handleBackToEmail: () => void;
  navigateLogin: () => void;
  clearError: () => void;
  clearSuccess: () => void;
}

function useForgotPasswordState(navigate: NavigateFunction): ForgotPasswordState {
  const { isAuthenticated } = useAuth();

  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [codeSent, setCodeSent] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const redirectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resendIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isAuthenticated) {
      void navigate('/home', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    return () => {
      if (redirectTimeoutRef.current) {
        clearTimeout(redirectTimeoutRef.current);
      }
      if (resendIntervalRef.current) {
        clearInterval(resendIntervalRef.current);
      }
    };
  }, []);

  const scheduleRedirect = (callback: () => void) => {
    if (redirectTimeoutRef.current) {
      clearTimeout(redirectTimeoutRef.current);
    }
    redirectTimeoutRef.current = setTimeout(callback, POST_RESET_REDIRECT_MS);
  };

  const startResendCooldown = () => {
    if (resendIntervalRef.current) {
      clearInterval(resendIntervalRef.current);
    }
    setResendCooldown(RESEND_COOLDOWN_MS);
    resendIntervalRef.current = setInterval(() => {
      setResendCooldown((prev) => {
        const next = prev - 1000;
        if (next <= 0 && resendIntervalRef.current) {
          clearInterval(resendIntervalRef.current);
          resendIntervalRef.current = null;
        }
        return Math.max(0, next);
      });
    }, 1000);
  };

  const handleRequestError = (err: unknown): boolean => {
    const typed = err as { name?: string; message?: string };
    if (SENSITIVE_RESET_ERROR_NAMES.has(typed.name ?? '')) {
      // Keep the user-facing response uniform, but log for operator visibility.
      console.warn(
        'Reset password request returned sensitive error; swallowing to avoid account enumeration:',
        typed.name,
        typed.message,
      );
      return false;
    }
    console.error('Reset password request failed:', err);
    setError(
      getErrorMessage(
        err,
        RESET_ERROR_MESSAGES,
        'Unable to send reset code. Please try again.',
      ),
    );
    return true;
  };

  const handleRequestCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail || !trimmedEmail.includes('@')) {
      setError('Please enter a valid email address');
      return;
    }

    setLoading(true);
    try {
      await resetPassword({ username: trimmedEmail });
    } catch (err: unknown) {
      if (handleRequestError(err)) {
        setLoading(false);
        return;
      }
    }
    setCodeSent(true);
    setSuccess(
      `If an account exists for ${trimmedEmail}, a reset code has been sent.`,
    );
    setLoading(false);
  };

  const handleResendCode = async () => {
    if (resendCooldown > 0) return;

    setError(null);
    setSuccess(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail || !trimmedEmail.includes('@')) {
      setError('Please enter a valid email address');
      return;
    }

    setLoading(true);
    try {
      await resetPassword({ username: trimmedEmail });
      setSuccess(
        `If an account exists for ${trimmedEmail}, a reset code has been sent.`,
      );
      startResendCooldown();
    } catch (err: unknown) {
      handleRequestError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    const codeError = validateConfirmationCode(code);
    if (codeError) {
      setError(codeError);
      return;
    }

    const validationError = validatePassword(password, confirmPassword);
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      await confirmResetPassword({
        username: email.trim(),
        confirmationCode: code.trim(),
        newPassword: password,
      });
      setSuccess('Your password has been reset successfully.');
      scheduleRedirect(() => {
        void navigate('/login', { replace: true });
      });
    } catch (err: unknown) {
      const typed = err as { name?: string };
      if (typed.name === 'UserNotFoundException') {
        setError('Invalid confirmation code. Please check and try again.');
      } else {
        console.error('Confirm reset password failed:', err);
        setError(
          getErrorMessage(
            err,
            CONFIRM_ERROR_MESSAGES,
            'Unable to reset password. Please try again.',
          ),
        );
      }
    } finally {
      setLoading(false);
    }
  };

  const handleBackToEmail = () => {
    if (redirectTimeoutRef.current) {
      clearTimeout(redirectTimeoutRef.current);
      redirectTimeoutRef.current = null;
    }
    if (resendIntervalRef.current) {
      clearInterval(resendIntervalRef.current);
      resendIntervalRef.current = null;
    }
    setResendCooldown(0);
    setCodeSent(false);
    setCode('');
    setPassword('');
    setConfirmPassword('');
    setError(null);
    setSuccess(null);
  };

  const navigateLogin = () => {
    void navigate('/login');
  };

  return {
    email,
    setEmail,
    code,
    setCode,
    password,
    setPassword,
    confirmPassword,
    setConfirmPassword,
    error,
    success,
    loading,
    codeSent,
    resendCooldown,
    handleRequestCode,
    handleConfirmReset,
    handleResendCode,
    handleBackToEmail,
    navigateLogin,
    clearError: () => setError(null),
    clearSuccess: () => setSuccess(null),
  };
}

interface RequestCodeFormProps {
  email: string;
  setEmail: (value: string) => void;
  loading: boolean;
  onSubmit: (e: React.FormEvent) => Promise<void>;
  onLogin: () => void;
}

const RequestCodeForm: React.FC<RequestCodeFormProps> = ({
  email,
  setEmail,
  loading,
  onSubmit,
  onLogin,
}) => (
  <Box component="form" onSubmit={(e) => { void onSubmit(e); }}>
    <Stack spacing={2} sx={{ mb: 3 }}>
      <TextField
        label="Email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        fullWidth
        autoComplete="email"
        disabled={loading}
        autoFocus
      />
    </Stack>

    <Button
      type="submit"
      variant="contained"
      fullWidth
      size="large"
      disabled={loading}
      aria-label={loading ? 'Sending reset code' : undefined}
      aria-busy={loading}
      sx={{ mb: 2 }}
    >
      {loading ? <CircularProgress size={24} /> : 'Send Reset Code'}
    </Button>

    <Box sx={{ textAlign: 'center' }}>
      <Typography variant="body2" color="text.secondary">
        Remember your password?{' '}
        <MuiLink
          component="button"
          type="button"
          variant="body2"
          onClick={onLogin}
          sx={{ cursor: 'pointer', fontWeight: 600 }}
        >
          Sign In
        </MuiLink>
      </Typography>
    </Box>
  </Box>
);

interface ConfirmResetFormProps {
  code: string;
  setCode: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  confirmPassword: string;
  setConfirmPassword: (value: string) => void;
  loading: boolean;
  resendCooldown: number;
  onSubmit: (e: React.FormEvent) => Promise<void>;
  onResendCode: () => Promise<void>;
  onBackToEmail: () => void;
  onLogin: () => void;
}

const ConfirmResetForm: React.FC<ConfirmResetFormProps> = ({
  code,
  setCode,
  password,
  setPassword,
  confirmPassword,
  setConfirmPassword,
  loading,
  resendCooldown,
  onSubmit,
  onResendCode,
  onBackToEmail,
  onLogin,
}) => (
  <Box component="form" onSubmit={(e) => { void onSubmit(e); }}>
    <Stack spacing={2} sx={{ mb: 3 }}>
      <TextField
        label="Confirmation Code"
        type="text"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        required
        fullWidth
        autoComplete="one-time-code"
        disabled={loading}
        slotProps={{ htmlInput: { maxLength: 6, pattern: '[0-9]*' } }}
        autoFocus
      />
      <TextField
        label="New Password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        fullWidth
        autoComplete="new-password"
        disabled={loading}
        helperText="Minimum 8 characters with uppercase, lowercase, numbers, and symbols"
        slotProps={{ htmlInput: { 'data-testid': 'new-password' } }}
      />
      <TextField
        label="Confirm New Password"
        type="password"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        required
        fullWidth
        autoComplete="new-password"
        disabled={loading}
        slotProps={{ htmlInput: { 'data-testid': 'confirm-password' } }}
      />
    </Stack>

    <Button
      type="submit"
      variant="contained"
      fullWidth
      size="large"
      disabled={loading}
      aria-label={loading ? 'Resetting password' : undefined}
      aria-busy={loading}
      sx={{ mb: 2 }}
    >
      {loading ? <CircularProgress size={24} /> : 'Reset Password'}
    </Button>

    <Stack spacing={1}>
      <Button
        variant="text"
        fullWidth
        onClick={() => { void onResendCode(); }}
        disabled={loading || resendCooldown > 0}
      >
        {resendCooldown > 0
          ? `Resend code in ${Math.ceil(resendCooldown / 1000)}s`
          : 'Resend Code'}
      </Button>
      <Button variant="text" fullWidth onClick={onBackToEmail} disabled={loading}>
        Back to Email
      </Button>
      <Button variant="text" fullWidth onClick={onLogin} disabled={loading}>
        Back to Login
      </Button>
    </Stack>
  </Box>
);

interface AlertMessagesProps {
  error: string | null;
  success: string | null;
  onCloseError: () => void;
  onCloseSuccess: () => void;
}

const AlertMessages: React.FC<AlertMessagesProps> = ({
  error,
  success,
  onCloseError,
  onCloseSuccess,
}) => (
  <>
    {error && (
      <Alert severity="error" sx={{ mb: 3 }} onClose={onCloseError}>
        {error}
      </Alert>
    )}
    {success && (
      <Alert severity="success" sx={{ mb: 3 }} onClose={onCloseSuccess}>
        {success}
      </Alert>
    )}
  </>
);

const PageHeader: React.FC<{ codeSent: boolean }> = ({ codeSent }) => (
  <Box sx={{ textAlign: 'center', mb: 4 }}>
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 0.5,
        mb: 2,
        flexWrap: 'wrap',
      }}
    >
      <Box
        component="img"
        src="/logo.svg"
        alt="KernelWorx mark"
        sx={{ width: 32, height: 32 }}
      />
      <Typography
        variant="h5"
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
    <Typography
      variant="h4"
      component="h1"
      gutterBottom
      sx={{
        fontFamily: '"Bricolage Grotesque", "Atkinson Hyperlegible", sans-serif',
        fontWeight: 700,
      }}
    >
      Reset Password
    </Typography>
    <Typography variant="body2" color="text.secondary">
      {codeSent
        ? 'Enter the confirmation code and your new password'
        : 'Enter your email to receive a reset code'}
    </Typography>
  </Box>
);

export const ForgotPasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const state = useForgotPasswordState(navigate);

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
          <PageHeader codeSent={state.codeSent} />
          <AlertMessages
            error={state.error}
            success={state.success}
            onCloseError={state.clearError}
            onCloseSuccess={state.clearSuccess}
          />
          {state.codeSent ? (
            <ConfirmResetForm
              code={state.code}
              setCode={state.setCode}
              password={state.password}
              setPassword={state.setPassword}
              confirmPassword={state.confirmPassword}
              setConfirmPassword={state.setConfirmPassword}
              loading={state.loading}
              resendCooldown={state.resendCooldown}
              onSubmit={state.handleConfirmReset}
              onResendCode={state.handleResendCode}
              onBackToEmail={state.handleBackToEmail}
              onLogin={state.navigateLogin}
            />
          ) : (
            <RequestCodeForm
              email={state.email}
              setEmail={state.setEmail}
              loading={state.loading}
              onSubmit={state.handleRequestCode}
              onLogin={state.navigateLogin}
            />
          )}
        </CardContent>
      </Card>
    </Box>
  );
};
