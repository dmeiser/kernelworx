/**
 * What a Scout is offered, and the places they hold (§3.5.3 participant surfaces).
 *
 * This page reads the participant projections only: `unitCampaignOpportunities`,
 * `myScoutCommitments`, and the signup/cancel writes that answer
 * `ParticipantSignup`. Nothing here can ask for an administrative type — no
 * allocation, no stock quantity, no sale, no buyer, no cash, no actor, no
 * finalization pointer (SEC-04) — and the slot the Scout sees carries
 * `openCapacity` the server computed, not a capacity the browser subtracted
 * (SEC-05).
 *
 * The list answers *which events are on offer*; it cannot answer *what the Scout
 * in the picker holds*, because one account may reach a campaign with several
 * Scouts and `unitCampaignOpportunities` gathers the signups of every roster
 * profile the caller can read. So each event card asks the per-Scout question it
 * needs — `showAndSellOpportunity(showAndSellId, profileId)` — and the Take, Give
 * back, and calendar controls are built from that answer alone. A row whose
 * per-Scout read has not arrived offers nothing yet, and one the server refused
 * (a Scout who is not on this roster) shows why rather than falling back to the
 * mixed list, where another Scout's place would otherwise decide this one's
 * buttons and address a write to the wrong profile.
 *
 * Four refusals are shown as facts about the Scout's standing rather than as
 * generic errors:
 *
 * - A Scout not on this campaign's roster gets a closed answer, not a list of
 *   things they cannot take (the same answer an unrelated Unit gives).
 * - A READ-only share cannot take a place, because signing up writes to the
 *   profile; the picker offers it for reading only.
 * - A full slot is full, stated in the row rather than after a click.
 * - An overlapping commitment is refused across every Unit Campaign (SLOT-04), and
 *   the page names the places that collide — the ones the Scout may not realize
 *   another campaign already holds.
 *
 * The calendar invite is generated in this tab from `showAndSellSignupCalendarData`
 * and handed straight to the download: no server file, URL, or email is involved,
 * and a downloaded invite is never updated when a place is later given back
 * (CAL-01, CAL-02).
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import {
  CANCEL_SHOW_AND_SELL_SIGNUP,
  GET_SHOW_AND_SELL_OPPORTUNITY,
  GET_SIGNUP_CALENDAR_DATA,
  LIST_MY_PROFILES,
  LIST_MY_SCOUT_COMMITMENTS,
  LIST_MY_SHARES,
  LIST_SCOUT_CAMPAIGN_JOINS,
  LIST_UNIT_CAMPAIGN_OPPORTUNITIES,
  SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT,
} from '../lib/graphql';
import {
  SHOW_AND_SELL_PAGE_SIZE,
  acceptsSignups,
  buildInvite,
  collidingCommitments,
  describeShowAndSellFailure,
  downloadInvite,
  intervalLabel,
  inviteFileName,
  openPlaces,
  showAndSellStatusLabel,
  signupForSlot,
  slotAvailabilityLabel,
  withIdempotency,
} from '../lib/showSell';
import { createWriteIntent, joinableProfiles, refreshQuery } from '../lib/units';
import { EmptyState } from '../components/EmptyState';
import { ErrorAlert, ErrorNote } from '../components/ErrorAlert';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { QueryGate } from '../components/QueryGate';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import type {
  GqlGetShowAndSellOpportunityQuery,
  GqlGetSignupCalendarDataQuery,
  GqlListMyProfilesQuery,
  GqlListMyScoutCommitmentsQuery,
  GqlListMySharesQuery,
  GqlListScoutCampaignJoinsQuery,
  GqlListUnitCampaignOpportunitiesQuery,
  GqlParticipantCommitmentFieldsFragment,
  GqlParticipantSignupFieldsFragment,
  GqlShowAndSellOpportunityFieldsFragment,
} from '../types/graphql-generated';

type Opportunity = GqlShowAndSellOpportunityFieldsFragment;
type OpportunitySlot = Opportunity['slots'][number];
type Commitment = GqlParticipantCommitmentFieldsFragment;
type Profile = { profileId: string; sellerName?: string | null };
type ApolloClient = ReturnType<typeof useApolloClient>;

const OPPORTUNITY_VARIABLES = (unitCampaignId: string, includePast: boolean) => ({
  unitCampaignId,
  includePast,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
});

/** The Scout the screen speaks for: the picked one, or the first joinable profile. */
function chosenOf(picked: string | null, options: readonly Profile[]): string {
  if (picked !== null) return picked;
  return options[0]?.profileId ?? '';
}

