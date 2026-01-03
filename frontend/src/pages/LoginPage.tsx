/**
 * Custom Login Page
 *
 * Provides branded login interface with:
 * - Email/password authentication
 * - Social login buttons (Google, Facebook)
 * - Password reset flow
 * - Link to signup page
 */

import { useState, useEffect } from 'react';
import {
  Box,
  Button,
  TextField,
  Typography,
  Paper,
  Stack,
  Divider,
  Alert,
  CircularProgress,
  Link as MuiLink,
} from '@mui/material';
import { Google as GoogleIcon, Facebook as FacebookIcon, Fingerprint as FingerprintIcon } from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { confirmSignIn, signIn, signInWithRedirect } from 'aws-amplify/auth';
import type { SignInOutput } from 'aws-amplify/auth';

// Get error message from unknown error
function getErrorMessage(err: unknown, fallback: string): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const error = err as any;
  return error?.message || fallback;
}

// Check if step contains WebAuthn
function isWebAuthnStep(step: string | undefined): boolean {
  return Boolean(step?.includes('WEBAUTHN'));
}

// Delayed redirect helper
function delayedRedirect(path: string): void {
  setTimeout(() => {
    window.location.href = path;
  }, 500);
}

// Handle login result that is not signed in
interface LoginStepResult {
  showMfa?: boolean;
  showPasskeyPrompt?: boolean;
  error?: string;
  needsFirstFactorSelection?: boolean;
}

// Dispatch table for known step actions
const STEP_ACTIONS: Record<string, LoginStepResult> = {
  CONFIRM_SIGN_IN_WITH_TOTP_CODE: { showMfa: true },
  CONFIRM_SIGN_IN_WITH_SMS_CODE: { showMfa: true },
  CONFIRM_SIGN_IN_WITH_EMAIL_CODE: { showMfa: true },
  CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION: {
    needsFirstFactorSelection: true,
  },
  CONFIRM_SIGN_IN_WITH_PASSWORD: {
    error: 'No passkey found for this account. Please register a passkey first or use password login.',
  },
};

function getLoginStepAction(stepName: string | undefined): LoginStepResult {
  if (!stepName) {
    return { error: 'Authentication failed. Please try again.' };
  }
  if (STEP_ACTIONS[stepName]) {
    return STEP_ACTIONS[stepName];
  }
  if (isWebAuthnStep(stepName)) {
    return { showPasskeyPrompt: true };
  }
  return { error: `Unexpected authentication step: ${stepName}` };
}

// Form props interface
interface FormProps {
  loading: boolean;
  onSubmit: (e: React.FormEvent) => void;
}

// MFA Form Component
interface MfaFormProps extends FormProps {
  mfaCode: string;
  setMfaCode: (code: string) => void;
  onBack: () => void;
}

const MfaForm: React.FC<MfaFormProps> = ({ loading, onSubmit, mfaCode, setMfaCode, onBack }) => (
  <form onSubmit={onSubmit}>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
      Enter the 6-digit code from your authenticator app
    </Typography>
    <Stack spacing={2} sx={{ mb: 3 }}>
      <TextField
        label="MFA Code"
        type="text"
        value={mfaCode}
        onChange={(e) => setMfaCode(e.target.value)}
        required
        fullWidth
        autoComplete="one-time-code"
        disabled={loading}
        inputProps={{ maxLength: 6, pattern: '[0-9]*' }}
        autoFocus
      />
    </Stack>

    <Button
      type="submit"
      variant="contained"
      fullWidth
      size="large"
      disabled={loading || mfaCode.length !== 6}
      sx={{ mb: 2 }}
    >
      {loading ? <CircularProgress size={24} /> : 'Verify'}
    </Button>

    <Button variant="text" fullWidth onClick={onBack} disabled={loading}>
      Back to Login
    </Button>
  </form>
);

// Credentials Form Component
interface CredentialsFormProps extends FormProps {
  email: string;
  setEmail: (email: string) => void;
  password: string;
  setPassword: (password: string) => void;
  onForgotPassword: () => void;
  onPasskeyLogin: () => void;
}

const CredentialsForm: React.FC<CredentialsFormProps> = ({
  loading,
  onSubmit,
  email,
  setEmail,
  password,
  setPassword,
  onForgotPassword,
  onPasskeyLogin,
}) => (
  <form onSubmit={onSubmit}>
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
      />
      <TextField
        label="Password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        fullWidth
        autoComplete="current-password"
        disabled={loading}
      />
    </Stack>

    <Box sx={{ textAlign: 'right', mb: 2 }}>
      <MuiLink component="button" type="button" variant="body2" onClick={onForgotPassword} sx={{ cursor: 'pointer' }}>
        Forgot password?
      </MuiLink>
    </Box>

    <Button type="submit" variant="contained" fullWidth size="large" disabled={loading} sx={{ mb: 2 }}>
      {loading ? <CircularProgress size={24} /> : 'Sign In'}
    </Button>

    <Button
      variant="outlined"
      fullWidth
      size="large"
      startIcon={<FingerprintIcon />}
      onClick={onPasskeyLogin}
      disabled={loading}
      sx={{ mb: 3 }}
    >
      Sign In with Passkey
    </Button>
  </form>
);

