/**
 * The event dialogs: create, edit, cancel, recreate (Show & Sell §3.5.1, EVT-M-01
 * through EVT-M-03).
 *
 * One fact decides every test in this file: an event's interval is chosen once and
 * never again. `UpdateShowAndSellInput` carries no `startAt`/`endAt` (SSE-07), so
 * the edit dialog shows the times, locked, and the only way to move an event is to
 * cancel it and create another — a different row with a different id, holding none
 * of the cancelled event's stock, slots or Scouts (§6.1). A test that proves a
 * reschedule button exists is a test that fails.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { GraphQLError } from 'graphql';
import {
  type EventUnitContext,
  EventActionDialogs,
  type PendingEventAction,
} from '../src/components/showSell/EventDialogs';
import { CANCEL_SHOW_AND_SELL, CREATE_SHOW_AND_SELL, UPDATE_SHOW_AND_SELL } from '../src/lib/graphql';
import { chooseOption, clearAndType, clearField, typeInto } from './helpers/unitUi';

const UC = 'UNITCAMP#pack-3149-fall';
const SSE = 'SSE#library';

const UNIT: EventUnitContext = {
  unitCampaignId: UC,
  timezone: 'America/Denver',
  splitDefault: 'EQUAL',
  campaignName: 'Fall Popcorn 2026',
};

// The SS-SM-06 event: T0 + 14 days, 09:00–12:30 in the Unit zone. Its version is
// the one every write below is expected to carry.
function eventFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: SSE,
    unitId: 'UNIT#pack-3149',
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: '200 Main St',
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:30:00.000Z',
    status: 'SCHEDULED',
    splitMethod: 'EQUAL',
    weOweEnabled: true,
    productIds: ['PROD#caramel'],
    allocations: [],
    slots: [],
    version: 3,
    createdAt: '2026-03-01T15:00:00.000Z',
    updatedAt: '2026-03-20T15:00:00.000Z',
    createdByAccountId: 'ACCOUNT#admin',
    updatedByAccountId: 'ACCOUNT#admin',
    cancelledByAccountId: null,
    cancelledAt: null,
    cancellationReason: null,
    ...overrides,
  } as never;
}

/** The one idempotency key the first write from a freshly mounted dialog carries. */
const FIRST_KEY = 'test-idem-1';

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function renderDialogs(pending: PendingEventAction, mocks: MockedResponse[] = []) {
  const harness = { onClose: vi.fn(), onRefresh: vi.fn(), onCancelled: vi.fn() };
  render(
    <MockedProvider mocks={mocks}>
      <EventActionDialogs
        pending={pending}
        context={UNIT}
        onClose={harness.onClose}
        onRefresh={harness.onRefresh}
        onCancelled={harness.onCancelled}
      />
    </MockedProvider>,
  );
  return harness;
}

