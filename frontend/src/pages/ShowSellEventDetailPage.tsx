/**
 * One Show & Sell event, as its Unit Admin manages it (§3.5.1 detail, hosting
 * §3.5.2 allocation editing, §3.5.3 slot administration, and §3.5.4 work
 * confirmation).
 *
 * The header is the part that carries the rules the panels underneath depend on:
 * the interval is shown, never edited (SSE-07); the state chip says where the event
 * stands, which is what decides whether the board below accepts writes; and the
 * version is the one every write on this page conditions on, so a save the server
 * refuses as stale is visibly the same number the screen was read at.
 *
 * The five panels are tabs rather than one long page because each writes a
 * different set of rows — allocations move stock reservations, slots move the
 * schedule, work rows move signup records, sales move the record of what was
 * sold, and We Owe moves what the Unit still owes and holds against it — and an
 * admin in the middle of one should not have the others in the way.
 *
 * An event whose id does not belong to the campaign in the route answers exactly
 * like an event that does not exist: the screen never confirms that the id is real
 * under someone else's campaign.
 */

import React, { useState } from 'react';
import { useQuery } from '@apollo/client/react';
import { useNavigate, useParams } from 'react-router-dom';
import { Box, Button, Card, CardContent, Chip, Stack, Tab, Tabs, Typography } from '@mui/material';
import { GET_SHOW_AND_SELL, GET_UNIT } from '../lib/graphql';
import {
  acceptsEventEdits,
  durationLabel,
  intervalLabel,
  isCancellable,
  minutesBetween,
  showAndSellStatusLabel,
  splitMethodLabel,
} from '../lib/showSell';
import { SHOW_SELL_BASE, unitDisplayName } from '../lib/units';
import { ErrorAlert } from '../components/ErrorAlert';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { AllocationEditor } from '../components/showSell/AllocationEditor';
import { SlotBoard } from '../components/showSell/SlotBoard';
import { SignupWorkBoard } from '../components/showSell/SignupWorkBoard';
import { SalesDesk } from '../components/showSell/SalesDesk';
import { WeOwePanel } from '../components/showSell/WeOwePanel';
import {
  EventActionDialogs,
  type CancelSummary,
  type EventUnitContext,
  type PendingEventAction,
} from '../components/showSell/EventDialogs';
import type {
  GqlGetShowAndSellQuery,
  GqlGetUnitQuery,
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellStatus,
} from '../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Unit = NonNullable<GqlGetUnitQuery['unit']>;
type EventTab = 'allocations' | 'slots' | 'signups' | 'sales' | 'weowe';

/** The three ids the route carries; empty when the route is somehow missing one. */
function useRouteIds(): { unitId: string; unitCampaignId: string; showAndSellId: string } {
  const params = useParams();
  return {
    unitId: params.unitId ?? '',
    unitCampaignId: params.unitCampaignId ?? '',
    showAndSellId: params.showAndSellId ?? '',
  };
}

function eventOf(data?: GqlGetShowAndSellQuery): Event | null {
  return data?.showAndSell ?? null;
}

function unitOf(data?: GqlGetUnitQuery): Unit | null {
  return data?.unit ?? null;
}

/**
 * The zone every time on this page is read in.
 *
 * `UTC` is the fallback while the Unit read is still in flight or has failed: the
 * event's own times are absolute, so a fallback moves the display but cannot invent
 * an event, and the writes are refused by the server long than by a missing zone.
 */
function timezoneOf(unit: Unit | null): string {
  return unit?.timezone ?? 'UTC';
}

/** The facts the edit dialogs need, from the Unit read that may still be missing. */
function contextOf(unit: Unit | null, unitCampaignId: string, timezone: string): EventUnitContext {
  return {
    unitCampaignId,
    timezone,
    splitDefault: unit?.splitDefault ?? 'EQUAL',
    campaignName: unit === null ? unitCampaignId : unitDisplayName(unit),
  };
}

