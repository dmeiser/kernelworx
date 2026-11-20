/**
 * The Show & Sell events of one Unit Campaign: list, create, edit, cancel, and
 * recreate (§3.5.1).
 *
 * The list is the admin's answer to "what does this campaign have on, and where
 * does it stand". Two things it is careful not to do:
 *
 * - **It does not offer a reschedule.** An event's interval is immutable (SSE-07),
 *   so the row that wants a new time gets *Cancel* and *Create another*, and the
 *   replacement is a new event with a new id — never a copy that drags stock or
 *   Scouts along with it.
 * - **It does not offer to cancel a started event.** Cancellation is a pre-start
 *   act (SSE-05, SSE-06); an event that is running or has ended is finished by
 *   finalizing it, and the row says so instead of presenting a button the server
 *   would refuse.
 *
 * Times are rendered in the Unit's own zone, because the Kernel and the Scouts
 * standing at the store read them in that zone, not the browser's.
 */

import React, { useState } from 'react';
import { useQuery } from '@apollo/client/react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { GET_UNIT, GET_UNIT_CAMPAIGN, LIST_SHOW_AND_SELLS } from '../lib/graphql';
import {
  SHOW_AND_SELL_PAGE_SIZE,
  durationLabel,
  intervalLabel,
  isCancellable,
  minutesUntil,
  showAndSellStatusLabel,
  splitMethodLabel,
} from '../lib/showSell';
import { SHOW_SELL_BASE, unitDisplayName } from '../lib/units';
import { ConnectionRestNotice } from '../components/ConnectionRestNotice';
import { EmptyState } from '../components/EmptyState';
import { ErrorAlert } from '../components/ErrorAlert';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { QueryGate } from '../components/QueryGate';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import {
  EventActionDialogs,
  type CancelSummary,
  type EventUnitContext,
  type PendingEventAction,
} from '../components/showSell/EventDialogs';
import type {
  GqlGetUnitCampaignQuery,
  GqlGetUnitQuery,
  GqlListShowAndSellsQuery,
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellStatus,
} from '../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Unit = NonNullable<GqlGetUnitQuery['unit']>;
type UnitCampaign = NonNullable<GqlGetUnitCampaignQuery['unitCampaign']>;

const LIST_VARIABLES = (unitCampaignId: string, status: GqlShowAndSellStatus | '') => ({
  unitCampaignId,
  status: status || undefined,
  dateRange: undefined,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
});

/** The Unit behind the route, or null when it is not the caller's to see. */
function unitOf(data?: GqlGetUnitQuery): Unit | null {
  return data?.unit ?? null;
}

function campaignOf(data?: GqlGetUnitCampaignQuery): UnitCampaign | null {
  return data?.unitCampaign ?? null;
}

/** The name in the page title: the campaign's own, or its id when the read failed. */
function campaignNameOf(campaign: UnitCampaign | null, unitCampaignId: string): string {
  if (campaign === null) return unitCampaignId;
  return campaign.campaignName;
}

/**
 * The route shell: read the Unit, decide whether this page can be shown at all.
 *
 * Everything below this point assumes a Unit the caller owns. Keeping that gate in
 * its own component is what leaves the list itself free to read one fact per line.
 */
/** The two ids the route carries, empty when the route is somehow missing one. */
function useRouteIds(): { unitId: string; unitCampaignId: string } {
  const params = useParams();
  return { unitId: params.unitId ?? '', unitCampaignId: params.unitCampaignId ?? '' };
}

export const ShowSellEventListPage: React.FC = () => {
  const { unitId, unitCampaignId } = useRouteIds();
  const unitQuery = useQuery<GqlGetUnitQuery>(GET_UNIT, { variables: { unitId } });
  const unit = unitOf(unitQuery.data);
  if (unitQuery.loading && !unitQuery.data) return <LoadingState />;
  if (unit === null) return <ErrorAlert message="This Unit is not yours, or it no longer exists." />;
  return <EventListBody unit={unit} unitId={unitId} unitCampaignId={unitCampaignId} />;
};

