/**
 * The slot board: every working slot of one Show & Sell event (§3.5.3).
 *
 * Slots are the unit a Scout signs up for, so the board is where an admin decides
 * how many places exist and when they are held. Three rules shape the surface:
 * a slot may be any length (SSE-03 — no hourly rule is encoded here), it has to
 * fit inside the event's immutable window (§3.3.2), and an event holds at most
 * {@link MAX_SLOTS_PER_EVENT} of them. Times are entered and read in the Unit's
 * zone; the write carries UTC.
 *
 * The board closes when the event starts. A slot that already holds Scouts cannot
 * be deleted — their places would disappear with it — so its delete is disabled
 * and the reason is stated on the button.
 */

import React, { useMemo, useState } from 'react';
import { useMutation } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import { DELETE_SHOW_AND_SELL_SLOT, UPSERT_SHOW_AND_SELL_SLOT } from '../../lib/graphql';
import {
  MAX_SLOTS_PER_EVENT,
  acceptsSlotEdits,
  durationLabel,
  intervalLabel,
  minutesBetween,
  parseSlotInterval,
  slotIntervalOf,
  sortSlots,
  withIdempotency,
  reportWriteFailure,
  type SlotDraft,
} from '../../lib/showSell';
import { createWriteIntent, refreshQuery } from '../../lib/units';
import { ErrorNote } from '../ErrorAlert';
import type {
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSlotFieldsFragment,
  GqlUpsertShowAndSellSlotMutation,
} from '../../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Slot = GqlShowAndSellSlotFieldsFragment;

/** The board's draft for a slot that does not exist yet. */
const NEW_SLOT: SlotDraft = { label: '', startAt: '', endAt: '', capacity: '' };

export const SlotBoard: React.FC<{
  event: Event;
  timezone: string;
  onChanged: () => Promise<unknown>;
}> = ({ event, timezone, onChanged }) => {
  const [draft, setDraft] = useState<SlotDraft | null>(null);
  const [editing, setEditing] = useState<Slot | null>(null);
  const [deleting, setDeleting] = useState<Slot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intent = React.useRef(createWriteIntent());
  const [upsertSlot, { loading }] = useMutation<GqlUpsertShowAndSellSlotMutation>(UPSERT_SHOW_AND_SELL_SLOT);
  const [deleteSlot] = useMutation(DELETE_SHOW_AND_SELL_SLOT);

  const editable = acceptsSlotEdits(event.status);
  const slots = useMemo(() => sortSlots(event.slots), [event.slots]);
  const full = slots.length >= MAX_SLOTS_PER_EVENT;

  const close = () => {
    setDraft(null);
    setEditing(null);
    setDeleting(null);
    setError(null);
  };

  const openNew = () => {
    setEditing(null);
    setDraft({ ...NEW_SLOT, ...slotIntervalOf(event, timezone) });
  };

  const openEdit = (slot: Slot) => {
    setEditing(slot);
    setDraft({
      slotId: slot.slotId,
      version: slot.version,
      label: slot.label ?? '',
      ...slotIntervalOf(slot, timezone),
      capacity: String(slot.capacity),
    });
  };

  const save = async () => {
    if (draft === null) return;
    const parsed = parseSlotInterval(draft, event, timezone);
    if (parsed.error !== null) {
      setError(parsed.error);
      return;
    }
    const body = slotInput(event, editing, parsed);
    try {
      await upsertSlot({ variables: { input: withIdempotency(body, intent.current) } });
    } catch (mutationError) {
      setError(await reportWriteFailure(mutationError, 'Could not save this slot.', onChanged));
      return;
    }
    close();
    await refreshQuery(onChanged);
  };

  const remove = async (slot: Slot) => {
    const body = { showAndSellId: event.showAndSellId, slotId: slot.slotId, version: { expectedVersion: event.version } };
    try {
      await deleteSlot({ variables: { input: withIdempotency(body, intent.current) } });
    } catch (mutationError) {
      setError(await reportWriteFailure(mutationError, 'Could not delete this slot.', onChanged));
      return;
    }
    close();
    await refreshQuery(onChanged);
  };

  return (
    <Box sx={{ pt: 2 }}>
      <Alert severity="info" sx={{ mb: 2 }} data-testid="slot-note">
        A slot is any length of time inside the event, with its own capacity. Scouts may hold places in more than one
        slot as long as the times do not overlap — at this event or any other Show &amp; Sell.
      </Alert>
      {editable ? null : (
        <Alert severity="warning" sx={{ mb: 2 }} data-testid="slot-locked-note">
          The slot board closes when the event starts. Scouts already signed up keep their places; correct their records
          on the signup board instead.
        </Alert>
      )}
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap">
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          disabled={!editable || full}
          onClick={openNew}
          data-testid="add-slot"
        >
          Add a slot
        </Button>
        <Typography variant="body2" color="text.secondary" data-testid="slot-count">
          {slots.length} of {MAX_SLOTS_PER_EVENT} slots used
        </Typography>
        <SlotLimitNote full={full} editable={editable} />
      </Stack>
      <ErrorNote message={error} />
      <SlotTable
        slots={slots}
        timezone={timezone}
        editable={editable}
        onEdit={openEdit}
        onDelete={setDeleting}
      />
      <SlotFormDialog
        draft={draft}
        editing={editing}
        event={event}
        timezone={timezone}
        loading={loading}
        onChange={(changes) => setDraft((current) => ({ ...(current as SlotDraft), ...changes }))}
        onClose={close}
        onSave={() => void save()}
      />
      <SlotDeleteDialog pending={deleting} onClose={close} onDelete={(slot) => void remove(slot)} />
    </Box>
  );
};

