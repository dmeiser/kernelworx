/**
 * RouteErrorBoundary - Catches errors from lazy-loaded route components
 *
 * Displays a recovery UI when a route chunk fails to load, instead of
 * leaving the user stuck on the Suspense fallback. Non-chunk runtime
 * errors are rethrown so the surrounding ErrorBoundary (which owns reset
 * behavior and prod/dev gating) can handle them.
 */

import React from 'react';
import { Box, Button } from '@mui/material';
import { ErrorAlert } from './ErrorAlert';

interface RouteErrorBoundaryProps {
  children: React.ReactNode;
}

interface RouteErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export function isChunkLoadError(error: Error | null | undefined): boolean {
  if (!(error instanceof Error)) {
    return false;
  }

  const name = error.name.toLowerCase();
  const message = error.message.toLowerCase();

  return (
    name === 'chunkloaderror' ||
    /loading chunk [\w-]+ failed/i.test(message) ||
    /failed to fetch dynamically imported module/i.test(message) ||
    /importing a module script failed/i.test(message) ||
    /error loading dynamically imported module/i.test(message)
  );
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
    if (isChunkLoadError(error)) {
      console.error('Route chunk load error:', error, errorInfo);
    }
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      // Only chunk-load failures belong here. Propagate everything else to
      // the outer ErrorBoundary so route reset and dev gating still apply.
      if (!isChunkLoadError(this.state.error)) {
        throw this.state.error;
      }

      return (
        <Box sx={{ p: 3 }}>
          <ErrorAlert message="This page failed to load. Please check your connection and try again." />
          <Button variant="contained" onClick={this.handleReload}>
            Reload page
          </Button>
        </Box>
      );
    }

    return this.props.children;
  }
}
