/**
 * The slot board: every working slot of one Show & Sell event (§3.5.3 admin
 * surface, SS-SM-06 steps 1-8).
 *
 * What each assertion pins, and why it matters:
 *
 * - Slots are listed in start order with each slot's capacity and the signup
 *   count the SERVER keeps on the slot row. The board never recomputes a
 *   capacity balance it has no authority over (SEC-05).
 * - The three SS-SM-06 slots — 90, 120 and 180 minutes — are created with the
 *   UTC instants converted from the Unit's zone (`America/Denver`), never the
 *   browser's. A screen that read the boxes in the viewer's zone would move
 *   the event by the difference (SLOT-01, SSE-03: no hourly rule exists).
 * - A slot that reaches outside the event's immutable window, and capacities
 *   outside 1-100, are refused in the form with no write at all: those writes
 *   could only be refused (SLOT-01, §3.3.2).
 * - The 20-slot ceiling shows twice over: the board stops offering another
 *   slot at 20, and a server `INVALID_INPUT` against the 21st is shown as the
 *   sentence, not a code.
 * - A slot that holds Scouts is not deletable and says why (§3.3.3): a place
 *   a Scout holds must not vanish with the row that granted it.
 * - A `CONFLICT` (stale `expectedVersion`) shows the stale-row sentence AND
 *   reloads the board, so the next attempt is against what the row says now.
 * - A non-Admin's write is refused `FORBIDDEN` and the screen says only a
 *   Unit Admin can make this change — nothing is created.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { SlotBoard } from '../src/components/showSell/SlotBoard';
import { DELETE_SHOW_AND_SELL_SLOT, UPSERT_SHOW_AND_SELL_SLOT } from '../src/lib/graphql';
import { clearAndType, typeInto } from './helpers/unitUi';
import type {
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSlotFieldsFragment,
} from '../src/types/graphql-generated';

const UC = 'UNITCAMP#pack-3149-fall';
const SSE = 'SSE#library';
const ZONE = 'America/Denver';

// SS-SM-06's event: `Library on Main`, 2026-03-28, 09:00–12:30 in the Unit's
// own zone. The boxes carry wall clock; the write carries the UTC instants.
const EVENT_START = '2026-03-28T15:00:00.000Z';
const EVENT_END = '2026-03-28T18:30:00.000Z';

const STALE_SENTENCE =
  'That was refused because the event, a slot, or a signup has already moved. Reload this screen and try again with what it now shows.';
const FIT_SENTENCE = 'The slot has to fit inside the event — it cannot start before it or end after it.';
const CAPACITY_SENTENCE = 'A slot holds between 1 and 100 Scouts.';

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function slotFixture(overrides: Partial<GqlShowAndSellSlotFieldsFragment> = {}): GqlShowAndSellSlotFieldsFragment {
  return {
    __typename: 'ShowAndSellSlot',
    showAndSellId: SSE,
    slotId: 'SLOT#first',
    label: 'First Sales',
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T16:30:00.000Z',
    capacity: 1,
    activeSignupCount: 0,
    version: 3,
    createdAt: '2026-03-21T15:00:00.000Z',
    updatedAt: '2026-03-21T15:00:00.000Z',
    ...overrides,
  };
}

function eventFixture(
  slots: GqlShowAndSellSlotFieldsFragment[],
  overrides: Partial<GqlShowAndSellAdminFieldsFragment> = {},
): GqlShowAndSellAdminFieldsFragment {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: SSE,
    unitId: 'UNIT#pack-3149',
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: null,
    startAt: EVENT_START,
    endAt: EVENT_END,
    status: 'SCHEDULED',
    splitMethod: 'TIME_WORKED',
    weOweEnabled: false,
    productIds: [],
    allocations: [],
    slots,
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

/** N distinct empty slots, for the 20-slot ceiling. */
function filledSlotList(count: number): GqlShowAndSellSlotFieldsFragment[] {
  return Array.from({ length: count }, (_, index) =>
    slotFixture({ slotId: `SLOT#f${index}`, label: `Slot ${index + 1}`, version: index + 1 }),
  );
}