/** Why the add button is dead, when it is dead because the event is full. */
const SlotLimitNote: React.FC<{ full: boolean; editable: boolean }> = ({ full, editable }) => {
  if (!full) return null;
  const text = editable
    ? `An event holds at most ${MAX_SLOTS_PER_EVENT} slots.`
    : `This event already holds ${MAX_SLOTS_PER_EVENT} slots, and its board is closed.`;
  return (
    <Typography variant="body2" color="warning.main" data-testid="slot-limit-note">
      {text}
    </Typography>
  );
};

const SlotTable: React.FC<{
  slots: Slot[];
  timezone: string;
  editable: boolean;
  onEdit: (slot: Slot) => void;
  onDelete: (slot: Slot) => void;
}> = ({ slots, timezone, editable, onEdit, onDelete }) => (
  <>
    <Table size="small" aria-label="Working slots">
      <TableHead>
        <TableRow>
          <TableCell>Slot</TableCell>
          <TableCell>When</TableCell>
          <TableCell>Length</TableCell>
          <TableCell>Capacity</TableCell>
          <TableCell>Scouts holding a place</TableCell>
          <TableCell aria-label="Actions" />
        </TableRow>
      </TableHead>
      <TableBody>
        {slots.map((slot) => (
          <SlotRow
            key={slot.slotId}
            slot={slot}
            timezone={timezone}
            editable={editable}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ))}
      </TableBody>
    </Table>
    {slots.length === 0 ? (
      <Typography color="text.secondary" data-testid="no-slots">
        This event has no working slots yet, so Scouts have nothing to sign up for.
      </Typography>
    ) : null}
  </>
);