describe('EVT-M-01: creating an event', () => {
  it('writes the words the admin typed, as UTC instants in the Unit zone', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'create' }, [
      {
        request: {
          query: CREATE_SHOW_AND_SELL,
          variables: {
            input: {
              unitCampaignId: UC,
              locationName: 'Library on Main',
              address: '200 Main St',
              startAt: '2026-03-28T15:00:00.000Z',
              endAt: '2026-03-28T18:30:00.000Z',
              splitMethod: null,
              weOweEnabled: true,
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        result: { data: { createShowAndSell: eventFixture() } },
      },
    ]);

    await typeInto('event-location-input', 'Library on Main', user);
    await typeInto('event-address-input', '200 Main St', user);
    await typeInto('event-start-input', '2026-03-28T09:00', user);
    await typeInto('event-end-input', '2026-03-28T12:30', user);
    await user.click(screen.getByTestId('event-we-owe-switch'));
    await user.click(screen.getByTestId('submit-create-event'));

    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
    expect(harness.onRefresh).toHaveBeenCalledTimes(1);
  });

  it('carries the split override only when the admin chose one', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'create' }, [
      {
        request: {
          query: CREATE_SHOW_AND_SELL,
          variables: {
            input: {
              unitCampaignId: UC,
              locationName: 'Library on Main',
              address: null,
              startAt: '2026-03-28T15:00:00.000Z',
              endAt: '2026-03-28T18:30:00.000Z',
              splitMethod: 'TIME_WORKED',
              weOweEnabled: false,
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        result: { data: { createShowAndSell: eventFixture() } },
      },
    ]);

    await typeInto('event-location-input', 'Library on Main', user);
    await typeInto('event-start-input', '2026-03-28T09:00', user);
    await typeInto('event-end-input', '2026-03-28T12:30', user);
    await chooseOption('event-split-select', 'Split by worked time', user);
    await user.click(screen.getByTestId('submit-create-event'));

    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
  });

  it('refuses a form whose location is missing, with the field’s own sentence and no write', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'create' }, []);

    await typeInto('event-start-input', '2026-03-28T09:00', user);
    await typeInto('event-end-input', '2026-03-28T12:30', user);
    await user.click(screen.getByTestId('submit-create-event'));

    // The refusal is the location sentence, which is only reachable before a write:
    // had one been sent, MockedProvider would answer "No more mocked responses" and
    // this assertion would name that instead.
    await screen.findByText('Name where the event is, such as “Kroger on Monroe”.');
    expect(harness.onClose).not.toHaveBeenCalled();
  });

  it('refuses an end that is not after the start, before any write', async () => {
    const user = userEvent.setup();
    renderDialogs({ kind: 'create' }, []);

    await typeInto('event-location-input', 'Library on Main', user);
    await typeInto('event-start-input', '2026-03-28T12:30', user);
    await typeInto('event-end-input', '2026-03-28T09:00', user);
    await user.click(screen.getByTestId('submit-create-event'));

    await screen.findByText('The end must be after the start — an event cannot end before it begins.');
  });

  it('keeps the form when the create write is refused, and says why in the refusal’s words', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'create' }, [
      {
        request: {
          query: CREATE_SHOW_AND_SELL,
          variables: {
            input: {
              unitCampaignId: UC,
              locationName: 'Library on Main',
              address: null,
              startAt: '2026-03-28T15:00:00.000Z',
              endAt: '2026-03-28T18:30:00.000Z',
              splitMethod: null,
              weOweEnabled: false,
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        error: new GraphQLError('This Unit is at its event limit.', { extensions: { errorCode: 'INVALID_INPUT' } }),
      },
    ]);

    await typeInto('event-location-input', 'Library on Main', user);
    await typeInto('event-start-input', '2026-03-28T09:00', user);
    await typeInto('event-end-input', '2026-03-28T12:30', user);
    await user.click(screen.getByTestId('submit-create-event'));

    // The refusal is the Show & Sell sentence for a refused input, not the
    // transport's: a raw AppSync string tells an admin nothing about what to fix.
    await screen.findByText('The server refused what was entered. Check the values and try again.');
    expect(harness.onClose).not.toHaveBeenCalled();
    // What was typed is still there to fix, rather than a cleared form.
    expect(screen.getByLabelText('Where is it')).toHaveValue('Library on Main');
  });

  it('mounts no dialog at all when no action is pending', () => {
    // The list and detail pages keep one `pending` value; a stale action must not
    // leave two dialogs stacked over the same event.
    renderDialogs(null);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('names the zone the times are entered in, because a wrong-zone reading moves the event', () => {    renderDialogs({ kind: 'create' });
    expect(screen.getByTestId('event-timezone-note')).toHaveTextContent('Times are entered in America/Denver');
  });

  it('opens with focus moved into the dialog, so keyboard and mobile flow start in the same place', () => {
    renderDialogs({ kind: 'create' });
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement | null);
  });

  it('closes on Escape, the dismissal a keyboard-only admin reaches for', () => {
    const harness = renderDialogs({ kind: 'create' });
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(harness.onClose).toHaveBeenCalledTimes(1);
  });
});

