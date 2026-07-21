/**
 * LoadingState - Consistent centered loading spinner for pages and sections
 *
 * Use for full-page loads (default minHeight) or inline section loads (minHeight="200px" or "auto").
 */

import React from 'react';
import { Box, CircularProgress, type CircularProgressProps } from '@mui/material';

interface LoadingStateProps {
  minHeight?: string | number;
  size?: CircularProgressProps['size'];
  py?: number;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  minHeight = '400px',
  size = 40,
  py = 0,
}) => (
  <Box
    display="flex"
    justifyContent="center"
    alignItems="center"
    minHeight={minHeight}
    py={py}
  >
    <CircularProgress size={size} />
  </Box>
);