// Social Login Section
interface SocialSectionProps {
  loading: boolean;
  onSocialLogin: (provider: 'Google' | 'Facebook') => void;
  onSignup: () => void;
}

const SocialSection: React.FC<SocialSectionProps> = ({ loading, onSocialLogin, onSignup }) => (
  <>
    <Divider sx={{ my: 3 }}>
      <Typography variant="body2" color="text.secondary">
        OR
      </Typography>
    </Divider>

    <Stack spacing={2} sx={{ mb: 3 }}>
      <Button
        variant="outlined"
        fullWidth
        size="large"
        startIcon={<GoogleIcon />}
        onClick={() => onSocialLogin('Google')}
        disabled={loading}
      >
        Continue with Google
      </Button>
      <Button
        variant="outlined"
        fullWidth
        size="large"
        startIcon={<FacebookIcon />}
        onClick={() => onSocialLogin('Facebook')}
        disabled={loading}
      >
        Continue with Facebook
      </Button>
    </Stack>

    <Box sx={{ textAlign: 'center', mt: 3 }}>
      <Typography variant="body2" color="text.secondary">
        Don't have an account?{' '}
        <MuiLink
          component="button"
          type="button"
          variant="body2"
          onClick={onSignup}
          sx={{ cursor: 'pointer', fontWeight: 600 }}
        >
          Sign up
        </MuiLink>
      </Typography>
    </Box>

    <Alert
      severity="warning"
      sx={{
        mt: 3,
        mb: 4,
        backgroundColor: '#fff3e0',
        borderLeft: '4px solid #f57c00',
        '& .MuiAlert-icon': { color: '#e65100' },
      }}
    >
      <Typography variant="caption" sx={{ color: '#e65100' }}>
        <strong>⚠️ Age Requirement:</strong> You must be at least 13 years old to create an account (COPPA compliance).
      </Typography>
    </Alert>
  </>
);

// Custom hook for login state and handlers
function useLoginState(
  loginWithPassword: (email: string, password: string) => Promise<unknown>,
  navigate: ReturnType<typeof useNavigate>,
  from: string,
) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mfaCode, setMfaCode] = useState('');
  const [showMfa, setShowMfa] = useState(false);
  const [showPasskeyPrompt, setShowPasskeyPrompt] = useState(false);

  const applyLoginAction = (action: LoginStepResult) => {
    if (action.showMfa) {
      setShowMfa(true);
      setMfaCode('');
    } else if (action.showPasskeyPrompt) {
      setShowPasskeyPrompt(true);
    } else if (action.error) {
      setError(action.error);
    }
    setLoading(false);
  };

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result = (await loginWithPassword(email, password)) as SignInOutput;
      if (result.isSignedIn) {
        navigate(from, { replace: true });
        return;
      }
      applyLoginAction(getLoginStepAction(result.nextStep?.signInStep));
    } catch (err: unknown) {
      console.error('Login failed:', err);
      setError(getErrorMessage(err, 'Login failed. Please check your credentials.'));
      setLoading(false);
    }
  };

  const handleMfaSuccess = () => {
    setShowMfa(false);
    setMfaCode('');
    setPassword('');
    setTimeout(() => navigate(from, { replace: true }), 500);
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result = await confirmSignIn({ challengeResponse: mfaCode });
      if (result.isSignedIn) {
        handleMfaSuccess();
        return;
      }
      setError('MFA verification failed');
      setLoading(false);
    } catch (err: unknown) {
      console.error('MFA failed:', err);
      setError(getErrorMessage(err, 'Invalid MFA code'));
      setLoading(false);
    }
  };

  const handleFirstFactorSelection = async () => {
    const confirmResult = await confirmSignIn({
      challengeResponse: 'WEB_AUTHN',
    });
    if (confirmResult.isSignedIn) {
      delayedRedirect(from);
      return;
    }
    if (confirmResult.nextStep?.signInStep) {
      setShowPasskeyPrompt(true);
      setLoading(false);
    }
  };

  const processPasskeyResult = async (result: SignInOutput) => {
    if (result.isSignedIn) {
      delayedRedirect(from);
      return;
    }
    const action = getLoginStepAction(result.nextStep?.signInStep);
    if (action.needsFirstFactorSelection) {
      await handleFirstFactorSelection();
      return;
    }
    applyLoginAction(action);
  };

  const handlePasskeyLogin = async () => {
    if (!email) {
      setError('Please enter your email address');
      return;
    }

    setError(null);
    setLoading(true);

    try {
      const result = await signIn({
        username: email,
        options: { authFlowType: 'USER_AUTH' },
      });
      await processPasskeyResult(result);
    } catch (err: unknown) {
      console.error('Passkey login failed:', err);
      setError(getErrorMessage(err, 'Passkey authentication failed. Make sure you have a passkey registered.'));
      setLoading(false);
    }
  };

  const handleSocialLogin = async (provider: 'Google' | 'Facebook') => {
    setError(null);
    setLoading(true);
    try {
      if (from !== '/scouts') {
        sessionStorage.setItem('oauth_redirect', from);
      }
      await signInWithRedirect({ provider });
    } catch (err: unknown) {
      console.error('Social login failed:', err);
      setError(`${provider} login failed. Please try again.`);
      setLoading(false);
    }
  };

  const handleBack = () => {
    setShowMfa(false);
    setMfaCode('');
    setPassword('');
  };

  return {
    email,
    setEmail,
    password,
    setPassword,
    error,
    setError,
    loading,
    mfaCode,
    setMfaCode,
    showMfa,
    showPasskeyPrompt,
    handleEmailLogin,
    handleMfaSubmit,
    handlePasskeyLogin,
    handleSocialLogin,
    handleBack,
  };
}