describe('EVT-M-02: editing an event', () => {
  it('shows the stored interval in the Unit zone and locks every time field', () => {
    renderDialogs({ kind: 'edit', event: eventFixture() });

    expect(screen.getByTestId('edit-event-times')).toHaveTextContent('9:00 AM');
    expect(screen.getByTestId('times-immutable-note')).toHaveTextContent('read-only');
    expect(screen.getByLabelText('Starts')).toBeDisabled();
    expect(screen.getByLabelText('Ends')).toBeDisabled();
  });

  it('saves location, address and the split, with the version it read and no times', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'edit', event: eventFixture() }, [
      {
        request: {
          query: UPDATE_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: SSE,
              locationName: 'Library on Main',
              address: '210 Main St',
              splitMethod: 'EQUAL',
              weOweEnabled: true,
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        result: { data: { updateShowAndSell: eventFixture({ address: '210 Main St' }) } },
      },
    ]);

    await clearAndType('event-address-input', '210 Main St', user);
    await user.click(screen.getByTestId('submit-edit-event'));

    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
    expect(harness.onRefresh).toHaveBeenCalledTimes(1);
  });

  it('refuses an edit that would empty the location, with no write', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'edit', event: eventFixture() }, []);

    await clearField('event-location-input', user);
    await user.click(screen.getByTestId('submit-edit-event'));

    await screen.findByText('Name where the event is, such as “Kroger on Monroe”.');
    expect(harness.onClose).not.toHaveBeenCalled();
  });

  it('reloads the board and says so when the row moved under the dialog', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'edit', event: eventFixture() }, [
      {
        request: {
          query: UPDATE_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: SSE,
              locationName: 'Library on Main',
              address: '200 Main St',
              splitMethod: 'EQUAL',
              weOweEnabled: true,
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        error: new GraphQLError('The row already moved.', { extensions: { errorCode: 'CONFLICT' } }),
      },
    ]);

    await user.click(screen.getByTestId('submit-edit-event'));

    await screen.findByText(/already moved/);
    // A stale version is reported only after the read behind the screen is reloaded.
    await waitFor(() => expect(harness.onRefresh).toHaveBeenCalledTimes(1));
    expect(harness.onClose).not.toHaveBeenCalled();
  });

  it('offers nothing on an event that is finalized or cancelled', () => {
    renderDialogs({ kind: 'edit', event: eventFixture({ status: 'FINALIZED' }) });

    // The state gate locks every field the edit write could carry; the screen never
    // offers a save into a closed event.
    expect(screen.getByLabelText('Where is it')).toBeDisabled();
    expect(screen.getByLabelText('Address')).toBeDisabled();
    // A MUI Select keeps an off-screen native `select` for form semantics, so the
    // disabled state is read from the control the admin actually sees.
    const split = screen.getByTestId('event-split-select').querySelector('.MuiSelect-select') as HTMLElement;
    expect(split).toHaveClass('Mui-disabled');
    expect(split).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByTestId('event-we-owe-switch')).toHaveClass('Mui-disabled');
  });
});

