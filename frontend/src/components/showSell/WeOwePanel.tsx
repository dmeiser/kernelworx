/**
 * The We Owe board: every obligation this event created, and what the Unit
 * still owes and holds against it (§4.5.1, on §4.4 and §5.15).
 *
 * An obligation is the whole story of one line: what was entered, what the buyer
 * already holds, what the Unit reserved and what it still has to cover. The
 * panel is raw rows, never a projection — the buyer is a name and the numbers
 * are the server's own arithmetic, read back from the row after every write
 * (§4.5.2). The two actions are whole-obligation acts: reservation is a target
 * (a lower target releases the excess), and fulfillment is one recorded delivery
 * from one stock source, either partial or whole.
 *
 * A closed obligation is history: it offers no actions, and the close reason
 * says why it closed. A reservation that is released is the same write as one
 * that is added — the difference is the number.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
  IconButton,
} from '@mui/material';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import { FULFILL_WE_OWE, LIST_WE_OWE_OBLIGATIONS, SET_WE_OWE_RESERVATION } from '../../lib/graphql';
import {
  closeReasonLabel,
  fulfillmentPlan,
  fulfillmentSources,
  reservationPlan,
  weOweStatusLabel,
  formatCents,
  type FulfillmentPlan,
} from '../../lib/saleDesk';
import { SHOW_AND_SELL_PAGE_SIZE, describeShowAndSellFailure, formatInstant } from '../../lib/showSell';
import { createWriteIntent, isStaleVersionError, refreshQuery, type WriteIntent } from '../../lib/units';
import { ConnectionRestNotice } from '../ConnectionRestNotice';
import { ErrorNote } from '../ErrorAlert';
import { LoadingState } from '../LoadingState';
import { useCompleteConnection } from '../../hooks/useCompleteConnection';
import type {
  GqlFulfillWeOweMutation,
  GqlFulfillWeOweInput,
  GqlListWeOweObligationsQuery,
  GqlSetWeOweReservationInput,
  GqlSetWeOweReservationMutation,
  GqlShowAndSellAdminFieldsFragment,
  GqlWeOweFulfillmentSource,
  GqlWeOweObligationFieldsFragment,
  GqlWeOweStatus,
} from '../../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Obligation = GqlWeOweObligationFieldsFragment;
type StatusFilter = 'ALL' | 'OPEN' | 'CLOSED';

/** The filters the board offers, and the query argument each one names. */
const FILTER_OPTIONS: { value: StatusFilter; label: string; status?: GqlWeOweStatus }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'OPEN', label: 'Open', status: 'OPEN' },
  { value: 'CLOSED', label: 'Closed', status: 'CLOSED' },
];

function variablesOf(event: Event, status: GqlWeOweStatus | undefined) {
  return {
    unitCampaignId: event.unitCampaignId,
    showAndSellId: event.showAndSellId,
    status,
    page: { limit: SHOW_AND_SELL_PAGE_SIZE },
  };
}

/** The first source a draft may start from, read from the two numbers that decide it. */
function initialSourceOf(reservedQty: number, uncoveredQty: number): GqlWeOweFulfillmentSource {
  if (reservedQty > 0) return 'KERNEL_STOCK';
  if (uncoveredQty > 0) return 'EXTERNAL_COUNCIL';
  return 'KERNEL_STOCK';
}

/** The source the draft will send: the picked one while it is still on offer, else the first the obligation offers. */
function draftSourceOf(sources: readonly GqlWeOweFulfillmentSource[], source: GqlWeOweFulfillmentSource): GqlWeOweFulfillmentSource {
  return sources.includes(source) ? source : sources[0] ?? 'KERNEL_STOCK';
}

/** The sentence for the reservation button, in the words the screen already uses. */
function reservationButtonLabel(reservingNow: boolean, isRelease: boolean): string {
  if (reservingNow) return 'Saving…';
  if (isRelease) return 'Release the excess';
  return 'Reserve';
}

/** The target the hint describes, once it is a real and valid change; null when no hint is worth showing. */
function hintTargetOf(targetChanged: boolean, error: string | null, plannedTarget: number | null): number | null {
  return targetChanged && error === null ? plannedTarget : null;
}

/** The fulfillment sentence the screen shows: a typed quantity, never the empty-field state. */
function fulfillmentNoteOf(fulfillQty: string, fulfillmentOutcome: FulfillmentPlan): string | null {
  return fulfillQty.trim() !== '' ? fulfillmentOutcome.error : null;
}

