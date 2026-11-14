/**
 * The line a paginated list shows while it finishes, or when it cannot.
 *
 * A Show & Sell list that stops at page one is not merely unfinished: it states, by
 * omission, that the caller owns fewer rows than they do. So the continuation is
 * announced, and a failed continuation says the list is short rather than presenting a
 * short list as the whole truth.
 */

import React from 'react';
import { Box, Typography } from '@mui/material';
import { ErrorNote } from './ErrorAlert';

export const ConnectionRestNotice: React.FC<{ loading: boolean; failed: boolean }> = ({ loading, failed }) => {
  if (loading) {
    return (
      <Box data-testid="connection-rest-loading" sx={{ pt: 1 }}>
        <Typography color="text.secondary">Loading the rest of this list…</Typography>
      </Box>
    );
  }
  return <ErrorNote message={failed ? 'The rest of this list could not be loaded, so some rows are not shown.' : null} />;
};