function upsertMock(input: Record<string, unknown>, slot: GqlShowAndSellSlotFieldsFragment) {
  return {
    request: { query: UPSERT_SHOW_AND_SELL_SLOT, variables: { input } },
    result: { data: { upsertShowAndSellSlot: slot } },
  };
}

function refusedUpsert(input: Record<string, unknown>, code: string, message: string) {
  return {
    request: { query: UPSERT_SHOW_AND_SELL_SLOT, variables: { input } },
    error: new GraphQLError(message, { extensions: { code } }),
  };
}

function renderBoard(event: GqlShowAndSellAdminFieldsFragment, mocks: unknown[] = []) {
  const onChanged = vi.fn(async () => undefined);
  render(
    <MockedProvider mocks={mocks as never}>
      <SlotBoard event={event} timezone={ZONE} onChanged={onChanged} />
    </MockedProvider>,
  );
  return onChanged;
}

/** Opens the add dialog and fills the interval and capacity in the Unit's zone. */
async function fillSlotDialog(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
  startAt: string,
  endAt: string,
  capacity: string,
) {
  await user.click(await screen.findByTestId('add-slot'));
  if (label !== '') await typeInto('slot-label-input', label, user);
  await clearAndType('slot-start-input', startAt, user);
  await clearAndType('slot-end-input', endAt, user);
  await clearAndType('slot-capacity-input', capacity, user);
  await user.click(screen.getByTestId('submit-slot'));
}

