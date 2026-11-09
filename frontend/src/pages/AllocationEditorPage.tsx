import React, { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { Box, Button, Stack, Typography, TextField } from '@mui/material';

export function AllocationEditorPage() {
  const [targets, setTargets] = useState<Record<string, number>>({});
  const [warnings, setWarnings] = useState<string[]>([]);
  return (
    <Box>
      <PageHeader title="Allocation editor" />
      <Stack spacing={2}>
        <TextField label="Product target" type="number" onChange={(e) => setTargets({ ...targets, p1: Number(e.target.value) })} />
        <Button onClick={() => setWarnings(['server warning'])}>Validate</Button>
        {warnings.map((w, i) => <Typography key={i} color="warning.main">{w}</Typography>)}
      </Stack>
    </Box>
  );
}