export const ShowSellEventDetailPage: React.FC = () => {
  const { unitId, unitCampaignId, showAndSellId } = useRouteIds();
  const eventQuery = useQuery<GqlGetShowAndSellQuery>(GET_SHOW_AND_SELL, { variables: { showAndSellId } });
  const unitQuery = useQuery<GqlGetUnitQuery>(GET_UNIT, { variables: { unitId } });

  if (eventQuery.loading && !eventQuery.data) return <LoadingState />;
  const event = eventOf(eventQuery.data);
  if (event === null || event.unitCampaignId !== unitCampaignId) {
    return <ErrorAlert message="This event is not yours, or it no longer exists." />;
  }
  const onChanged = async () => {
    await eventQuery.refetch();
  };
  return (
    <EventDetailBody
      event={event}
      unit={unitOf(unitQuery.data)}
      unitCampaignId={unitCampaignId}
      onChanged={onChanged}
    />
  );
};

const EventDetailBody: React.FC<{
  event: Event;
  unit: Unit | null;
  unitCampaignId: string;
  onChanged: () => Promise<unknown>;
}> = ({ event, unit, unitCampaignId, onChanged }) => {
  const [tab, setTab] = useState<EventTab>('allocations');
  const [pending, setPending] = useState<PendingEventAction>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const timezone = timezoneOf(unit);
  const context = contextOf(unit, unitCampaignId, timezone);

  return (
    <>
      <EventHeader
        event={event}
        timezone={timezone}
        onEdit={() => setPending({ kind: 'edit', event })}
        onCancel={() => setPending({ kind: 'cancel', event })}
        onRecreate={() => setPending({ kind: 'recreate', from: event })}
      />
      <EventActionNotice message={notice} onDismiss={() => setNotice(null)} />
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={tab} onChange={(_event, value: EventTab) => setTab(value)} aria-label="Event sections">
          <Tab label="Stock" value="allocations" data-testid="tab-allocations" />
          <Tab label="Slots" value="slots" data-testid="tab-slots" />
          <Tab label="Signups and work" value="signups" data-testid="tab-signups" />
          <Tab label="Sales" value="sales" data-testid="tab-sales" />
          <Tab label="We Owe" value="weowe" data-testid="tab-weowe" />
        </Tabs>
      </Box>
      <EventPanels tab={tab} event={event} timezone={timezone} onChanged={onChanged} />
      <EventActionDialogs
        pending={pending}
        context={context}
        onClose={() => setPending(null)}
        onRefresh={onChanged}
        onCancelled={(summary) => setNotice(cancelledSentence(summary))}
        liveEvent={(target) => (target === event.showAndSellId ? event : null)}
      />
    </>
  );
};

/**
 * The panel the tab names.
 *
 * Only one is mounted at a time: each board carries its own drafts, and mounting a
 * board an admin has walked away from would keep a half-entered plan alive.
 */
const EventPanels: React.FC<{
  tab: EventTab;
  event: Event;
  timezone: string;
  onChanged: () => Promise<unknown>;
}> = ({ tab, event, timezone, onChanged }) => {
  if (tab === 'slots') return <SlotBoard event={event} timezone={timezone} onChanged={onChanged} />;
  if (tab === 'signups') return <SignupWorkBoard event={event} timezone={timezone} onChanged={onChanged} />;
  if (tab === 'sales') return <SalesDesk event={event} timezone={timezone} onChanged={onChanged} />;
  if (tab === 'weowe') return <WeOwePanel event={event} timezone={timezone} onChanged={onChanged} />;
  return <AllocationEditor event={event} onChanged={onChanged} />;
};

/**
 * The header every write on this page is read against.
 *
 * The times are printed once, in the Unit's zone, with their length spelled out:
 * an admin deciding whether to cancel needs to see that the event has already
 * started, and an admin deciding a slot length needs to see how much room the
 * interval leaves.
 */