/** The first refusal the browser can make, in the order the card reads it. */
function planErrorOf(reservationError: string | null, fulfillmentError: string | null, serverError: string | null): string | null {
  return reservationError ?? fulfillmentError ?? serverError;
}

/** The reservation write: the target, aimed at the obligation's current version. */
function reservationBodyOf(obligation: Obligation, planned: number, intent: WriteIntent): GqlSetWeOweReservationInput {
  return {
    weOweId: obligation.weOweId,
    targetReservedQty: planned,
    version: { expectedVersion: obligation.version },
    idempotency: {
      idempotencyKey: intent.keyFor({ weOweId: obligation.weOweId, targetReservedQty: planned, version: obligation.version }),
    },
  };
}

/** The fulfillment write: one recorded delivery from one source, aimed at the obligation's current version. */
function fulfillmentBodyOf(
  obligation: Obligation,
  quantity: number,
  source: GqlWeOweFulfillmentSource,
  intent: WriteIntent,
): GqlFulfillWeOweInput {
  return {
    weOweId: obligation.weOweId,
    quantity,
    source,
    version: { expectedVersion: obligation.version },
    idempotency: {
      idempotencyKey: intent.keyFor({ weOweId: obligation.weOweId, quantity, source, version: obligation.version }),
    },
  };
}

export const WeOwePanel: React.FC<{
  event: Event;
  timezone: string;
  onChanged: () => Promise<unknown>;
}> = ({ event, timezone, onChanged }) => {
  const [filter, setFilter] = useState<StatusFilter>('ALL');
  const status = useMemo(() => FILTER_OPTIONS.find((option) => option.value === filter)?.status, [filter]);
  const query = useQuery<GqlListWeOweObligationsQuery>(LIST_WE_OWE_OBLIGATIONS, {
    variables: variablesOf(event, status),
  });
  const all = useCompleteConnection<Obligation>(query.data?.weOweObligations, {
    query: LIST_WE_OWE_OBLIGATIONS,
    field: 'weOweObligations',
    limit: SHOW_AND_SELL_PAGE_SIZE,
    variables: variablesOf(event, status),
  });

  const openCount = useMemo(() => all.items.filter((obligation) => obligation.status === 'OPEN').length, [all.items]);
  const closedCount = all.items.length - openCount;

  return (
    <Box sx={{ pt: 2 }}>
      <Alert severity="info" sx={{ mb: 2 }} data-testid="we-owe-note">
        Every obligation this event created: what the buyer was promised, what the Unit reserved against it, and what is
        still uncovered. Reservation is a target — a lower number releases the excess. Fulfillment is one recorded
        delivery from one stock source.
      </Alert>
      <FilterBar openCount={openCount} closedCount={closedCount} filter={filter} onFilterChange={setFilter} />
      <BoardNotice loading={query.loading} hasData={Boolean(query.data)} rowCount={all.items.length} filter={filter} />
      <Stack spacing={2}>
        {all.items.map((obligation) => (
          <ObligationCard
            key={obligation.weOweId}
            obligation={obligation}
            timezone={timezone}
            onChanged={onChanged}
            onRefetch={async () => {
              await query.refetch();
            }}
          />
        ))}
      </Stack>
      <ConnectionRestNotice loading={all.loadingRest} failed={all.failedRest} />
    </Box>
  );
};

/** The counts and the status filter, in the one row that sets what the list shows. */
const FilterBar: React.FC<{
  openCount: number;
  closedCount: number;
  filter: StatusFilter;
  onFilterChange: (value: StatusFilter) => void;
}> = ({ openCount, closedCount, filter, onFilterChange }) => (
  <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
    <Typography variant="body2" color="text.secondary" data-testid="we-owe-counts">
      {openCount} open · {closedCount} closed
    </Typography>
    <Select
      size="small"
      label="Status"
      value={filter}
      displayEmpty
      onChange={(change) => onFilterChange(change.target.value as StatusFilter)}
      data-testid="we-owe-status-filter"
      inputProps={{ 'aria-label': 'Filter obligations by status' }}
      sx={{ minWidth: 130 }}
    >
      {FILTER_OPTIONS.map((option) => (
        <MenuItem key={option.value} value={option.value} data-testid={`we-owe-filter-${option.value}`}>
          {option.label}
        </MenuItem>
      ))}
    </Select>
  </Stack>
);

