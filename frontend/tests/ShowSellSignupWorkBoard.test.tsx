/**
 * The signup board and work confirmation of one event (§3.5.4, built on
 * §3.4.1-§3.4.5; SS-SM-06 steps 9-10, CAL-01/CAL-02).
 *
 * What each assertion pins, and why it matters:
 *
 * - A signup is not worked time (SLOT-05): the minutes column starts at what
 *   the server stores, empty until a Kernel enters a number, and a cancelled
 *   signup stays on the board — it is the history an audit question asks about.
 * - 75 minutes in the 90-minute slot and 115 in the 120-minute slot are SS-SM-06
 *   step 9: two rows sent, nothing else, and the preview under the board is the
 *   SERVER's pending picture (190 minutes is a computed number, never a sum
 *   this screen invents).
 * - 115 in the 90-minute slot is refused in the form with no write, so the
 *   other rows the admin typed are not thrown away by a batch-wide server
 *   refusal; entering 0 IS a write, because un-confirming is not deleting.
 * - A batch over 100 rows is refused at the ceiling before anything is sent.
 * - The calendar button reads the authorized invite fields and hands the
 *   browser a file it assembled itself — object URL minted here, revoked here,
 *   no server artifact anywhere (CAL-01, CAL-02).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { SignupWorkBoard } from '../src/components/showSell/SignupWorkBoard';
import {
  CONFIRM_SHOW_AND_SELL_WORK,
  GET_SIGNUP_CALENDAR_DATA,
  LIST_SHOW_AND_SELL_SIGNUPS,
  LIST_UNIT_CAMPAIGN_ROSTER,
} from '../src/lib/graphql';
import { SHOW_AND_SELL_PAGE_SIZE, workRowKey } from '../src/lib/showSell';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { clearAndType } from './helpers/unitUi';
import type {
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSignupFieldsFragment,
  GqlUnitCampaignMembershipFieldsFragment,
} from '../src/types/graphql-generated';

const UC = 'UNITCAMP#pack-3149-fall';
const SSE = 'SSE#library';
const ZONE = 'America/Denver';
const AVERY = 'PROFILE#avery';
const BLAKE = 'PROFILE#blake';
const DANA = 'PROFILE#dana';

const SIGNUP_VARIABLES = { showAndSellId: SSE, status: undefined, page: { limit: SHOW_AND_SELL_PAGE_SIZE } };
const ROSTER_VARIABLES = { unitCampaignId: UC, status: undefined, page: { limit: UNIT_PAGE_SIZE } };

const STALE_SENTENCE =
  'That was refused because the event, a slot, or a signup has already moved. Reload this screen and try again with what it now shows.';

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function signupFixture(overrides: Partial<GqlShowAndSellSignupFieldsFragment> = {}): GqlShowAndSellSignupFieldsFragment {
  return {
    __typename: 'ShowAndSellSignup',
    showAndSellId: SSE,
    slotId: 'SLOT#first',
    profileId: AVERY,
    unitCampaignId: UC,
    campaignId: 'CAMP#avery-fall',
    status: 'ACTIVE',
    actualMinutes: 0,
    signedUpByAccountId: 'ACCOUNT#casey',
    confirmedByAccountId: null,
    confirmedAt: null,
    version: 2,
    createdAt: '2026-03-25T15:00:00.000Z',
    updatedAt: '2026-03-25T15:00:00.000Z',
    ...overrides,
  };
}

function rosterFixture(overrides: Partial<GqlUnitCampaignMembershipFieldsFragment> = {}): GqlUnitCampaignMembershipFieldsFragment {
  return {
    __typename: 'UnitCampaignMembership',
    unitCampaignId: UC,
    unitId: 'UNIT#pack-3149',
    campaignId: 'CAMP#avery-fall',
    profileId: AVERY,
    scoutName: 'Avery Scout',
    campaignName: 'Avery Fall Campaign',
    scoutCampaignCatalogId: 'CATALOG#popcorn-2026',
    status: 'ACTIVE',
    joinedByAccountId: 'ACCOUNT#avery',
    joinedAt: '2026-01-06T15:00:00Z',
    removedByAccountId: null,
    removedAt: null,
    version: 1,
    guardVersion: 1,
    ...overrides,
  };
}

function eventFixture(overrides: Partial<GqlShowAndSellAdminFieldsFragment> = {}): GqlShowAndSellAdminFieldsFragment {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: SSE,
    unitId: 'UNIT#pack-3149',
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: null,
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:30:00.000Z',
    status: 'ACTIVE',
    splitMethod: 'TIME_WORKED',
    weOweEnabled: false,
    productIds: [],
    allocations: [],
    slots: [
      {
        __typename: 'ShowAndSellSlot',
        showAndSellId: SSE,
        slotId: 'SLOT#first',
        label: 'First Sales',
        startAt: '2026-03-28T15:00:00.000Z',
        endAt: '2026-03-28T16:30:00.000Z',
        capacity: 1,
        activeSignupCount: 1,
        version: 3,
        createdAt: '2026-03-21T15:00:00.000Z',
        updatedAt: '2026-03-21T15:00:00.000Z',
      },
      {
        __typename: 'ShowAndSellSlot',
        showAndSellId: SSE,
        slotId: 'SLOT#midday',
        label: 'Midday',
        startAt: '2026-03-28T16:30:00.000Z',
        endAt: '2026-03-28T18:30:00.000Z',
        capacity: 1,
        activeSignupCount: 1,
        version: 3,
        createdAt: '2026-03-21T15:00:00.000Z',
        updatedAt: '2026-03-21T15:00:00.000Z',
      },
    ],
    version: 7,
    createdAt: '2026-03-21T15:00:00.000Z',
    updatedAt: '2026-03-21T15:00:00.000Z',
    createdByAccountId: 'ACCOUNT#casey',
    updatedByAccountId: 'ACCOUNT#casey',
    cancelledByAccountId: null,
    cancelledAt: null,
    cancellationReason: null,
    ...overrides,
  };
}

function signupsQuery(items: unknown[]) {
  return {
    request: { query: LIST_SHOW_AND_SELL_SIGNUPS, variables: SIGNUP_VARIABLES },
    result: {
      data: {
        showAndSellSignups: {
          __typename: 'ShowAndSellSignupConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function rosterQuery(items: unknown[]) {
  return {
    request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: ROSTER_VARIABLES },
    result: {
      data: {
        unitCampaignRoster: {
          __typename: 'UnitCampaignMembershipConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function renderBoard(mocks: unknown[], event = eventFixture()) {
  const onChanged = vi.fn(async () => undefined);
  render(
    <MockedProvider mocks={mocks as never}>
      <SignupWorkBoard event={event} timezone={ZONE} onChanged={onChanged} />
    </MockedProvider>,
  );
  return onChanged;
}

/** Stands in for the browser half of a download: the object URL, and the click. */
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

