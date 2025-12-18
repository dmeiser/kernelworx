/**
 * Custom Login Page
 *
 * Provides branded login interface with:
 * - Email/password authentication
 * - Social login buttons (Google, Facebook, Apple)
 * - Password reset flow
 * - Link to signup page
 */

import { useState, useEffect } from "react";
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
} from "@mui/material";
import {
  Google as GoogleIcon,
  Facebook as FacebookIcon,
  Apple as AppleIcon,
  Fingerprint as FingerprintIcon,
} from "@mui/icons-material";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { confirmSignIn, signIn } from "aws-amplify/auth";
import type { SignInOutput } from "aws-amplify/auth";

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, loginWithPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [showMfa, setShowMfa] = useState(false);
  const [showPasskeyPrompt, setShowPasskeyPrompt] = useState(false);

  // If already logged in, redirect to profiles
  useEffect(() => {
    if (isAuthenticated) {
      navigate("/profiles", { replace: true });
    }
  }, [isAuthenticated, navigate]);

  // Get the redirect path from location state (defaults to /profiles)
  const from = (location.state as any)?.from?.pathname || "/profiles";

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result = (await loginWithPassword(email, password)) as SignInOutput;

      if (result.isSignedIn) {
        // Login successful, navigate to destination
        navigate(from, { replace: true });
      } else if (result.nextStep?.signInStep === "CONFIRM_SIGN_IN_WITH_TOTP_CODE") {
        // TOTP MFA required - show MFA form
        setShowMfa(true);
        setMfaCode("");
        setLoading(false);
      } else if (result.nextStep?.signInStep === "CONFIRM_SIGN_IN_WITH_SMS_CODE") {
        // SMS MFA required - show MFA form
        setShowMfa(true);
        setMfaCode("");
        setLoading(false);
      } else if (result.nextStep?.signInStep === "CONFIRM_SIGN_IN_WITH_EMAIL_CODE") {
        // Email MFA required - show MFA form
        setShowMfa(true);
        setMfaCode("");
        setLoading(false);
      } else if (result.nextStep) {
        // Other challenge types
        console.log("Unexpected next step:", result.nextStep);
        setError(`Unexpected authentication step: ${result.nextStep.signInStep}`);
        setLoading(false);
      } else {
        // No nextStep and not signed in - unclear state
        setError("Authentication failed. Please try again.");
        setLoading(false);
      }
    } catch (err: any) {
      console.error("Login failed:", err);
      setError(err.message || "Login failed. Please check your credentials.");
      setLoading(false);
    }
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result = await confirmSignIn({ challengeResponse: mfaCode });

      if (result.isSignedIn) {
        // MFA successful - refresh auth session to pick up new tokens
        // Then navigate to destination. The AuthContext will detect the new session.
        setShowMfa(false);
        setMfaCode("");
        setPassword("");
        // Refresh auth session and trigger redirect via useEffect hook
        setTimeout(() => {
          navigate(from, { replace: true });
        }, 500);
      } else {
        setError("MFA verification failed");
        setLoading(false);
      }
    } catch (err: any) {
      console.error("MFA failed:", err);
      setError(err.message || "Invalid MFA code");
      setLoading(false);
    }
  };

  const handlePasskeyLogin = async () => {
    if (!email) {
      setError("Please enter your email address");
      return;
    }

    setError(null);
    setLoading(true);

    try {
      // Sign in with USER_AUTH flow
      const result = await signIn({
        username: email,
        options: {
          authFlowType: "USER_AUTH",
        },
      });

      if (result.isSignedIn) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        window.location.href = from;
      } else if (
        result.nextStep?.signInStep ===
        "CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION"
      ) {
        // Multiple auth methods available - check what's available and select WebAuthn
        console.log("Available auth factors:", result.nextStep);

        // Select WebAuthn from available options
        const confirmResult = await confirmSignIn({
          challengeResponse: "WEB_AUTHN",
        });

        if (confirmResult.isSignedIn) {
          await new Promise((resolve) => setTimeout(resolve, 500));
          window.location.href = from;
        } else if (confirmResult.nextStep?.signInStep) {
          // Handle next step (could be WebAuthn or other)
          setShowPasskeyPrompt(true);
          setLoading(false);
        }
      } else if (
        result.nextStep?.signInStep &&
        result.nextStep.signInStep.includes("WEBAUTHN")
      ) {
        // Passkey challenge initiated directly
        setShowPasskeyPrompt(true);
        setLoading(false);
      } else if (
        result.nextStep?.signInStep === "CONFIRM_SIGN_IN_WITH_PASSWORD"
      ) {
        // Cognito chose password - this means WebAuthn isn't available or user doesn't have passkey
        setError(
          "No passkey found for this account. Please register a passkey first or use password login.",
        );
        setLoading(false);
      } else if (result.nextStep) {
        console.log("Unexpected next step:", result.nextStep);
        setError(`Unexpected step: ${result.nextStep.signInStep}`);
        setLoading(false);
      }
    } catch (err: any) {
      console.error("Passkey login failed:", err);
      setError(
        err.message ||
          "Passkey authentication failed. Make sure you have a passkey registered.",
      );
      setLoading(false);
    }
  };

  const handleSocialLogin = (provider: "Google" | "Facebook" | "Apple") => {
    setError(null);
    setLoading(true);

    try {
      // Redirect to Cognito Hosted UI for social login
      const domain = import.meta.env.VITE_COGNITO_DOMAIN;
      const clientId = import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID;
      const redirectUri = encodeURIComponent(
        import.meta.env.VITE_OAUTH_REDIRECT_SIGNIN || window.location.origin,
      );
      const identityProvider = provider.toLowerCase();

      window.location.href = `https://${domain}/oauth2/authorize?client_id=${clientId}&response_type=code&redirect_uri=${redirectUri}&identity_provider=${identityProvider}&scope=openid+email+profile`;
    } catch (err: any) {
      console.error("Social login failed:", err);
      setError(`${provider} login failed. Please try again.`);
      setLoading(false);
    }
  };

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
          width: "100%",
          maxWidth: 450,
        }}
      >
        {/* Header */}
        <Box sx={{ textAlign: "center", mb: 4 }}>
          <Typography
            variant="h4"
            component="h1"
            gutterBottom
            sx={{ fontFamily: "Kaushan Script, cursive" }}
          >
            Welcome Back
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Sign in to your KernelWorx account
          </Typography>
        </Box>

        {/* Error Alert */}
        {error && (
          <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Passkey Prompt Info */}
        {showPasskeyPrompt && (
          <Alert severity="info" sx={{ mb: 3 }}>
            Use your security key, fingerprint, or face recognition to sign in
          </Alert>
        )}

        {/* MFA Code Form */}
        {showMfa ? (
          <form onSubmit={handleMfaSubmit}>
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
                inputProps={{ maxLength: 6, pattern: "[0-9]*" }}
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
              {loading ? <CircularProgress size={24} /> : "Verify"}
            </Button>

            <Button
              variant="text"
              fullWidth
              onClick={() => {
                setShowMfa(false);
                setMfaCode("");
                setPassword("");
              }}
              disabled={loading}
            >
              Back to Login
            </Button>
          </form>
        ) : (
          /* Email/Password Form */
          <form onSubmit={handleEmailLogin}>
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

            {/* Forgot Password Link */}
            <Box sx={{ textAlign: "right", mb: 2 }}>
              <MuiLink
                component="button"
                type="button"
                variant="body2"
                onClick={() => navigate("/forgot-password")}
                sx={{ cursor: "pointer" }}
              >
                Forgot password?
              </MuiLink>
            </Box>

            {/* Sign In Button */}
            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="large"
              disabled={loading}
              sx={{ mb: 2 }}
            >
              {loading ? <CircularProgress size={24} /> : "Sign In"}
            </Button>

            {/* Passkey Login Button */}
            <Button
              variant="outlined"
              fullWidth
              size="large"
              startIcon={<FingerprintIcon />}
              onClick={handlePasskeyLogin}
              disabled={loading}
              sx={{ mb: 3 }}
            >
              Sign In with Passkey
            </Button>
          </form>
        )}

        {/* Divider */}
        {!showMfa && (
          <>
            <Divider sx={{ my: 3 }}>
              <Typography variant="body2" color="text.secondary">
                OR
              </Typography>
            </Divider>

            {/* Social Login Buttons */}
            <Stack spacing={2} sx={{ mb: 3 }}>
              <Button
                variant="outlined"
                fullWidth
                size="large"
                startIcon={<GoogleIcon />}
                onClick={() => handleSocialLogin("Google")}
                disabled={loading}
              >
                Continue with Google
              </Button>
              <Button
                variant="outlined"
                fullWidth
                size="large"
                startIcon={<FacebookIcon />}
                onClick={() => handleSocialLogin("Facebook")}
                disabled={loading}
              >
                Continue with Facebook
              </Button>
              <Button
                variant="outlined"
                fullWidth
                size="large"
                startIcon={<AppleIcon />}
                onClick={() => handleSocialLogin("Apple")}
                disabled={loading}
              >
                Continue with Apple
              </Button>
            </Stack>

            {/* Sign Up Link */}
            <Box sx={{ textAlign: "center", mt: 3 }}>
              <Typography variant="body2" color="text.secondary">
                Don't have an account?{" "}
                <MuiLink
                  component="button"
                  type="button"
                  variant="body2"
                  onClick={() => navigate("/signup")}
                  sx={{ cursor: "pointer", fontWeight: 600 }}
                >
                  Sign up
                </MuiLink>
              </Typography>
            </Box>

            {/* COPPA Notice */}
            <Alert
              severity="warning"
              sx={{
                mt: 3,
                mb: 4,
                backgroundColor: "#fff3e0",
                borderLeft: "4px solid #f57c00",
                "& .MuiAlert-icon": {
                  color: "#e65100",
                },
              }}
            >
              <Typography variant="caption" sx={{ color: "#e65100" }}>
                <strong>⚠️ Age Requirement:</strong> You must be at least 13
                years old to create an account (COPPA compliance).
              </Typography>
            </Alert>
          </>
        )}
      </Paper>
    </Box>
  );
};