/** What the board says when it has no rows: the spinner on the first read, the empty sentence after it. */
const BoardNotice: React.FC<{ loading: boolean; hasData: boolean; rowCount: number; filter: StatusFilter }> = ({
  loading,
  hasData,
  rowCount,
  filter,
}) => (
  <>
    {loading && !hasData ? <LoadingState minHeight="120px" /> : null}
    {rowCount === 0 && !loading ? <EmptyNotice filter={filter} /> : null}
  </>
);

/** The empty board, in the filter's own words. */
const EmptyNotice: React.FC<{ filter: StatusFilter }> = ({ filter }) => (
  <Alert severity="info" data-testid="we-owe-empty" sx={{ mb: 2 }}>
    {filter === 'ALL' ? 'No obligations yet. Obligations are created when a sale takes an owed quantity.' : `No ${filter.toLowerCase()} obligations.`}
  </Alert>
);

/** The whole obligation, as the server reads it back. */
const ObligationCard: React.FC<{
  obligation: Obligation;
  timezone: string;
  onChanged: () => Promise<unknown>;
  onRefetch: () => Promise<unknown>;
}> = ({ obligation, timezone, onChanged, onRefetch }) => {
  const intent = useRef(createWriteIntent());
  const [target, setTarget] = useState<string>(String(obligation.reservedQty));
  const [fulfillQty, setFulfillQty] = useState<string>('');
  const [source, setSource] = useState<GqlWeOweFulfillmentSource>(() =>
    initialSourceOf(obligation.reservedQty, obligation.uncoveredQty),
  );
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState<'reservation' | 'fulfillment' | null>(null);
  const [reservation, { loading: reserving }] = useMutation<GqlSetWeOweReservationMutation>(SET_WE_OWE_RESERVATION);
  const [fulfill, { loading: fulfilling }] = useMutation<GqlFulfillWeOweMutation>(FULFILL_WE_OWE);

  // The rows come from the server after every write; the drafts are reset when the
  // obligation's own version moves, so a save never shows the pre-write numbers.
  useEffect(() => {
    setTarget(String(obligation.reservedQty));
    setFulfillQty('');
    setSource(initialSourceOf(obligation.reservedQty, obligation.uncoveredQty));
    setServerError(null);
  }, [obligation.version, obligation.weOweId, obligation.reservedQty, obligation.uncoveredQty, obligation.remainingQty]);

  const isOpen = obligation.status === 'OPEN';
  const sources = fulfillmentSources(obligation);
  const fulfillSource = draftSourceOf(sources, source);
  const reservationOutcome = reservationPlan(target, obligation);
  const fulfillmentOutcome = fulfillmentPlan(fulfillQty, fulfillSource, obligation);
  const plannedTarget = reservationOutcome.target;
  const targetChanged = target.trim() !== String(obligation.reservedQty);
  const fulfillmentNote = fulfillmentNoteOf(fulfillQty, fulfillmentOutcome);
  const error = planErrorOf(reservationOutcome.error, fulfillmentNote, serverError);

  const saveReservation = async () => {
    /* v8 ignore start -- both saves are disabled by this same sentence; the write-side check is what
       keeps a body the card never approved from being sent if the click ever reaches here */
    if (reservationOutcome.error !== null) {
      setServerError(reservationOutcome.error);
      return;
    }
    const planned = reservationOutcome.target;
    if (planned === null) return;
    /* v8 ignore stop */
    setSaving('reservation');
    setServerError(null);
    try {
      await reservation({ variables: { input: reservationBodyOf(obligation, planned, intent.current) } });
      // The intent is spent: a later, deliberately identical reservation is a new write.
      intent.current = createWriteIntent();
      await refreshQuery(onChanged);
      await refreshQuery(onRefetch);
    } catch (mutationError) {
      setServerError(describeShowAndSellFailure(mutationError, 'Could not save the reservation.'));
      if (isStaleVersionError(mutationError)) await refreshQuery(onChanged);
    } finally {
      setSaving(null);
    }
  };

  const saveFulfillment = async () => {
    /* v8 ignore start -- the button is disabled by this same sentence, and by an empty quantity; the
       write-side check is what keeps a movement the card never approved from being sent */
    if (fulfillmentOutcome.error !== null || fulfillmentOutcome.quantity === null) {
      setServerError(fulfillmentOutcome.error);
      return;
    }
    /* v8 ignore stop */
    setSaving('fulfillment');
    setServerError(null);
    try {
      await fulfill({
        variables: { input: fulfillmentBodyOf(obligation, fulfillmentOutcome.quantity, fulfillSource, intent.current) },
      });
      // The intent is spent: a later, deliberately identical fulfillment is a new write.
      intent.current = createWriteIntent();
      await refreshQuery(onChanged);
      await refreshQuery(onRefetch);
    } catch (mutationError) {
      setServerError(describeShowAndSellFailure(mutationError, 'Could not record the fulfillment.'));
      if (isStaleVersionError(mutationError)) await refreshQuery(onChanged);
    } finally {
      setSaving(null);
    }
  };

  const reservingNow = reserving || saving === 'reservation';
  const fulfillingNow = fulfilling || saving === 'fulfillment';

  return (
    <ObligationView
      obligation={obligation}
      timezone={timezone}
      isOpen={isOpen}
      sources={sources}
      target={target}
      onTargetChange={setTarget}
      fulfillQty={fulfillQty}
      onFulfillQtyChange={setFulfillQty}
      source={fulfillSource}
      onSourceChange={setSource}
      reservingNow={reservingNow}
      fulfillingNow={fulfillingNow}
      error={error}
      targetChanged={targetChanged}
      plannedTarget={plannedTarget}
      reservationIsRelease={reservationOutcome.isRelease}
      reservationTargetError={reservationOutcome.error}
      fulfillmentTargetError={fulfillmentOutcome.error}
      onSaveReservation={() => void saveReservation()}
      onSaveFulfillment={() => void saveFulfillment()}
    />
  );
};

