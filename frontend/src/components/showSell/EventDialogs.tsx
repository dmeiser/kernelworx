/**
 * The dialog half of the event screens: create, edit, cancel, and recreate
 * (Show & Sell §3.5.1).
 *
 * All four live in one file because they share the one thing that decides them —
 * the interval is chosen once and never again. `UpdateShowAndSellInput` carries no
 * `startAt`/`endAt` at all (SSE-07), so the edit dialog shows the times and cannot
 * change them, and the only way an admin can move an event is to cancel it and
 * create a new one. The recreate dialog is deliberately a *create* with prefilled
 * text: it writes a new row with a new id, and it carries no allocations and no
 * signups, because §6.1 refuses an automatic transfer of either.
 */

import React, { useEffect, useState } from 'react';
import { useMutation } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import {
  CANCEL_SHOW_AND_SELL,
  CREATE_SHOW_AND_SELL,
  UPDATE_SHOW_AND_SELL,
} from '../../lib/graphql';
import {
  MAX_CANCELLATION_REASON_LENGTH,
  acceptsEventEdits,
  describeShowAndSellFailure,
  intervalLabel,
  parseAddress,
  parseCancellationReason,
  parseInterval,
  parseLocationName,
  reportWriteFailure,
  splitMethodLabel,
  trimmedOrNull,
  utcToZonedWallClock,
  withIdempotency,
  type IntervalParse,
} from '../../lib/showSell';
import { createWriteIntent, refreshQuery } from '../../lib/units';
import { ErrorNote } from '../ErrorAlert';
import type {
  GqlCreateShowAndSellMutation,
  GqlShowAndSellAdminFieldsFragment,
  GqlSplitMethod,
} from '../../types/graphql-generated';

/** What the four dialogs are asked to do, in the shape the pages hold. */
export type PendingEventAction =
  | { kind: 'create' }
  | { kind: 'recreate'; from: GqlShowAndSellAdminFieldsFragment }
  | { kind: 'edit'; event: GqlShowAndSellAdminFieldsFragment }
  | { kind: 'cancel'; event: GqlShowAndSellAdminFieldsFragment }
  | null;

/** The Unit facts the forms need: the zone times are entered in, and the split to inherit. */
export interface EventUnitContext {
  unitCampaignId: string;
  timezone: string;
  splitDefault: GqlSplitMethod;
  campaignName: string;
}

/** What a cancellation undid, in the counts the server answered. */
export interface CancelSummary {
  locationName: string;
  released: number;
  signups: number;
}

interface FormValues {
  locationName: string;
  address: string;
  startAt: string;
  endAt: string;
  splitMethod: GqlSplitMethod | '';
  weOweEnabled: boolean;
}

/**
 * The three dialogs one Show & Sell screen can open, wired to one pending action.
 *
 * A single `pending` value decides which dialog is mounted, and each dialog is
 * handed null unless the pending action is exactly the kind it edits — so a stale
 * action cannot leave two dialogs open over the same event.
 */
export const EventActionDialogs: React.FC<{
  pending: PendingEventAction;
  context: EventUnitContext;
  onClose: () => void;
  onRefresh: () => Promise<unknown> | void;
  onCancelled: (summary: CancelSummary) => void;
  /**
   * Looks the event up in the page's own refreshed reads, by id.
   *
   * A dialog is opened for a row the admin was looking at, but that row can move
   * while the dialog is open — another Kernel edits it, or this same write is
   * refused as stale and the page re-reads it. The pending action carries the row as
   * it was when the button was pressed, so a retry from that object would resend the
   * version the server already refused and be refused again forever. Every edit and
   * cancel dialog therefore works from whatever this resolver answers now, which is
   * the refreshed row the page is holding.
   */
  liveEvent?: (showAndSellId: string) => GqlShowAndSellAdminFieldsFragment | null;
}> = ({ pending, context, onClose, onRefresh, onCancelled, liveEvent }) => {
  const current = refreshedPending(pending, liveEvent);
  return (
    <>
      <EventCreateDialog pending={createPending(current)} unit={context} onClose={onClose} onCreated={onRefresh} />
      <EventEditDialog pending={editPending(current)} unit={context} onClose={onClose} onSaved={onRefresh} />
      <EventCancelDialog
        pending={cancelPending(current)}
        unit={context}
        onClose={onClose}
        onRefresh={onRefresh}
        onCancel={(summary) => {
          onCancelled(summary);
          return onRefresh();
        }}
      />
    </>
  );
};

