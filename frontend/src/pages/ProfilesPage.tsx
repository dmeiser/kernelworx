/**
 * Profiles page - List of owned and shared seller profiles
 */

import React from 'react';
import { Typography, Box, Paper } from '@mui/material';

export const ProfilesPage: React.FC = () => {
  return (
    <Box>
      <Typography variant="h4" component="h1" gutterBottom>
        My Profiles
      </Typography>
      <Paper sx={{ p: 3, mt: 2 }}>
        <Typography variant="body1" color="text.secondary">
          This page will display your seller profiles (owned and shared).
          Implementation coming in Phase 2 Step 5.
        </Typography>
      </Paper>
    </Box>
  );
};