function opportunitiesOf(data?: GqlListUnitCampaignOpportunitiesQuery): Opportunity[] {
  return data?.unitCampaignOpportunities?.items ?? [];
}

/**
 * The Scout Campaign the roster keys this Scout to in this Unit Campaign.
 *
 * The signup names it, and the server refuses a pair that is not the roster's own,
 * so credit and Orders keep the scope the join created (§2.3.1's identity rule).
 */
function scoutCampaignOf(data: GqlListScoutCampaignJoinsQuery | undefined, unitCampaignId: string): string | null {
  const joined = (data?.listCampaignsByProfile.campaigns ?? []).find(
    (campaign) => campaign.unitCampaignId === unitCampaignId && campaign.isActive,
  );
  return joined?.campaignId ?? null;
}

/** The zone the offers are read in — the Unit's own, which the participant projection carries. */
function timezoneOf(items: readonly Opportunity[]): string {
  return items[0]?.timezone ?? 'UTC';
}

/** Active commitments only: a cancelled one no longer blocks anything. */
function activeCommitments(commitments: readonly Commitment[]): Commitment[] {
  return commitments.filter((commitment) => commitment.status === 'ACTIVE');
}

/** The places that could collide with this slot: the Scout's other active places. */
function otherActivePlaces(commitments: readonly Commitment[], slotId: string): Commitment[] {
  return activeCommitments(commitments).filter((commitment) => commitment.slotId !== slotId);
}

export const ShowSellOpportunitiesPage: React.FC = () => {
  const { unitCampaignId = '' } = useParams();
  const profiles = useQuery<GqlListMyProfilesQuery>(LIST_MY_PROFILES, {});
  const shares = useQuery<GqlListMySharesQuery>(LIST_MY_SHARES, {});
  const options = useMemo(
    () => joinableProfiles(profiles.data?.listMyProfiles.profiles ?? [], shares.data?.listMyShares ?? []),
    [profiles.data, shares.data],
  );
  if (profiles.loading && !profiles.data) return <LoadingState />;
  return <ScoutWorkspace options={options} unitCampaignId={unitCampaignId} profiles={profiles} shares={shares} />;
};

/**
 * The workspace for one Scout: the offers, the places held, and the three writes.
 *
 * The Scout is picked on this screen because one account can own or hold write
 * access to several profiles, and every write has to name exactly one of them.
 */
