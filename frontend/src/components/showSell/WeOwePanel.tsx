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
} from '../../lib/saleDesk';
import { SHOW_AND_SELL_PAGE_SIZE, describeShowAndSellFailure, formatInstant } from '../../lib/showSell';
import { createWriteIntent, isStaleVersionError, refreshQuery } from '../../lib/units';
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

export const WeOwePanel: React.FC<{
  event: Event;
  timezone: string;
  onChanged: () => Promise<unknown>;
}> = ({ event, timezone, onChanged }) => {
  const [filter, setFilter] = useState<StatusFilter>('ALL');
  const status = FILTER_OPTIONS.find((option) => option.value === filter)?.status;
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
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        <Typography variant="body2" color="text.secondary" data-testid="we-owe-counts">
          {openCount} open · {closedCount} closed
        </Typography>
        <Select
          size="small"
          label="Status"
          value={filter}
          displayEmpty
          onChange={(change) => setFilter(change.target.value as StatusFilter)}
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
      {query.loading && !query.data ? <LoadingState minHeight="120px" /> : null}
      {all.items.length === 0 && !query.loading ? (
        <Alert severity="info" data-testid="we-owe-empty" sx={{ mb: 2 }}>
          {filter === 'ALL' ? 'No obligations yet. Obligations are created when a sale takes an owed quantity.' : `No ${filter.toLowerCase()} obligations.`}
        </Alert>
      ) : null}
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

const ObligationCard: React.FC<{
  obligation: Obligation;
  timezone: string;
  onChanged: () => Promise<unknown>;
  onRefetch: () => Promise<unknown>;
}> = ({ obligation, timezone, onChanged, onRefetch }) => {
  const intent = useRef(createWriteIntent());
  const [target, setTarget] = useState<string>(String(obligation.reservedQty));
  const [fulfillQty, setFulfillQty] = useState<string>('');
  const [source, setSource] = useState<GqlWeOweFulfillmentSource>(fulfillmentSources(obligation)[0] ?? 'KERNEL_STOCK');
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState<'reservation' | 'fulfillment' | null>(null);
  const [reservation, { loading: reserving }] = useMutation<GqlSetWeOweReservationMutation>(SET_WE_OWE_RESERVATION);
  const [fulfill, { loading: fulfilling }] = useMutation<GqlFulfillWeOweMutation>(FULFILL_WE_OWE);

  // The rows come from the server after every write; the drafts are reset when the
  // obligation's own version moves, so a save never shows the pre-write numbers.
  useEffect(() => {
    setTarget(String(obligation.reservedQty));
    setFulfillQty('');
    setSource(fulfillmentSources(obligation)[0] ?? 'KERNEL_STOCK');
    setServerError(null);
  }, [obligation.version, obligation.weOweId, obligation.reservedQty, obligation.uncoveredQty, obligation.remainingQty]);

  const isOpen = obligation.status === 'OPEN';
  const sources = fulfillmentSources(obligation);
  const reservationPlanOutcome = reservationPlan(target, obligation);
  const fulfillmentOutcome = fulfillmentPlan(fulfillQty, source, obligation);
  const draftSource = sources.includes(source) ? source : sources[0];
  const plannedTarget = reservationPlanOutcome.target;
  const targetChanged = target.trim() !== String(obligation.reservedQty);

  // A refusal the browser can make is the first thing the screen says; a server
  // failure only shows once the browser is happy, so a stale sentence never masks
  // a typed-in mistake. An empty fulfillment field is not a mistake — it is the
  // state the card opens in, so it produces no note; the button stays disabled.
  const fulfillmentError = fulfillQty.trim() !== '' ? fulfillmentOutcome.error : null;
  const planError = reservationPlanOutcome.error ?? fulfillmentError;
  const error = planError ?? serverError;

  const saveReservation = async () => {
    if (reservationPlanOutcome.error !== null) {
      setServerError(reservationPlanOutcome.error);
      return;
    }
    const planned = reservationPlanOutcome.target;
    if (planned === null) return;
    setSaving('reservation');
    setServerError(null);
    const body: GqlSetWeOweReservationInput = {
      weOweId: obligation.weOweId,
      targetReservedQty: planned,
      version: { expectedVersion: obligation.version },
      idempotency: {
        idempotencyKey: intent.current.keyFor({ weOweId: obligation.weOweId, targetReservedQty: planned, version: obligation.version }),
      },
    };
    try {
      await reservation({ variables: { input: body } });
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
    if (fulfillmentOutcome.error !== null || fulfillmentOutcome.quantity === null) {
      setServerError(fulfillmentOutcome.error);
      return;
    }
    setSaving('fulfillment');
    setServerError(null);
    const body: GqlFulfillWeOweInput = {
      weOweId: obligation.weOweId,
      quantity: fulfillmentOutcome.quantity,
      source: draftSource ?? 'KERNEL_STOCK',
      version: { expectedVersion: obligation.version },
      idempotency: {
        idempotencyKey: intent.current.keyFor({ weOweId: obligation.weOweId, quantity: fulfillmentOutcome.quantity, source: draftSource ?? 'KERNEL_STOCK', version: obligation.version }),
      },
    };
    try {
      await fulfill({ variables: { input: body } });
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
    <Card variant="outlined" data-testid={`we-owe-card-${obligation.weOweId}`}>
      <CardContent>
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
        <Typography variant="caption" color="text.secondary" data-testid={`we-owe-meta-${obligation.weOweId}`} sx={{ mt: 0.5, display: 'block' }}>
          Original {obligation.originalQty} · fulfilled {obligation.fulfilledQty} · reserved {obligation.reservedQty} · uncovered{' '}
          {obligation.uncoveredQty} · remaining {obligation.remainingQty}
          {obligation.createdAt ? ` · opened ${formatInstant(obligation.createdAt, timezone)}` : ''}
        </Typography>
        {isOpen ? (
          <>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mt: 2 }}>
              <TextField
                size="small"
                label="Reserve"
                inputMode="numeric"
                value={target}
                onChange={(change) => setTarget(change.target.value)}
                disabled={reservingNow || fulfillingNow}
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
                onClick={() => void saveReservation()}
                disabled={reservingNow || reservationPlanOutcome.error !== null || !targetChanged}
                data-testid={`we-owe-save-reservation-${obligation.weOweId}`}
              >
                {reservingNow ? 'Saving…' : reservationPlanOutcome.isRelease ? 'Release the excess' : 'Reserve'}
              </Button>
              {targetChanged && reservationPlanOutcome.error === null && plannedTarget !== null ? (
                <Typography variant="caption" color="text.secondary" data-testid={`we-owe-release-hint-${obligation.weOweId}`}>
                  {reservationPlanOutcome.isRelease
                    ? `Releases ${obligation.reservedQty - plannedTarget} Kernel${obligation.reservedQty - plannedTarget === 1 ? '' : 's'} back to sellable stock.`
                    : `Holds ${plannedTarget} Kernel${plannedTarget === 1 ? '' : 's'} against this obligation.`}
                </Typography>
              ) : null}
            </Stack>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mt: 1 }}>
              <TextField
                size="small"
                label="Fulfill"
                inputMode="numeric"
                value={fulfillQty}
                onChange={(change) => setFulfillQty(change.target.value)}
                disabled={fulfillingNow || reservingNow}
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
                value={draftSource ?? 'KERNEL_STOCK'}
                displayEmpty
                onChange={(change) => setSource(change.target.value as GqlWeOweFulfillmentSource)}
                disabled={fulfillingNow || reservingNow || sources.length === 0}
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
                onClick={() => void saveFulfillment()}
                disabled={fulfillingNow || reservingNow || fulfillmentOutcome.error !== null}
                data-testid={`we-owe-fulfill-${obligation.weOweId}`}
              >
                {fulfillingNow ? 'Fulfilling…' : 'Record the fulfillment'}
              </Button>
            </Stack>
            {sources.length === 0 ? (
              <Typography variant="caption" color="text.secondary" data-testid={`we-owe-no-source-${obligation.weOweId}`} sx={{ mt: 1, display: 'block' }}>
                No source: nothing is reserved and nothing is uncovered.
              </Typography>
            ) : null}
            <Tooltip title="KERNEL_STOCK may only reach what is reserved; EXTERNAL_COUNCIL may only reach what is not covered. A covered portion must be released first." describeChild>
              <IconButton size="small" aria-label="Why fulfillment is limited this way" data-testid={`we-owe-help-${obligation.weOweId}`}>
                <HelpOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            {error ? <ErrorNote message={error} data-testid={`we-owe-error-${obligation.weOweId}`} /> : null}
          </>
        ) : (
          <Typography variant="caption" color="text.secondary" data-testid={`we-owe-closed-${obligation.weOweId}`} sx={{ mt: 1, display: 'block' }}>
            Closed — the obligation is history. A mistake is corrected by a later fulfillment, never by rewriting this one.
          </Typography>
        )}
      </CardContent>
    </Card>
  );
};
