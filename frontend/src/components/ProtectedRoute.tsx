/**
 * Protected route wrapper component
 *
 * Redirects to login if user is not authenticated.
 * Optionally requires admin privileges or TOTP MFA setup.
 */

import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useAdminMfa } from '../hooks/useAdminMfa';
import { getSafeRedirect } from '../lib/redirect';
import { Box, CircularProgress, Typography } from '@mui/material';
import { MfaSetupRequiredState } from './MfaSetupRequiredState';

interface ProtectedRouteProps {
  children: React.ReactNode;
  /** Whether route requires admin privileges */
  requireAdmin?: boolean;
}

type RouteState = 'loading' | 'login' | 'denied' | 'mfa_required' | 'ok';

const computeAdminRouteState = (isAdmin: boolean, isMfaRequired: boolean): RouteState => {
  if (!isAdmin) return 'denied';
  if (isMfaRequired) return 'mfa_required';
  return 'ok';
};

const computeRouteState = (
  loading: boolean,
  isAuthenticated: boolean,
  requireAdmin: boolean,
  isAdmin: boolean,
  isMfaRequired: boolean,
): RouteState => {
  if (loading) return 'loading';
  if (!isAuthenticated) return 'login';
  if (requireAdmin) return computeAdminRouteState(isAdmin, isMfaRequired);
  return 'ok';
};

const renderBlockedState = (routeState: RouteState): React.ReactNode => {
  if (routeState === 'loading') {
    return (
      <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" minHeight="100vh" gap={2}>
        <CircularProgress size={48} />
        <Typography variant="body1" color="text.secondary">
          Loading...
        </Typography>
      </Box>
    );
  }

  if (routeState === 'denied') {
    return (
      <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" minHeight="100vh" gap={2}>
        <Typography variant="h4" color="error">
          Access Denied
        </Typography>
        <Typography variant="body1" color="text.secondary">
          You do not have permission to access this page.
        </Typography>
      </Box>
    );
  }

  if (routeState === 'mfa_required') {
    return (
      <Box p={3}>
        <MfaSetupRequiredState autoOpenDialog />
      </Box>
    );
  }

  return null;
};

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, requireAdmin = false }) => {
  const { isAuthenticated, isAdmin, loading } = useAuth();
  const { isMfaRequired } = useAdminMfa();
  const location = useLocation();

  const routeState = React.useMemo(
    () => computeRouteState(loading, isAuthenticated, requireAdmin, isAdmin, isMfaRequired),
    [loading, isAuthenticated, requireAdmin, isAdmin, isMfaRequired],
  );

  if (routeState === 'login') {
    const safeRedirect = getSafeRedirect(location.pathname, '/home');
    sessionStorage.setItem('oauth_redirect', safeRedirect);
    return <Navigate to="/login" state={{ from: { pathname: location.pathname } }} replace />;
  }

  const blockedView = renderBlockedState(routeState);
  if (blockedView) {
    return <>{blockedView}</>;
  }

  return <>{children}</>;
};
