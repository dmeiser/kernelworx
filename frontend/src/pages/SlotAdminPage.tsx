import React, { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { Box, Button, Stack, Typography, TextField } from '@mui/material';

export function SlotAdminPage() {
  const [duration, setDuration] = useState(60);
  const [capacity, setCapacity] = useState(1);
  const [conflict, setConflict] = useState<string | null>(null);
  return (
    <Box>
      <PageHeader title="Slot administration" />
      <Stack spacing={2}>
        <TextField label="Duration (min)" type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
        <TextField label="Capacity" type="number" value={capacity} onChange={(e) => setCapacity(Number(e.target.value))} />
        <Button onClick={() => setConflict(capacity < 1 ? 'Full Booth conflict' : null)}>Save slot</Button>
        {conflict && <Typography color="error">{conflict}</Typography>}
      </Stack>
    </Box>
  );
}