/**
 * The pending action, addressed to the row as the page reads it now.
 *
 * A create and a recreate have no row to refresh, so they pass through: a recreate
 * is a new event, and the cancelled one it was opened from is history by design.
 */
function refreshedPending(
  pending: PendingEventAction,
  liveEvent?: (id: string) => GqlShowAndSellAdminFieldsFragment | null,
): PendingEventAction {
  if (!pending || (pending.kind !== 'edit' && pending.kind !== 'cancel')) return pending;
  const fresh = movedRow(pending.event, liveEvent);
  return fresh === null ? pending : { ...pending, event: fresh };
}

/**
 * The row the page holds now, when it is not the one the button was pressed on.
 *
 * `null` means nothing moved: the page has no newer answer than the captured row, so
 * the dialog keeps what it was given rather than addressing a write at a version it
 * never read.
 */
function movedRow(
  event: GqlShowAndSellAdminFieldsFragment,
  liveEvent?: (id: string) => GqlShowAndSellAdminFieldsFragment | null,
): GqlShowAndSellAdminFieldsFragment | null {
  if (!liveEvent) return null;
  const fresh = liveEvent(event.showAndSellId);
  return fresh === null || fresh === event ? null : fresh;
}

function createPending(pending: PendingEventAction) {
  if (pending?.kind === 'create' || pending?.kind === 'recreate') return pending;
  return null;
}

function editPending(pending: PendingEventAction) {
  if (pending?.kind === 'edit') return pending;
  return null;
}

function cancelPending(pending: PendingEventAction) {
  if (pending?.kind === 'cancel') return pending;
  return null;
}

/** The event a dialog was opened for, or null while it is closed. */
function eventOf(pending: { event: GqlShowAndSellAdminFieldsFragment } | null): GqlShowAndSellAdminFieldsFragment | null {
  return pending?.event ?? null;
}

/** The first refusal in the order the form reads its fields. */
function firstFieldError(...errors: (string | null)[]): string | null {
  return errors.find((error) => error !== null) ?? null;
}

/** The form a create starts with: a cancelled event's words, never its settings or times. */
function formSeedFor(
  pending: Extract<PendingEventAction, { kind: 'create' } | { kind: 'recreate' }> | null,
): FormValues {
  if (pending?.kind !== 'recreate') return emptyForm();
  const words = pending.from;
  // Only the words carry over. The split and We Owe of a replacement event are a new
  // decision, and copying them would leave a new event quietly running the settings of
  // one that was cancelled — while its own first save looks like it changed nothing
  // because the form already held those values (§6.1).
  return {
    ...emptyForm(),
    locationName: words.locationName,
    address: words.address ?? '',
  };
}

/** An empty create form: We Owe off, split inherited, no times. */
function emptyForm(): FormValues {
  return { locationName: '', address: '', startAt: '', endAt: '', splitMethod: '', weOweEnabled: false };
}

/**
 * The text an edit form starts with.
 *
 * `splitMethod` is seeded with the event's own value, so the form cannot silently
 * inherit a different default than the event already has.
 */
function formOf(event: GqlShowAndSellAdminFieldsFragment, timezone: string): FormValues {
  return {
    locationName: event.locationName,
    address: event.address ?? '',
    startAt: utcToZonedWallClock(event.startAt, timezone),
    endAt: utcToZonedWallClock(event.endAt, timezone),
    splitMethod: event.splitMethod,
    weOweEnabled: event.weOweEnabled,
  };
}

/**
 * One dialog for create and recreate.
 *
 * Recreate prefills the cancelled event's words but never its times: a prefilled
 * interval would invite an admin to press Save and rebuild the event they just
 * cancelled at the moment it was cancelled for. The copy says what is not carried
 * over, because an admin who expects the Scouts to move with the event will
 * otherwise discover it at the slot, not here (SSE-07).
 */