// Error Alert Component
interface ErrorAlertProps {
  error: string | null;
  onClose: () => void;
}

const ErrorAlert: React.FC<ErrorAlertProps> = ({ error, onClose }) => {
  if (!error) return null;
  return (
    <Alert severity="error" sx={{ mb: 3 }} onClose={onClose}>
      {error}
    </Alert>
  );
};

// Passkey Prompt Component
const PasskeyPrompt: React.FC<{ show: boolean }> = ({ show }) => {
  if (!show) return null;
  return (
    <Alert severity="info" sx={{ mb: 3 }}>
      Use your security key, fingerprint, or face recognition to sign in
    </Alert>
  );
};

// Login Form Container
interface LoginFormContainerProps {
  state: ReturnType<typeof useLoginState>;
  onForgotPassword: () => void;
}

const LoginFormContainer: React.FC<LoginFormContainerProps> = ({ state, onForgotPassword }) => {
  if (state.showMfa) {
    return (
      <MfaForm
        loading={state.loading}
        onSubmit={state.handleMfaSubmit}
        mfaCode={state.mfaCode}
        setMfaCode={state.setMfaCode}
        onBack={state.handleBack}
      />
    );
  }
  return (
    <CredentialsForm
      loading={state.loading}
      onSubmit={state.handleEmailLogin}
      email={state.email}
      setEmail={state.setEmail}
      password={state.password}
      setPassword={state.setPassword}
      onForgotPassword={onForgotPassword}
      onPasskeyLogin={state.handlePasskeyLogin}
    />
  );
};

// Optional Social Section
interface OptionalSocialSectionProps {
  showMfa: boolean;
  loading: boolean;
  onSocialLogin: (provider: 'Google' | 'Facebook') => void;
  onSignup: () => void;
}

const OptionalSocialSection: React.FC<OptionalSocialSectionProps> = ({ showMfa, loading, onSocialLogin, onSignup }) => {
  if (showMfa) return null;
  return <SocialSection loading={loading} onSocialLogin={onSocialLogin} onSignup={onSignup} />;
};

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, loginWithPassword } = useAuth();

  const from = (location.state as { from?: { pathname?: string } } | undefined)?.from?.pathname || '/scouts';

  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  const state = useLoginState(loginWithPassword, navigate, from);

  const handleForgotPassword = () => navigate('/forgot-password');
  const handleSignup = () => navigate('/signup');
  const clearError = () => state.setError(null);

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%)',
        p: 2,
      }}
    >
      <Paper elevation={6} sx={{ p: 4, width: '100%', maxWidth: 450 }}>
        <Box sx={{ textAlign: 'center', mb: 4 }}>
          <Typography variant="h4" component="h1" gutterBottom sx={{ fontFamily: 'Kaushan Script, cursive' }}>
            Welcome Back
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Sign in to your KernelWorx account
          </Typography>
        </Box>

        <ErrorAlert error={state.error} onClose={clearError} />
        <PasskeyPrompt show={state.showPasskeyPrompt} />
        <LoginFormContainer state={state} onForgotPassword={handleForgotPassword} />
        <OptionalSocialSection
          showMfa={state.showMfa}
          loading={state.loading}
          onSocialLogin={state.handleSocialLogin}
          onSignup={handleSignup}
        />
      </Paper>
    </Box>
  );
};