describe('EVT-M-03: cancelling an event', () => {
  it('states the consequence, names the interval, and refuses to cancel without a reason', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'cancel', event: eventFixture() }, []);

    expect(screen.getByTestId('cancel-consequence')).toHaveTextContent('releases every stock allocation');
    expect(screen.getByTestId('cancel-event-when')).toHaveTextContent('9:00 AM');

    await user.click(screen.getByTestId('submit-cancel-event'));

    await screen.findByText('Say why this event is being cancelled — the reason is kept in the audit record.');
    expect(harness.onCancelled).not.toHaveBeenCalled();
  });

  it('cancels with the version it read and reports what the server released', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'cancel', event: eventFixture() }, [
      {
        request: {
          query: CANCEL_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: SSE,
              reason: 'Store closed for the holiday',
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        result: {
          data: {
            cancelShowAndSell: {
              __typename: 'CancelShowAndSellResult',
              event: eventFixture({ status: 'CANCELLED' }),
              releasedAllocations: [{ __typename: 'ShowAndSellAllocation', productId: 'PROD#caramel' }],
              cancelledSignups: [
                { __typename: 'ShowAndSellSignup', profileId: 'PROFILE#avery' },
                { __typename: 'ShowAndSellSignup', profileId: 'PROFILE#blake' },
              ],
            },
          },
        },
      },
    ]);

    await typeInto('cancellation-reason-input', 'Store closed for the holiday', user);
    await user.click(screen.getByTestId('submit-cancel-event'));

    await waitFor(() =>
      expect(harness.onCancelled).toHaveBeenCalledWith({ locationName: 'Library on Main', released: 1, signups: 2 }),
    );
  });

  it('replays the same write on the same idempotency key when the transport fails', async () => {
    const user = userEvent.setup();
    const variables = {
      input: {
        showAndSellId: SSE,
        reason: 'Store closed for the holiday',
        version: { expectedVersion: 3 },
        idempotency: { idempotencyKey: FIRST_KEY },
      },
    };
    const harness = renderDialogs({ kind: 'cancel', event: eventFixture() }, [
      {
        request: { query: CANCEL_SHOW_AND_SELL, variables },
        error: new GraphQLError('The service is busy.', { extensions: { errorCode: 'RESOURCE_BUSY' } }),
      },
      {
        request: { query: CANCEL_SHOW_AND_SELL, variables },
        result: {
          data: {
            cancelShowAndSell: {
              __typename: 'CancelShowAndSellResult',
              event: eventFixture({ status: 'CANCELLED' }),
              releasedAllocations: [],
              cancelledSignups: [],
            },
          },
        },
      },
    ]);

    await typeInto('cancellation-reason-input', 'Store closed for the holiday', user);
    await user.click(screen.getByTestId('submit-cancel-event'));
    await screen.findByText(/nothing was changed/);

    // The admin presses the same button again. The unchanged reason is the same
    // write, so the retry carries the same key rather than minting a new one — the
    // second mock below is that retry, and it only matches if the key held.
    await user.click(screen.getByTestId('submit-cancel-event'));
    await waitFor(() => expect(harness.onCancelled).toHaveBeenCalledTimes(1));
  });

  it('reloads and says so when the event moved under the cancel dialog', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'cancel', event: eventFixture() }, [
      {
        request: {
          query: CANCEL_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: SSE,
              reason: 'Store closed for the holiday',
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        error: new GraphQLError('The row already moved.', { extensions: { errorCode: 'CONFLICT' } }),
      },
    ]);

    await typeInto('cancellation-reason-input', 'Store closed for the holiday', user);
    await user.click(screen.getByTestId('submit-cancel-event'));

    await screen.findByText(/already moved/);
    await waitFor(() => expect(harness.onRefresh).toHaveBeenCalledTimes(1));
    expect(harness.onCancelled).not.toHaveBeenCalled();
  });

  it('§6.1: recreating an event that had no address leaves the address box empty', async () => {
    renderDialogs({ kind: 'recreate', from: eventFixture({ status: 'CANCELLED', address: null }) });

    // The words carry over, the empty stays empty: a null address must not come back
    // as the string "null" for the admin to notice later.
    expect(screen.getByLabelText('Where is it')).toHaveValue('Library on Main');
    expect(screen.getByLabelText('Address')).toHaveValue('');
  });
});

describe('§6.1: the replacement event is a new event', () => {
  it('prefills the words, never the times, and carries nothing over', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'recreate', from: eventFixture({ status: 'CANCELLED' }) }, [
      {
        request: {
          query: CREATE_SHOW_AND_SELL,
          variables: {
            input: {
              unitCampaignId: UC,
              locationName: 'Library on Main (makeup)',
              address: '200 Main St',
              startAt: '2026-04-04T15:00:00.000Z',
              endAt: '2026-04-04T18:30:00.000Z',
              splitMethod: 'EQUAL',
              weOweEnabled: true,
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        result: {
          data: {
            createShowAndSell: eventFixture({ showAndSellId: 'SSE#library-makeup', locationName: 'Library on Main (makeup)' }),
          },
        },
      },
    ]);

    expect(screen.getByTestId('create-event-title')).toHaveTextContent('Create the replacement event');
    expect(screen.getByTestId('recreate-note')).toHaveTextContent('nothing — stock, slots, or Scouts — moves');

    // The words carry over so the admin is not retyping them; the times are blank.
    expect(screen.getByLabelText('Where is it')).toHaveValue('Library on Main');
    expect(screen.getByLabelText('Starts')).toHaveValue('');

    await clearAndType('event-location-input', 'Library on Main (makeup)', user);
    await typeInto('event-start-input', '2026-04-04T09:00', user);
    await typeInto('event-end-input', '2026-04-04T12:30', user);
    await user.click(screen.getByTestId('submit-create-event'));

    // Only CREATE is mocked: a dialog that tried to restore the cancelled row, or
    // to copy its allocations, would die here on the missing mock.
    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
  });
});
