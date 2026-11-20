/**
 * What a Scout is offered, and the places they hold (§3.5.3 participant
 * surface; SS-SM-06 steps 3-7, SS-SM-05's capacity-1 exchange, CAL-01/CAL-02).
 *
 * What each assertion pins, and why it matters:
 *
 * - `openCapacity` is the server's answer, shown verbatim (SEC-05): the
 *   fixture deliberately sets it against what `capacity` minus this Scout's
 *   signups would say, so a screen that subtracts for itself fails the mock.
 * - A Full Booth overlapping two places the Scout already holds is refused by
 *   the server, and the screen names the collision before the write — across
 *   every Unit Campaign, because the overlap rule is campaign-wide (SLOT-04).
 * - Taking a capacity-1 place that is already gone answers `CONFLICT`, and the
 *   screen says the place moved rather than showing a stack trace; the list
 *   re-reads so the next take is against the fresh count.
 * - Cancellation conditions on the signup version the last answer carried —
 *   giving the place back must not stomp a signup that moved underneath.
 * - Every read and write on this page selects only participant-safe fields
 *   (SEC-04), so a slot another Scout holds can never appear on this screen.
 * - The `listScoutCampaignJoins` read is what names the Scout Campaign a write
 *   is addressed to (§2.3.1's identity rule), and the invite is assembled in
 *   this browser from the authorized calendar-data fields — never a server URL.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { GraphQLError, print } from 'graphql';
import { ShowSellOpportunitiesPage } from '../src/pages/ShowSellOpportunitiesPage';
import {
  CANCEL_SHOW_AND_SELL_SIGNUP,
  GET_SIGNUP_CALENDAR_DATA,
  LIST_MY_PROFILES,
  LIST_MY_SCOUT_COMMITMENTS,
  LIST_MY_SHARES,
  LIST_SCOUT_CAMPAIGN_JOINS,
  LIST_UNIT_CAMPAIGN_OPPORTUNITIES,
  SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT,
} from '../src/lib/graphql';
import { SHOW_AND_SELL_PAGE_SIZE } from '../src/lib/showSell';
import { findOption } from './helpers/unitUi';

const SSE = 'SSE#library';
const SSE_GROVE = 'SSE#grove';
const ZONE = 'America/Denver';
const AVERY = 'PROFILE#avery';
const SHARED = 'PROFILE#shared';
const NO_NAME = 'PROFILE#noname';
const CAMP_AVERY = 'CAMP#avery-fall';

let keySequence = 0;
let testSequence = 0;
// Fresh per test: react-router v7 keeps params in a module-level store, so one
// MockedProvider from an earlier test would otherwise read the previous test's
// Unit Campaign.
// The id arrives url-encoded: react-router cuts the location string at '#', and
// an unescaped storage id would arrive as the bare 'UNITCAMP' prefix.
const UC = () => `UNITCAMP#pack-3149-fall-${testSequence}`;
const UC_URL = () => encodeURIComponent(UC());

const STALE_SENTENCE =
  'That was refused because the event, a slot, or a signup has already moved. Reload this screen and try again with what it now shows.';
const NO_SHOW_AND_SELL = 'This campaign has no Show & Sell for you, or it is not one you can reach.';
const OPPORTUNITY_READ = (uc: string) => ({ unitCampaignId: uc, includePast: false, page: { limit: SHOW_AND_SELL_PAGE_SIZE } });

beforeEach(() => {
  testSequence += 1;
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function profileFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'SellerProfile',
    profileId: AVERY,
    ownerAccountId: 'ACCOUNT#avery',
    sellerName: 'Avery Scout',
    createdAt: '2026-01-02T15:00:00Z',
    updatedAt: '2026-01-02T15:00:00Z',
    isOwner: true,
    permissions: [],
    latestCampaign: { __typename: 'Campaign', campaignId: CAMP_AVERY, campaignName: 'Avery 2026', campaignYear: 2026, isActive: true },
    ...overrides,
  };
}

function shareFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'SharedProfile',
    profileId: SHARED,
    ownerAccountId: 'ACCOUNT#other',
    sellerName: 'Shared Scout',
    unitType: 'Pack',
    unitNumber: 3149,
    createdAt: '2026-01-02T15:00:00Z',
    updatedAt: '2026-01-02T15:00:00Z',
    isOwner: false,
    permissions: ['WRITE'],
    latestCampaign: { __typename: 'Campaign', campaignId: 'CAMP#shared-fall', campaignName: 'Shared 2026', campaignYear: 2026, isActive: true },
    ...overrides,
  };
}

function participantSignup(slotId: string, overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ParticipantSignup',
    showAndSellId: SSE,
    slotId,
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T16:30:00.000Z',
    status: 'ACTIVE',
    actualMinutes: 0,
    signupVersion: 1,
    ...overrides,
  };
}

function commitmentFixture(showAndSellId: string, slotId: string, overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ParticipantCommitment',
    showAndSellId,
    slotId,
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:00:00.000Z',
    status: 'ACTIVE',
    signupVersion: 2,
    ...overrides,
  };
}

function opportunitySlot(slotId: string, overrides: Record<string, unknown> = {}) {
  return {
    slotId,
    label: slotId,
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T16:30:00.000Z',
    capacity: 1,
    openCapacity: 1,
    ...overrides,
  };
}

function opportunityFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShowAndSellOpportunity',
    showAndSellId: SSE,
    locationName: 'Library on Main',
    address: '200 Main St',
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:30:00.000Z',
    status: 'SCHEDULED',
    splitMethod: 'TIME_WORKED',
    weOweEnabled: true,
    timezone: ZONE,
    eventVersion: 7,
    slots: [opportunitySlot('SLOT#first', { label: 'First Sales' })],
    mySignups: [] as unknown[],
    ...overrides,
  };
}

function profilesQuery(profiles: unknown[]) {
  return { request: { query: LIST_MY_PROFILES }, result: { data: { listMyProfiles: { __typename: 'ProfileConnection', profiles, nextToken: null } } } };
}

function sharesQuery(shares: unknown[]) {
  return { request: { query: LIST_MY_SHARES }, result: { data: { listMyShares: shares } } };
}

function joinsQuery(profileId: string, campaigns: unknown[]) {
  return {
    request: { query: LIST_SCOUT_CAMPAIGN_JOINS, variables: { profileId } },
    result: { data: { listCampaignsByProfile: { __typename: 'CampaignConnection', campaigns, nextToken: null } } },
  };
}

function campaignJoin(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'Campaign',
    campaignId: CAMP_AVERY,
    campaignName: 'Avery 2026',
    campaignYear: 2026,
    isActive: true,
    unitCampaignId: UC(),
    ...overrides,
  };
}

function commitmentsQuery(profileId: string, items: unknown[]) {
  return {
    request: { query: LIST_MY_SCOUT_COMMITMENTS, variables: { profileId, includeCancelled: false, page: { limit: SHOW_AND_SELL_PAGE_SIZE } } },
    result: {
      data: {
        myScoutCommitments: {
          __typename: 'ParticipantCommitmentConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function opportunitiesQuery(items: unknown[]) {
  return {
    request: { query: LIST_UNIT_CAMPAIGN_OPPORTUNITIES, variables: { unitCampaignId: UC(), includePast: false, page: { limit: SHOW_AND_SELL_PAGE_SIZE } } },
    result: {
      data: {
        unitCampaignOpportunities: {
          __typename: 'ShowAndSellOpportunityConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function signupMock(slotId: string, campaignId: string, profileId: string, signup: unknown) {
  return {
    request: {
      query: SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT,
      variables: { input: { showAndSellId: SSE, slotId, campaignId, profileId, idempotency: { idempotencyKey: 'test-idem-1' } } },
    },
    result: { data: { signupScoutForShowAndSellSlot: signup } },
  };
}

function calendarQuery(showAndSellId: string, slotId: string, profileId: string, data: unknown) {
  return {
    request: { query: GET_SIGNUP_CALENDAR_DATA, variables: { showAndSellId, slotId, profileId } },
    result: { data: { showAndSellSignupCalendarData: data } },
  };
}

const CALENDAR_DATA = {
  __typename: 'CalendarInviteData',
  unitId: 'UNIT#pack-3149',
  unitDisplayName: 'Pack 3149',
  unitCampaignId: UC(),
  unitCampaignName: 'Fall Popcorn 2026',
  showAndSellId: SSE,
  slotId: 'SLOT#first',
  profileId: AVERY,
  slotLabel: 'First Sales',
  locationName: 'Library on Main',
  address: null,
  timezone: ZONE,
  slotStartAt: '2026-03-28T15:00:00.000Z',
  slotEndAt: '2026-03-28T16:30:00.000Z',
};

function renderPage(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      {/* A fresh router instance per test: the shared ParamsStore would otherwise
          replay a previous test's params and every read would go out with the wrong
          Unit Campaign. */}
      <MemoryRouter initialEntries={[`/show-sell/${UC_URL()}`]}>
        <Routes>
          <Route path="/show-sell/:unitCampaignId" element={<ShowSellOpportunitiesPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

function stubBrowserDownload() {
  const createObjectURL = vi.fn(() => 'blob:invite');
  const revokeObjectURL = vi.fn();
  const anchors: HTMLAnchorElement[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function capture(this: HTMLAnchorElement) {
    anchors.push(this);
  });
  vi.stubGlobal('URL', Object.assign(Object.create(URL), URL, { createObjectURL, revokeObjectURL }));
  return { anchors, createObjectURL, revokeObjectURL };
}

/** Waits until the take button is no longer blocked on the join read. */
async function enabledTake(slotId: string) {
  const button = await screen.findByTestId(`take-${slotId}`);
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

describe('ShowSellOpportunitiesPage', () => {
  it('SEC-05 (SS-SM-06 step 3): the offer list renders the server’s openCapacity verbatim, not what capacity-minus-signups would say', async () => {
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([
        opportunityFixture({
          slots: [
            // Capacity 2, nothing held by this Scout — the screen's own
            // arithmetic would say "2 places left", the server says full.
            opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 2, openCapacity: 0 }),
            opportunitySlot('SLOT#midday', { label: 'Midday', capacity: 1, openCapacity: 1 }),
            // Capacity 3 with one of Avery's own signups — subtraction over
            // this Scout's signups alone would say 2, the server says 2…
            opportunitySlot('SLOT#booth', { label: 'Full Booth', startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T18:00:00.000Z', capacity: 3, openCapacity: 2 }),
          ],
        }),
        // A second event with no slots opened, no address, no We Owe.
        opportunityFixture({ showAndSellId: 'SSE#grove', locationName: 'Grove Stand', address: null, weOweEnabled: false, slots: [] }),
      ]),
    ]);

    expect(await screen.findByText('Show & Sell signups')).toBeInTheDocument();
    // The header renders before any query answers, and the mock cache hands a
    // successful read back to every later read of it — so the page state
    // asserted below, not a roster alert, is what proves the join read landed.
    const library = await screen.findByTestId(`opportunity-${SSE}`);
    expect(within(library).getByTestId(`opportunity-location-${SSE}`)).toHaveTextContent('Library on Main');
    expect(within(library).getByTestId(`opportunity-we-owe`)).toBeInTheDocument();
    expect(within(library).getByTestId('opportunity-address')).toHaveTextContent('200 Main St');

    expect(screen.getByTestId('slot-availability-SLOT#first')).toHaveTextContent('This slot is full');
    expect(screen.getByTestId('slot-availability-SLOT#midday')).toHaveTextContent('1 place left');
    expect(screen.getByTestId('slot-availability-SLOT#booth')).toHaveTextContent('2 places left');
    expect(screen.getByTestId('take-SLOT#first')).toBeDisabled();
    expect(screen.getByTestId('take-SLOT#midday')).toBeEnabled();

    const grove = screen.getByTestId('opportunity-SSE#grove');
    expect(within(grove).getByTestId('no-slots-offered')).toHaveTextContent(
      'No working slots have been opened for this event yet.',
    );
    expect(within(grove).queryByTestId('opportunity-we-owe')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('opportunity-address')).toHaveLength(1);

    expect(screen.getByTestId('commitment-panel')).toHaveTextContent('No Show & Sell places right now.');
  });

  it('SLOT-04 (SS-SM-06 step 5): Full Booth against Avery’s two existing places is refused with the collision named', async () => {
    const user = userEvent.setup();
    const download = stubBrowserDownload();
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, [
        commitmentFixture(SSE_GROVE, 'SLOT#grove-am'),
        commitmentFixture(SSE_GROVE, 'SLOT#grove-pm', { startAt: '2026-03-28T16:30:00.000Z', endAt: '2026-03-28T18:00:00.000Z' }),
      ]),
      opportunitiesQuery([
        opportunityFixture({
          status: 'ACTIVE',
          address: null,
          slots: [
            opportunitySlot('SLOT#first', { label: 'First Sales' }),
            opportunitySlot('SLOT#booth', { label: 'Full Booth', startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T18:00:00.000Z', openCapacity: 1 }),
          ],
          mySignups: [participantSignup('SLOT#first', { signupVersion: 4, actualMinutes: 75 })],
        }),
      ]),
      calendarQuery(SSE_GROVE, 'SLOT#grove-am', AVERY, { ...CALENDAR_DATA, showAndSellId: SSE_GROVE, slotId: 'SLOT#grove-am' }),
    ]);

    // Avery holds two places at a different event; both sit in the panel so the
    // overlap can be seen from this page at all.
    expect(await screen.findByTestId(`commitment-${SSE_GROVE}-SLOT#grove-am`)).toBeInTheDocument();
    expect(screen.getByTestId(`commitment-${SSE_GROVE}-SLOT#grove-pm`)).toBeInTheDocument();

    const booth = screen.getByTestId('slot-offer-SLOT#booth');
    expect(within(booth).getByTestId('slot-conflict-SLOT#booth')).toHaveTextContent(
      'This overlaps a place you already hold (2 commitments), at this or another Show & Sell.',
    );
    // The server decides this refusal; the screen says why and leaves the call
    // to the write. First Sales overlaps the morning place (one commitment).
    const first = screen.getByTestId('slot-offer-SLOT#first');
    expect(within(first).getByTestId('slot-conflict-SLOT#first')).toHaveTextContent('1 commitment');

    // The place Avery holds here is running (status ACTIVE): the give button
    // is closed, because giving back is a pre-start act.
    expect(screen.getByTestId('give-SLOT#first')).toBeDisabled();

    // An invite for a place at the other event is still this browser's file.
    await user.click(screen.getByTestId('commitment-invite-SLOT#grove-am'));
    await waitFor(() => expect(download.anchors).toHaveLength(1));
    expect(download.anchors[0].href).toBe('blob:invite');
    expect(download.anchors[0].download).toBe('show-and-sell-SSE#grove-SLOT#grove-am.ics');
    expect(download.revokeObjectURL).toHaveBeenCalledWith('blob:invite');
    vi.unstubAllGlobals();
  });

  it('SLOT-02 (SS-SM-06 step 3): taking a capacity-1 place that is already gone answers CONFLICT, and the screen re-reads the count', async () => {
    const user = userEvent.setup();
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 1 })] })]),
      {
        request: {
          query: SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT,
          variables: {
            input: { showAndSellId: SSE, slotId: 'SLOT#first', campaignId: CAMP_AVERY, profileId: AVERY, idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        error: new GraphQLError('capacity: this slot is now full', { extensions: { code: 'CONFLICT' } }),
      },
      // The re-read after the refusal: Blake got the only place while Avery
      // was deciding, and the next take has to be against that count.
      opportunitiesQuery([opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 0 })] })]),
    ]);

    await user.click(await enabledTake('SLOT#first'));

    // No stack trace, no raw error text: the stale-refusal sentence, and the
    // list re-reads so the row now states the fact in the server's words.
    expect(await screen.findByText(STALE_SENTENCE)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('slot-availability-SLOT#first')).toHaveTextContent('This slot is full'));
    expect(screen.getByTestId('take-SLOT#first')).toBeDisabled();
    expect(screen.queryByTestId('signup-notice')).not.toBeInTheDocument();
  });

  it('VER-01 (SS-SM-05): cancelling a place sends the signup version the last answer carried', async () => {
    const user = userEvent.setup();
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([
        opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 0 })], mySignups: [participantSignup('SLOT#first', { signupVersion: 4 })] }),
      ]),
      {
        request: {
          query: CANCEL_SHOW_AND_SELL_SIGNUP,
          variables: {
            input: { showAndSellId: SSE, slotId: 'SLOT#first', profileId: AVERY, version: { expectedVersion: 4 }, idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { cancelShowAndSellSignup: participantSignup('SLOT#first', { status: 'CANCELLED', signupVersion: 5 }) } },
      },
      // Both reads re-read after the give, so the row states the fresh version.
      // The mock cache hands back the first answer, so the re-reads are proven
      // by being asked for at all.
      {
        request: { query: LIST_UNIT_CAMPAIGN_OPPORTUNITIES, variables: OPPORTUNITY_READ },
        result: { data: { unitCampaignOpportunities: { __typename: 'ShowAndSellOpportunityConnection', items: [opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 1 })], mySignups: [participantSignup('SLOT#first', { status: 'CANCELLED', signupVersion: 5 })] })], pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false } } } },
      },
      {
        request: { query: LIST_MY_SCOUT_COMMITMENTS, variables: { profileId: AVERY, includeCancelled: false, page: { limit: SHOW_AND_SELL_PAGE_SIZE } } },
        result: { data: { myScoutCommitments: { __typename: 'ParticipantCommitmentConnection', items: [], pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false } } } },
      },
    ]);

    await user.click(await screen.findByTestId('give-SLOT#first'));
    expect(await screen.findByText('You gave this place back. Anyone else may now take it.')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('slot-availability-SLOT#first')).toHaveTextContent('You gave this place back'));
  });

  it('CAL-01/CAL-02: a place just taken offers an invite this browser built itself — no server URL anywhere', async () => {
    const user = userEvent.setup();
    const download = stubBrowserDownload();
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 1 })] })]),
      signupMock('SLOT#first', CAMP_AVERY, AVERY, participantSignup('SLOT#first', { signupVersion: 1 })),
      // The re-read after the take still shows the list page as it stood, and
      // the mock cache keeps the first answer — the re-read is proven by being
      // asked for at all.
      {
        request: { query: LIST_UNIT_CAMPAIGN_OPPORTUNITIES, variables: OPPORTUNITY_READ },
        result: { data: { unitCampaignOpportunities: { __typename: 'ShowAndSellOpportunityConnection', items: [opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 0 })] })], pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false } } } },
      },
      calendarQuery(SSE, 'SLOT#first', AVERY, CALENDAR_DATA),
    ]);

    await user.click(await enabledTake('SLOT#first'));
    expect(
      await screen.findByText('You have a place in this slot. Download the calendar invite if you want it on your calendar.'),
    ).toBeInTheDocument();

    await user.click(await screen.findByTestId('invite-new-SLOT#first'));
    await waitFor(() => expect(download.anchors).toHaveLength(1));
    const anchor = download.anchors[0];
    // The anchor points at the object URL this tab minted, not at any URL the
    // server issued — the server holds no file, and nothing here downloads one.
    expect(anchor.href).toBe('blob:invite');
    expect(anchor.download).toBe('show-and-sell-SSE#library-SLOT#first.ics');
    expect(download.createObjectURL).toHaveBeenCalledTimes(1);
    expect(download.revokeObjectURL).toHaveBeenCalledWith('blob:invite');
    expect(document.querySelector(`a[href="blob:invite"]`)).toBeNull();
    vi.unstubAllGlobals();
  });

  it('SEC-04: every document this page reads or writes selects only participant-safe Show & Sell fields', () => {
    // The administrative projection carries allocations, stock quantities,
    // audit actors and the finalization pointers; none of them may appear on
    // the participant surface — the words themselves are the guard's list.
    const FORBIDDEN = [
      'ShowAndSellAdmin',
      'ShowAndSellAllocation',
      'fragment ShowAndSellSignupFields',
      'ShowAndSellWorkPreview',
      'allocations',
      'allocatedQty',
      'soldQty',
      'releasedQty',
      'remainingQty',
      'productIds',
      'activeSignupCount',
      'createdByAccountId',
      'updatedByAccountId',
      'cancelledByAccountId',
      'cancelledAt',
      'cancellationReason',
      'signedUpByAccountId',
      'confirmedByAccountId',
      'confirmedAt',
      'assignShowAndSellInventory',
      'upsertShowAndSellSlot',
      'deleteShowAndSellSlot',
      'ShowAndSellSlotFields',
      'ShowAndSellSlot }',
      'confirmShowAndSellWork',
      'showAndSellSignups',
      'eventInventoryAllocations',
    ];
    const documents = [
      LIST_UNIT_CAMPAIGN_OPPORTUNITIES,
      LIST_MY_SCOUT_COMMITMENTS,
      LIST_SCOUT_CAMPAIGN_JOINS,
      GET_SIGNUP_CALENDAR_DATA,
      SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT,
      CANCEL_SHOW_AND_SELL_SIGNUP,
    ];
    for (const document of documents) {
      const text = print(document);
      for (const field of FORBIDDEN) expect(text).not.toContain(field);
    }
    expect(print(LIST_UNIT_CAMPAIGN_OPPORTUNITIES)).toContain('ShowAndSellOpportunity');
    expect(print(LIST_UNIT_CAMPAIGN_OPPORTUNITIES)).toContain('ParticipantSignup');
    expect(print(LIST_MY_SCOUT_COMMITMENTS)).toContain('ParticipantCommitment');
    expect(print(GET_SIGNUP_CALENDAR_DATA)).toContain('showAndSellSignupCalendarData');
  });

  it('SEC-04: a slot another Scout holds shows the Scout nothing about that Scout', async () => {
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([
        opportunityFixture({
          slots: [
            // Charlie holds the only place in First Sales; Avery's own signup
            // here is cancelled history.
            opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 0 }),
            opportunitySlot('SLOT#booth', { label: 'Full Booth', startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T18:00:00.000Z', capacity: 1, openCapacity: 1 }),
          ],
          mySignups: [participantSignup('SLOT#first', { status: 'CANCELLED', signupVersion: 6 })],
        }),
      ]),
    ]);

    const first = await screen.findByTestId('slot-offer-SLOT#first');
    // Only what Avery's own signups answer: full is stated, and nobody else is
    // named, profile id or otherwise.
    expect(within(first).getByTestId('slot-availability-SLOT#first')).toHaveTextContent('You gave this place back');
    expect(within(first).getByTestId('take-SLOT#first')).toBeDisabled();

    const library = screen.getByTestId(`opportunity-${SSE}`);
    expect(library.textContent).not.toContain('PROFILE#');
    expect(library.textContent).not.toContain('Charlie');
    expect(library.textContent).not.toContain('Blake');
  });

  it('§2.3.1: the scout-campaign join read is what names the Scout Campaign the write addresses', async () => {
    const user = userEvent.setup();
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      // Avery's active join to this Unit Campaign, an inactive one (the roster
      // key cannot be), and a join to a different Unit Campaign.
      joinsQuery(AVERY, [campaignJoin(), campaignJoin({ campaignId: 'CAMP#old', isActive: false }), campaignJoin({ campaignId: 'CAMP#beth', unitCampaignId: `${UC()}-not-me` })]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 1 })] })]),
      signupMock('SLOT#first', CAMP_AVERY, AVERY, participantSignup('SLOT#first', { signupVersion: 1 })),
      // The mock cache keeps the first list answer; the re-read after the take
      // is proven by being asked for at all.
      {
        request: { query: LIST_UNIT_CAMPAIGN_OPPORTUNITIES, variables: OPPORTUNITY_READ },
        result: { data: { unitCampaignOpportunities: { __typename: 'ShowAndSellOpportunityConnection', items: [opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 0 })] })], pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false } } } },
      },
    ]);

    await user.click(await enabledTake('SLOT#first'));
    // The signup mock only matches with campaignId CAMP#avery-fall — the
    // active join read is what names the Scout Campaign the write addresses,
    // not the Unit Campaign id and not a campaign that belongs to someone else.
    expect(
      await screen.findByText('You have a place in this slot. Download the calendar invite if you want it on your calendar.'),
    ).toBeInTheDocument();
    // The re-read is mocked once, and MockedProvider hands that answer out at
    // most once — so the fresh signup is proven by the invite for the new place.
    await screen.findByTestId('invite-new-SLOT#first');
  });

  it('SS-SM-06 step 7: an unjoined Scout gets a sentence, not a blank page', async () => {
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      // Avery's profile exists but no campaign is joined to this Unit Campaign.
      joinsQuery(AVERY, [campaignJoin({ campaignId: 'CAMP#elsewhere', unitCampaignId: `${UC()}-not-me` })]),
      commitmentsQuery(AVERY, []),
      {
        request: { query: LIST_UNIT_CAMPAIGN_OPPORTUNITIES, variables: { unitCampaignId: UC(), includePast: false, page: { limit: SHOW_AND_SELL_PAGE_SIZE } } },
        error: new GraphQLError('this Scout is not on this campaign’s roster', { extensions: { code: 'FORBIDDEN' } }),
      },
    ]);

    // The refusal is a fact about the Scout's standing, in words, next to the
    // closed answer for the offers — never a blank screen.
    expect(await screen.findByText(NO_SHOW_AND_SELL)).toBeInTheDocument();
    expect(screen.getByTestId('not-on-roster')).toHaveTextContent(
      'This Scout is not on this campaign’s roster, so there is nothing to sign up for here. A Scout joins with the campaign’s join code.',
    );
    expect(screen.queryByTestId(`opportunity-${SSE}`)).not.toBeInTheDocument();
  });

  it('§3.5.3: the picker names every Scout this account may write as, and a WRITE share can take a place', async () => {
    const user = userEvent.setup();
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([
        shareFixture(),
        // A READ share can see an offer but cannot take a place: it is not in
        // the pickable set, because joining and signing up both write.
        shareFixture({ profileId: 'PROFILE#readonly', sellerName: 'Read Only Scout', permissions: ['READ'] }),
        // A shared Scout with no name is still chosen by something readable.
        shareFixture({ profileId: NO_NAME, sellerName: null }),
      ]),
      joinsQuery(AVERY, [campaignJoin()]),
      joinsQuery(SHARED, [campaignJoin({ campaignId: 'CAMP#shared-fall', campaignName: 'Shared 2026' })]),
      commitmentsQuery(AVERY, []),
      commitmentsQuery(SHARED, []),
      opportunitiesQuery([opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 1 })] })]),
      signupMock('SLOT#first', 'CAMP#shared-fall', SHARED, participantSignup('SLOT#first', { signupVersion: 1 })),
      // The mock cache keeps the first list answer; the re-read after the take
      // is proven by being asked for at all.
      {
        request: { query: LIST_UNIT_CAMPAIGN_OPPORTUNITIES, variables: OPPORTUNITY_READ },
        result: { data: { unitCampaignOpportunities: { __typename: 'ShowAndSellOpportunityConnection', items: [opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 0 })] })], pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false } } } },
      },
    ]);

    const picker = await screen.findByTestId('profile-picker');
    expect(picker.textContent).toContain('Avery Scout');
    expect(picker.textContent).not.toContain('Read Only Scout');

    // Picking the shared Scout switches whose join read and whose write run.
    const option = await findOption('profile-picker', 'Shared Scout', user);
    await user.click(option);
    await user.click(await enabledTake('SLOT#first'));
    // The signup mock above matched only with profileId SHARED and campaignId
    // CAMP#shared-fall — the join read of the picked Scout is what named it.
    expect(
      await screen.findByText('You have a place in this slot. Download the calendar invite if you want it on your calendar.'),
    ).toBeInTheDocument();
    await screen.findByTestId('invite-new-SLOT#first');
  });

  it('CAL-01: a calendar read that answers nothing is a sentence, not a broken download', async () => {
    const user = userEvent.setup();
    const download = stubBrowserDownload();
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([
        opportunityFixture({ slots: [opportunitySlot('SLOT#first', { label: 'First Sales', capacity: 1, openCapacity: 0 })], mySignups: [participantSignup('SLOT#first', { signupVersion: 2 })] }),
      ]),
      calendarQuery(SSE, 'SLOT#first', AVERY, null),
    ]);

    await user.click(await screen.findByTestId('invite-SLOT#first'));
    expect(await screen.findByText('The server answered no calendar data for this place.')).toBeInTheDocument();
    expect(download.anchors).toHaveLength(0);
    vi.unstubAllGlobals();
  });

  it('§3.5.3: an account with no Scout it can write as is told so, and the offers are not listed', async () => {
    renderPage([
      profilesQuery([]),
      sharesQuery([]),
      opportunitiesQuery([opportunityFixture()]),
    ]);

    // SEC-04/§2.3.1: with no profile this account may sign up as, there is no Scout
    // to speak for, so the page answers the roster sentence rather than listing what
    // is on offer with controls that could only fail.
    await screen.findByTestId('not-on-roster');
    expect(screen.queryByTestId(`opportunity-${SSE}`)).toBeNull();
    // The picker is locked: there is no Scout this account may write as, so the
    // screen cannot address a signup at all.
    const picker = screen.getByTestId('profile-picker').querySelector('.MuiSelect-select') as HTMLElement;
    expect(picker).toHaveAttribute('aria-disabled', 'true');
  });

  it('§3.5.3: a campaign with nothing scheduled says so instead of an empty list', async () => {
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([]),
    ]);

    await screen.findByText('Nothing is on offer here right now');
    expect(screen.queryByTestId(`opportunity-${SSE}`)).toBeNull();
  });

  it('§3.5.3: a slot the Kernel left unnamed is still offered, named by what it is', async () => {
    renderPage([
      profilesQuery([profileFixture()]),
      sharesQuery([]),
      joinsQuery(AVERY, [campaignJoin()]),
      commitmentsQuery(AVERY, []),
      opportunitiesQuery([
        opportunityFixture({ slots: [opportunitySlot('SLOT#anon', { label: null, capacity: 2, openCapacity: 2 })] }),
      ]),
    ]);

    const offer = await screen.findByTestId('slot-offer-SLOT#anon');
    expect(within(offer).getByTestId('slot-offer-label-SLOT#anon')).toHaveTextContent('Slot');
    // An unnamed slot is still a place a Scout can take: the name is cosmetic, the
    // interval and the open count are what the write is addressed by.
    expect(within(offer).getByTestId('take-SLOT#anon')).toBeEnabled();
  });
});
