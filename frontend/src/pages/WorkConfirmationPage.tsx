import React, { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { Box, Button, Stack, Typography, TextField } from '@mui/material';

export function WorkConfirmationPage() {
  const [actual, setActual] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  return (
    <Box>
      <PageHeader title="Work confirmation" />
      <Stack spacing={2}>
        <TextField label="Actual minutes" type="number" value={actual} onChange={(e) => setActual(Number(e.target.value))} />
        <Button onClick={() => setConfirmed(true)}>Confirm</Button>
        <Button onClick={() => setConfirmed(false)}>Unconfirm</Button>
        {confirmed && <Typography>Confirmed {actual} min</Typography>}
      </Stack>
    </Box>
  );
}
