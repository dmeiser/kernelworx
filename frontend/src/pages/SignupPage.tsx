/**
 * Custom Signup Page
 *
 * Provides branded signup interface with:
 * - Email/password registration
 * - Optional user metadata (first name, last name, city, state, unit number)
 * - COPPA compliance warning (13+ age requirement)
 * - Email verification flow
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
  Link as MuiLink,
  Checkbox,
  FormControlLabel,
  MenuItem,
} from '@mui/material';
import { useNavigate, type NavigateFunction } from 'react-router-dom';
import { signUp, confirmSignUp, autoSignIn, fetchAuthSession } from 'aws-amplify/auth';
import { useMutation } from '@apollo/client/react';
import { UPDATE_MY_ACCOUNT } from '../lib/graphql';
import { useAuth } from '../contexts/AuthContext';
import { UNIT_TYPES } from '../constants/unitTypes';

// Types for optional fields
interface OptionalFields {
  givenName: string;
  familyName: string;
  city: string;
  state: string;
  unitType: string;
  unitNumber: string;
}

// Dispatch table for signup error messages
const SIGNUP_ERROR_MESSAGES: Record<string, string> = {
  UsernameExistsException: 'An account with this email already exists',
  InvalidPasswordException:
    'Password does not meet requirements: minimum 8 characters with uppercase, lowercase, numbers, and symbols',
  InvalidParameterException: 'Invalid input. Please check your information',
};

// Dispatch table for verification error messages
const VERIFICATION_ERROR_MESSAGES: Record<string, string> = {
  CodeMismatchException: 'Invalid verification code. Please check and try again',
  ExpiredCodeException: 'Verification code expired. Please request a new one',
};

// Helper: Get error message from dispatch table with fallback
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

// Helper: Get signup error message from dispatch table
function getSignupErrorMessage(error: { name?: string; message?: string }): string {
  const fallback = error.message || 'Signup failed. Please try again';
  return getErrorFromTable(SIGNUP_ERROR_MESSAGES, error.name, fallback);
}

// Helper: Get verification error message from dispatch table
function getVerificationErrorMessage(error: { name?: string; message?: string }): string {
  const fallback = error.message || 'Verification failed. Please try again';
  return getErrorFromTable(VERIFICATION_ERROR_MESSAGES, error.name, fallback);
}

// Validation rules as array of [condition, errorMessage] tuples
type ValidationRule = [boolean, string];

function getValidationError(rules: ValidationRule[]): string | null {
  for (const [condition, message] of rules) {
    if (condition) return message;
  }
  return null;
}

// Helper: Validate form fields and return error message or null
function validateFormFields(
  email: string,
  password: string,
  confirmPassword: string,
  ageConfirmed: boolean,
): string | null {
  const rules: ValidationRule[] = [
    [!email || !password || !confirmPassword, 'Email and password are required'],
    [!email.includes('@'), 'Please enter a valid email address'],
    [password.length < 8, 'Password must be at least 8 characters'],
    [password !== confirmPassword, 'Passwords do not match'],
    [!ageConfirmed, 'You must be 13 years or older to create an account'],
  ];
  return getValidationError(rules);
}

// Helper: Check if any optional fields are provided
function hasOptionalFields(fields: OptionalFields): boolean {
  const { unitNumber, ...stringFields } = fields;
  const hasStringField = Object.values(stringFields).some(Boolean);
  return hasStringField || Boolean(unitNumber.trim());
}

// Helper: Parse unit number string to number or undefined
function parseUnitNumber(unitNumber: string): number | undefined {
  const trimmed = unitNumber.trim();
  return trimmed ? parseInt(trimmed, 10) : undefined;
}

// Helper: Build optional fields input for mutation
function buildOptionalFieldsInput(fields: OptionalFields): Record<string, string | number> {
  const result: Record<string, string | number> = {};
  const stringFieldKeys: (keyof Omit<OptionalFields, 'unitNumber'>)[] = [
    'givenName',
    'familyName',
    'city',
    'state',
    'unitType',
  ];
  for (const key of stringFieldKeys) {
    if (fields[key]) result[key] = fields[key];
  }
  const parsed = parseUnitNumber(fields.unitNumber);
  if (parsed) result.unitNumber = parsed;
  return result;
}

// Helper: Save optional fields via mutation
async function saveOptionalFields(
  updateMyAccount: (options: { variables: { input: Record<string, unknown> } }) => Promise<unknown>,
  fields: OptionalFields,
): Promise<void> {
  if (!hasOptionalFields(fields)) return;
  try {
    const input = buildOptionalFieldsInput(fields);
    await updateMyAccount({ variables: { input } });
    console.log('Optional fields saved successfully');
  } catch (updateError) {
    console.error('Failed to save optional fields:', updateError);
    // Don't block navigation if this fails
  }
}

// Helper: Handle post-verification navigation
async function handlePostVerificationAuth(
  refreshSession: () => Promise<void>,
  navigate: NavigateFunction,
  setSuccess: (msg: string | null) => void,
): Promise<void> {
  try {
    await fetchAuthSession();
    console.log('User is authenticated despite autoSignIn failure');
    await refreshSession();
    navigate('/scouts');
  } catch {
    console.log('User is not authenticated, redirecting to login');
    setSuccess('Please log in with your new account');
    setTimeout(() => navigate('/login'), 1500);
  }
}

// Helper: Process auto sign-in and save optional fields
async function processAutoSignIn(
  updateMyAccount: (options: { variables: { input: Record<string, unknown> } }) => Promise<unknown>,
  optionalFields: OptionalFields,
  refreshSession: () => Promise<void>,
  navigate: NavigateFunction,
  setSuccess: (msg: string | null) => void,
): Promise<void> {
  try {
    await autoSignIn();
    await saveOptionalFields(updateMyAccount, optionalFields);
    await refreshSession();
    navigate('/scouts');
  } catch (autoSignInError) {
    console.log('Auto sign-in failed, checking authentication state:', autoSignInError);
    await handlePostVerificationAuth(refreshSession, navigate, setSuccess);
  }
}

export const SignupPage: React.FC = () => {
  const navigate = useNavigate();
  const { refreshSession } = useAuth();
  const [updateMyAccount] = useMutation(UPDATE_MY_ACCOUNT);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [givenName, setGivenName] = useState('');
  const [familyName, setFamilyName] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [unitType, setUnitType] = useState('');
  const [unitNumber, setUnitNumber] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [showVerification, setShowVerification] = useState(false);
  const [verificationCode, setVerificationCode] = useState('');

  const getOptionalFields = (): OptionalFields => ({
    givenName,
    familyName,
    city,
    state,
    unitType,
    unitNumber,
  });

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const validationError = validateFormFields(email, password, confirmPassword, ageConfirmed);
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);

    try {
      const signUpResult = await signUp({
        username: email,
        password,
        options: {
          userAttributes: {
            email,
            ...(givenName && { given_name: givenName }),
            ...(familyName && { family_name: familyName }),
          },
          autoSignIn: true,
        },
      });

      console.log('Signup successful:', signUpResult);
      handleSignupNextStep(signUpResult.nextStep.signUpStep);
    } catch (err: unknown) {
      console.error('Signup failed:', err);
      const typedError = err as { name?: string; message?: string };
      setError(getSignupErrorMessage(typedError));
    } finally {
      setLoading(false);
    }
  };

  const handleSignupNextStep = (signUpStep: string) => {
    if (signUpStep === 'CONFIRM_SIGN_UP') {
      setShowVerification(true);
      setSuccess('Please check your email for a verification code');
      return;
    }
    if (signUpStep === 'DONE') {
      setSuccess('Account created successfully!');
      setTimeout(() => navigate('/login'), 1500);
    }
  };

  const handleVerifyEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const confirmResult = await confirmSignUp({
        username: email,
        confirmationCode: verificationCode,
      });

      console.log('Email confirmed:', confirmResult);

      if (!confirmResult.isSignUpComplete) {
        return;
      }

      setSuccess('Email verified! Signing you in...');
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await processAutoSignIn(updateMyAccount, getOptionalFields(), refreshSession, navigate, setSuccess);
    } catch (err: unknown) {
      console.error('Email verification failed:', err);
      const typedError = err as { name?: string; message?: string };
      setError(getVerificationErrorMessage(typedError));
    } finally {
      setLoading(false);
    }
  };

  const handleResendCode = async () => {
    // TODO: Implement resend verification code
    setSuccess('Resend code functionality coming soon');
  };

  if (showVerification) {
    return (
      <VerificationView
        email={email}
        verificationCode={verificationCode}
        setVerificationCode={setVerificationCode}
        error={error}
        success={success}
        loading={loading}
        onVerify={handleVerifyEmail}
        onResendCode={handleResendCode}
        onNavigateToLogin={() => navigate('/login')}
      />
    );
  }

  return (
    <SignupFormView
      email={email}
      setEmail={setEmail}
      givenName={givenName}
      setGivenName={setGivenName}
      familyName={familyName}
      setFamilyName={setFamilyName}
      city={city}
      setCity={setCity}
      state={state}
      setState={setState}
      unitType={unitType}
      setUnitType={setUnitType}
      unitNumber={unitNumber}
      setUnitNumber={setUnitNumber}
      password={password}
      setPassword={setPassword}
      confirmPassword={confirmPassword}
      setConfirmPassword={setConfirmPassword}
      ageConfirmed={ageConfirmed}
      setAgeConfirmed={setAgeConfirmed}
      error={error}
      success={success}
      loading={loading}
      onSignup={handleSignup}
      onNavigateToLogin={() => navigate('/login')}
    />
  );
};

// Sub-component: Page layout wrapper
interface PageLayoutProps {
  maxWidth?: number;
  children: React.ReactNode;
}

const PageLayout: React.FC<PageLayoutProps> = ({ maxWidth = 500, children }) => (
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
    <Paper elevation={6} sx={{ p: 4, maxWidth, width: '100%' }}>
      {children}
    </Paper>
  </Box>
);

// Sub-component: Alert messages display
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

// Sub-component: Verification view
interface VerificationViewProps {
  email: string;
  verificationCode: string;
  setVerificationCode: (code: string) => void;
  error: string | null;
  success: string | null;
  loading: boolean;
  onVerify: (e: React.FormEvent) => void;
  onResendCode: () => void;
  onNavigateToLogin: () => void;
}

const VerificationView: React.FC<VerificationViewProps> = ({
  email,
  verificationCode,
  setVerificationCode,
  error,
  success,
  loading,
  onVerify,
  onResendCode,
  onNavigateToLogin,
}) => (
  <PageLayout maxWidth={450}>
    <Typography
      variant="h4"
      component="h1"
      gutterBottom
      sx={{ fontFamily: 'Kaushan Script, cursive', textAlign: 'center' }}
    >
      Verify Email
    </Typography>

    <Typography variant="body2" color="text.secondary" paragraph>
      We've sent a verification code to <strong>{email}</strong>. Please enter it below to complete your registration.
    </Typography>

    <AlertMessages error={error} success={success} />

    <Box component="form" onSubmit={onVerify}>
      <TextField
        fullWidth
        label="Verification Code"
        value={verificationCode}
        onChange={(e) => setVerificationCode(e.target.value)}
        margin="normal"
        required
        autoFocus
        placeholder="123456"
      />

      <Button type="submit" fullWidth variant="contained" sx={{ mt: 3, mb: 2 }} disabled={loading}>
        {loading ? <CircularProgress size={24} /> : 'Verify Email'}
      </Button>

      <Stack spacing={1}>
        <Button fullWidth variant="text" onClick={onResendCode} disabled={loading}>
          Resend Code
        </Button>
        <Button fullWidth variant="text" onClick={onNavigateToLogin}>
          Back to Login
        </Button>
      </Stack>
    </Box>
  </PageLayout>
);

// Sub-component: COPPA Warning Alert
const CoppaWarningAlert: React.FC = () => (
  <Alert
    severity="warning"
    sx={{
      mb: 3,
      backgroundColor: '#fff3e0',
      borderLeft: '4px solid #f57c00',
      '& .MuiAlert-icon': { color: '#e65100' },
    }}
  >
    <Typography variant="body2" sx={{ color: '#e65100' }}>
      <strong>⚠️ Age Requirement:</strong> You must be 13 years or older to create an account. By signing up, you
      confirm that you meet this age requirement as required by COPPA (Children's Online Privacy Protection Act).
    </Typography>
  </Alert>
);

// Sub-component: Signup form view
interface SignupFormViewProps {
  email: string;
  setEmail: (v: string) => void;
  givenName: string;
  setGivenName: (v: string) => void;
  familyName: string;
  setFamilyName: (v: string) => void;
  city: string;
  setCity: (v: string) => void;
  state: string;
  setState: (v: string) => void;
  unitType: string;
  setUnitType: (v: string) => void;
  unitNumber: string;
  setUnitNumber: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  confirmPassword: string;
  setConfirmPassword: (v: string) => void;
  ageConfirmed: boolean;
  setAgeConfirmed: (v: boolean) => void;
  error: string | null;
  success: string | null;
  loading: boolean;
  onSignup: (e: React.FormEvent) => void;
  onNavigateToLogin: () => void;
}

const SignupFormView: React.FC<SignupFormViewProps> = ({
  email,
  setEmail,
  givenName,
  setGivenName,
  familyName,
  setFamilyName,
  city,
  setCity,
  state,
  setState,
  unitType,
  setUnitType,
  unitNumber,
  setUnitNumber,
  password,
  setPassword,
  confirmPassword,
  setConfirmPassword,
  ageConfirmed,
  setAgeConfirmed,
  error,
  success,
  loading,
  onSignup,
  onNavigateToLogin,
}) => (
  <PageLayout>
    <Typography
      variant="h4"
      component="h1"
      gutterBottom
      sx={{ fontFamily: 'Kaushan Script, cursive', textAlign: 'center' }}
    >
      Create Account
    </Typography>

    <Typography variant="body2" color="text.secondary" paragraph align="center">
      Join KernelWorx to manage your popcorn sales
    </Typography>

    <CoppaWarningAlert />
    <AlertMessages error={error} success={success} />

    <Box component="form" onSubmit={onSignup}>
      <TextField
        fullWidth
        label="Email Address"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        margin="normal"
        required
        autoComplete="email"
      />

      <Stack direction="row" spacing={2}>
        <TextField
          fullWidth
          label="First Name"
          value={givenName}
          onChange={(e) => setGivenName(e.target.value)}
          margin="normal"
          helperText="Optional"
        />
        <TextField
          fullWidth
          label="Last Name"
          value={familyName}
          onChange={(e) => setFamilyName(e.target.value)}
          margin="normal"
          helperText="Optional"
        />
      </Stack>

      <TextField
        fullWidth
        label="City"
        value={city}
        onChange={(e) => setCity(e.target.value)}
        margin="normal"
        helperText="Optional"
      />

      <TextField
        fullWidth
        label="State"
        value={state}
        onChange={(e) => setState(e.target.value.toUpperCase())}
        margin="normal"
        helperText="Optional (e.g., CA, TX, NY)"
        inputProps={{ maxLength: 2 }}
      />

      <TextField
        fullWidth
        select
        label="Unit Type (Optional)"
        value={unitType}
        onChange={(e) => setUnitType(e.target.value)}
        margin="normal"
        helperText="Select the type of Scouting unit"
      >
        {UNIT_TYPES.map((opt) => (
          <MenuItem key={opt.value} value={opt.value}>
            {opt.label}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        fullWidth
        type="number"
        label="Unit Number (Optional)"
        value={unitNumber}
        onChange={(e) => setUnitNumber(e.target.value)}
        margin="normal"
        helperText="Optional (e.g., 123, 456)"
        slotProps={{ htmlInput: { min: 1, step: 1 } }}
      />

      <TextField
        fullWidth
        label="Password"
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
        label="Confirm Password"
        type="password"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        margin="normal"
        required
        autoComplete="new-password"
      />

      <FormControlLabel
        control={<Checkbox checked={ageConfirmed} onChange={(e) => setAgeConfirmed(e.target.checked)} required />}
        label="I confirm that I am 13 years of age or older"
        sx={{ mt: 2 }}
      />

      <Button type="submit" fullWidth variant="contained" sx={{ mt: 3, mb: 2 }} disabled={loading}>
        {loading ? <CircularProgress size={24} /> : 'Create Account'}
      </Button>

      <Typography variant="body2" align="center" color="text.secondary">
        Already have an account?{' '}
        <MuiLink component="button" type="button" onClick={onNavigateToLogin} sx={{ cursor: 'pointer' }}>
          Sign In
        </MuiLink>
      </Typography>
    </Box>
  </PageLayout>
);