const ScoutWorkspace: React.FC<{
  options: readonly Profile[];
  unitCampaignId: string;
  profiles: { data?: GqlListMyProfilesQuery };
  shares: { data?: GqlListMySharesQuery };
}> = ({ options, unitCampaignId, profiles, shares }) => {
  const client = useApolloClient();
  // The first joinable Scout is the default a single-Scout account expects; an
  // account managing two Scouts picks, and the pick decides which profile the
  // write names.
  const [picked, setPicked] = useState<string | null>(null);
  const profileId = chosenOf(picked, options);

  const joins = useQuery<GqlListScoutCampaignJoinsQuery>(LIST_SCOUT_CAMPAIGN_JOINS, {
    variables: { profileId },
    skip: profileId === '',
  });
  const opportunities = useQuery<GqlListUnitCampaignOpportunitiesQuery>(LIST_UNIT_CAMPAIGN_OPPORTUNITIES, {
    variables: OPPORTUNITY_VARIABLES(unitCampaignId, false),
  });
  const commitments = useQuery<GqlListMyScoutCommitmentsQuery>(LIST_MY_SCOUT_COMMITMENTS, {
    variables: { profileId, includeCancelled: false, page: { limit: SHOW_AND_SELL_PAGE_SIZE } },
    skip: profileId === '',
  });
  const allCommitments = useCompleteConnection<Commitment>(commitments.data?.myScoutCommitments, {
    query: LIST_MY_SCOUT_COMMITMENTS,
    field: 'myScoutCommitments',
    limit: SHOW_AND_SELL_PAGE_SIZE,
    variables: { profileId, includeCancelled: false },
  });

  const scoutCampaignId = useMemo(
    () => scoutCampaignOf(joins.data, unitCampaignId),
    [joins.data, unitCampaignId],
  );
  const items = useMemo(() => opportunitiesOf(opportunities.data), [opportunities.data]);

  const [pendingInvite, setPendingInvite] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped whenever a write may have changed what the picked Scout holds, so every
  // event card re-asks its per-Scout question. The offer list re-reads too, because
  // `openCapacity` is the other half of the row, but the list alone can never answer
  // this question: its signups belong to every readable roster profile.
  const [scoutViewToken, setScoutViewToken] = useState(0);
  const intent = React.useRef(createWriteIntent());
  const [signupScout, { loading: signingUp }] = useMutation(SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT);
  const [cancelSignup] = useMutation(CANCEL_SHOW_AND_SELL_SIGNUP);

  const canSignup = scoutCampaignId !== null && canWrite(profiles.data, shares.data, profileId);

  const take = async (event: Opportunity, slotId: string) => {
    if (profileId === '' || scoutCampaignId === null) return;
    setError(null);
    const body = { showAndSellId: event.showAndSellId, slotId, campaignId: scoutCampaignId, profileId };
    try {
      await signupScout({ variables: { input: withIdempotency(body, intent.current) } });
      setNotice('You have a place in this slot. Download the calendar invite if you want it on your calendar.');
      setPendingInvite(`${event.showAndSellId}:${slotId}`);
    } catch (mutationError) {
      setError(describeShowAndSellFailure(mutationError, 'Could not take this place.'));
      setPendingInvite(null);
    }
    await refreshQuery(opportunities.refetch);
    // The place just taken is a commitment too: it is what the next row's overlap
    // warning is computed against, and what the Places-you-hold panel lists.
    await refreshQuery(commitments.refetch);
    setScoutViewToken((token) => token + 1);
  };

  const give = async (showAndSellId: string, signup: GqlParticipantSignupFieldsFragment) => {
    if (profileId === '') return;
    setError(null);
    const body = {
      showAndSellId,
      slotId: signup.slotId,
      profileId,
      version: { expectedVersion: signup.signupVersion },
    };
    try {
      await cancelSignup({ variables: { input: withIdempotency(body, intent.current) } });
      setNotice('You gave this place back. Anyone else may now take it.');
    } catch (mutationError) {
      setError(describeShowAndSellFailure(mutationError, 'Could not give this place back.'));
    }
    await refreshQuery(opportunities.refetch);
    await refreshQuery(commitments.refetch);
    setScoutViewToken((token) => token + 1);
  };

  const invite = async (showAndSellId: string, slotId: string) => {
    if (profileId === '') return;
    setError(null);
    try {
      const data = await readInvite(client, showAndSellId, slotId, profileId);
      downloadInvite(inviteFileName(data), buildInvite(data));
      setNotice(
        'The invite was downloaded by your browser. It is not stored anywhere, and it will not update itself if the plan changes.',
      );
    } catch (calendarError) {
      setError(describeShowAndSellFailure(calendarError, 'Could not read the calendar data for this place.'));
    }
  };

  return (
    <>
      <PageHeader
        title="Show & Sell signups"
        subtitle="The events this campaign is offering your Scouts, and the places they hold"
      />
      <Box sx={{ mb: 3 }}>
        <ProfilePicker options={options} value={profileId} onPick={setPicked} />
      </Box>
      <RosterNotice joined={scoutCampaignId !== null && profileId !== ''} />
      <SignupNotice message={notice} />
      <ErrorNote message={error} />
      <CommitmentPanel
        commitments={activeCommitments(allCommitments.items)}
        timezone={timezoneOf(items)}
        onInvite={(showAndSellId, slotId) => void invite(showAndSellId, slotId)}
      />
      <QueryGate
        query={opportunities}
        loading={<LoadingState minHeight="200px" />}
        failure={<ErrorAlert message="This campaign has no Show & Sell for you, or it is not one you can reach." />}
      >
        <OpportunityList
          items={items}
          profileId={profileId}
          scoutViewToken={scoutViewToken}
          canSignup={canSignup}
          signingUp={signingUp}
          pendingInvite={pendingInvite}
          commitments={allCommitments.items}
          onTake={(event, slotId) => void take(event, slotId)}
          onGive={(event, signup) => void give(event.showAndSellId, signup)}
          onInvite={(event, slotId) => void invite(event.showAndSellId, slotId)}
        />
      </QueryGate>
    </>
  );
};

