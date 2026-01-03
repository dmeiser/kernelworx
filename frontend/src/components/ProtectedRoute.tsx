/**
 * Protected route wrapper component
 *
 * Redirects to login if user is not authenticated.
 * Optionally requires admin privileges.
 */

import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Box, CircularProgress, Typography } from '@mui/material';

interface ProtectedRouteProps {
  children: React.ReactNode;
  /** Whether route requires admin privileges */
  requireAdmin?: boolean;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, requireAdmin = false }) => {
  const { isAuthenticated, isAdmin, loading } = useAuth();
  const location = useLocation();

  const routeState = React.useMemo(() => {
    if (loading) return 'loading' as const;
    if (!isAuthenticated) return 'login' as const;
    if (requireAdmin && !isAdmin) return 'denied' as const;
    return 'ok' as const;
  }, [isAuthenticated, isAdmin, loading, requireAdmin]);

  // Show loading spinner while checking auth state
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

  // Redirect to login if not authenticated
  if (routeState === 'login') {
    // Save the intended destination for after login
    sessionStorage.setItem('oauth_redirect', location.pathname);
    return <Navigate to="/login" state={{ from: { pathname: location.pathname } }} replace />;
  }

  // Show access denied if admin required but user is not admin
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

  return <>{children}</>;
};