const EventListBody: React.FC<{ unit: Unit; unitId: string; unitCampaignId: string }> = ({
  unit,
  unitId,
  unitCampaignId,
}) => {
  const navigate = useNavigate();
  const [status, setStatus] = useState<GqlShowAndSellStatus | ''>('');
  const [pending, setPending] = useState<PendingEventAction>(null);
  const [cancelled, setCancelled] = useState<CancelSummary | null>(null);

  const campaignQuery = useQuery<GqlGetUnitCampaignQuery>(GET_UNIT_CAMPAIGN, { variables: { unitCampaignId } });
  const eventsQuery = useQuery<GqlListShowAndSellsQuery>(LIST_SHOW_AND_SELLS, {
    variables: LIST_VARIABLES(unitCampaignId, status),
  });

  const events = useCompleteConnection<Event>(eventsQuery.data?.showAndSells, {
    query: LIST_SHOW_AND_SELLS,
    field: 'showAndSells',
    limit: SHOW_AND_SELL_PAGE_SIZE,
    variables: LIST_VARIABLES(unitCampaignId, status),
  });

  const context: EventUnitContext = {
    unitCampaignId,
    timezone: unit.timezone,
    splitDefault: unit.splitDefault,
    campaignName: campaignNameOf(campaignOf(campaignQuery.data), unitCampaignId),
  };
  const eventsPath = `${SHOW_SELL_BASE}/units/${unitId}/campaigns/${unitCampaignId}/show-sell`;

  return (
    <>
      <PageHeader
        title={`Show & Sell — ${context.campaignName}`}
        subtitle={`${unitDisplayName(unit)} · times shown in ${unit.timezone}`}
        backButton={{
          onClick: () => void navigate(`${SHOW_SELL_BASE}/units/${unitId}/campaigns/${unitCampaignId}`),
          label: 'Back to campaign',
          'aria-label': 'Back to campaign',
        }}
        action={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => setPending({ kind: 'create' })}
            data-testid="new-show-and-sell"
          >
            New Show & Sell
          </Button>
        }
      />
      <LandingCard unitCampaignId={unitCampaignId} />
      <EventCancelledNotice summary={cancelled} onDismiss={() => setCancelled(null)} />
      <EventFilterTabs status={status} onChange={setStatus} />
      <QueryGate
        query={eventsQuery}
        loading={<LoadingState minHeight="200px" />}
        failure={<ErrorAlert message="Could not load this campaign’s events." />}
      >
        <EventTable
          events={events.items}
          timezone={unit.timezone}
          eventsPath={eventsPath}
          onEdit={(event) => setPending({ kind: 'edit', event })}
          onCancel={(event) => setPending({ kind: 'cancel', event })}
          onRecreate={(event) => setPending({ kind: 'recreate', from: event })}
        />
        <ConnectionRestNotice loading={events.loadingRest} failed={events.failedRest} />
      </QueryGate>
      <EventActionDialogs
        pending={pending}
        context={context}
        onClose={() => setPending(null)}
        onRefresh={() => eventsQuery.refetch()}
        onCancelled={setCancelled}
        liveEvent={(target) => events.items.find((item) => item.showAndSellId === target) ?? null}
      />
    </>
  );
};

/** What this page is for, and the one place a Scout's view of the same campaign is. */
const LandingCard: React.FC<{ unitCampaignId: string }> = ({ unitCampaignId }) => (
  <Card variant="outlined" sx={{ mb: 3 }}>
    <CardContent data-testid="show-sell-landing" component={Stack} spacing={1}>
      <Typography variant="subtitle1" gutterBottom>
        Managing this campaign’s events
      </Typography>
      <Typography color="text.secondary">
        Each event has its own stock allocation, its own working slots, and its own Scout signups. Stock is assigned on
        the event, not here, and a cancelled event keeps its reason, its allocations, and its signup history as audit
        records.
      </Typography>
      <Link to={`${SHOW_SELL_BASE}/campaigns/${unitCampaignId}/opportunities`} data-testid="open-scout-view">
        See what this campaign’s Scouts are offered
      </Link>
    </CardContent>
  </Card>
);