/** The invite fields for one place, read fresh every time: a cached read could describe a slot that moved. */
async function readInvite(
  client: ApolloClient,
  showAndSellId: string,
  slotId: string,
  profileId: string,
): Promise<NonNullable<GqlGetSignupCalendarDataQuery['showAndSellSignupCalendarData']>> {
  const { data } = await client.query<GqlGetSignupCalendarDataQuery>({
    query: GET_SIGNUP_CALENDAR_DATA,
    variables: { showAndSellId, slotId, profileId },
    fetchPolicy: 'network-only',
  });
  const invite = data?.showAndSellSignupCalendarData;
  if (!invite) throw new Error('The server answered no calendar data for this place.');
  return invite;
}

/** The picker: which Scout, out of the profiles this account owns or holds WRITE on. */
const ProfilePicker: React.FC<{
  options: readonly Profile[];
  value: string;
  onPick: (profileId: string) => void;
}> = ({ options, value, onPick }) => (
  <TextField
    select
    label="Signed up as"
    value={value}
    onChange={(event) => onPick(event.target.value)}
    disabled={options.length === 0}
    data-testid="profile-picker"
    helperText="Your own Scouts, and the Scouts shared to you with write access. A read-only share can see an offer but cannot take a place."
    sx={{ minWidth: 320 }}
  >
    {options.map((profile) => (
      <MenuItem key={profile.profileId} value={profile.profileId} data-testid={`profile-option-${profile.profileId}`}>
        {profile.sellerName ?? profile.profileId}
      </MenuItem>
    ))}
  </TextField>
);

/**
 * The closed answer for a Scout who is not on this campaign's roster.
 *
 * It is deliberately the same shape the screen gives a Scout from an unrelated
 * Unit: the offers are not listed with disabled buttons, because that would show
 * what is on offer somewhere the Scout has no standing.
 */
const RosterNotice: React.FC<{ joined: boolean }> = ({ joined }) => {
  if (joined) return null;
  return (
    <Alert severity="info" sx={{ mb: 3 }} data-testid="not-on-roster">
      This Scout is not on this campaign’s roster, so there is nothing to sign up for here. A Scout joins with the
      campaign’s join code.
    </Alert>
  );
};

/** What the last write did, kept on the page so its effect is visible next to the row it changed. */
const SignupNotice: React.FC<{ message: string | null }> = ({ message }) => {
  if (message === null) return null;
  return (
    <Alert severity="success" sx={{ mb: 3 }} data-testid="signup-notice">
      {message}
    </Alert>
  );
};

