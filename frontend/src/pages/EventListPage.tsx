import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import {
  Box,
  Button,
  Stack,
  Typography,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';

interface Ev {
  id: string;
  name: string;
  startsAt: string;
  cancelled: boolean;
  cancellationReason?: string;
}

export function EventListPage() {
  const [events, setEvents] = useState<Ev[]>([]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [startsAt, setStartsAt] = useState('');
  const [splitOverride, setSplitOverride] = useState(false);
  const [weOwe, setWeOwe] = useState(false);

  const create = () => {
    setEvents((e) => [...e, { id: crypto.randomUUID(), name, startsAt, cancelled: false }]);
    setOpen(false);
    setName('');
    setStartsAt('');
    setSplitOverride(false);
    setWeOwe(false);
  };
  const cancel = (id: string, reason: string) => {
    setEvents((e) => e.map((x) => (x.id === id ? { ...x, cancelled: true, cancellationReason: reason } : x)));
  };
  const recreate = (id: string) => {
    const src = events.find((e) => e.id === id);
    if (!src) return;
    setEvents((e) => [
      ...e,
      { id: crypto.randomUUID(), name: src.name + ' (recreated)', startsAt: src.startsAt, cancelled: false },
    ]);
  };

  return (
    <Box>
      <PageHeader title="Events" />
      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <Button variant="contained" onClick={() => setOpen(true)}>
          Create event
        </Button>
      </Stack>
      {events.map((e) => (
        <Box key={e.id} sx={{ mb: 1, p: 1, border: '1px solid #ccc' }}>
          <Typography>{e.name}</Typography>
          <Typography variant="caption">Starts: {e.startsAt} (immutable)</Typography>
          {e.cancelled ? (
            <Typography color="error">Cancelled: {e.cancellationReason}</Typography>
          ) : (
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <Button size="small" onClick={() => cancel(e.id, 'reason')}>
                Cancel
              </Button>
              <Button size="small" onClick={() => recreate(e.id)}>
                Recreate
              </Button>
            </Stack>
          )}
        </Box>
      ))}
      <Dialog open={open} onClose={() => setOpen(false)}>
        <DialogTitle>Create event</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Name" value={name} onChange={(ev) => setName(ev.target.value)} />
            <TextField label="Starts at" value={startsAt} onChange={(ev) => setStartsAt(ev.target.value)} />
            <label>
              <input type="checkbox" checked={splitOverride} onChange={(ev) => setSplitOverride(ev.target.checked)} />{' '}
              Split override
            </label>
            <label>
              <input type="checkbox" checked={weOwe} onChange={(ev) => setWeOwe(ev.target.checked)} /> We Owe (default
              off)
            </label>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={create} variant="contained">
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