/** The whole card: the header, the numbers, and the actions the obligation still offers. */
const ObligationView: React.FC<{
  obligation: Obligation;
  timezone: string;
  isOpen: boolean;
  sources: readonly GqlWeOweFulfillmentSource[];
  target: string;
  onTargetChange: (value: string) => void;
  fulfillQty: string;
  onFulfillQtyChange: (value: string) => void;
  source: GqlWeOweFulfillmentSource;
  onSourceChange: (value: GqlWeOweFulfillmentSource) => void;
  reservingNow: boolean;
  fulfillingNow: boolean;
  error: string | null;
  targetChanged: boolean;
  plannedTarget: number | null;
  reservationIsRelease: boolean;
  reservationTargetError: string | null;
  fulfillmentTargetError: string | null;
  onSaveReservation: () => void;
  onSaveFulfillment: () => void;
}> = ({
  obligation,
  timezone,
  isOpen,
  sources,
  target,
  onTargetChange,
  fulfillQty,
  onFulfillQtyChange,
  source,
  onSourceChange,
  reservingNow,
  fulfillingNow,
  error,
  targetChanged,
  plannedTarget,
  reservationIsRelease,
  reservationTargetError,
  fulfillmentTargetError,
  onSaveReservation,
  onSaveFulfillment,
}) => (
  <Card variant="outlined" data-testid={`we-owe-card-${obligation.weOweId}`}>
    <CardContent>
      <ObligationHeader obligation={obligation} />
      <ObligationMeta obligation={obligation} timezone={timezone} />
      {isOpen ? (
        <OpenObligation
          obligation={obligation}
          sources={sources}
          target={target}
          onTargetChange={onTargetChange}
          fulfillQty={fulfillQty}
          onFulfillQtyChange={onFulfillQtyChange}
          source={source}
          onSourceChange={onSourceChange}
          reservingNow={reservingNow}
          fulfillingNow={fulfillingNow}
          reservationTargetError={reservationTargetError}
          fulfillmentTargetError={fulfillmentTargetError}
          targetChanged={targetChanged}
          plannedTarget={plannedTarget}
          reservationIsRelease={reservationIsRelease}
          error={error}
          onSaveReservation={onSaveReservation}
          onSaveFulfillment={onSaveFulfillment}
        />
      ) : (
        <ClosedObligation obligation={obligation} />
      )}
    </CardContent>
  </Card>
);

/** What the obligation is, in the words the card shows. */
const ObligationHeader: React.FC<{ obligation: Obligation }> = ({ obligation }) => (
  <Stack direction="row" spacing={2} alignItems="baseline" flexWrap="wrap" useFlexGap>
    <Typography variant="subtitle2" data-testid={`we-owe-product-${obligation.weOweId}`}>
      {obligation.productNameSnapshot}
    </Typography>
    <Typography variant="body2" color="text.secondary" data-testid={`we-owe-buyer-${obligation.weOweId}`}>
      {obligation.buyerName}
    </Typography>
    <Typography variant="body2" color="text.secondary">
      {formatCents(obligation.valueCentsSnapshot)}
    </Typography>
    <Typography variant="body2" color="text.secondary" data-testid={`we-owe-status-${obligation.weOweId}`}>
      {weOweStatusLabel(obligation.status)}
      {obligation.closeReason ? ` · ${closeReasonLabel(obligation.closeReason)}` : ''}
    </Typography>
  </Stack>
);

