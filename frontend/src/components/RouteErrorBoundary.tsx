/**
 * RouteErrorBoundary - Catches errors from lazy-loaded route components
 *
 * Displays a recovery UI when a route chunk fails to load, instead of
 * leaving the user stuck on the Suspense fallback.
 */

import React from 'react';
import { Box, Button, Typography } from '@mui/material';
import { ErrorAlert } from './ErrorAlert';

interface RouteErrorBoundaryProps {
  children: React.ReactNode;
}

interface RouteErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class RouteErrorBoundary extends React.Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  constructor(props: RouteErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error('Route chunk load error:', error, errorInfo);
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <Box sx={{ p: 3 }}>
          <ErrorAlert message="This page failed to load. Please check your connection and try again." />
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {this.state.error?.message}
          </Typography>
          <Button variant="contained" onClick={this.handleReload}>
            Reload page
          </Button>
        </Box>
      );
    }

    return this.props.children;
  }
}
