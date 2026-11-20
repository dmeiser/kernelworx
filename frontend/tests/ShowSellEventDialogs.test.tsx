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

import { useState } from 'react';
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
import type { GqlShowAndSellAdminFieldsFragment } from '../src/types/graphql-generated';
import { chooseOption, clearAndType, clearField, typeInto } from './helpers/unitUi';

type User = ReturnType<typeof userEvent.setup>;

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
function eventFixture(overrides: Partial<GqlShowAndSellAdminFieldsFragment> = {}): GqlShowAndSellAdminFieldsFragment {
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
  };
}

/** The one idempotency key the first write from a freshly mounted dialog carries. */
const FIRST_KEY = 'test-idem-1';

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function renderDialogs(
  pending: PendingEventAction,
  mocks: MockedResponse[] = [],
  liveEvent?: (showAndSellId: string) => never,
) {
  const harness = { onClose: vi.fn(), onRefresh: vi.fn(), onCancelled: vi.fn() };
  render(
    <MockedProvider mocks={mocks}>
      <EventActionDialogs
        pending={pending}
        context={UNIT}
        onClose={harness.onClose}
        onRefresh={harness.onRefresh}
        onCancelled={harness.onCancelled}
        liveEvent={liveEvent}
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

  it('names the zone the times are entered in, because a wrong-zone reading moves the event', () => {
    renderDialogs({ kind: 'create' });
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

  it('sends the Unit’s current default when the admin chooses “inherit”', async () => {
    const user = userEvent.setup();
    // The event was created when this Unit split by worked time; it now splits equally.
    // *Inherit the Unit default* has to be answered by sending EQUAL, because the
    // update resolver reads a null splitMethod as "the caller asked for nothing"
    // (`_event_update_changes`): the old write reported a saved change while the
    // event kept the split it already had.
    const harness = renderDialogs({ kind: 'edit', event: eventFixture({ splitMethod: 'TIME_WORKED' }) }, [
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
        result: { data: { updateShowAndSell: eventFixture({ splitMethod: 'EQUAL' }) } },
      },
    ]);

    await chooseOption('event-split-select', 'Inherit the Unit default', user);
    await user.click(screen.getByTestId('submit-edit-event'));

    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
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

/**
 * The list page's contract with its dialogs, in miniature: the page holds the rows,
 * its refetch replaces them, and the dialog is pointed at whatever the page holds
 * now. The pending action still carries the row as it was when the button was
 * pressed — which is exactly the object a retry must not resend after a CONFLICT.
 */
function renderLiveRows(
  pending: PendingEventAction,
  refreshed: GqlShowAndSellAdminFieldsFragment,
  mocks: MockedResponse[],
) {
  const harness = { onClose: vi.fn(), onRefresh: vi.fn(), onCancelled: vi.fn() };
  const Host = () => {
    const [rows, setRows] = useState<GqlShowAndSellAdminFieldsFragment[]>([rowOf(pending)]);
    const refresh = async () => {
      harness.onRefresh();
      setRows([refreshed]);
    };
    return (
      <MockedProvider mocks={mocks}>
        <EventActionDialogs
          pending={pending}
          context={UNIT}
          onClose={harness.onClose}
          onRefresh={refresh}
          onCancelled={harness.onCancelled}
          liveEvent={(target) => rows.find((row) => idOf(row) === target) ?? null}
        />
      </MockedProvider>
    );
  };
  render(<Host />);
  return harness;
}

function rowOf(pending: PendingEventAction): GqlShowAndSellAdminFieldsFragment {
  return (pending && 'event' in pending ? pending.event : eventFixture()) as GqlShowAndSellAdminFieldsFragment;
}

/** The option a split control has chosen, read from the menu the admin would see. */
function selectedOptionName(): string | null {
  const chosen = screen.getAllByRole('option').find((option) => option.getAttribute('aria-selected') === 'true');
  return chosen?.textContent ?? null;
}

function idOf(row: GqlShowAndSellAdminFieldsFragment): string {
  return row.showAndSellId;
}

describe('EVT-M-02/03: a stale write is retried against the row the page re-read', () => {
  it('saves on the second attempt, with the version the reload brought back', async () => {
    const user = userEvent.setup();
    const harness = renderLiveRows({ kind: 'edit', event: eventFixture() }, eventFixture({ version: 7 }), [
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
        error: new GraphQLError('The row already moved.', { extensions: { errorCode: 'CONFLICT' } }),
      },
      {
        // The retry: the version the reload answered, and a new key, because the
        // payload is a different write. Only this mock can satisfy the second save,
        // so a dialog that resent version 3 would fail here rather than pass quietly.
        request: {
          query: UPDATE_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: SSE,
              locationName: 'Library on Main',
              address: '210 Main St',
              splitMethod: 'EQUAL',
              weOweEnabled: true,
              version: { expectedVersion: 7 },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: { data: { updateShowAndSell: eventFixture({ version: 7, address: '210 Main St' }) } },
      },
    ]);

    await clearAndType('event-address-input', '210 Main St', user);
    await user.click(screen.getByTestId('submit-edit-event'));
    await screen.findByText(/already moved/);

    // The refusal does not empty the form: the words that were typed are still there
    // to retry with.
    expect(screen.getByLabelText('Address')).toHaveValue('210 Main St');
    await user.click(screen.getByTestId('submit-edit-event'));

    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
    expect(harness.onRefresh).toHaveBeenCalledTimes(2);
  });

  it('cancels on the second attempt, with the version the reload brought back', async () => {
    const user = userEvent.setup();
    const harness = renderLiveRows({ kind: 'cancel', event: eventFixture() }, eventFixture({ version: 9 }), [
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
      {
        request: {
          query: CANCEL_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: SSE,
              reason: 'Store closed for the holiday',
              version: { expectedVersion: 9 },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: {
          data: {
            cancelShowAndSell: {
              __typename: 'CancelShowAndSellResult',
              event: eventFixture({ version: 9, status: 'CANCELLED' }),
              releasedAllocations: [],
              cancelledSignups: [],
            },
          },
        },
      },
    ]);

    await typeInto('cancellation-reason-input', 'Store closed for the holiday', user);
    await user.click(screen.getByTestId('submit-cancel-event'));
    await screen.findByText(/already moved/);
    expect(screen.getByLabelText('Why is it being cancelled')).toHaveValue('Store closed for the holiday');

    await user.click(screen.getByTestId('submit-cancel-event'));
    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
    expect(harness.onCancelled).toHaveBeenCalledTimes(1);
  });

  it('leaves a create alone: a replacement event has no row to re-read', async () => {
    const user = userEvent.setup();
    const from = eventFixture({ status: 'CANCELLED' });
    const harness = renderLiveRows({ kind: 'recreate', from }, eventFixture({ version: 7 }), [
      {
        request: {
          query: CREATE_SHOW_AND_SELL,
          variables: {
            input: {
              unitCampaignId: UC,
              locationName: 'Library on Main',
              address: '200 Main St',
              startAt: '2026-04-04T15:00:00.000Z',
              endAt: '2026-04-04T18:30:00.000Z',
              splitMethod: null,
              weOweEnabled: false,
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        result: { data: { createShowAndSell: eventFixture({ showAndSellId: 'SSE#makeup' }) } },
      },
    ]);

    await typeInto('event-start-input', '2026-04-04T09:00', user);
    await typeInto('event-end-input', '2026-04-04T12:30', user);
    await user.click(screen.getByTestId('submit-create-event'));

    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
  });
});

describe('EVT-M-01: two events that look alike are still two events', () => {
  it('starts a new write intent every time the create dialog is opened', async () => {
    const user = userEvent.setup();
    const harness = { onClose: vi.fn(), onRefresh: vi.fn(), onCancelled: vi.fn() };
    const body = (idempotencyKey: string) => ({
      unitCampaignId: UC,
      locationName: 'Library on Main',
      address: '200 Main St',
      startAt: '2026-03-28T15:00:00.000Z',
      endAt: '2026-03-28T18:30:00.000Z',
      splitMethod: null,
      weOweEnabled: false,
      idempotency: { idempotencyKey },
    });
    const Host = () => {
      const [pending, setPending] = useState<PendingEventAction>(null);
      return (
        <>
          <button type="button" data-testid="open-create" onClick={() => setPending({ kind: 'create' })}>
            Create a Show &amp; Sell
          </button>
          <MockedProvider
            mocks={[
              {
                request: { query: CREATE_SHOW_AND_SELL, variables: { input: body(FIRST_KEY) } },
                result: { data: { createShowAndSell: eventFixture() } },
              },
              {
                // The same words and the same times, typed again on purpose: the Unit
                // is holding two sessions at the same place. A key reused from the
                // first create makes the server replay that one, and the admin gets
                // the first event back instead of a new id.
                request: { query: CREATE_SHOW_AND_SELL, variables: { input: body('test-idem-2') } },
                result: { data: { createShowAndSell: eventFixture({ showAndSellId: 'SSE#second' }) } },
              },
            ]}
          >
            <EventActionDialogs
              pending={pending}
              context={UNIT}
              onClose={() => setPending(null)}
              onRefresh={harness.onRefresh}
              onCancelled={harness.onCancelled}
            />
          </MockedProvider>
        </>
      );
    };
    render(<Host />);

    for (let attempt = 0; attempt < 2; attempt += 1) {
      await user.click(screen.getByTestId('open-create'));
      await typeInto('event-location-input', 'Library on Main', user);
      await typeInto('event-address-input', '200 Main St', user);
      await typeInto('event-start-input', '2026-03-28T09:00', user);
      await typeInto('event-end-input', '2026-03-28T12:30', user);
      await user.click(screen.getByTestId('submit-create-event'));
      await waitFor(() => expect(screen.queryByTestId('submit-create-event')).toBeNull());
    }

    expect(harness.onRefresh).toHaveBeenCalledTimes(2);
  });
});

describe('SS-SM-11: the cancel path, and the seat it is refused from', () => {
  it('SS-SM-11: a Scout who is not a Unit Admin is refused the cancel, and the event stays where it was', async () => {
    const user = userEvent.setup();
    const harness = renderDialogs({ kind: 'cancel', event: eventFixture() }, [
      {
        request: {
          query: CANCEL_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: SSE,
              reason: 'Try it from the wrong seat',
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: FIRST_KEY },
            },
          },
        },
        error: new GraphQLError('not an admin', { extensions: { errorCode: 'FORBIDDEN' } }),
      },
    ]);

    await typeInto('cancellation-reason-input', 'Try it from the wrong seat', user);
    await user.click(screen.getByTestId('submit-cancel-event'));

    // The refusal is the role sentence, and nothing about the event changed: the
    // dialog stays open with what was typed, and no release is reported.
    await screen.findByText('Only a Unit Admin of this Unit can make this change.');
    expect(harness.onCancelled).not.toHaveBeenCalled();
    expect(harness.onClose).not.toHaveBeenCalled();
  });

  it('SS-SM-11 step 3: the cancel dialog offers no way to move the event', async () => {
    renderDialogs({ kind: 'cancel', event: eventFixture() });

    // There is no reschedule operation to find (SSE-07). The only path to a new time
    // runs through Create another, which is a different dialog on a cancelled row.
    expect(screen.queryByRole('button', { name: /reschedule|move this event/i })).toBeNull();
    expect(screen.queryByTestId('event-start-input')).toBeNull();
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
              splitMethod: null,
              weOweEnabled: false,
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
    // So is every money rule: the replacement starts back at *Inherit the Unit
    // default* with We Owe off. Copying the cancelled event's split and We Owe would
    // start a new event on one that was cancelled, and the admin's first save would
    // look like it changed nothing because the form already held those values (§6.1).
    await user.click(screen.getByRole('combobox', { name: 'Earnings split' }));
    expect(selectedOptionName()).toBe('Inherit the Unit default');
    await user.keyboard('{Escape}');
    expect(screen.getByTestId('event-we-owe-switch')).not.toHaveAttribute('aria-checked', 'true');

    await clearAndType('event-location-input', 'Library on Main (makeup)', user);
    await typeInto('event-start-input', '2026-04-04T09:00', user);
    await typeInto('event-end-input', '2026-04-04T12:30', user);
    await user.click(screen.getByTestId('submit-create-event'));

    // Only CREATE is mocked: a dialog that tried to restore the cancelled row, or
    // to copy its allocations, would die here on the missing mock.
    await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
  });
});

// --- the same four workflows without a pointer, at a phone's width -----------
//
// A Kernel runs a Show & Sell from the sales floor with a phone in one hand, and an
// admin who cannot use a pointer has to reach every one of these writes with the
// keyboard alone. Both are claims about the same markup: every control sits inside the
// dialog, in a walkable order, visible at a narrow width, and none of them appears
// only on hover. The writes are driven with real keystrokes and `{Enter}`, so a
// control that only answers a mouse click fails here.

describe('§3.5.1: keyboard-only and phone-width runs of the four workflows', () => {
  /**
   * Renders and drives the block with the browser reporting a `width`-pixel viewport.
   *
   * MUI asks `matchMedia` how wide the window is; the stub answers the min/max-width
   * queries the dialogs actually use, so the paper is laid out for a phone rather than
   * for the desktop default.
   */
  async function withViewport<T>(width: number, run: () => Promise<T>): Promise<T> {
    const kept = ['innerWidth', 'outerWidth', 'matchMedia'].map((key) => [key, Object.getOwnPropertyDescriptor(window, key)] as const);
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
    Object.defineProperty(window, 'outerWidth', { configurable: true, value: width });
    Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: responsiveMedia(width) });
    try {
      return await run();
    } finally {
      for (const [key, descriptor] of kept) {
        if (descriptor) Object.defineProperty(window, key, descriptor);
      }
    }
  }

  /** Answers the min/max-width queries MUI asks, measured against `width`. */
  function responsiveMedia(width: number) {
    return (query: string) => {
      const max = /max-width:\s*(\d+)px/.exec(query);
      const min = /min-width:\s*(\d+)px/.exec(query);
      const matches = (max === null || width <= Number(max[1])) && (min === null || width >= Number(min[1]));
      return {
        matches,
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => true,
      };
    };
  }

  /** The paper as MUI lays it out: a phone gets the full width, not a fixed column. */
  function expectPhonePaper(): void {
    const paper = document.querySelector('.MuiDialog-paper') as HTMLElement;
    expect(paper).toHaveClass('MuiDialog-paperFullWidth');
  }

  /**
   * Tabs until the named control has focus.
   *
   * The walk is the assertion: a control that is `display: none` at this width, or
   * outside the dialog's focus trap, is never reached and the loop throws.
   */
  async function focusByTab(element: HTMLElement, user: User): Promise<void> {
    for (let step = 0; step < 15; step += 1) {
      if (document.activeElement === element) return;
      await user.tab();
    }
    throw new Error(`Tab never reached ${element.getAttribute('data-testid') ?? element.getAttribute('aria-label')}`);
  }

  it('creates an event by Tab and Enter, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      const harness = renderDialogs(
        { kind: 'create' },
        [
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
                  weOweEnabled: false,
                  idempotency: { idempotencyKey: FIRST_KEY },
                },
              },
            },
            result: { data: { createShowAndSell: eventFixture() } },
          },
        ],
      );
      expectPhonePaper();

      await focusByTab(screen.getByTestId('event-location-input'), user);
      await user.keyboard('Library on Main');
      await focusByTab(screen.getByTestId('event-address-input'), user);
      await user.keyboard('200 Main St');
      await focusByTab(screen.getByTestId('event-start-input'), user);
      await user.keyboard('2026-03-28T09:00');
      await focusByTab(screen.getByTestId('event-end-input'), user);
      await user.keyboard('2026-03-28T12:30');
      // The split control is on the way to the write, so a keyboard admin can see what
      // the event will inherit before pressing Create.
      await focusByTab(screen.getByRole('combobox', { name: 'Earnings split' }), user);
      await focusByTab(screen.getByTestId('submit-create-event'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
    });
  });

  it('edits an event by Tab and Enter, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      const harness = renderDialogs({ kind: 'edit', event: eventFixture() }, [
        {
          request: {
            query: UPDATE_SHOW_AND_SELL,
            variables: {
              input: {
                showAndSellId: SSE,
                locationName: 'Library on Main',
                address: '212 Main St',
                splitMethod: 'EQUAL',
                weOweEnabled: true,
                version: { expectedVersion: 3 },
                idempotency: { idempotencyKey: FIRST_KEY },
              },
            },
          },
          result: { data: { updateShowAndSell: eventFixture({ address: '212 Main St' }) } },
        },
      ]);
      expectPhonePaper();
      // The locked fields are still in the walk: an admin reads the interval the event
      // cannot change, and Tab does not skip past it into the actions.
      const starts = screen.getByLabelText('Starts');
      expect(starts).toBeDisabled();
      expect(screen.getByTestId('times-immutable-note')).toBeVisible();

      await focusByTab(screen.getByTestId('event-address-input'), user);
      await user.clear(document.activeElement as HTMLElement);
      await user.keyboard('212 Main St');
      await focusByTab(screen.getByTestId('submit-edit-event'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
    });
  });

  it('cancels an event by Tab and Enter, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      const harness = renderDialogs({ kind: 'cancel', event: eventFixture() }, [
        {
          request: {
            query: CANCEL_SHOW_AND_SELL,
            variables: {
              input: {
                showAndSellId: SSE,
                reason: 'Store closed',
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
                releasedAllocations: [],
                cancelledSignups: [],
              },
            },
          },
        },
      ]);
      expectPhonePaper();
      expect(screen.getByTestId('cancel-consequence')).toBeVisible();

      await focusByTab(screen.getByTestId('cancellation-reason-input'), user);
      await user.keyboard('Store closed');
      await focusByTab(screen.getByTestId('submit-cancel-event'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(harness.onCancelled).toHaveBeenCalledTimes(1));
    });
  });

  it('creates the replacement event by Tab and Enter, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      const harness = renderDialogs({ kind: 'recreate', from: eventFixture({ status: 'CANCELLED' }) }, [
        {
          request: {
            query: CREATE_SHOW_AND_SELL,
            variables: {
              input: {
                unitCampaignId: UC,
                locationName: 'Library on Main',
                address: '200 Main St',
                startAt: '2026-04-04T15:00:00.000Z',
                endAt: '2026-04-04T18:30:00.000Z',
                splitMethod: null,
                weOweEnabled: false,
                idempotency: { idempotencyKey: FIRST_KEY },
              },
            },
          },
          result: { data: { createShowAndSell: eventFixture({ showAndSellId: 'SSE#makeup' }) } },
        },
      ]);
      expectPhonePaper();
      // The words are already there; only the new interval has to be typed.
      expect(screen.getByTestId('event-location-input')).toHaveValue('Library on Main');

      await focusByTab(screen.getByTestId('event-start-input'), user);
      await user.keyboard('2026-04-04T09:00');
      await focusByTab(screen.getByTestId('event-end-input'), user);
      await user.keyboard('2026-04-04T12:30');
      await focusByTab(screen.getByTestId('submit-create-event'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(harness.onClose).toHaveBeenCalledTimes(1));
    });
  });
});