const SlotRow: React.FC<{
  slot: Slot;
  timezone: string;
  editable: boolean;
  onEdit: (slot: Slot) => void;
  onDelete: (slot: Slot) => void;
}> = ({ slot, timezone, editable, onEdit, onDelete }) => {
  const name = slot.label || slot.slotId;
  return (
    <TableRow data-testid={`slot-row-${slot.slotId}`}>
      <TableCell data-testid={`slot-label-${slot.slotId}`}>{slot.label || '—'}</TableCell>
      <TableCell data-testid={`slot-interval-${slot.slotId}`}>
        {intervalLabel(slot.startAt, slot.endAt, timezone)}
      </TableCell>
      <TableCell data-testid={`slot-length-${slot.slotId}`}>
        {durationLabel(minutesBetween(slot.startAt, slot.endAt))}
      </TableCell>
      <TableCell data-testid={`slot-capacity-${slot.slotId}`}>{slot.capacity}</TableCell>
      <TableCell data-testid={`slot-held-${slot.slotId}`}>{slot.activeSignupCount}</TableCell>
      <TableCell>
        <Stack direction="row" spacing={0.5}>
          <IconButton
            size="small"
            aria-label={`Edit slot ${name}`}
            disabled={!editable}
            onClick={() => onEdit(slot)}
            data-testid={`edit-slot-${slot.slotId}`}
          >
            <EditIcon fontSize="small" />
          </IconButton>
          <SlotDeleteButton slot={slot} name={name} editable={editable} onDelete={onDelete} />
        </Stack>
      </TableCell>
    </TableRow>
  );
};

/**
 * Delete, or the reason deleting is not offered.
 *
 * A slot that holds Scouts is not deletable at any point in the event's life: the
 * server refuses it so a place a Scout holds cannot vanish, and the button says so
 * rather than waiting for the refusal (§3.3.3).
 */
const SlotDeleteButton: React.FC<{
  slot: Slot;
  name: string;
  editable: boolean;
  onDelete: (slot: Slot) => void;
}> = ({ slot, name, editable, onDelete }) => {
  if (slot.activeSignupCount > 0) {
    return (
      <Tooltip title="This slot holds Scouts. Cancel their signups instead of deleting the slot.">
        <span>
          <IconButton size="small" aria-label={`Delete slot ${name}`} disabled>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
    );
  }
  return (
    <IconButton
      size="small"
      aria-label={`Delete slot ${name}`}
      disabled={!editable}
      onClick={() => onDelete(slot)}
      data-testid={`delete-slot-${slot.slotId}`}
    >
      <DeleteIcon fontSize="small" />
    </IconButton>
  );
};

/** The write's body: the parsed slot, plus the versions the caller last read. */
function slotInput(
  event: Event,
  editing: Slot | null,
  parsed: { label: string | null; capacity: number | null; startAt: string | null; endAt: string | null },
) {
  const body: Record<string, unknown> = {
    showAndSellId: event.showAndSellId,
    label: parsed.label,
    startAt: parsed.startAt,
    endAt: parsed.endAt,
    capacity: parsed.capacity,
    version: { expectedVersion: event.version },
  };
  if (editing !== null) {
    body.slotId = editing.slotId;
    body.slotVersion = { expectedVersion: editing.version };
  }
  return body;
}

/**
 * The slot dialog: label, interval inside the event, and capacity.
 *
 * The interval boxes start at the event's own interval, so the common case — a
 * slot the length of the event — is a capacity entry and nothing else. Times are
 * entered in the Unit's zone, the same zone every other Show & Sell time is read in.
 */
const SlotFormDialog: React.FC<{
  draft: SlotDraft | null;
  editing: Slot | null;
  event: Event;
  timezone: string;
  loading: boolean;
  onChange: (changes: Partial<SlotDraft>) => void;
  onClose: () => void;
  onSave: () => void;
}> = ({ draft, editing, event, timezone, loading, onChange, onClose, onSave }) => (
  <Dialog open={draft !== null} onClose={onClose} fullWidth maxWidth="sm">
    {draft === null ? null : (
      <SlotFormFields
        draft={draft}
        editing={editing}
        event={event}
        timezone={timezone}
        loading={loading}
        onChange={onChange}
        onClose={onClose}
        onSave={onSave}
      />
    )}
  </Dialog>
);