/** The state filter. An empty value is "all", which is what the read sends when it omits `status`. */
const EventFilterTabs: React.FC<{ status: GqlShowAndSellStatus | ''; onChange: (value: GqlShowAndSellStatus | '') => void }> =
  ({ status, onChange }) => (
    <Box sx={{ mb: 2 }}>
      <Tabs
        value={status}
        onChange={(_event, value: GqlShowAndSellStatus | '') => onChange(value)}
        aria-label="Event state filter"
        variant="scrollable"
        scrollButtons="auto"
      >
        <Tab label="All" value="" data-testid="filter-all" />
        <Tab label="Scheduled" value="SCHEDULED" data-testid="filter-scheduled" />
        <Tab label="Running" value="ACTIVE" data-testid="filter-active" />
        <Tab label="Ended" value="ENDED" data-testid="filter-ended" />
        <Tab label="Finalized" value="FINALIZED" data-testid="filter-finalized" />
        <Tab label="Reopened" value="REOPENED" data-testid="filter-reopened" />
        <Tab label="Cancelled" value="CANCELLED" data-testid="filter-cancelled" />
      </Tabs>
    </Box>
  );

/**
 * The row's own standing, in one chip and one sentence.
 *
 * The countdown is a display aid for the admin deciding whether to cancel; the
 * server decides whether the event can still be cancelled from the stored interval, not from this number.
 */
const EventStanding: React.FC<{ event: Event }> = ({ event }) => {
  const until = minutesUntil(event.startAt);
  return (
    <Stack spacing={0.5}>
      <Chip
        size="small"
        color={statusChipColor(event.status)}
        label={showAndSellStatusLabel(event.status)}
        data-testid={`event-status-${event.showAndSellId}`}
      />
      {until !== null && isCancellable(event.status) ? (
        <Typography variant="body2" color="text.secondary" data-testid={`event-countdown-${event.showAndSellId}`}>
          Starts in {durationLabel(until)}
        </Typography>
      ) : null}
    </Stack>
  );
};

function statusChipColor(status: GqlShowAndSellStatus): 'default' | 'success' | 'info' {
  if (status === 'CANCELLED') return 'default';
  if (status === 'ACTIVE') return 'success';
  return 'info';
}

const EventTable: React.FC<{
  events: Event[];
  timezone: string;
  eventsPath: string;
  onEdit: (event: Event) => void;
  onCancel: (event: Event) => void;
  onRecreate: (event: Event) => void;
}> = ({ events, timezone, eventsPath, onEdit, onCancel, onRecreate }) => {
  if (events.length === 0) {
    return (
      <EmptyState
        title="No Show & Sell events yet"
        message="Create one to assign stock to a store or event, open working slots, and let this campaign’s Scouts take places."
      />
    );
  }
  return (
    <Table size="small" aria-label="Show and Sell events">
      <TableHead>
        <TableRow>
          <TableCell>Where and when</TableCell>
          <TableCell>Standing</TableCell>
          <TableCell>Slots</TableCell>
          <TableCell>Stock</TableCell>
          <TableCell aria-label="Actions" />
        </TableRow>
      </TableHead>
      <TableBody>
        {events.map((event) => (
          <EventRow
            key={event.showAndSellId}
            event={event}
            timezone={timezone}
            eventsPath={eventsPath}
            onEdit={onEdit}
            onCancel={onCancel}
            onRecreate={onRecreate}
          />
        ))}
      </TableBody>
    </Table>
  );
};

const EventRow: React.FC<{
  event: Event;
  timezone: string;
  eventsPath: string;
  onEdit: (event: Event) => void;
  onCancel: (event: Event) => void;
  onRecreate: (event: Event) => void;
}> = ({ event, timezone, eventsPath, onEdit, onCancel, onRecreate }) => (
  <TableRow data-testid={`event-row-${event.showAndSellId}`}>
    <EventWhere event={event} timezone={timezone} eventsPath={eventsPath} />
    <TableCell>
      <EventStanding event={event} />
    </TableCell>
    <TableCell data-testid={`event-slots-${event.showAndSellId}`}>{event.slots.length}</TableCell>
    <TableCell data-testid={`event-stock-${event.showAndSellId}`}>{openAllocationCount(event)} products</TableCell>
    <TableCell>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Button size="small" onClick={() => onEdit(event)} data-testid={`edit-event-${event.showAndSellId}`}>
          Edit
        </Button>
        <EventCancelAction event={event} onCancel={onCancel} />
        {event.status === 'CANCELLED' ? (
          <Button size="small" onClick={() => onRecreate(event)} data-testid={`recreate-event-${event.showAndSellId}`}>
            Create another
          </Button>
        ) : null}
      </Stack>
    </TableCell>
  </TableRow>
);