const EventHeader: React.FC<{
  event: Event;
  timezone: string;
  onEdit: () => void;
  onCancel: () => void;
  onRecreate: () => void;
}> = ({ event, timezone, onEdit, onCancel, onRecreate }) => {
  const navigate = useNavigate();
  const back = `${SHOW_SELL_BASE}/units/${event.unitId}/campaigns/${event.unitCampaignId}/show-sell`;
  return (
    <>
      <PageHeader
        title={event.locationName}
        subtitle={intervalLabel(event.startAt, event.endAt, timezone)}
        backButton={{
          onClick: () => void navigate(back),
          label: 'Back to events',
          'aria-label': 'Back to events',
        }}
        action={
          <Chip
            label={showAndSellStatusLabel(event.status)}
            color={statusChipColor(event.status)}
            data-testid="event-status"
          />
        }
      />
      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Stack spacing={1}>
            <Typography data-testid="event-interval" gutterBottom>
              {intervalLabel(event.startAt, event.endAt, timezone)}
            </Typography>
            <EventAddress event={event} />
            <Typography color="text.secondary" data-testid="event-settings">
              {splitMethodLabel(event.splitMethod)} · We Owe {event.weOweEnabled ? 'on' : 'off'} ·{' '}
              {durationLabel(minutesBetween(event.startAt, event.endAt))} long
            </Typography>
            <Typography color="text.secondary" data-testid="event-version">
              Event version {event.version} — every change here is written against it, so a board someone else has
              already changed is refused rather than overwritten.
            </Typography>
            <CancellationReason event={event} />
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <EventHeaderActions event={event} onEdit={onEdit} onCancel={onCancel} onRecreate={onRecreate} />
            </Stack>
            <CancelRefusalNote event={event} />
          </Stack>
        </CardContent>
      </Card>
    </>
  );
};

function statusChipColor(status: GqlShowAndSellStatus): 'default' | 'success' | 'info' {
  if (status === 'CANCELLED') return 'default';
  if (status === 'ACTIVE') return 'success';
  return 'info';
}

const EventAddress: React.FC<{ event: Event }> = ({ event }) => {
  if (!event.address) return null;
  return (
    <Typography color="text.secondary" data-testid="event-address">
      {event.address}
    </Typography>
  );
};

/** The reason a cancelled event was cancelled — kept visible so nobody re-opens it by mistake. */
const CancellationReason: React.FC<{ event: Event }> = ({ event }) => {
  if (event.status !== 'CANCELLED' || !event.cancellationReason) return null;
  return (
    <Typography color="text.secondary" data-testid="cancellation-reason">
      Cancelled: {event.cancellationReason}
    </Typography>
  );
};

const EventHeaderActions: React.FC<{
  event: Event;
  onEdit: () => void;
  onCancel: () => void;
  onRecreate: () => void;
}> = ({ event, onEdit, onCancel, onRecreate }) => (
  <>
    <Button
      variant="outlined"
      onClick={onEdit}
      disabled={!acceptsEventEdits(event.status)}
      data-testid="edit-event"
    >
      Edit location or settings
    </Button>
    <Button
      variant="outlined"
      color="error"
      onClick={onCancel}
      disabled={!isCancellable(event.status)}
      data-testid="cancel-event"
    >
      Cancel event
    </Button>
    <Button
      variant="outlined"
      onClick={onRecreate}
      disabled={event.status !== 'CANCELLED'}
      data-testid="recreate-event"
    >
      Create another at a new time
    </Button>
  </>
);

/**
 * Why Cancel is disabled rather than absent.
 *
 * A started event is finished by finalizing it; cancellation is only for a Show &
 * Sell that has not begun (SSE-06), and the screen says that where the button is.
 */
const CancelRefusalNote: React.FC<{ event: Event }> = ({ event }) => {
  if (isCancellable(event.status) || event.status === 'CANCELLED') return null;
  return (
    <Typography variant="body2" color="text.secondary" data-testid="cancel-refusal-note">
      This event has already started. A started event is finished by finalizing it — cancellation is only for a Show &amp;
      Sell that has not begun.
    </Typography>
  );
};

/** The cancellation in one sentence, with the plurals matched to the server's own counts. */
function cancelledSentence(summary: CancelSummary): string {
  const allocations = summary.released === 1 ? 'allocation' : 'allocations';
  const signups = summary.signups === 1 ? 'signup' : 'signups';
  return `Cancelled: ${summary.released} product ${allocations} released back to the campaign, ${summary.signups} Scout ${signups} cancelled.`;
}

/** What the last header action did, kept on the page so the write's effect is visible. */
const EventActionNotice: React.FC<{ message: string | null; onDismiss: () => void }> = ({ message, onDismiss }) => {
  if (message === null) return null;
  return (
    <Box
      sx={{ mb: 3 }}
      role="status"
      data-testid="event-action-notice"
      p={2}
      border="1px solid"
      borderColor="divider"
      borderRadius={1}
    >
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
        <Typography data-testid="event-action-notice-text">{message}</Typography>
        <Button size="small" onClick={onDismiss} data-testid="dismiss-event-action-notice">
          Dismiss
        </Button>
      </Stack>
    </Box>
  );
};