export const EventCreateDialog: React.FC<{
  pending: Extract<PendingEventAction, { kind: 'create' } | { kind: 'recreate' }> | null;
  unit: EventUnitContext;
  onClose: () => void;
  onCreated: () => Promise<unknown> | void;
}> = ({ pending, unit, onClose, onCreated }) => {
  const [form, setForm] = useState<FormValues>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const intent = React.useRef(createWriteIntent());
  const [createEvent, { loading }] = useMutation<GqlCreateShowAndSellMutation>(CREATE_SHOW_AND_SELL);

  useEffect(() => {
    setForm(formSeedFor(pending));
    setError(null);
    setFormError(null);
    // A fresh write intent for every time this dialog is opened. The dialog stays
    // mounted while the screen is up, so an intent kept for the mount's lifetime
    // would give a second, deliberate create the same idempotency key as the first:
    // an admin who creates one event and then opens the dialog again to create a
    // second one with the same words and times would get the first event back, not a
    // new id. Within one attempt a retry still replays its own write.
    intent.current = createWriteIntent();
  }, [pending]);

  const save = async () => {
    const location = parseLocationName(form.locationName);
    const address = parseAddress(form.address);
    const interval = parseInterval(form.startAt, form.endAt, unit.timezone);
    const fieldError = firstFieldError(location, address, interval.error);
    if (fieldError !== null) {
      setFormError(fieldError);
      return;
    }
    setFormError(null);
    const body = createBody(unit, form, interval);
    try {
      await createEvent({ variables: { input: withIdempotency(body, intent.current) } });
    } catch (mutationError) {
      setError(describeShowAndSellFailure(mutationError, 'Could not create the event.'));
      return;
    }
    onClose();
    await refreshQuery(onCreated);
  };

  return (
    <Dialog open={pending !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle data-testid="create-event-title">{createTitle(pending)}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <RecreateNote pending={pending} />
          <Typography color="text.secondary" data-testid="event-timezone-note">
            Times are entered in {unit.timezone}, the zone this Unit runs in. They are fixed once the event is created:
            to change them, cancel this event and create another.
          </Typography>
          <EventFormFields
            form={form}
            unit={unit}
            timesEditable
            disabled={loading}
            onChange={(changes) => setForm((current) => ({ ...current, ...changes }))}
          />
          <ErrorNote message={formError} />
          <ErrorNote message={error} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} data-testid="cancel-create-event">
          Cancel
        </Button>
        <Button variant="contained" onClick={() => void save()} disabled={loading} data-testid="submit-create-event">
          {loading ? 'Creating…' : 'Create event'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

/** What the dialog is called: a replacement event is a new event, not an undo. */
function createTitle(pending: Extract<PendingEventAction, { kind: 'create' } | { kind: 'recreate' }> | null): string {
  return pending?.kind === 'recreate' ? 'Create the replacement event' : 'New Show & Sell';
}

/**
 * What recreation does not carry over.
 *
 * The cancelled event keeps its record and everything it touched; the new event
 * starts with nothing. Saying it here is cheaper than an admin learning it at the
 * allocation editor (SSE-07).
 */
const RecreateNote: React.FC<{
  pending: Extract<PendingEventAction, { kind: 'create' } | { kind: 'recreate' }> | null;
}> = ({ pending }) => {
  if (pending?.kind !== 'recreate') return null;
  return (
    <Alert severity="info" data-testid="recreate-note">
      This creates a new event with its own id: “{pending.from.locationName}” stays cancelled with its audit record, and
      nothing — stock, slots, or Scouts — moves to the new one. You re-assign stock and re-open signups yourself.
    </Alert>
  );
};

/** The create write: the form's words, the parsed interval, and the Unit it belongs to. */
function createBody(unit: EventUnitContext, form: FormValues, interval: IntervalParse) {
  return {
    unitCampaignId: unit.unitCampaignId,
    locationName: form.locationName.trim(),
    address: trimmedOrNull(form.address),
    startAt: interval.startAt as string,
    endAt: interval.endAt as string,
    splitMethod: splitOverride(form.splitMethod),
    weOweEnabled: form.weOweEnabled,
  };
}

/** An empty split choice inherits the Unit default, which is what `null` means here. */
function splitOverride(value: GqlSplitMethod | ''): GqlSplitMethod | null {
  return value === '' ? null : value;
}

/** The shared field set: location, address, times, split override, We Owe. */
const EventFormFields: React.FC<{
  form: FormValues;
  unit: EventUnitContext;
  timesEditable: boolean;
  disabled: boolean;
  onChange: (changes: Partial<FormValues>) => void;
}> = ({ form, unit, timesEditable, disabled, onChange }) => (
  <>
    <TextField
      label="Where is it"
      value={form.locationName}
      onChange={(event) => onChange({ locationName: event.target.value })}
      helperText="Required, short: the name a Scout reads, such as “Kroger on Monroe”."
      disabled={disabled}
      inputProps={{ 'data-testid': 'event-location-input' }}
      fullWidth
    />
    <TextField
      label="Address"
      value={form.address}
      onChange={(event) => onChange({ address: event.target.value })}
      helperText="Optional. Shown on the signup screen and on a downloaded calendar invite."
      disabled={disabled}
      multiline
      minRows={2}
      inputProps={{ 'data-testid': 'event-address-input' }}
      fullWidth
    />
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
      <TextField
        label="Starts"
        type="datetime-local"
        value={form.startAt}
        onChange={(event) => onChange({ startAt: event.target.value })}
        disabled={disabled || !timesEditable}
        InputLabelProps={{ shrink: true }}
        inputProps={{ 'data-testid': 'event-start-input' }}
        fullWidth
      />
      <TextField
        label="Ends"
        type="datetime-local"
        value={form.endAt}
        onChange={(event) => onChange({ endAt: event.target.value })}
        disabled={disabled || !timesEditable}
        InputLabelProps={{ shrink: true }}
        inputProps={{ 'data-testid': 'event-end-input' }}
        fullWidth
      />
    </Stack>
    {!timesEditable ? (
      <Alert severity="info" data-testid="times-immutable-note">
        These times are read-only. An event’s interval is fixed when it is created, and the edit write cannot carry a new
        one — cancel the event and create a new one to move it.
      </Alert>
    ) : null}
    <TextField
      select
      label="Earnings split"
      value={form.splitMethod}
      onChange={(event) => onChange({ splitMethod: event.target.value as GqlSplitMethod | '' })}
      disabled={disabled}
      data-testid="event-split-select"
      helperText={`This Unit splits ${splitMethodLabel(unit.splitDefault)}. Overriding here changes this event only.`}
    >
      <MenuItem value="">Inherit the Unit default</MenuItem>
      <MenuItem value="EQUAL">Split equally</MenuItem>
      <MenuItem value="TIME_WORKED">Split by worked time</MenuItem>
    </TextField>
    <FormControlLabel
      control={
        <Switch
          checked={form.weOweEnabled}
          onChange={(event) => onChange({ weOweEnabled: event.target.checked })}
          disabled={disabled}
          data-testid="event-we-owe-switch"
          aria-label="Offer We Owe at this event"
        />
      }
      label="Offer We Owe at this event"
    />
    <Typography variant="body2" color="text.secondary" data-testid="we-owe-note">
      We Owe is off unless a Kernel turns it on for this event. Turning it off again is refused while an obligation is
      still open.
    </Typography>
  </>
);

/**
 * The edit dialog: location, address, split override, We Owe.
 *
 * The times are displayed and locked. The server refuses a `startAt` in the input
 * outright (EVT-M-02-01) rather than ignoring it, so a screen that offered the
 * field would be offering a guaranteed refusal.
 */
export const EventEditDialog: React.FC<{
  pending: Extract<PendingEventAction, { kind: 'edit' }> | null;
  unit: EventUnitContext;
  onClose: () => void;
  onSaved: () => Promise<unknown> | void;
}> = ({ pending, unit, onClose, onSaved }) => {
  const event = eventOf(pending);
  const [form, setForm] = useState<FormValues>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  // Which event this dialog has been seeded for, so a re-read of the same event does
  // not re-seed the form. See the effect below.
  const seededFor = React.useRef<string | null>(null);
  const intent = React.useRef(createWriteIntent());
  const [updateEvent, { loading }] = useMutation(UPDATE_SHOW_AND_SELL);

  useEffect(() => {
    if (event === null) {
      seededFor.current = null;
      return;
    }
    // Seeded once per event, not once per read: a stale-row reload hands this dialog a
    // new object for the same event, and re-seeding then would throw away what the
    // admin typed and the refusal sentence they are reading. The version the next write
    // carries comes from the live object, so the retry is still addressed to the row as
    // it is now.
    if (seededFor.current === event.showAndSellId) return;
    seededFor.current = event.showAndSellId;
    setForm(formOf(event, unit.timezone));
    setError(null);
    setFormError(null);
    intent.current = createWriteIntent();
  }, [event, unit.timezone]);

  const save = async () => {
    if (event === null) return;
    const fieldError = firstFieldError(parseLocationName(form.locationName), parseAddress(form.address));
    if (fieldError !== null) {
      setFormError(fieldError);
      return;
    }
    setFormError(null);
    const body = editBody(unit, event, form);
    try {
      await updateEvent({ variables: { input: withIdempotency(body, intent.current) } });
    } catch (mutationError) {
      // A stale version means the row the form read is not the row there is: say
      // so and reload the read behind the dialog before the admin tries again.
      setError(await reportWriteFailure(mutationError, 'Could not save the event.', onSaved));
      return;
    }
    onClose();
    await refreshQuery(onSaved);
  };

  return (
    <Dialog open={pending !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle data-testid="edit-event-title">Edit this Show & Sell</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <EditEventTimes event={event} timezone={unit.timezone} />
          <EventFormFields
            form={form}
            unit={unit}
            timesEditable={false}
            disabled={loading || !editAccepts(event)}
            onChange={(changes) => setForm((current) => ({ ...current, ...changes }))}
          />
          <ErrorNote message={formError} />
          <ErrorNote message={error} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} data-testid="cancel-edit-event">
          Close
        </Button>
        <Button variant="contained" onClick={() => void save()} disabled={loading} data-testid="submit-edit-event">
          {loading ? 'Saving…' : 'Save changes'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

/** The interval the cancel dialog names, so the admin is certain which event this is. */
const CancelEventWhen: React.FC<{ event: GqlShowAndSellAdminFieldsFragment | null; timezone: string }> = ({
  event,
  timezone,
}) => (
  <Typography sx={{ mt: 2 }} data-testid="cancel-event-when">
    {event === null ? '' : intervalLabel(event.startAt, event.endAt, timezone)}
  </Typography>
);

/** The reason field's helper, which becomes the refusal once there is one. */
function reasonHelp(reasonError: string | null): string {
  if (reasonError !== null) return reasonError;
  return `Required, and kept in the audit record. At most ${MAX_CANCELLATION_REASON_LENGTH} characters.`;
}

/** What the cancellation undid, in the numbers the list page reports back. */
function cancelSummary(
  event: GqlShowAndSellAdminFieldsFragment,
  result: unknown,
): { locationName: string; released: number; signups: number } {
  const payload = (
    result as { data?: { cancelShowAndSell?: { releasedAllocations?: unknown[]; cancelledSignups?: unknown[] } } }
  ).data?.cancelShowAndSell;
  return {
    locationName: event.locationName,
    released: countOf(payload?.releasedAllocations),
    signups: countOf(payload?.cancelledSignups),
  };
}

/** How many things the cancellation names, or zero when it named none. */
function countOf(items: unknown[] | undefined): number {
  return items?.length ?? 0;
}

/** The locked interval an edit dialog shows but cannot change. */
const EditEventTimes: React.FC<{
  event: GqlShowAndSellAdminFieldsFragment | null;
  timezone: string;
}> = ({ event, timezone }) => {
  if (event === null) return null;
  return <Typography data-testid="edit-event-times">{intervalLabel(event.startAt, event.endAt, timezone)}</Typography>;
};

/** The edit write: everything except the times, which the input cannot carry (EVT-M-02-01). */
function editBody(unit: EventUnitContext, event: GqlShowAndSellAdminFieldsFragment, form: FormValues) {
  return {
    showAndSellId: event.showAndSellId,
    locationName: form.locationName.trim(),
    // `null` clears the address; leaving the key out would leave it alone.
    address: trimmedOrNull(form.address),
    splitMethod: editSplitMethod(form.splitMethod, unit.splitDefault),
    weOweEnabled: form.weOweEnabled,
    version: { expectedVersion: event.version },
  };
}

/**
 * The split an edit write carries.
 *
 * `UpdateShowAndSellInput.splitMethod` is an optional field, and the resolver reads a
 * null as "the caller wants nothing changed" (`_event_update_changes` in
 * `src/handlers/unit_operations.py`). So the edit form's *Inherit the Unit default*
 * cannot be sent as null: that would report a saved change while the event kept the
 * split it already had. The choice is resolved to the Unit's current default, which is
 * what inheriting means, and the write then says so.
 */
function editSplitMethod(value: GqlSplitMethod | '', unitDefault: GqlSplitMethod): GqlSplitMethod {
  return value === '' ? unitDefault : value;
}

/** Whether this event's state still accepts the edit write. */
function editAccepts(event: GqlShowAndSellAdminFieldsFragment | null): boolean {
  if (event === null) return false;
  return acceptsEventEdits(event.status);
}

/**
 * The cancellation dialog: reason required, consequences stated, version carried.
 *
 * Cancellation is atomic on the server — the event goes CANCELLED, every open
 * allocation releases its remainder, and every signup and its commitment go
 * CANCELLED (SSE-05). Saying so here is what stops an admin treating it as an
 * undo button for a mistake at the slot. An event that has started is refused
 * server-side (SSE-06), and the button that would ask for it is not offered.
 */
export const EventCancelDialog: React.FC<{
  pending: Extract<PendingEventAction, { kind: 'cancel' }> | null;
  unit: EventUnitContext;
  onClose: () => void;
  onCancel: (summary: CancelSummary) => Promise<unknown> | void;
  onRefresh: () => Promise<unknown> | void;
}> = ({ pending, unit, onClose, onCancel, onRefresh }) => {
  const event = eventOf(pending);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [reasonError, setReasonError] = useState<string | null>(null);
  // One key per cancellation intent: a retry of the same reason replays the write,
  // and an admin who changes the words after a failure is making a different write.
  const intent = React.useRef(createWriteIntent());
  // Which event this dialog was seeded for, so a reload of the same event keeps the
  // reason that was typed and the sentence that explains the refusal.
  const seededFor = React.useRef<string | null>(null);
  const [cancelEvent, { loading }] = useMutation(CANCEL_SHOW_AND_SELL);

  useEffect(() => {
    if (event === null) {
      seededFor.current = null;
      return;
    }
    if (seededFor.current === event.showAndSellId) return;
    seededFor.current = event.showAndSellId;
    setReason('');
    setError(null);
    setReasonError(null);
    intent.current = createWriteIntent();
  }, [event]);

  const confirm = async () => {
    if (event === null) return;
    const invalid = parseCancellationReason(reason);
    if (invalid !== null) {
      setReasonError(invalid);
      return;
    }
    setReasonError(null);
    const body = {
      showAndSellId: event.showAndSellId,
      reason: reason.trim(),
      version: { expectedVersion: event.version },
    };
    try {
      const result = await cancelEvent({ variables: { input: withIdempotency(body, intent.current) } });
      onClose();
      await refreshQuery(() => onCancel(cancelSummary(event, result)));
    } catch (mutationError) {
      setError(await reportWriteFailure(mutationError, 'Could not cancel the event.', onRefresh));
    }
  };

  return (
    <Dialog open={pending !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle data-testid="cancel-event-title">Cancel this Show & Sell?</DialogTitle>
      <DialogContent>
        <Box sx={{ pt: 1 }}>
          <Alert severity="warning" data-testid="cancel-consequence">
            Cancelling releases every stock allocation this event still holds back to the campaign, and cancels every
            Scout signup and calendar commitment with it. Nothing is deleted: the event keeps its reason and who
            cancelled it, and sales and obligations stay as history. This cannot be undone.
          </Alert>
          <CancelEventWhen event={event} timezone={unit.timezone} />
          <TextField
            sx={{ mt: 2 }}
            label="Why is it being cancelled"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            error={reasonError !== null}
            helperText={reasonHelp(reasonError)}
            disabled={loading}
            multiline
            minRows={3}
            inputProps={{ 'data-testid': 'cancellation-reason-input' }}
            fullWidth
          />
          <ErrorNote message={error} />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} data-testid="keep-event">
          Keep the event
        </Button>
        <Button variant="contained" color="error" onClick={() => void confirm()} disabled={loading} data-testid="submit-cancel-event">
          {loading ? 'Cancelling…' : 'Cancel the event'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
