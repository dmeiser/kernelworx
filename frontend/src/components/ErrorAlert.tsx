/**
 * ErrorAlert - Consistent error alert for page/section load failures
 */

import React from 'react';
import { Alert } from '@mui/material';

interface ErrorAlertProps {
  message: string;
  sx?: React.ComponentProps<typeof Alert>['sx'];
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({ message, sx = { mb: 3 } }) => (
  <Alert severity="error" sx={sx}>
    {message}
  </Alert>
);
