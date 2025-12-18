/**
 * Custom Signup Page
 *
 * Provides branded signup interface with:
 * - Email/password registration
 * - Optional user metadata (first name, last name, city, state, unit number)
 * - COPPA compliance warning (13+ age requirement)
 * - Email verification flow
 */

import { useState } from "react";
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
} from "@mui/material";
import { useNavigate } from "react-router-dom";
import {
  signUp,
  confirmSignUp,
  autoSignIn,
  fetchAuthSession,
} from "aws-amplify/auth";
import { useMutation } from "@apollo/client/react";
import { UPDATE_MY_ACCOUNT } from "../lib/graphql";

export const SignupPage: React.FC = () => {
  const navigate = useNavigate();
  const [updateMyAccount] = useMutation(UPDATE_MY_ACCOUNT);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [givenName, setGivenName] = useState("");
  const [familyName, setFamilyName] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [unitNumber, setUnitNumber] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [showVerification, setShowVerification] = useState(false);
  const [verificationCode, setVerificationCode] = useState("");

  const validateForm = (): boolean => {
    if (!email || !password || !confirmPassword) {
      setError("Email and password are required");
      return false;
    }

    if (!email.includes("@")) {
      setError("Please enter a valid email address");
      return false;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return false;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return false;
    }

    if (!ageConfirmed) {
      setError("You must be 13 years or older to create an account");
      return false;
    }

    return true;
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!validateForm()) {
      return;
    }

    setLoading(true);

    try {
      // Sign up with Cognito
      const signUpResult = await signUp({
        username: email,
        password,
        options: {
          userAttributes: {
            email,
            ...(givenName && { given_name: givenName }),
            ...(familyName && { family_name: familyName }),
          },
          autoSignIn: true, // Enable auto sign-in after confirmation
        },
      });

      console.log("Signup successful:", signUpResult);

      if (signUpResult.nextStep.signUpStep === "CONFIRM_SIGN_UP") {
        // Email verification required
        setShowVerification(true);
        setSuccess("Please check your email for a verification code");
      } else if (signUpResult.nextStep.signUpStep === "DONE") {
        // No verification needed (shouldn't happen with email)
        // Store optional fields via updateMyAccount after auto sign-in
        setSuccess("Account created successfully!");
        setTimeout(() => navigate("/login"), 1500);
      }
    } catch (err: any) {
      console.error("Signup failed:", err);

      // Provide user-friendly error messages
      if (err.name === "UsernameExistsException") {
        setError("An account with this email already exists");
      } else if (err.name === "InvalidPasswordException") {
        setError(
          "Password does not meet requirements: minimum 8 characters with uppercase, lowercase, numbers, and symbols",
        );
      } else if (err.name === "InvalidParameterException") {
        setError(err.message || "Invalid input. Please check your information");
      } else {
        setError(err.message || "Signup failed. Please try again");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // Confirm the email with verification code
      const confirmResult = await confirmSignUp({
        username: email,
        confirmationCode: verificationCode,
      });

      console.log("Email confirmed:", confirmResult);

      if (confirmResult.isSignUpComplete) {
        setSuccess("Email verified! Signing you in...");

        // Auto sign-in is enabled, so this should happen automatically
        // Wait a moment for the auto sign-in to complete
        await new Promise((resolve) => setTimeout(resolve, 1000));

        try {
          // Try to complete the auto sign-in
          await autoSignIn();

          // Store optional fields if provided
          if (givenName || familyName || city || state || unitNumber) {
            try {
              await updateMyAccount({
                variables: {
                  input: {
                    ...(givenName && { givenName }),
                    ...(familyName && { familyName }),
                    ...(city && { city }),
                    ...(state && { state }),
                    ...(unitNumber && { unitNumber }),
                  },
                },
              });
              console.log("Optional fields saved successfully");
            } catch (updateError) {
              console.error("Failed to save optional fields:", updateError);
              // Don't block navigation if this fails
            }
          }

          // Auto sign-in successful, redirect to profiles
          navigate("/profiles");
        } catch (autoSignInError) {
          // Auto sign-in API call failed, but user might still be authenticated
          // Check actual auth state instead of assuming
          console.log(
            "Auto sign-in failed, checking authentication state:",
            autoSignInError,
          );

          try {
            // Check if user is actually authenticated
            await fetchAuthSession();
            // User is authenticated, proceed to profiles
            console.log("User is authenticated despite autoSignIn failure");
            navigate("/profiles");
          } catch (sessionError) {
            // User is not authenticated, redirect to login
            console.log("User is not authenticated, redirecting to login");
            setSuccess("Please log in with your new account");
            setTimeout(() => navigate("/login"), 1500);
          }
        }
      }
    } catch (err: any) {
      console.error("Email verification failed:", err);

      if (err.name === "CodeMismatchException") {
        setError("Invalid verification code. Please check and try again");
      } else if (err.name === "ExpiredCodeException") {
        setError("Verification code expired. Please request a new one");
      } else {
        setError(err.message || "Verification failed. Please try again");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleResendCode = async () => {
    // TODO: Implement resend verification code
    setSuccess("Resend code functionality coming soon");
  };

  if (showVerification) {
    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%)",
          p: 2,
        }}
      >
        <Paper
          elevation={6}
          sx={{
            p: 4,
            maxWidth: 450,
            width: "100%",
          }}
        >
          <Typography
            variant="h4"
            component="h1"
            gutterBottom
            sx={{ fontFamily: "Kaushan Script, cursive", textAlign: "center" }}
          >
            Verify Email
          </Typography>

          <Typography variant="body2" color="text.secondary" paragraph>
            We've sent a verification code to <strong>{email}</strong>. Please
            enter it below to complete your registration.
          </Typography>

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

          <Box component="form" onSubmit={handleVerifyEmail}>
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

            <Button
              type="submit"
              fullWidth
              variant="contained"
              sx={{ mt: 3, mb: 2 }}
              disabled={loading}
            >
              {loading ? <CircularProgress size={24} /> : "Verify Email"}
            </Button>

            <Stack spacing={1}>
              <Button
                fullWidth
                variant="text"
                onClick={handleResendCode}
                disabled={loading}
              >
                Resend Code
              </Button>
              <Button
                fullWidth
                variant="text"
                onClick={() => navigate("/login")}
              >
                Back to Login
              </Button>
            </Stack>
          </Box>
        </Paper>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%)",
        p: 2,
      }}
    >
      <Paper
        elevation={6}
        sx={{
          p: 4,
          maxWidth: 500,
          width: "100%",
        }}
      >
        <Typography
          variant="h4"
          component="h1"
          gutterBottom
          sx={{ fontFamily: "Kaushan Script, cursive", textAlign: "center" }}
        >
          Create Account
        </Typography>

        <Typography
          variant="body2"
          color="text.secondary"
          paragraph
          align="center"
        >
          Join KernelWorx to manage your popcorn sales
        </Typography>

        {/* COPPA Warning */}
        <Alert
          severity="warning"
          sx={{
            mb: 3,
            backgroundColor: "#fff3e0",
            borderLeft: "4px solid #f57c00",
            "& .MuiAlert-icon": {
              color: "#e65100",
            },
          }}
        >
          <Typography variant="body2" sx={{ color: "#e65100" }}>
            <strong>⚠️ Age Requirement:</strong> You must be 13 years or older
            to create an account. By signing up, you confirm that you meet this
            age requirement as required by COPPA (Children's Online Privacy
            Protection Act).
          </Typography>
        </Alert>

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

        <Box component="form" onSubmit={handleSignup}>
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
            label="Unit/Pack/Troop Number"
            value={unitNumber}
            onChange={(e) => setUnitNumber(e.target.value)}
            margin="normal"
            helperText="Optional (e.g., Pack 123, Troop 456)"
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
            control={
              <Checkbox
                checked={ageConfirmed}
                onChange={(e) => setAgeConfirmed(e.target.checked)}
                required
              />
            }
            label="I confirm that I am 13 years of age or older"
            sx={{ mt: 2 }}
          />

          <Button
            type="submit"
            fullWidth
            variant="contained"
            sx={{ mt: 3, mb: 2 }}
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : "Create Account"}
          </Button>

          <Typography variant="body2" align="center" color="text.secondary">
            Already have an account?{" "}
            <MuiLink
              component="button"
              type="button"
              onClick={() => navigate("/login")}
              sx={{ cursor: "pointer" }}
            >
              Sign In
            </MuiLink>
          </Typography>
        </Box>
      </Paper>
    </Box>
  );
};