/** The offers, or the reason there are none. */
const OpportunityList: React.FC<{
  items: Opportunity[];
  profileId: string;
  scoutViewToken: number;
  canSignup: boolean;
  signingUp: boolean;
  pendingInvite: string | null;
  commitments: readonly Commitment[];
  onTake: (event: Opportunity, slotId: string) => void;
  onGive: (event: Opportunity, signup: GqlParticipantSignupFieldsFragment) => void;
  onInvite: (event: Opportunity, slotId: string) => void;
}> = ({ items, profileId, scoutViewToken, canSignup, signingUp, pendingInvite, commitments, onTake, onGive, onInvite }) => {
  if (items.length === 0) {
    return (
      <EmptyState
        title="Nothing is on offer here right now"
        message="When this campaign’s Kernels schedule a Show & Sell and open its slots, the events and the places in them appear here."
      />
    );
  }
  return (
    <Stack spacing={2}>
      {items.map((event) => (
        <OpportunityCard
          key={event.showAndSellId}
          event={event}
          profileId={profileId}
          scoutViewToken={scoutViewToken}
          canSignup={canSignup}
          signingUp={signingUp}
          inviteKey={pendingInvite}
          commitments={commitments}
          onTake={(slotId) => onTake(event, slotId)}
          onGive={(signup) => onGive(event, signup)}
          onInvite={(slotId) => onInvite(event, slotId)}
        />
      ))}
    </Stack>
  );
};

/**
 * A card per event: what it is, when it runs, and the slots with room left.
 *
 * The event's own facts come from the offer list; the Scout's places come from the
 * per-Scout read, because the list's `mySignups` covers every roster profile the
 * caller can read. Taking that shortcut is how one Scout's held place hides another
 * Scout's Take button, and how a Give back or a calendar invite ends up addressed to
 * a profile the reader was not looking at.
 */
