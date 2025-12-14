/**
 * Custom Login Page
 * 
 * Provides branded login interface with:
 * - Email/password authentication
 * - Social login buttons (Google, Facebook, Apple)
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
import { Google as GoogleIcon, Facebook as FacebookIcon, Apple as AppleIcon } from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, loginWithPassword } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // If already logged in, redirect to profiles
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/profiles', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  // Get the redirect path from location state (defaults to /profiles)
  const from = (location.state as any)?.from?.pathname || '/profiles';

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await loginWithPassword(email, password);
      // On success, navigate to the intended destination
      navigate(from, { replace: true });
    } catch (err: any) {
      console.error('Login failed:', err);
      setError(err.message || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  const handleSocialLogin = (provider: 'Google' | 'Facebook' | 'Apple') => {
    setError(null);
    setLoading(true);

    try {
      // Redirect to Cognito Hosted UI for social login
      const domain = import.meta.env.VITE_COGNITO_DOMAIN;
      const clientId = import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID;
      const redirectUri = encodeURIComponent(
        import.meta.env.VITE_OAUTH_REDIRECT_SIGNIN || window.location.origin
      );
      const identityProvider = provider.toLowerCase();
      
      window.location.href = `https://${domain}/oauth2/authorize?client_id=${clientId}&response_type=code&redirect_uri=${redirectUri}&identity_provider=${identityProvider}&scope=openid+email+profile`;
    } catch (err: any) {
      console.error('Social login failed:', err);
      setError(`${provider} login failed. Please try again.`);
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
      <Paper
        elevation={3}
        sx={{
          p: 4,
          width: '100%',
          maxWidth: 450,
        }}
      >
        {/* Header */}
        <Box sx={{ textAlign: 'center', mb: 4 }}>
          <Typography variant="h4" component="h1" gutterBottom fontWeight={600}>
            Welcome Back
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Sign in to your Popcorn Manager account
          </Typography>
        </Box>

        {/* Error Alert */}
        {error && (
          <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Email/Password Form */}
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
          <Box sx={{ textAlign: 'right', mb: 2 }}>
            <MuiLink
              component="button"
              type="button"
              variant="body2"
              onClick={() => navigate('/forgot-password')}
              sx={{ cursor: 'pointer' }}
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
            sx={{ mb: 3 }}
          >
            {loading ? <CircularProgress size={24} /> : 'Sign In'}
          </Button>
        </form>

        {/* Divider */}
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
            onClick={() => handleSocialLogin('Google')}
            disabled={loading}
          >
            Continue with Google
          </Button>
          <Button
            variant="outlined"
            fullWidth
            size="large"
            startIcon={<FacebookIcon />}
            onClick={() => handleSocialLogin('Facebook')}
            disabled={loading}
          >
            Continue with Facebook
          </Button>
          <Button
            variant="outlined"
            fullWidth
            size="large"
            startIcon={<AppleIcon />}
            onClick={() => handleSocialLogin('Apple')}
            disabled={loading}
          >
            Continue with Apple
          </Button>
        </Stack>

        {/* Sign Up Link */}
        <Box sx={{ textAlign: 'center', mt: 3 }}>
          <Typography variant="body2" color="text.secondary">
            Don't have an account?{' '}
            <MuiLink
              component="button"
              type="button"
              variant="body2"
              onClick={() => navigate('/signup')}
              sx={{ cursor: 'pointer', fontWeight: 600 }}
            >
              Sign up
            </MuiLink>
          </Typography>
        </Box>

        {/* COPPA Notice */}
        <Alert severity="warning" sx={{ mt: 3 }}>
          <Typography variant="caption">
            You must be at least 13 years old to create an account (COPPA compliance).
          </Typography>
        </Alert>
      </Paper>
    </Box>
  );
};
