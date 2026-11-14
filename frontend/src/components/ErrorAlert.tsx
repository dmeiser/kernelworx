/**
 * ErrorAlert - Consistent error alert for page/section load failures
 */

import React from 'react';
import { Alert } from '@mui/material';

interface ErrorAlertProps {
  message: string;
  sx?: React.ComponentProps<typeof Alert>['sx'];
  onDismiss?: () => void;
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({ message, sx = { mb: 3 }, onDismiss }) => (
  <Alert severity="error" sx={sx} onClose={onDismiss}>
    {message}
  </Alert>
);

/**
 * An error that only exists when there is one.
 *
 * Written as a component rather than `{message && <ErrorAlert/>}` at every call
 * site: the inline form spends a branch in each screen, and screens are already
 * paying for the conditions that actually matter.
 */
export const ErrorNote: React.FC<{
  message: string | null;
  sx?: React.ComponentProps<typeof Alert>['sx'];
  onDismiss?: () => void;
}> = ({ message, sx, onDismiss }) => {
  if (!message) return null;
  return <ErrorAlert message={message} sx={sx} onDismiss={onDismiss} />;
};