describe('SlotBoard', () => {
  it('SLOT-01: the board lists the SS-SM-06 slots in start order with each capacity and the server-counted signups', async () => {
    // Deliberately out of order, and with one slot the server counts holding
    // Scouts: the counts on this screen are the slot row's own, never a
    // subtraction the board makes from capacity.
    const event = eventFixture([
      slotFixture({ slotId: 'SLOT#midday', label: 'Midday', startAt: '2026-03-28T16:30:00.000Z', endAt: '2026-03-28T18:30:00.000Z' }),
      slotFixture({ slotId: 'SLOT#booth', label: 'Full Booth', startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T18:00:00.000Z', activeSignupCount: 1 }),
      slotFixture({ slotId: 'SLOT#sweep', label: null, startAt: '2026-03-28T18:00:00.000Z', endAt: '2026-03-28T18:30:00.000Z', capacity: 2 }),
      slotFixture({ activeSignupCount: 1 }),
    ]);
    renderBoard(event);

    const rows = screen.getAllByTestId(/^slot-row-/);
    expect(rows.map((row) => row.getAttribute('data-testid'))).toEqual([
      'slot-row-SLOT#booth',
      'slot-row-SLOT#first',
      'slot-row-SLOT#midday',
      'slot-row-SLOT#sweep',
    ]);

    const first = screen.getByTestId('slot-row-SLOT#first');
    expect(within(first).getByTestId('slot-capacity-SLOT#first')).toHaveTextContent('1');
    expect(within(first).getByTestId('slot-held-SLOT#first')).toHaveTextContent('1');
    // Any length is a real length — no hourly assumption in the copy (SSE-03).
    expect(within(first).getByTestId('slot-length-SLOT#first')).toHaveTextContent('1 hour 30 minutes');
    expect(within(screen.getByTestId('slot-row-SLOT#midday')).getByTestId('slot-length-SLOT#midday')).toHaveTextContent('2 hours');
    expect(within(screen.getByTestId('slot-row-SLOT#booth')).getByTestId('slot-length-SLOT#booth')).toHaveTextContent('3 hours');
    // A slot the Kernel never named still reads as a row: the label cell keeps
    // its place and the delete button names the slot by its id.
    expect(within(screen.getByTestId('slot-row-SLOT#sweep')).getByTestId('slot-label-SLOT#sweep')).toHaveTextContent('—');
    expect(screen.getByRole('button', { name: 'Delete slot SLOT#sweep' })).toBeEnabled();

    expect(screen.getByTestId('slot-count')).toHaveTextContent('4 of 20 slots used');
    expect(screen.queryByTestId('slot-limit-note')).not.toBeInTheDocument();
  });

  it('SLOT-01 (SS-SM-06 steps 1-4): creating the 90, 120 and 180 minute slots sends UTC instants converted from the Unit zone', async () => {
    const user = userEvent.setup();
    // These mocks match the variables the writes must carry, so a wrong zone
    // conversion would leave the mutation unmatched and the write unmade:
    // `09:00` in the Unit's zone on 2026-03-28 is 15:00Z.
    const onChanged = renderBoard(eventFixture([]), [
      upsertMock(
        {
          showAndSellId: SSE,
          label: 'First Sales',
          startAt: '2026-03-28T15:00:00.000Z',
          endAt: '2026-03-28T16:30:00.000Z',
          capacity: 1,
          version: { expectedVersion: 7 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        slotFixture(),
      ),
      upsertMock(
        {
          showAndSellId: SSE,
          label: 'Midday',
          startAt: '2026-03-28T16:30:00.000Z',
          endAt: '2026-03-28T18:30:00.000Z',
          capacity: 1,
          version: { expectedVersion: 7 },
          idempotency: { idempotencyKey: 'test-idem-2' },
        },
        slotFixture({ slotId: 'SLOT#midday', label: 'Midday' }),
      ),
      upsertMock(
        {
          showAndSellId: SSE,
          label: 'Full Booth',
          startAt: '2026-03-28T15:00:00.000Z',
          endAt: '2026-03-28T18:00:00.000Z',
          capacity: 1,
          version: { expectedVersion: 7 },
          idempotency: { idempotencyKey: 'test-idem-3' },
        },
        slotFixture({ slotId: 'SLOT#booth', label: 'Full Booth' }),
      ),
    ]);
    expect(await screen.findByTestId('no-slots')).toHaveTextContent(
      'This event has no working slots yet, so Scouts have nothing to sign up for.',
    );

    await fillSlotDialog(user, 'First Sales', '2026-03-28T09:00', '2026-03-28T10:30', '1');
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByTestId('submit-slot')).not.toBeInTheDocument());

    await fillSlotDialog(user, 'Midday', '2026-03-28T10:30', '2026-03-28T12:30', '1');
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));

    await fillSlotDialog(user, 'Full Booth', '2026-03-28T09:00', '2026-03-28T12:00', '1');
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(3));
  });

  it('§3.3.2: a slot that reaches outside the event window is refused in the form, with no write', async () => {
    const user = userEvent.setup();
    const onChanged = renderBoard(eventFixture([]));

    // The dialog starts at the event's own window; the admin shortens it wrong.
    await fillSlotDialog(user, '', '2026-03-28T08:00', '2026-03-28T09:30', '1');
    expect(await screen.findByText(FIT_SENTENCE)).toBeInTheDocument();

    await clearAndType('slot-start-input', '2026-03-28T11:00', user);
    await clearAndType('slot-end-input', '2026-03-28T13:30', user);
    await user.click(screen.getByTestId('submit-slot'));
    await waitFor(() => expect(screen.getAllByText(FIT_SENTENCE).length).toBeGreaterThan(0));
    // No write mock exists at all, and the reload that follows every accepted
    // write was never called: the refusal happened in the form.
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByTestId('submit-slot')).toBeInTheDocument();
  });

  it('§3.3.2: capacity 0 and capacity 101 are refused in the form, with no write', async () => {
    const user = userEvent.setup();
    const onChanged = renderBoard(eventFixture([]));

    await fillSlotDialog(user, '', '2026-03-28T09:00', '2026-03-28T10:30', '0');
    expect(await screen.findByText(CAPACITY_SENTENCE)).toBeInTheDocument();

    await clearAndType('slot-capacity-input', '101', user);
    await user.click(screen.getByTestId('submit-slot'));
    await waitFor(() => expect(screen.getAllByText(CAPACITY_SENTENCE).length).toBeGreaterThan(0));
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('§3.3.2: at 20 slots the board stops offering another', async () => {
    renderBoard(eventFixture(filledSlotList(20)));

    await waitFor(() => expect(screen.getByTestId('add-slot')).toBeDisabled());
    expect(screen.getByTestId('slot-count')).toHaveTextContent('20 of 20 slots used');
    expect(screen.getByTestId('slot-limit-note')).toHaveTextContent('An event holds at most 20 slots.');
  });

  it('SLOT-01: the 21st slot is refused by the server as a sentence, not a code', async () => {
    const user = userEvent.setup();
    // 19 slots: the board still offers one, and the server is the one that
    // refuses the 21st — the screen shows its refusal as a sentence.
    const onChanged = renderBoard(eventFixture(filledSlotList(19)), [
      refusedUpsert(
        {
          showAndSellId: SSE,
          label: null,
          startAt: '2026-03-28T15:00:00.000Z',
          endAt: '2026-03-28T18:30:00.000Z',
          capacity: 1,
          version: { expectedVersion: 7 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        'INVALID_INPUT',
        'an event holds at most 20 slots',
      ),
    ]);

    await fillSlotDialog(user, '', '2026-03-28T09:00', '2026-03-28T12:30', '1');
    expect(await screen.findByText('The server refused what was entered. Check the values and try again.')).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByTestId('submit-slot')).toBeInTheDocument();
  });

  it('§3.3.2: a started event with 20 slots says its board is already full and closed', async () => {
    renderBoard(eventFixture(filledSlotList(20), { status: 'ACTIVE' }));

    await waitFor(() => expect(screen.getByTestId('add-slot')).toBeDisabled());
    expect(screen.getByTestId('slot-limit-note')).toHaveTextContent(
      'This event already holds 20 slots, and its board is closed.',
    );
  });

  it('SLOT-02 (§3.3.3): a slot that holds a Scout is not deletable, and the screen says why', async () => {
    const user = userEvent.setup();
    renderBoard(eventFixture([slotFixture({ activeSignupCount: 1 })]));

    // There is no enabled delete for this row at all, and the reason is on the
    // dead button itself: a Scout's place cannot vanish with the slot.
    expect(screen.queryByTestId('delete-slot-SLOT#first')).not.toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Delete slot First Sales' });
    expect(button).toBeDisabled();
    await user.hover(button.parentElement as HTMLElement);
    expect(
      await screen.findByText('This slot holds Scouts. Cancel their signups instead of deleting the slot.'),
    ).toBeInTheDocument();
  });

  it('SLOT-01 (VER-01): a stale slot edit shows the stale-row sentence AND reloads the board', async () => {
    const user = userEvent.setup();
    const stale = {
      showAndSellId: SSE,
      label: 'First Sales',
      startAt: '2026-03-28T15:00:00.000Z',
      endAt: '2026-03-28T16:30:00.000Z',
      capacity: 2,
      version: { expectedVersion: 7 },
      slotId: 'SLOT#first',
      slotVersion: { expectedVersion: 3 },
      idempotency: { idempotencyKey: 'test-idem-1' },
    };
    const onChanged = renderBoard(eventFixture([slotFixture()]), [
      {
        request: { query: UPSERT_SHOW_AND_SELL_SLOT, variables: { input: stale } },
        error: new GraphQLError('expectedVersion 7 does not match 11', { extensions: { code: 'CONFLICT' } }),
      },
    ]);

    await user.click(await screen.findByTestId('edit-slot-SLOT#first'));
    expect(await screen.findByTestId('slot-dialog-title')).toHaveTextContent('Edit First Sales');
    await clearAndType('slot-capacity-input', '2', user);
    await user.click(screen.getByTestId('submit-slot'));

    expect(await screen.findByText(STALE_SENTENCE)).toBeInTheDocument();
    // The reload is part of reporting a stale row: the next attempt has to be
    // against versions nobody has looked at yet.
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(screen.getByTestId('submit-slot')).toBeInTheDocument();
  });

  it('SLOT-01: an edit carries the slot’s own version alongside the event’s', async () => {
    const user = userEvent.setup();
    const edited = slotFixture({ label: 'First Sales Shift', version: 4 });
    const onChanged = renderBoard(eventFixture([slotFixture()]), [
      upsertMock(
        {
          showAndSellId: SSE,
          label: 'First Sales Shift',
          startAt: '2026-03-28T15:00:00.000Z',
          endAt: '2026-03-28T16:30:00.000Z',
          capacity: 1,
          version: { expectedVersion: 7 },
          slotId: 'SLOT#first',
          slotVersion: { expectedVersion: 3 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        edited,
      ),
    ]);

    await user.click(await screen.findByTestId('edit-slot-SLOT#first'));
    // The boxes start at the slot's own interval in the Unit's zone, so an
    // untouched edit cannot move a slot the admin only came to re-caption.
    await clearAndType('slot-label-input', 'First Sales Shift', user);
    await user.click(screen.getByTestId('submit-slot'));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('submit-slot')).not.toBeInTheDocument());
  });

  it('§3.3.3: deleting an empty slot is one write that names the event’s current version', async () => {
    const user = userEvent.setup();
    const midday = slotFixture({ slotId: 'SLOT#midday', label: 'Midday' });
    const onChanged = renderBoard(eventFixture([midday]), [
      {
        request: {
          query: DELETE_SHOW_AND_SELL_SLOT,
          variables: {
            input: {
              showAndSellId: SSE,
              slotId: 'SLOT#midday',
              version: { expectedVersion: 7 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { deleteShowAndSellSlot: true } },
      },
    ]);

    await user.click(await screen.findByTestId('delete-slot-SLOT#midday'));
    expect(await screen.findByTestId('slot-delete-title')).toHaveTextContent('Delete this slot?');
    expect(screen.getByTestId('slot-delete-body')).toHaveTextContent(
      'Midday holds no Scouts, so deleting it removes only the slot.',
    );
    await user.click(screen.getByTestId('confirm-slot-delete'));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('confirm-slot-delete')).not.toBeInTheDocument());
  });

  it('VER-01: a refused delete reloads the board and keeps the sentence on screen', async () => {
    const user = userEvent.setup();
    const midday = slotFixture({ slotId: 'SLOT#midday', label: 'Midday' });
    const onChanged = renderBoard(eventFixture([midday]), [
      {
        request: {
          query: DELETE_SHOW_AND_SELL_SLOT,
          variables: {
            input: {
              showAndSellId: SSE,
              slotId: 'SLOT#midday',
              version: { expectedVersion: 7 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('a signup moved under this slot', { extensions: { code: 'CONFLICT' } }),
      },
    ]);

    await user.click(await screen.findByTestId('delete-slot-SLOT#midday'));
    await user.click(screen.getByTestId('confirm-slot-delete'));

    expect(await screen.findByText(STALE_SENTENCE)).toBeInTheDocument();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('SS-SM-06 step 8 (FORBIDDEN): a non-Admin is told only a Unit Admin can make this change', async () => {
    const user = userEvent.setup();
    // Riley the Scout may open the board but owns no write: the refusal comes
    // back FORBIDDEN and nothing is created — no reload, no new row.
    const onChanged = renderBoard(eventFixture([]), [
      refusedUpsert(
        {
          showAndSellId: SSE,
          label: 'First Sales',
          startAt: '2026-03-28T15:00:00.000Z',
          endAt: '2026-03-28T16:30:00.000Z',
          capacity: 1,
          version: { expectedVersion: 7 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        'FORBIDDEN',
        'a Unit Admin of this Unit only',
      ),
    ]);

    await fillSlotDialog(user, 'First Sales', '2026-03-28T09:00', '2026-03-28T10:30', '1');
    expect(await screen.findByText('Only a Unit Admin of this Unit can make this change.')).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByTestId('slot-count')).toHaveTextContent('0 of 20 slots used');
  });

  it('§3.3.2: the slot board closes when the event starts', async () => {
    renderBoard(eventFixture([slotFixture({ activeSignupCount: 1 }), slotFixture({ slotId: 'SLOT#midday', label: 'Midday' })], { status: 'ACTIVE' }));

    expect(await screen.findByTestId('slot-locked-note')).toHaveTextContent(
      'The slot board closes when the event starts. Scouts already signed up keep their places; correct their records on the signup board instead.',
    );
    expect(screen.getByTestId('add-slot')).toBeDisabled();
    expect(screen.getByTestId('edit-slot-SLOT#first')).toBeDisabled();
    expect(screen.getByTestId('delete-slot-SLOT#midday')).toBeDisabled();
  });
});