/** The arithmetic behind the card: what was owed, held, and still uncovered. */
const ObligationMeta: React.FC<{ obligation: Obligation; timezone: string }> = ({ obligation, timezone }) => (
  <Typography variant="caption" color="text.secondary" data-testid={`we-owe-meta-${obligation.weOweId}`} sx={{ mt: 0.5, display: 'block' }}>
    Original {obligation.originalQty} · fulfilled {obligation.fulfilledQty} · reserved {obligation.reservedQty} · uncovered{' '}
    {obligation.uncoveredQty} · remaining {obligation.remainingQty}
    {obligation.createdAt ? ` · opened ${formatInstant(obligation.createdAt, timezone)}` : ''}
  </Typography>
);

/** What a closed obligation says: the history it is, and the one thing it is not. */
const ClosedObligation: React.FC<{ obligation: Obligation }> = ({ obligation }) => (
  <Typography variant="caption" color="text.secondary" data-testid={`we-owe-closed-${obligation.weOweId}`} sx={{ mt: 1, display: 'block' }}>
    Closed — the obligation is history. A mistake is corrected by a later fulfillment, never by rewriting this one.
  </Typography>
);

/** The release hint: what the target will do to the stock, in one sentence. */
const ReleaseHint: React.FC<{ obligation: Obligation; plannedTarget: number; isRelease: boolean }> = ({
  obligation,
  plannedTarget,
  isRelease,
}) => (
  <Typography variant="caption" color="text.secondary" data-testid={`we-owe-release-hint-${obligation.weOweId}`}>
    {isRelease
      ? `Releases ${obligation.reservedQty - plannedTarget} Kernel${obligation.reservedQty - plannedTarget === 1 ? '' : 's'} back to sellable stock.`
      : `Holds ${plannedTarget} Kernel${plannedTarget === 1 ? '' : 's'} against this obligation.`}
  </Typography>
);

/** The note under the fulfillment row when the obligation offers no source at all. */
const NoSourceNote: React.FC<{ obligation: Obligation }> = ({ obligation }) => (
  <Typography variant="caption" color="text.secondary" data-testid={`we-owe-no-source-${obligation.weOweId}`} sx={{ mt: 1, display: 'block' }}>
    No source: nothing is reserved and nothing is uncovered.
  </Typography>
);

/** The reservation row: the target, the save, and what the target will do. */
const ReservationRow: React.FC<{
  obligation: Obligation;
  target: string;
  onTargetChange: (value: string) => void;
  disabled: boolean;
  error: string | null;
  targetChanged: boolean;
  isRelease: boolean;
  plannedTarget: number | null;
  reservingNow: boolean;
  onSave: () => void;
}> = ({ obligation, target, onTargetChange, disabled, error, targetChanged, isRelease, plannedTarget, reservingNow, onSave }) => {
  const hintTarget = hintTargetOf(targetChanged, error, plannedTarget);
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mt: 2 }}>
      <TextField
        size="small"
        label="Reserve"
        inputMode="numeric"
        value={target}
        onChange={(change) => onTargetChange(change.target.value)}
        disabled={disabled}
        inputProps={{
          'aria-label': 'Reservation target',
          'data-testid': `we-owe-reserve-target-${obligation.weOweId}`,
          maxLength: 4,
        }}
        sx={{ width: 130 }}
      />
      <Button
        size="small"
        variant="outlined"
        onClick={onSave}
        disabled={disabled || error !== null || !targetChanged}
        data-testid={`we-owe-save-reservation-${obligation.weOweId}`}
      >
        {reservationButtonLabel(reservingNow, isRelease)}
      </Button>
      {hintTarget !== null ? <ReleaseHint obligation={obligation} plannedTarget={hintTarget} isRelease={isRelease} /> : null}
    </Stack>
  );
};

