import React, { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { Box, Button, Stack, Typography } from '@mui/material';

export function EventListPage() {
  const [events] = useState<Array<{ id: string; name: string }>>([]);
  return (
    <Box>
      <PageHeader title="Events" />
      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <Button variant="contained">Create event</Button>
      </Stack>
      {events.length === 0 ? (
        <Typography>No events yet.</Typography>
      ) : null}
    </Box>
  );
}