/** Where the event is and when it runs — the two things that identify it in a list. */
const EventWhere: React.FC<{ event: Event; timezone: string; eventsPath: string }> = ({
  event,
  timezone,
  eventsPath,
}) => (
  <TableCell>
    <Stack spacing={0.5}>
      <Link to={`${eventsPath}/${event.showAndSellId}`} data-testid={`open-event-${event.showAndSellId}`}>
        <strong>{event.locationName}</strong>
      </Link>
      <Typography variant="body2" color="text.secondary" data-testid={`event-interval-${event.showAndSellId}`}>
        {intervalLabel(event.startAt, event.endAt, timezone)}
      </Typography>
      <EventAddress event={event} />
      <Typography variant="caption" color="text.secondary" data-testid={`event-split-${event.showAndSellId}`}>
        {splitMethodLabel(event.splitMethod)} · We Owe {event.weOweEnabled ? 'on' : 'off'}
      </Typography>
    </Stack>
  </TableCell>
);

const EventAddress: React.FC<{ event: Event }> = ({ event }) => {
  if (!event.address) return null;
  return (
    <Typography variant="body2" color="text.secondary" data-testid={`event-address-${event.showAndSellId}`}>
      {event.address}
    </Typography>
  );
};

/** How many products the event still holds stock for (a released allocation is history, not stock). */
function openAllocationCount(event: Event): number {
  return event.allocations.filter((allocation) => allocation.status === 'OPEN').length;
}

/** Cancel, or the reason the row does not offer it. */
const EventCancelAction: React.FC<{ event: Event; onCancel: (event: Event) => void }> = ({ event, onCancel }) => {
  if (!isCancellable(event.status)) return <StartedEventNotice event={event} />;
  return (
    <Button
      size="small"
      color="error"
      onClick={() => onCancel(event)}
      data-testid={`cancel-event-${event.showAndSellId}`}
    >
      Cancel
    </Button>
  );
};

/**
 * Why a started event has no Cancel button.
 *
 * A Unit Admin who cannot find the button looks for a reason, so the row gives it:
 * an event that has started is finished by finalizing it, and cancelling is not a
 * way to undo a start (SSE-06).
 */
const StartedEventNotice: React.FC<{ event: Event }> = ({ event }) => (
  <Typography
    variant="caption"
    color="text.secondary"
    data-testid={`no-cancel-${event.showAndSellId}`}
    title="Only a not-yet-started event can be cancelled"
  >
    {event.status === 'CANCELLED'
      ? 'Already cancelled'
      : 'Started — an event is finished by finalizing it, not by cancelling'}
  </Typography>
);

/**
 * What the cancellation did, in the counts the server answered.
 *
 * The numbers are the payload's own — allocations released and signups cancelled —
 * so the admin can see that the whole workflow ran rather than the event row
 * alone flipping state.
 */
const EventCancelledNotice: React.FC<{ summary: CancelSummary | null; onDismiss: () => void }> = ({
  summary,
  onDismiss,
}) => {
  if (summary === null) return null;
  return (
    <Box
      sx={{ mb: 3 }}
      role="status"
      data-testid="cancelled-summary"
      p={2}
      border="1px solid"
      borderColor="divider"
      borderRadius={1}
    >
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
        <Typography data-testid="cancelled-summary-text">{cancelledSentence(summary)}</Typography>
        <Button size="small" onClick={onDismiss} data-testid="dismiss-cancelled-summary">
          Dismiss
        </Button>
      </Stack>
    </Box>
  );
};

/** The counts in words, with the plural matched to the number the server answered. */
function cancelledSentence(summary: CancelSummary): string {
  const allocations = summary.released === 1 ? 'allocation' : 'allocations';
  const signups = summary.signups === 1 ? 'signup' : 'signups';
  return `“${summary.locationName}” is cancelled. ${summary.released} product ${allocations} went back to the campaign and ${summary.signups} Scout ${signups} were released.`;
}