const OpportunityCard: React.FC<{
  event: Opportunity;
  profileId: string;
  scoutViewToken: number;
  canSignup: boolean;
  signingUp: boolean;
  inviteKey: string | null;
  commitments: readonly Commitment[];
  onTake: (slotId: string) => void;
  onGive: (signup: GqlParticipantSignupFieldsFragment) => void;
  onInvite: (slotId: string) => void;
}> = ({ event, profileId, scoutViewToken, canSignup, signingUp, inviteKey, commitments, onTake, onGive, onInvite }) => {
  const scoutView = useQuery<GqlGetShowAndSellOpportunityQuery>(GET_SHOW_AND_SELL_OPPORTUNITY, {
    variables: { showAndSellId: event.showAndSellId, profileId },
    skip: profileId === '',
  });
  useScoutViewRefresh(scoutView, scoutViewToken);
  const view = scoutView.data?.showAndSellOpportunity ?? null;
  const shown = view ?? event;
  return (
    <Card variant="outlined" data-testid={`opportunity-${event.showAndSellId}`}>
      <CardContent>
        <Stack spacing={1}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="h6" data-testid={`opportunity-location-${event.showAndSellId}`}>
              {shown.locationName}
            </Typography>
            <Chip
              size="small"
              label={showAndSellStatusLabel(shown.status)}
              data-testid={`opportunity-status-${event.showAndSellId}`}
            />
            <WeOweChip event={shown} />
          </Stack>
          <Typography color="text.secondary" data-testid={`opportunity-when-${event.showAndSellId}`}>
            {intervalLabel(shown.startAt, shown.endAt, shown.timezone)}
          </Typography>
          <OpportunityAddress event={shown} />
          <NoSlotsNote event={shown} />
          <ScoutViewNotice showAndSellId={event.showAndSellId} view={view} loading={scoutView.loading} />
          {shown.slots.map((slot) => (
            <SlotOfferRow
              key={slot.slotId}
              slot={slot}
              event={shown}
              signup={view ? signupForSlot(view.mySignups, slot.slotId) : undefined}
              actionsKnown={view !== null}
              collisions={collidingCommitments(slot, otherActivePlaces(commitments, slot.slotId))}
              canSignup={canSignup}
              signingUp={signingUp}
              inviteRequested={inviteKey === `${event.showAndSellId}:${slot.slotId}`}
              onTake={onTake}
              onGive={onGive}
              onInvite={onInvite}
            />
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
};

/**
 * Re-ask the per-Scout question after a write.
 *
 * The card's own query answers from the cache, so a place taken or given back would
 * leave this row showing the buttons it had when the page loaded — a Take that is
 * really a duplicate, or a Give back for a place that is already gone. The token is
 * the force that re-runs the request the card already made; token 0 is the mount.
 */
function useScoutViewRefresh(scoutView: { refetch: () => unknown }, token: number): void {
  const seen = useRef(0);
  useEffect(() => {
    if (token === seen.current) return;
    seen.current = token;
    void scoutView.refetch();
  }, [scoutView, token]);
}

/**
 * Whether this card knows what the picked Scout holds.
 *
 * Two states, each said plainly: the read is in flight, or it answered nothing —
 * refused because this Scout has no standing on this event. Neither state falls back
 * to the offer list's signups, because those belong to other Scouts as well.
 */
const ScoutViewNotice: React.FC<{ showAndSellId: string; view: Opportunity | null; loading: boolean }> = ({
  showAndSellId,
  view,
  loading,
}) => {
  if (view !== null) return null;
  if (loading) {
    return (
      <Typography variant="body2" color="text.secondary" data-testid={`scout-view-loading-${showAndSellId}`}>
        Checking which places this Scout already holds…
      </Typography>
    );
  }
  return (
    <Typography variant="body2" color="text.secondary" data-testid={`scout-view-refused-${showAndSellId}`}>
      This Scout cannot be offered this Show &amp; Sell, so no places are shown for it.
    </Typography>
  );
};

const WeOweChip: React.FC<{ event: Opportunity }> = ({ event }) => {
  if (!event.weOweEnabled) return null;
  return <Chip size="small" variant="outlined" label="We Owe offered" data-testid="opportunity-we-owe" />;
};

const OpportunityAddress: React.FC<{ event: Opportunity }> = ({ event }) => {
  if (!event.address) return null;
  return (
    <Typography color="text.secondary" data-testid="opportunity-address">
      {event.address}
    </Typography>
  );
};

/** An event with no slots is not an event with nothing to take: it is one nobody has opened yet. */
const NoSlotsNote: React.FC<{ event: Opportunity }> = ({ event }) => {
  if (event.slots.length > 0) return null;
  return (
    <Typography color="text.secondary" data-testid="no-slots-offered">
      No working slots have been opened for this event yet.
    </Typography>
  );
};

/**
 * One slot on offer: when it runs, whether it has room, and what this Scout can do.
 *
 * The availability sentence is the server's arithmetic (`openCapacity`), and the
 * collision warning is computed from the Scout's own commitments — the ones held in
 * another campaign included, because the overlap rule runs across every campaign
 * (SLOT-04) while this list only shows one.
 */
const SlotOfferRow: React.FC<{
  slot: OpportunitySlot;
  event: Opportunity;
  signup?: GqlParticipantSignupFieldsFragment;
  actionsKnown: boolean;
  collisions: readonly unknown[];
  canSignup: boolean;
  signingUp: boolean;
  inviteRequested: boolean;
  onTake: (slotId: string) => void;
  onGive: (signup: GqlParticipantSignupFieldsFragment) => void;
  onInvite: (slotId: string) => void;
}> = ({
  slot,
  event,
  signup,
  actionsKnown,
  collisions,
  canSignup,
  signingUp,
  inviteRequested,
  onTake,
  onGive,
  onInvite,
}) => {
  const open = acceptsSignups(event.status) && openPlaces(slot) > 0;
  return (
    <Stack
      direction="row"
      spacing={2}
      alignItems="center"
      flexWrap="wrap"
      useFlexGap
      data-testid={`slot-offer-${slot.slotId}`}
    >
      <Box sx={{ flexGrow: 1 }}>
        <Typography data-testid={`slot-offer-label-${slot.slotId}`}>{slot.label || 'Slot'}</Typography>
        <Typography variant="body2" color="text.secondary" data-testid={`slot-when-${slot.slotId}`}>
          {intervalLabel(slot.startAt, slot.endAt, event.timezone)}
        </Typography>
        <Typography variant="body2" color="text.secondary" data-testid={`slot-availability-${slot.slotId}`}>
          {slotAvailabilityLabel(slot, event.status, signup)}
        </Typography>
        <SlotConflictNote slot={slot} collisions={collisions} />
      </Box>
      {slotActions({ slot, event, signup, actionsKnown, open, canSignup, signingUp, inviteRequested, onTake, onGive, onInvite })}
    </Stack>
  );
};

/**
 * The controls for one slot, or none while this Scout's places are unknown.
 *
 * A Take button that does not know this Scout already holds the place offers a
 * duplicate write, and a Give back whose signup came from the shared offer list is a
 * write addressed to whichever profile the caller happens to have picked. So the
 * controls appear only once `showAndSellOpportunity` has answered for the picked
 * Scout — the same answer the row's held/cancelled sentence is read from.
 */
function slotActions(args: {
  slot: OpportunitySlot;
  event: Opportunity;
  signup?: GqlParticipantSignupFieldsFragment;
  actionsKnown: boolean;
  open: boolean;
  canSignup: boolean;
  signingUp: boolean;
  inviteRequested: boolean;
  onTake: (slotId: string) => void;
  onGive: (signup: GqlParticipantSignupFieldsFragment) => void;
  onInvite: (slotId: string) => void;
}): React.ReactNode {
  if (!args.actionsKnown) return null;
  if (args.signup !== undefined && args.signup.status === 'ACTIVE') {
    return (
      <HeldPlaceActions slot={args.slot} signup={args.signup} event={args.event} onGive={args.onGive} onInvite={args.onInvite} />
    );
  }
  return (
    <>
      <TakePlaceButton
        slotId={args.slot.slotId}
        blocked={takeBlocked(args.open, args.canSignup, args.signingUp)}
        onTake={args.onTake}
      />
      <NewPlaceInvite requested={args.inviteRequested} slotId={args.slot.slotId} onInvite={args.onInvite} />
    </>
  );
}

/** The invite offered straight after a place was taken, before the row re-reads. */
const NewPlaceInvite: React.FC<{ requested: boolean; slotId: string; onInvite: (slotId: string) => void }> = ({
  requested,
  slotId,
  onInvite,
}) => {
  if (!requested) return null;
  return (
    <Button
      size="small"
      startIcon={<FileDownloadIcon />}
      onClick={() => onInvite(slotId)}
      data-testid={`invite-new-${slotId}`}
    >
      Calendar invite
    </Button>
  );
};

/** The overlap warning: the places this Scout already holds that this slot would collide with. */
const SlotConflictNote: React.FC<{ slot: OpportunitySlot; collisions: readonly unknown[] }> = ({
  slot,
  collisions,
}) => {
  if (collisions.length === 0) return null;
  const word = collisions.length === 1 ? 'commitment' : 'commitments';
  return (
    <Typography variant="body2" color="warning.main" data-testid={`slot-conflict-${slot.slotId}`}>
      This overlaps a place you already hold ({collisions.length} {word}), at this or another Show &amp; Sell.
    </Typography>
  );
};

/** Why the Take button is dead: full, closed, being written, or not this Scout's to write. */
function takeBlocked(open: boolean, canSignup: boolean, signingUp: boolean): boolean {
  return !open || !canSignup || signingUp;
}

const TakePlaceButton: React.FC<{ slotId: string; blocked: boolean; onTake: (slotId: string) => void }> = ({
  slotId,
  blocked,
  onTake,
}) => (
  <Button
    size="small"
    variant="contained"
    onClick={() => onTake(slotId)}
    disabled={blocked}
    data-testid={`take-${slotId}`}
  >
    Take this place
  </Button>
);

const HeldPlaceActions: React.FC<{
  slot: OpportunitySlot;
  signup?: GqlParticipantSignupFieldsFragment;
  event: Opportunity;
  onGive: (signup: GqlParticipantSignupFieldsFragment) => void;
  onInvite: (slotId: string) => void;
}> = ({ slot, signup, event, onGive, onInvite }) => (
  <Stack direction="row" spacing={1}>
    <Button
      size="small"
      startIcon={<FileDownloadIcon />}
      onClick={() => onInvite(slot.slotId)}
      data-testid={`invite-${slot.slotId}`}
    >
      Calendar invite
    </Button>
    <Button
      size="small"
      color="error"
      onClick={() => signup !== undefined && onGive(signup)}
      disabled={!acceptsSignups(event.status)}
      data-testid={`give-${slot.slotId}`}
    >
      Give this place back
    </Button>
  </Stack>
);

/** The places this Scout holds across every campaign, so an overlap can be seen. */
const CommitmentPanel: React.FC<{
  commitments: Commitment[];
  timezone: string;
  onInvite: (showAndSellId: string, slotId: string) => void;
}> = ({ commitments, timezone, onInvite }) => (
  <Card variant="outlined" sx={{ mb: 3 }} data-testid="commitment-panel">
    <CardContent>
      <Typography variant="subtitle1" gutterBottom>
        Places you hold
      </Typography>
      {commitments.length === 0 ? (
        <Typography color="text.secondary" data-testid="no-commitments">
          No Show & Sell places right now.
        </Typography>
      ) : (
        <Stack spacing={1}>
          {commitments.map((commitment) => (
            <CommitmentRow key={`${commitment.showAndSellId}:${commitment.slotId}`} commitment={commitment} timezone={timezone} onInvite={onInvite} />
          ))}
        </Stack>
      )}
    </CardContent>
  </Card>
);

const CommitmentRow: React.FC<{
  commitment: Commitment;
  timezone: string;
  onInvite: (showAndSellId: string, slotId: string) => void;
}> = ({ commitment, timezone, onInvite }) => (
  <Stack
    direction="row"
    spacing={2}
    alignItems="center"
    data-testid={`commitment-${commitment.showAndSellId}-${commitment.slotId}`}
  >
    <Typography sx={{ flexGrow: 1 }} data-testid={`commitment-when-${commitment.slotId}`}>
      {intervalLabel(commitment.startAt, commitment.endAt, timezone)}
    </Typography>
    <Button
      size="small"
      startIcon={<FileDownloadIcon />}
      onClick={() => onInvite(commitment.showAndSellId, commitment.slotId)}
      data-testid={`commitment-invite-${commitment.slotId}`}
    >
      Calendar invite
    </Button>
  </Stack>
);

/**
 * Whether the chosen profile may be written to.
 *
 * A READ share can see an offer and cannot take a place; the picker already hides
 * read-only profiles from the joinable set, and this is the same question asked of
 * the write, so the button and the entitlement cannot drift apart.
 */
function canWrite(
  profileData: GqlListMyProfilesQuery | undefined,
  shareData: GqlListMySharesQuery | undefined,
  profileId: string,
): boolean {
  if (profileId === '') return false;
  return ownsProfile(profileData, profileId) || hasWriteShare(shareData, profileId);
}

function ownsProfile(profileData: GqlListMyProfilesQuery | undefined, profileId: string): boolean {
  return (profileData?.listMyProfiles.profiles ?? []).some((profile) => profile.profileId === profileId);
}

function hasWriteShare(shareData: GqlListMySharesQuery | undefined, profileId: string): boolean {
  return (shareData?.listMyShares ?? []).some(
    (share) => share.profileId === profileId && (share.permissions ?? []).includes('WRITE'),
  );
}