const calendarData = {
  __typename: 'CalendarInviteData',
  unitId: 'UNIT#pack-3149',
  unitDisplayName: 'Pack 3149',
  unitCampaignId: UC,
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

describe('SignupWorkBoard', () => {
  it('SLOT-05: the board shows each signup’s slot and the minutes the server says are confirmed today', async () => {
    renderBoard([
      signupsQuery([
        signupFixture({ profileId: BLAKE }),
        signupFixture({ profileId: DANA }),
        signupFixture({ slotId: 'SLOT#midday' }),
        signupFixture({ slotId: 'SLOT#midday', profileId: BLAKE, status: 'CANCELLED', actualMinutes: 60, confirmedByAccountId: 'ACCOUNT#casey', confirmedAt: '2026-03-28T19:00:00.000Z' }),
        signupFixture(),
      ]),
      rosterQuery([rosterFixture(), rosterFixture({ profileId: BLAKE, campaignId: 'CAMP#blake-fall' })]),
    ]);

    // Ordered by slot, then Scout — the order the confirmation batch is read back in.
    const rows = await screen.findAllByTestId(/^signup-row-/);
    expect(rows.map((row) => row.getAttribute('data-testid'))).toEqual([
      `signup-row-${workRowKey('SLOT#first', AVERY)}`,
      `signup-row-${workRowKey('SLOT#first', BLAKE)}`,
      `signup-row-${workRowKey('SLOT#first', DANA)}`,
      `signup-row-${workRowKey('SLOT#midday', AVERY)}`,
      `signup-row-${workRowKey('SLOT#midday', BLAKE)}`,
    ]);

    const avery = screen.getByTestId(`signup-row-${workRowKey('SLOT#first', AVERY)}`);
    expect(avery).toHaveTextContent('Avery Scout');
    expect(avery).toHaveTextContent('First Sales');
    expect(avery).toHaveTextContent('Holding a place');
    // A place held is not time worked (SLOT-05): the minutes start empty at zero.
    expect(screen.getByTestId(`work-minutes-${workRowKey('SLOT#first', AVERY)}`)).toHaveValue('0');
    expect(avery).toHaveTextContent('Not confirmed');

    // A cancelled confirmation stays on the board as history, minutes and all,
    // and a Scout whose roster row cannot be read is still named by id.
    const cancelled = screen.getByTestId(`signup-row-${workRowKey('SLOT#midday', BLAKE)}`);
    expect(cancelled).toHaveTextContent('Cancelled');
    expect(cancelled).toHaveTextContent('Kernel');
    expect(screen.getByTestId(`work-minutes-${workRowKey('SLOT#midday', BLAKE)}`)).toHaveValue('60');
    expect(screen.getByTestId(`signup-scout-${workRowKey('SLOT#first', DANA)}`)).toHaveTextContent(DANA);

    // The pending picture is the write's answer, so there is none before a save.
    expect(screen.getByTestId('work-preview-empty')).toBeInTheDocument();
  });

  it('SLOT-05 (SS-SM-06 step 9): 75 in the 90-minute slot and 115 in the 120-minute slot are exactly two work rows, with the server’s preview', async () => {
    const user = userEvent.setup();
    const onChanged = renderBoard([
      signupsQuery([signupFixture(), signupFixture({ slotId: 'SLOT#midday' }), signupFixture({ profileId: BLAKE })]),
      rosterQuery([rosterFixture(), rosterFixture({ profileId: BLAKE, campaignId: 'CAMP#blake-fall' })]),
      {
        request: {
          query: CONFIRM_SHOW_AND_SELL_WORK,
          variables: {
            input: {
              showAndSellId: SSE,
              work: [
                { slotId: 'SLOT#first', profileId: AVERY, actualMinutes: 75 },
                { slotId: 'SLOT#midday', profileId: AVERY, actualMinutes: 115 },
              ],
              version: { expectedVersion: 7 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            confirmShowAndSellWork: {
              __typename: 'ConfirmShowAndSellWorkPayload',
              work: [
                signupFixture({ actualMinutes: 75, confirmedByAccountId: 'ACCOUNT#casey', confirmedAt: '2026-03-28T19:00:00.000Z' }),
                signupFixture({ slotId: 'SLOT#midday', actualMinutes: 115, confirmedByAccountId: 'ACCOUNT#casey', confirmedAt: '2026-03-28T19:00:00.000Z' }),
              ],
              preview: {
                __typename: 'ShowAndSellWorkPreview',
                eventVersion: 8,
                totalConfirmedMinutes: 190,
                confirmedWorkRows: 2,
                confirmedParticipants: 1,
                minimumFinalizationActions: 4,
              },
            },
          },
        },
      },
    ]);

    // Blake's row is deliberately left blank: an untouched row is not a zero.
    await clearAndType(`work-minutes-${workRowKey('SLOT#first', AVERY)}`, '75', user);
    await clearAndType(`work-minutes-${workRowKey('SLOT#midday', AVERY)}`, '115', user);
    await user.click(await screen.findByTestId('save-work'));

    // Only the two typed rows reach the server (the mock matches those exact
    // variables), and 190 is the server's total, not a sum made here.
    expect(await screen.findByTestId('work-preview')).toBeInTheDocument();
    expect(screen.getByTestId('preview-minutes')).toHaveTextContent('190 confirmed minutes');
    expect(screen.getByTestId('preview-rows')).toHaveTextContent('2 confirmed rows');
    expect(screen.getByTestId('preview-people')).toHaveTextContent('1');
    expect(screen.getByTestId('preview-actions')).toHaveTextContent('4 finalization actions needed');
    expect(screen.getByTestId('work-preview')).toHaveTextContent('Pending work picture (event version 8)');
    expect(screen.getByTestId('work-saved-count')).toHaveTextContent('2 work rows saved.');
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('§3.4.3: 115 in the 90-minute slot is refused in the form, with no write', async () => {
    const user = userEvent.setup();
    // No write mock in this test: the batch never leaves the screen, so the
    // other row the admin typed is not thrown away by a server refusal.
    const onChanged = renderBoard([
      signupsQuery([signupFixture(), signupFixture({ slotId: 'SLOT#midday' })]),
      rosterQuery([rosterFixture()]),
    ]);

    await clearAndType(`work-minutes-${workRowKey('SLOT#first', AVERY)}`, '115', user);
    await clearAndType(`work-minutes-${workRowKey('SLOT#midday', AVERY)}`, '115', user);
    await user.click(await screen.findByTestId('save-work'));

    expect(
      await screen.findByText('This slot is 1 hour 30 minutes long, so a Scout cannot have worked more than that.'),
    ).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('§3.4.3: entering 0 un-confirms as a write, and the signup row stays where it was', async () => {
    const user = userEvent.setup();
    const onChanged = renderBoard([
      signupsQuery([signupFixture({ actualMinutes: 75, confirmedByAccountId: 'ACCOUNT#casey', confirmedAt: '2026-03-28T19:00:00.000Z' })]),
      rosterQuery([rosterFixture()]),
      {
        request: {
          query: CONFIRM_SHOW_AND_SELL_WORK,
          variables: {
            input: {
              showAndSellId: SSE,
              work: [{ slotId: 'SLOT#first', profileId: AVERY, actualMinutes: 0 }],
              version: { expectedVersion: 7 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            confirmShowAndSellWork: {
              __typename: 'ConfirmShowAndSellWorkPayload',
              work: [signupFixture({ actualMinutes: 0, confirmedByAccountId: null, confirmedAt: null })],
            },
          },
        },
      },
    ]);

    await clearAndType(`work-minutes-${workRowKey('SLOT#first', AVERY)}`, '0', user);
    await user.click(await screen.findByTestId('save-work'));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    // The row still exists and still holds its place: zero takes the
    // confirmation back, it does not delete the Scout's history.
    expect(screen.getByTestId(`signup-row-${workRowKey('SLOT#first', AVERY)}`)).toBeInTheDocument();
    expect(screen.getByTestId('work-saved-count')).toHaveTextContent('1 work row saved.');
    expect(screen.getByTestId('work-preview-empty')).toBeInTheDocument();
  });

  it('§3.4.3: a batch over 100 rows is refused with the ceiling sentence, and nothing is sent', async () => {
    const crowd = Array.from({ length: 101 }, (_, index) => signupFixture({ profileId: `PROFILE#s${index}` }));
    renderBoard([signupsQuery(crowd), rosterQuery([])]);

    await screen.findAllByTestId(/^signup-row-/);
    // A crowd this big is fixture, not behavior: the rows are filled with one
    // synthetic change each, and the behavior under test is the refusal.
    for (const signup of crowd) {
      fireEvent.change(screen.getByTestId(`work-minutes-${workRowKey('SLOT#first', signup.profileId)}`), { target: { value: '10' } });
    }
    fireEvent.click(screen.getByTestId('save-work'));

    expect(await screen.findByText('Save at most 100 work rows at a time.')).toBeInTheDocument();
  }, 30_000);

  it('SLOT-05 (VER-01): a CONFLICT on the batch names the refusal and reloads the board', async () => {
    const user = userEvent.setup();
    const onChanged = renderBoard([
      signupsQuery([signupFixture()]),
      rosterQuery([rosterFixture()]),
      {
        request: {
          query: CONFIRM_SHOW_AND_SELL_WORK,
          variables: {
            input: {
              showAndSellId: SSE,
              work: [{ slotId: 'SLOT#first', profileId: AVERY, actualMinutes: 75 }],
              version: { expectedVersion: 7 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('event version moved', { extensions: { code: 'CONFLICT' } }),
      },
    ]);

    await clearAndType(`work-minutes-${workRowKey('SLOT#first', AVERY)}`, '75', user);
    await user.click(await screen.findByTestId('save-work'));

    expect(await screen.findByText(STALE_SENTENCE)).toBeInTheDocument();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('SLOT-05: re-typing the stored minutes writes nothing, because nothing moved', async () => {
    const user = userEvent.setup();
    // No write mock: a batch of unchanged rows must not move the event version
    // or the audit trail.
    const onChanged = renderBoard([
      signupsQuery([signupFixture({ actualMinutes: 75 })]),
      rosterQuery([rosterFixture()]),
    ]);

    await clearAndType(`work-minutes-${workRowKey('SLOT#first', AVERY)}`, '75', user);
    await user.click(await screen.findByTestId('save-work'));

    await waitFor(() => expect(onChanged).not.toHaveBeenCalled());
    expect(screen.queryByTestId('work-saved-count')).not.toBeInTheDocument();
    expect(screen.queryByTestId('work-preview')).not.toBeInTheDocument();
  });

  it('CAL-01/CAL-02 (SS-SM-06 step 2): the calendar button reads the signup data and hands the browser a file it built itself', async () => {
    const user = userEvent.setup();
    const download = stubBrowserDownload();
    renderBoard([
      signupsQuery([signupFixture()]),
      rosterQuery([rosterFixture()]),
      {
        request: {
          query: GET_SIGNUP_CALENDAR_DATA,
          variables: { showAndSellId: SSE, slotId: 'SLOT#first', profileId: AVERY },
        },
        result: { data: { showAndSellSignupCalendarData: calendarData } },
      },
    ]);

    await user.click(await screen.findByTestId(`invite-${workRowKey('SLOT#first', AVERY)}`));

    await waitFor(() => expect(download.anchors).toHaveLength(1));
    const anchor = download.anchors[0];
    // The href is the object URL this tab minted a moment ago — never a URL
    // the server handed out, because the server holds no file at all (CAL-02).
    expect(anchor.href).toBe('blob:invite');
    expect(anchor.download).toBe('show-and-sell-SSE#library-SLOT#first.ics');
    expect(download.createObjectURL).toHaveBeenCalledTimes(1);
    expect(download.revokeObjectURL).toHaveBeenCalledWith('blob:invite');
    expect(document.querySelector(`a[href="blob:invite"]`)).toBeNull();
    vi.unstubAllGlobals();
  });

  it('CAL-01: a signup with no calendar data answered gets a sentence, not a broken file', async () => {
    const user = userEvent.setup();
    const download = stubBrowserDownload();
    renderBoard([
      signupsQuery([signupFixture()]),
      rosterQuery([rosterFixture()]),
      {
        request: {
          query: GET_SIGNUP_CALENDAR_DATA,
          variables: { showAndSellId: SSE, slotId: 'SLOT#first', profileId: AVERY },
        },
        result: { data: { showAndSellSignupCalendarData: null } },
      },
    ]);

    await user.click(await screen.findByTestId(`invite-${workRowKey('SLOT#first', AVERY)}`));

    expect(await screen.findByText('The server answered no calendar data for this signup.')).toBeInTheDocument();
    expect(download.anchors).toHaveLength(0);
    vi.unstubAllGlobals();
  });

  it('§3.4.3: the work board is locked while the event’s state does not allow confirmation', async () => {
    renderBoard([signupsQuery([signupFixture()]), rosterQuery([rosterFixture()])], eventFixture({ status: 'SCHEDULED' }));

    expect(await screen.findByTestId('work-locked-note')).toHaveTextContent(
      'Worked time is entered while the event is running, after it ends, or while it is reopened for correction. This event’s state does not allow it.',
    );
    expect(await screen.findByTestId(`work-minutes-${workRowKey('SLOT#first', AVERY)}`)).toBeDisabled();
    expect(screen.getByTestId('save-work')).toBeDisabled();
  });

  it('§3.5.4: a signup read that failed is not shown as an empty one', async () => {
    renderBoard([
      {
        request: { query: LIST_SHOW_AND_SELL_SIGNUPS, variables: SIGNUP_VARIABLES },
        error: new GraphQLError('Service unavailable.'),
      },
      rosterQuery([rosterFixture()]),
    ]);

    expect(await screen.findByText('Could not load this event’s signups.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('§3.5.4: an event with no places taken says so, and there is nothing to confirm', async () => {
    renderBoard([signupsQuery([]), rosterQuery([rosterFixture()])]);

    expect(await screen.findByTestId('no-signups')).toHaveTextContent('No Scout has a place in this event yet.');
    expect(screen.getByTestId('save-work')).toBeEnabled();
  });
});