/** The fulfillment row: the quantity, the source, and the save. */
const FulfillmentRow: React.FC<{
  obligation: Obligation;
  sources: readonly GqlWeOweFulfillmentSource[];
  fulfillQty: string;
  onFulfillQtyChange: (value: string) => void;
  source: GqlWeOweFulfillmentSource;
  onSourceChange: (value: GqlWeOweFulfillmentSource) => void;
  disabled: boolean;
  error: string | null;
  fulfillingNow: boolean;
  onSave: () => void;
}> = ({ obligation, sources, fulfillQty, onFulfillQtyChange, source, onSourceChange, disabled, error, fulfillingNow, onSave }) => (
  <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mt: 1 }}>
    <TextField
      size="small"
      label="Fulfill"
      inputMode="numeric"
      value={fulfillQty}
      onChange={(change) => onFulfillQtyChange(change.target.value)}
      disabled={disabled}
      inputProps={{
        'aria-label': 'Quantity to fulfill',
        'data-testid': `we-owe-fulfill-qty-${obligation.weOweId}`,
        maxLength: 4,
      }}
      sx={{ width: 120 }}
    />
    <Select
      size="small"
      label="Source"
      value={source}
      displayEmpty
      onChange={(change) => onSourceChange(change.target.value as GqlWeOweFulfillmentSource)}
      disabled={disabled || sources.length === 0}
      data-testid={`we-owe-source-${obligation.weOweId}`}
      inputProps={{ 'aria-label': 'Fulfillment source' }}
      sx={{ minWidth: 220 }}
    >
      <MenuItem value="">Choose a source</MenuItem>
      {sources.map((entry) => (
        <MenuItem key={entry} value={entry} data-testid={`we-owe-source-${entry}-${obligation.weOweId}`}>
          {entry === 'KERNEL_STOCK' ? 'Kernel stock (reserved)' : 'External Council (uncovered)'}
        </MenuItem>
      ))}
    </Select>
    <Button
      size="small"
      onClick={onSave}
      disabled={disabled || error !== null || fulfillQty.trim() === ''}
      data-testid={`we-owe-fulfill-${obligation.weOweId}`}
    >
      {fulfillingNow ? 'Fulfilling…' : 'Record the fulfillment'}
    </Button>
  </Stack>
);

/** The actions the obligation still offers: reservation, fulfillment, the note, and the help. */
const OpenObligation: React.FC<{
  obligation: Obligation;
  sources: readonly GqlWeOweFulfillmentSource[];
  target: string;
  onTargetChange: (value: string) => void;
  fulfillQty: string;
  onFulfillQtyChange: (value: string) => void;
  source: GqlWeOweFulfillmentSource;
  onSourceChange: (value: GqlWeOweFulfillmentSource) => void;
  reservingNow: boolean;
  fulfillingNow: boolean;
  reservationTargetError: string | null;
  fulfillmentTargetError: string | null;
  targetChanged: boolean;
  plannedTarget: number | null;
  reservationIsRelease: boolean;
  error: string | null;
  onSaveReservation: () => void;
  onSaveFulfillment: () => void;
}> = ({
  obligation,
  sources,
  target,
  onTargetChange,
  fulfillQty,
  onFulfillQtyChange,
  source,
  onSourceChange,
  reservingNow,
  fulfillingNow,
  reservationTargetError,
  fulfillmentTargetError,
  targetChanged,
  plannedTarget,
  reservationIsRelease,
  error,
  onSaveReservation,
  onSaveFulfillment,
}) => (
  <>
    <ReservationRow
      obligation={obligation}
      target={target}
      onTargetChange={onTargetChange}
      disabled={reservingNow || fulfillingNow}
      error={reservationTargetError}
      targetChanged={targetChanged}
      isRelease={reservationIsRelease}
      plannedTarget={plannedTarget}
      reservingNow={reservingNow}
      onSave={onSaveReservation}
    />
    <FulfillmentRow
      obligation={obligation}
      sources={sources}
      fulfillQty={fulfillQty}
      onFulfillQtyChange={onFulfillQtyChange}
      source={source}
      onSourceChange={onSourceChange}
      disabled={fulfillingNow || reservingNow}
      error={fulfillmentTargetError}
      fulfillingNow={fulfillingNow}
      onSave={onSaveFulfillment}
    />
    {sources.length === 0 ? <NoSourceNote obligation={obligation} /> : null}
    <Tooltip title="KERNEL_STOCK may only reach what is reserved; EXTERNAL_COUNCIL may only reach what is not covered. A covered portion must be released first." describeChild>
      <IconButton size="small" aria-label="Why fulfillment is limited this way" data-testid={`we-owe-help-${obligation.weOweId}`}>
        <HelpOutlineIcon fontSize="small" />
      </IconButton>
    </Tooltip>
    {error ? <ErrorNote message={error} data-testid={`we-owe-error-${obligation.weOweId}`} /> : null}
  </>
);