/**
 * The dialog's content, rendered only once a draft exists.
 *
 * Mui keeps a closed `Dialog` mounted, so the boxes would have to survive a null
 * draft; rendering them only with a draft keeps every value plain and lets the
 * unparseable draft stay unrenderable rather than half-filled.
 */
const SlotFormFields: React.FC<{
  draft: SlotDraft;
  editing: Slot | null;
  event: Event;
  timezone: string;
  loading: boolean;
  onChange: (changes: Partial<SlotDraft>) => void;
  onClose: () => void;
  onSave: () => void;
}> = ({ draft, editing, event, timezone, loading, onChange, onClose, onSave }) => (
  <>
    <DialogTitle data-testid="slot-dialog-title">{slotDialogTitle(editing)}</DialogTitle>
    <DialogContent>
      <Stack spacing={2} sx={{ pt: 1 }}>
        <Typography color="text.secondary" data-testid="slot-dialog-event-window">
          The event runs {intervalLabel(event.startAt, event.endAt, timezone)}. A slot has to fit inside it, and its
          length can be anything.
        </Typography>
        <TextField
          label="Name (optional)"
          value={draft.label}
          onChange={(input) => onChange({ label: input.target.value })}
          helperText="What Scouts see on the signup screen, such as “Morning shift”."
          disabled={loading}
          inputProps={{ 'data-testid': 'slot-label-input' }}
          fullWidth
        />
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField
            label="Starts"
            type="datetime-local"
            value={draft.startAt}
            onChange={(input) => onChange({ startAt: input.target.value })}
            InputLabelProps={{ shrink: true }}
            disabled={loading}
            inputProps={{ 'data-testid': 'slot-start-input' }}
            fullWidth
          />
          <TextField
            label="Ends"
            type="datetime-local"
            value={draft.endAt}
            onChange={(input) => onChange({ endAt: input.target.value })}
            InputLabelProps={{ shrink: true }}
            disabled={loading}
            inputProps={{ 'data-testid': 'slot-end-input' }}
            fullWidth
          />
        </Stack>
        <TextField
          label="How many Scouts can hold a place"
          value={draft.capacity}
          onChange={(input) => onChange({ capacity: input.target.value })}
          helperText="Between 1 and 100. A capacity cannot go below the places the slot already holds."
          inputMode="numeric"
          disabled={loading}
          inputProps={{ 'data-testid': 'slot-capacity-input' }}
          fullWidth
        />
      </Stack>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} data-testid="slot-dialog-cancel">
        Cancel
      </Button>
      <Button variant="contained" onClick={onSave} disabled={loading} data-testid="submit-slot">
        {saveLabel(loading, editing)}
      </Button>
    </DialogActions>
  </>
);

function slotDialogTitle(editing: Slot | null): string {
  if (editing === null) return 'Add a slot';
  return `Edit ${editing.label || 'this slot'}`;
}

function saveLabel(loading: boolean, editing: Slot | null): string {
  if (loading) return 'Saving…';
  return editing === null ? 'Add slot' : 'Save slot';
}

const SlotDeleteDialog: React.FC<{
  pending: Slot | null;
  onClose: () => void;
  onDelete: (slot: Slot) => void;
}> = ({ pending, onClose, onDelete }) => (
  <Dialog open={pending !== null} onClose={onClose} maxWidth="xs" fullWidth>
    <DialogTitle data-testid="slot-delete-title">Delete this slot?</DialogTitle>
    <DialogContent>
      <Typography data-testid="slot-delete-body">
        {pending === null ? '' : `${pending.label || 'This slot'} holds no Scouts, so deleting it removes only the slot.`}
      </Typography>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} data-testid="slot-delete-cancel">
        Keep it
      </Button>
      <Button color="error" onClick={() => pending !== null && onDelete(pending)} data-testid="confirm-slot-delete">
        Delete slot
      </Button>
    </DialogActions>
  </Dialog>
);
