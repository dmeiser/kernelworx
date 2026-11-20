/**
 * The Stage 3 Show & Sell rules the browser owns (§3.5), tested at the layer the
 * screens read them from.
 *
 * Three of these are the ones a reviewer should look for first:
 *
 * - **Times are the Unit's, not the browser's.** A Show & Sell is entered and read
 *   in the Unit's IANA zone, so the wall-clock conversion is tested across a
 *   daylight-saving boundary rather than on a single nice date. A screen that used
 *   the browser's zone would move an event by the difference.
 * - **Duration is free.** Slots are 90, 120, 180 minutes long (SS-SM-06) and a work
 *   row may be 75 minutes of a 90-minute slot. Any hourly assumption in the copy or
 *   the validator is a rule the product rejected (SSE-03, SLOT-05).
 * - **The invite is built here and nowhere else.** The file is assembled in the tab,
 *   carries UTC instants with an explicit `Z`, and names the Unit's zone in prose.
 *   A `TZID` without a `VTIMEZONE` block is an invite that lands an hour out, and a
 *   server artifact would be a file that outlives the place it described
 *   (CAL-01, CAL-02).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphQLError } from 'graphql';
import {
  MAX_LOCATION_NAME_LENGTH,
  MAX_SLOT_CAPACITY,
  MAX_SLOT_LABEL_LENGTH,
  MAX_WORK_LINES_PER_BATCH,
  SHOW_AND_SELL_PAGE_SIZE,
  acceptsAllocationEdits,
  acceptsEventEdits,
  acceptsSignups,
  acceptsSlotEdits,
  acceptsWorkConfirmation,
  allocationTargets,
  buildInvite,
  changedWorkLines,
  collidingCommitments,
  describeShowAndSellFailure,
  downloadInvite,
  durationBySlot,
  durationLabel,
  formatInstant,
  hasAllocationChanges,
  intervalLabel,
  inviteFileName,
  inviteLocation,
  inviteSummary,
  inviteUid,
  intervalsOverlap,
  isCancellable,
  isSignupConflictError,
  isSlotAvailable,
  icsUtc,
  minutesBetween,
  minutesUntil,
  openAllocationsByProduct,
  openPlaces,
  overageWarnings,
  parseAddress,
  parseCancellationReason,
  parseCapacity,
  parseInterval,
  parseLocationName,
  parseSlotInterval,
  parseSlotLabel,
  parseWorkMinutes,
  productQuantityOf,
  reportWriteFailure,
  signupForSlot,
  showAndSellStatusLabel,
  splitMethodLabel,
  slotAvailabilityLabel,
  slotIntervalOf,
  slotNameOf,
  sortBy,
  sortSlots,
  trimmedOrNull,
  warningSentence,
  withIdempotency,
  workDraftsOf,
  workRowKey,
  zoneOffsetMinutes,
  zonedWallClockToUtc,
  utcToZonedWallClock,
  type AllocationTarget,
} from '../src/lib/showSell';
import type { GqlCalendarInviteData } from '../src/types/graphql-generated';

// SS-SM-06's event: `Library on Main`, T0 + 7 days, 09:00–12:30 in America/Denver,
// with the three slots of different length the scenario is built from.
const ZONE = 'America/Denver';

/** An instant in the Unit's zone, written the way the boxes carry it. */
const wall = (day: string, time: string) => `${day}T${time}`;

// --- status and state gates -------------------------------------------------

describe('Show & Sell state gates', () => {
  it('names every state in words an operator already uses', () => {
    expect(SHOW_AND_SELL_PAGE_SIZE).toBe(50);
    expect(acceptsSignups('SCHEDULED')).toBe(true);
    expect(acceptsSignups('ACTIVE')).toBe(false);
    expect(acceptsSlotEdits('SCHEDULED')).toBe(true);
    expect(acceptsSlotEdits('CANCELLED')).toBe(false);
    expect(isCancellable('SCHEDULED')).toBe(true);
    expect(isCancellable('ACTIVE')).toBe(false);
    expect(acceptsWorkConfirmation('ENDED')).toBe(true);
    expect(acceptsWorkConfirmation('REOPENED')).toBe(true);
    expect(acceptsWorkConfirmation('FINALIZED')).toBe(false);
    expect(acceptsAllocationEdits('REOPENED')).toBe(true);
    expect(acceptsAllocationEdits('FINALIZED')).toBe(false);
    expect(acceptsEventEdits('CANCELLED')).toBe(false);
  });
});

// --- the Unit's zone, not the browser's ------------------------------------

describe('zoned wall clock', () => {
  it('reads a wall-clock time in the Unit zone, not the browser zone', () => {
    const instant = zonedWallClockToUtc(wall('2026-03-14', '09:00'), ZONE);
    expect(instant?.toISOString()).toBe('2026-03-14T15:00:00.000Z');
  });

  it('follows the zone across a daylight-saving change', () => {
    // Denver is UTC-7 before 8 March 2026 and UTC-6 after it. The same wall-clock
    // time on both sides is a different instant, and getting this wrong is exactly
    // the hour-off event the conversion exists to prevent.
    expect(zonedWallClockToUtc(wall('2026-03-07', '09:00'), ZONE)?.toISOString()).toBe('2026-03-07T16:00:00.000Z');
    expect(zonedWallClockToUtc(wall('2026-03-09', '09:00'), ZONE)?.toISOString()).toBe('2026-03-09T15:00:00.000Z');
    expect(zoneOffsetMinutes(new Date('2026-03-07T16:00:00Z'), ZONE)).toBe(-420);
    expect(zoneOffsetMinutes(new Date('2026-03-09T15:00:00Z'), ZONE)).toBe(-360);
  });

  it('refuses text that is not a date and a time', () => {
    expect(zonedWallClockToUtc('', ZONE)).toBeNull();
    expect(zonedWallClockToUtc('March 14', ZONE)).toBeNull();
    expect(zonedWallClockToUtc('2026-13-45T09:00', ZONE)).toBeNull();
  });

  it('round-trips an instant back into the box the admin reads', () => {
    expect(utcToZonedWallClock('2026-03-14T15:00:00.000Z', ZONE)).toBe('2026-03-14T09:00');
    expect(utcToZonedWallClock('not a time', ZONE)).toBe('');
  });

  it('falls back to the text itself for a zone the browser cannot name', () => {
    // A Unit created with a typo'd zone must not blank the screen: the box keeps the
    // value, and the server still refuses an interval it cannot use.
    expect(utcToZonedWallClock('2026-03-14T15:00:00.000Z', 'Mars/Olympus_Mons')).toBe('2026-03-14T15:00');
    expect(formatInstant('2026-03-14T15:00:00.000Z', 'Mars/Olympus_Mons')).toContain('UTC');
  });
});

describe('interval parsing', () => {
  it('turns the two boxes into the UTC instants the write carries', () => {
    const parsed = parseInterval(wall('2026-03-14', '09:00'), wall('2026-03-14', '12:30'), ZONE);
    expect(parsed.error).toBeNull();
    expect(parsed.startAt).toBe('2026-03-14T15:00:00.000Z');
    expect(parsed.endAt).toBe('2026-03-14T18:30:00.000Z');
  });

  it('refuses a missing or unparseable box', () => {
    const missing = parseInterval('', '', ZONE);
    expect(missing.error).toContain('Enter a start and an end');
    expect(parseInterval('March 14', 'March 15', ZONE).error).toContain('Enter a start and an end');
  });

  it('refuses an end that is not after the start', () => {
    const same = parseInterval(wall('2026-03-14', '09:00'), wall('2026-03-14', '09:00'), ZONE);
    expect(same.error).toContain('The end must be after the start');
    const backwards = parseInterval(wall('2026-03-14', '12:00'), wall('2026-03-14', '09:00'), ZONE);
    expect(backwards.error).toContain('The end must be after the start');
  });

  it('accepts an instant the server already stored, so an unedited row can be saved', () => {
    const parsed = parseInterval('2026-03-14T15:00:00.000Z', '2026-03-14T18:30:00.000Z', ZONE);
    expect(parsed.error).toBeNull();
  });
});

describe('durations and instants', () => {
  it('counts minutes between two instants', () => {
    expect(minutesBetween('2026-03-14T15:00:00.000Z', '2026-03-14T16:30:00.000Z')).toBe(90);
  });

  it('says a duration in words without inventing an hour', () => {
    expect(durationLabel(75)).toBe('1 hour 15 minutes');
    expect(durationLabel(90)).toBe('1 hour 30 minutes');
    expect(durationLabel(120)).toBe('2 hours');
    expect(durationLabel(180)).toBe('3 hours');
    expect(durationLabel(45)).toBe('45 minutes');
    expect(durationLabel(0)).toBe('0 minutes');
    expect(durationLabel(-5)).toBe('0 minutes');
  });

  it('renders an instant in the Unit zone and names the zone in the interval', () => {
    expect(formatInstant('2026-03-14T15:00:00.000Z', ZONE)).toContain('9:00 AM');
    expect(intervalLabel('2026-03-14T15:00:00.000Z', '2026-03-14T18:30:00.000Z', ZONE)).toContain('3 hours 30 minutes');
  });

  it('counts down only to an event that has not started', () => {
    const future = new Date(Date.now() + 90 * 60_000).toISOString();
    expect(minutesUntil(future)).toBeGreaterThan(80);
    expect(minutesUntil(new Date(Date.now() - 60_000).toISOString())).toBeNull();
  });
});

// --- field validators ------------------------------------------------------

describe('field validators', () => {
  it('requires a short location name', () => {
    expect(parseLocationName('')).toContain('Name where the event is');
    expect(parseLocationName('   ')).toContain('Name where the event is');
    expect(parseLocationName('Library on Main')).toBeNull();
    expect(parseLocationName('x'.repeat(MAX_LOCATION_NAME_LENGTH + 1))).toContain('characters');
  });

  it('bounds an optional address', () => {
    expect(parseAddress('')).toBeNull();
    expect(parseAddress('200 Main St')).toBeNull();
    expect(parseAddress('x'.repeat(501))).toContain('characters');
  });

  it('requires a cancellation reason and bounds it', () => {
    expect(parseCancellationReason('')).toContain('reason');
    expect(parseCancellationReason('Store closed')).toBeNull();
    expect(parseCancellationReason('x'.repeat(501))).toContain('characters');
  });

  it('bounds a slot label and leaves it optional', () => {
    expect(parseSlotLabel('')).toBeNull();
    expect(parseSlotLabel('First Sales')).toBeNull();
    expect(parseSlotLabel('x'.repeat(MAX_SLOT_LABEL_LENGTH + 1))).toContain('characters');
  });

  it('holds a slot between 1 and 100 Scouts', () => {
    expect(parseCapacity('').error).toContain('how many Scouts');
    expect(parseCapacity('0').error).toContain('between 1 and 100');
    expect(parseCapacity(`${MAX_SLOT_CAPACITY + 1}`).error).toContain('between 1 and 100');
    expect(parseCapacity('two').error).toContain('whole number');
    expect(parseCapacity('1.5').error).toContain('whole number');
    expect(parseCapacity('1')).toEqual({ value: 1, error: null });
    expect(parseCapacity('100')).toEqual({ value: 100, error: null });
  });

  it('trims an optional field into the value a write carries', () => {
    expect(trimmedOrNull('  ')).toBeNull();
    expect(trimmedOrNull('  200 Main St  ')).toBe('200 Main St');
  });
});

// --- slots -----------------------------------------------------------------

describe('slot entry', () => {
  const event = { startAt: '2026-03-21T15:00:00.000Z', endAt: '2026-03-21T18:30:00.000Z' };

  it('accepts a slot of any length inside the event', () => {
    const draft = { label: 'First Sales', startAt: wall('2026-03-21', '09:00'), endAt: wall('2026-03-21', '10:30'), capacity: '1' };
    const parsed = parseSlotInterval(draft, event, ZONE);
    expect(parsed.error).toBeNull();
    expect(parsed.capacity).toBe(1);
    expect(minutesBetween(parsed.startAt as string, parsed.endAt as string)).toBe(90);
  });

  it('refuses a slot that reaches outside the event window', () => {
    const early = parseSlotInterval(
      { label: '', startAt: wall('2026-03-21', '08:00'), endAt: wall('2026-03-21', '10:00'), capacity: '1' },
      event,
      ZONE,
    );
    expect(early.error).toContain('fit inside the event');
    const late = parseSlotInterval(
      { label: '', startAt: wall('2026-03-21', '11:00'), endAt: wall('2026-03-21', '13:00'), capacity: '1' },
      event,
      ZONE,
    );
    expect(late.error).toContain('fit inside the event');
  });

  it('reports the first field that is wrong, in the order the form reads', () => {
    const bad = parseSlotInterval(
      { label: 'x'.repeat(MAX_SLOT_LABEL_LENGTH + 1), startAt: wall('2026-03-21', '09:00'), endAt: wall('2026-03-21', '10:00'), capacity: '1' },
      event,
      ZONE,
    );
    expect(bad.error).toContain('under 100 characters');
    const capacity = parseSlotInterval(
      { label: '', startAt: wall('2026-03-21', '09:00'), endAt: wall('2026-03-21', '10:00'), capacity: '0' },
      event,
      ZONE,
    );
    expect(capacity.error).toContain('between 1 and 100');
  });

  it('seeds a new slot with the event window, in the zone the board shows', () => {
    const seeded = slotIntervalOf(event, ZONE);
    expect(seeded.startAt).toBe('2026-03-21T09:00');
    expect(seeded.endAt).toBe('2026-03-21T12:30');
  });

  it('orders slots soonest first and names one by its label or its id', () => {
    const first = { slotId: 'SLOT#b', startAt: '2026-03-21T16:00:00.000Z', label: 'Midday' };
    const second = { slotId: 'SLOT#a', startAt: '2026-03-21T15:00:00.000Z', label: null };
    expect(sortSlots([first, second] as never).map((slot) => slot.slotId)).toEqual(['SLOT#a', 'SLOT#b']);
    expect(slotNameOf([first, second] as never, 'SLOT#a')).toBe('SLOT#a');
    expect(slotNameOf([first, second] as never, 'SLOT#b')).toBe('Midday');
    expect(sortBy([3, 1, 2], (value) => String(value))).toEqual([1, 2, 3]);
  });

  it('bounds work minutes by the slot the row belongs to, not the event', () => {
    const eventWithSlots = {
      slots: [
        { slotId: 'SLOT#first', startAt: '2026-03-21T15:00:00.000Z', endAt: '2026-03-21T16:30:00.000Z' },
        { slotId: 'SLOT#midday', startAt: '2026-03-21T16:30:00.000Z', endAt: '2026-03-21T18:30:00.000Z' },
      ],
    };
    const durationOf = durationBySlot(eventWithSlots);
    expect(durationOf('SLOT#first')).toBe(90);
    expect(durationOf('SLOT#midday')).toBe(120);
    expect(durationOf('SLOT#gone')).toBe(0);
    // 75 in a 90-minute slot and 115 in a 120-minute slot: SS-SM-06 step 9.
    expect(parseWorkMinutes('75', 90)).toEqual({ value: 75, error: null });
    expect(parseWorkMinutes('115', 120)).toEqual({ value: 115, error: null });
    // 115 in the 90-minute slot is the same number that is refused elsewhere.
    expect(parseWorkMinutes('115', 90).error).toContain('1 hour 30 minutes long');
  });

  it('treats zero as un-confirming rather than deleting', () => {
    expect(parseWorkMinutes('0', 90)).toEqual({ value: 0, error: null });
    expect(parseWorkMinutes('', 90).error).toContain('or 0 to leave the work unconfirmed');
    expect(parseWorkMinutes('-5', 90).error).toContain('whole number');
    expect(parseWorkMinutes('1.5', 90).error).toContain('whole number');
  });
});

// --- the shape every write takes -------------------------------------------

describe('write shape', () => {
  it('keeps one idempotency token per unchanged body and mints a new one when it changes', () => {
    let sequence = 0;
    vi.stubGlobal('crypto', { randomUUID: () => `key-${++sequence}` });
    const body = { showAndSellId: 'SSE#1', capacity: 1 };
    const intent = withIdempotency(body, { keyFor: (input) => JSON.stringify(input) === JSON.stringify(body) ? 'key-a' : 'key-b' });
    expect(intent.idempotency.idempotencyKey).toBe('key-a');
    expect(withIdempotency(body, { keyFor: () => 'key-c' }).idempotency.idempotencyKey).toBe('key-c');
    vi.unstubAllGlobals();
  });

  it('reloads after a version conflict and still names the refusal', () => {
    const reload = vi.fn(async () => undefined);
    const conflict = new GraphQLError('version', { extensions: { errorCode: 'CONFLICT' } });
    return reportWriteFailure(conflict, 'fallback', reload).then((message) => {
      expect(reload).toHaveBeenCalled();
      expect(message).toContain('has already moved');
    });
  });

  it('does not reload for a refusal that is not a version conflict', async () => {
    const reload = vi.fn(async () => undefined);
    const forbidden = new GraphQLError('no', { extensions: { errorCode: 'FORBIDDEN' } });
    const message = await reportWriteFailure(forbidden, 'fallback', reload);
    expect(reload).not.toHaveBeenCalled();
    expect(message).toContain('Only a Unit Admin');
  });
});

// --- allocations -----------------------------------------------------------

const allocation = (productId: string, allocatedQty: number, overrides: Record<string, unknown> = {}) => ({
  __typename: 'ShowAndSellAllocation',
  unitCampaignId: 'UNITCAMP#fall',
  productId,
  showAndSellId: 'SSE#1',
  startAt: '2026-03-21T15:00:00.000Z',
  endAt: '2026-03-21T18:30:00.000Z',
  status: 'OPEN',
  allocatedQty,
  soldQty: 0,
  releasedQty: 0,
  remainingQty: allocatedQty,
  version: 1,
  createdAt: '2026-03-01T15:00:00.000Z',
  updatedAt: '2026-03-01T15:00:00.000Z',
  ...overrides,
});

describe('allocation editor arithmetic', () => {
  const held = openAllocationsByProduct([
    allocation('PROD#caramel', 4),
    allocation('PROD#butter', 2, { status: 'RELEASED', remainingQty: 0 }),
  ] as never);

  it('keeps only the allocations that still reserve stock', () => {
    expect([...held.keys()]).toEqual(['PROD#caramel']);
    expect(openAllocationsByProduct([] as never).size).toBe(0);
  });

  it('sends an unchanged blank as nothing and a cleared field as target zero', () => {
    const targets = allocationTargets(held, new Map([['PROD#caramel', '']]));
    expect(targets).toEqual([]);
    const released = allocationTargets(held, new Map([['PROD#caramel', '0']]));
    expect(released).toEqual<AllocationTarget[]>([{ productId: 'PROD#caramel', quantity: 0 }]);
  });

  it('leaves a product the admin did not touch out of the write', () => {
    expect(allocationTargets(held, new Map([['PROD#caramel', '4']]))).toEqual([]);
    expect(hasAllocationChanges(held, new Map([['PROD#caramel', '4']]))).toBe(false);
    expect(hasAllocationChanges(held, new Map([['PROD#caramel', '5']]))).toBe(true);
  });

  it('refuses to build a plan out of text that is not a number', () => {
    expect(allocationTargets(held, new Map([['PROD#caramel', 'four']]))).toEqual([]);
    expect(allocationTargets(held, new Map([['PROD#caramel', '-1']]))).toEqual([]);
  });

  it('sums a product across every event of the campaign, over all pages', () => {
    const totals = productQuantityOf([
      allocation('PROD#caramel', 4),
      allocation('PROD#caramel', 3, { showAndSellId: 'SSE#2' }),
      allocation('PROD#caramel', 5, { showAndSellId: 'SSE#3', status: 'RELEASED', remainingQty: 0 }),
    ] as never);
    expect(totals.get('PROD#caramel')).toBe(7);
    expect(totals.get('PROD#gone')).toBeUndefined();
  });

  it('reads the server warnings and says them in one sentence each', () => {
    const warnings = overageWarnings([
      {
        __typename: 'AllocationWarning',
        code: 'ASSIGNMENT_OVERAGE',
        productId: 'PROD#caramel',
        currentStockQty: 4,
        assignedQty: 6,
        overageQty: 2,
        message: 'assigned more than the campaign holds',
      },
    ]);
    expect(warnings).toHaveLength(1);
    // The server's own sentence wins when it sends one; the fallback names the
    // three numbers so a row without a message is still actionable.
    expect(warningSentence(warnings[0])).toBe('assigned more than the campaign holds');
    const silent = overageWarnings([{ ...warnings[0], message: null }]);
    expect(warningSentence(silent[0])).toContain('6 assigned against 4 in stock');
    expect(warningSentence(silent[0])).toContain('2 more than the campaign holds');
    expect(overageWarnings(undefined)).toEqual([]);
    expect(overageWarnings(null)).toEqual([]);
  });

  it('puts the biggest overage first, which is the one to fix first', () => {
    const shape = {
      __typename: 'AllocationWarning' as const,
      code: 'ASSIGNMENT_OVERAGE',
      productId: 'PROD#caramel',
      currentStockQty: 4,
      assignedQty: 6,
      message: null,
    };
    const small = { ...shape, overageQty: 1 };
    const big = { ...shape, overageQty: 7 };
    expect(overageWarnings([small, big]).map((warning) => warning.overageQty)).toEqual([7, 1]);
  });
});

// --- participant availability ----------------------------------------------

describe('slot availability', () => {
  const slot = { slotId: 'SLOT#first', startAt: '2026-03-21T15:00:00.000Z', endAt: '2026-03-21T16:30:00.000Z', capacity: 1, openCapacity: 0 };

  it('uses the server capacity rather than a browser subtraction', () => {
    expect(openPlaces(slot)).toBe(0);
    expect(openPlaces({ ...slot, openCapacity: 3 })).toBe(3);
    expect(openPlaces({ ...slot, openCapacity: undefined as unknown as number })).toBe(0);
  });

  it('says why a place is not on offer', () => {
    expect(slotAvailabilityLabel(slot, 'SCHEDULED')).toBe('This slot is full');
    expect(slotAvailabilityLabel({ ...slot, openCapacity: 2 }, 'SCHEDULED')).toBe('2 places left');
    expect(slotAvailabilityLabel({ ...slot, openCapacity: 1 }, 'SCHEDULED')).toBe('1 place left');
    expect(slotAvailabilityLabel({ ...slot, openCapacity: 5 }, 'ENDED')).toBe('This event is no longer taking places');
    expect(
      slotAvailabilityLabel({ ...slot, openCapacity: 5 }, 'SCHEDULED', { status: 'ACTIVE' } as never),
    ).toBe('You are signed up for this slot');
    expect(
      slotAvailabilityLabel({ ...slot, openCapacity: 5 }, 'SCHEDULED', { status: 'CANCELLED' } as never),
    ).toBe('You gave this place back');
  });

  it('finds the signup this Scout holds for a slot', () => {
    const signups = [{ slotId: 'SLOT#a' }, { slotId: 'SLOT#first' }] as never;
    expect(signupForSlot(signups, 'SLOT#first')?.slotId).toBe('SLOT#first');
    expect(signupForSlot(signups, 'SLOT#missing')).toBeUndefined();
  });

  it('treats two intervals as overlapping only where they truly do (SLOT-04)', () => {
    const firstSales = { startAt: '2026-03-21T15:00:00.000Z', endAt: '2026-03-21T16:30:00.000Z' };
    const midday = { startAt: '2026-03-21T16:30:00.000Z', endAt: '2026-03-21T18:30:00.000Z' };
    const fullBooth = { startAt: '2026-03-21T15:00:00.000Z', endAt: '2026-03-21T18:00:00.000Z' };
    // Back-to-back places are allowed: the boundary minute belongs to the later one.
    expect(intervalsOverlap(firstSales, midday)).toBe(false);
    expect(intervalsOverlap(fullBooth, firstSales)).toBe(true);
    expect(intervalsOverlap(fullBooth, midday)).toBe(true);
    expect(collidingCommitments(fullBooth, [firstSales, midday])).toHaveLength(2);
    expect(collidingCommitments(firstSales, [midday])).toHaveLength(0);
  });
});

// --- work confirmation -----------------------------------------------------

describe('work rows', () => {
  const durationOf = (slotId: string) => (slotId === 'SLOT#first' ? 90 : 120);
  const key = (slotId: string, profileId: string) => workRowKey(slotId, profileId);

  it('keys a row by the pair the write is addressed by', () => {
    expect(key('SLOT#first', 'PROFILE#avery')).toBe('SLOT#first#PROFILE#avery');
  });

  const pair = (slotId: string, profileId: string) => ({ slotId, profileId, actualMinutes: 0 });

  it('keys a row by the pair the write is addressed by, and reads that pair whole', () => {
    expect(key('SLOT#first', 'PROFILE#avery')).toBe('SLOT#first#PROFILE#avery');
    // A stored id carries `#` of its own, so the batch is addressed by the pair the
    // board holds, never by splitting the display key back apart on a delimiter.
    const typed = new Map([[key('SLOT#first', 'PROFILE#avery'), '75']]);
    expect(workDraftsOf([pair('SLOT#first', 'PROFILE#avery')], typed)).toEqual([
      { slotId: 'SLOT#first', profileId: 'PROFILE#avery', raw: '75' },
    ]);
    expect(workDraftsOf([pair('SLOT#first', 'PROFILE#avery')], new Map())).toEqual([
      { slotId: 'SLOT#first', profileId: 'PROFILE#avery', raw: '' },
    ]);
  });

  it('sends the two rows SS-SM-06 step 9 enters, and nothing else', () => {
    const rows = [pair('SLOT#first', 'PROFILE#avery'), pair('SLOT#midday', 'PROFILE#avery'), pair('SLOT#first', 'PROFILE#blake')];
    const typed = new Map([
      [key('SLOT#first', 'PROFILE#avery'), '75'],
      [key('SLOT#midday', 'PROFILE#avery'), '115'],
      [key('SLOT#first', 'PROFILE#blake'), ''],
    ]);
    const collected = changedWorkLines(workDraftsOf(rows, typed), [], durationOf);
    expect(collected.error).toBeNull();
    expect(collected.lines).toEqual([
      { slotId: 'SLOT#first', profileId: 'PROFILE#avery', actualMinutes: 75 },
      { slotId: 'SLOT#midday', profileId: 'PROFILE#avery', actualMinutes: 115 },
    ]);
    expect(collected.lines.reduce((total, line) => total + line.actualMinutes, 0)).toBe(190);
  });

  it('refuses the whole batch rather than dropping the bad row', () => {
    const typed = new Map([[key('SLOT#first', 'PROFILE#avery'), '115']]);
    const collected = changedWorkLines(workDraftsOf([pair('SLOT#first', 'PROFILE#avery')], typed), [], durationOf);
    expect(collected.lines).toEqual([]);
    expect(collected.error).toContain('1 hour 30 minutes long');
  });

  it('leaves out a row whose minutes did not move', () => {
    const existing = [{ slotId: 'SLOT#first', profileId: 'PROFILE#avery', actualMinutes: 75 }];
    const typed = new Map([[key('SLOT#first', 'PROFILE#avery'), '75']]);
    expect(changedWorkLines(workDraftsOf([pair('SLOT#first', 'PROFILE#avery')], typed), existing, durationOf).lines).toEqual([]);
  });

  it('keeps zero as a row, because un-confirming is a write', () => {
    const existing = [{ slotId: 'SLOT#first', profileId: 'PROFILE#avery', actualMinutes: 75 }];
    const typed = new Map([[key('SLOT#first', 'PROFILE#avery'), '0']]);
    expect(changedWorkLines(workDraftsOf([pair('SLOT#first', 'PROFILE#avery')], typed), existing, durationOf).lines).toEqual([
      { slotId: 'SLOT#first', profileId: 'PROFILE#avery', actualMinutes: 0 },
    ]);
  });

  it('refuses a plan bigger than one batch may carry', () => {
    const rows = Array.from({ length: MAX_WORK_LINES_PER_BATCH + 1 }, (_, index) =>
      pair('SLOT#first', `PROFILE#${index}`),
    );
    const typed = new Map(rows.map((row) => [key(row.slotId, row.profileId), '10']));
    const collected = changedWorkLines(workDraftsOf(rows, typed), [], durationOf);
    expect(collected.error).toContain(`at most ${MAX_WORK_LINES_PER_BATCH}`);
  });
});

// --- the browser-built invite (CAL-01, CAL-02) -----------------------------

const inviteData: GqlCalendarInviteData = {
  __typename: 'CalendarInviteData',
  unitId: 'UNIT#pack-3149',
  unitDisplayName: 'Pack 3149',
  unitCampaignId: 'UNITCAMP#fall',
  unitCampaignName: 'Fall Popcorn 2026',
  showAndSellId: 'SSE#library',
  slotId: 'SLOT#first',
  profileId: 'PROFILE#avery',
  slotLabel: 'First Sales',
  locationName: 'Library on Main',
  address: null,
  timezone: ZONE,
  slotStartAt: '2026-03-28T15:00:00.000Z',
  slotEndAt: '2026-03-28T16:30:00.000Z',
};

describe('the calendar invite', () => {
  it('names the invite after the place and the slot, and needs no street address', () => {
    expect(inviteSummary(inviteData)).toBe('Show & Sell: First Sales — Library on Main');
    expect(inviteLocation(inviteData)).toBe('Library on Main');
    expect(inviteLocation({ ...inviteData, address: '200 Main St' })).toBe('Library on Main, 200 Main St');
    expect(inviteSummary({ ...inviteData, slotLabel: null })).toBe('Show & Sell: Library on Main');
  });

  it('gives the same signup the same UID every time it is downloaded', () => {
    expect(inviteUid(inviteData)).toBe(inviteUid({ ...inviteData }));
    expect(inviteUid({ ...inviteData, slotId: 'SLOT#midday' })).not.toBe(inviteUid(inviteData));
  });

  it('writes instants as UTC with an explicit marker, and never invents a TZID', () => {
    expect(icsUtc('2026-03-28T15:00:00.000Z')).toBe('20260328T150000Z');
    expect(icsUtc('not a time')).toBe('');
    const ics = buildInvite(inviteData, new Date('2026-03-21T12:00:00.000Z'));
    expect(ics).toContain('DTSTART:20260328T150000Z');
    expect(ics).toContain('DTEND:20260328T163000Z');
    expect(ics).toContain('DTSTAMP:20260321T120000Z');
    expect(ics).not.toContain('TZID');
    expect(ics).not.toContain('VTIMEZONE');
  });

  it('parses as a VCALENDAR with one VEVENT carrying the stable UID and the place', () => {
    const ics = buildInvite(inviteData, new Date('2026-03-21T12:00:00.000Z'));
    // RFC 5545 folds a long line at 75 octets with CRLF + space, and the UID line
    // is long by construction, so the unfolded copy is what a calendar app parses.
    const lines = ics.split('\r\n ').join('').split('\r\n');
    expect(lines[0]).toBe('BEGIN:VCALENDAR');
    expect(lines).toContain('VERSION:2.0');
    expect(lines.filter((line) => line === 'BEGIN:VEVENT')).toHaveLength(1);
    expect(lines.filter((line) => line === 'END:VEVENT')).toHaveLength(1);
    expect(lines).toContain(`UID:${inviteUid(inviteData)}`);
    expect(ics).toContain('SUMMARY:Show & Sell: First Sales — Library on Main');
    expect(ics).toContain('LOCATION:Library on Main');
    // The Unit's zone is named in prose, with the times spelled in it. The
    // description is folded, so it is read back unfolded.
    const description = lines.find((line) => line.startsWith('DESCRIPTION:')) ?? '';
    expect(description).toContain(`Times in ${ZONE}`);
    expect(description).toContain('Pack 3149');
    expect(description).toContain('Fall Popcorn 2026');
  });

  it('escapes and folds what the event text carries', () => {
    const ics = buildInvite(
      { ...inviteData, locationName: 'Library, Main; "Main"', slotLabel: 'First\nSales' },
      new Date('2026-03-21T12:00:00.000Z'),
    );
    expect(ics).toContain('LOCATION:Library\\, Main\\; "Main"');
    expect(ics).toContain('SUMMARY:Show & Sell: First\\nSales — Library\\, Main\\; "Main"');
    for (const line of ics.split('\r\n')) expect(line.length).toBeLessThanOrEqual(75);
  });

  it('folds by octets, which is what a calendar app counts', () => {
    // An em dash is three octets, so a name measured in characters can still put a
    // line over the limit the format allows.
    const ics = buildInvite(
      { ...inviteData, locationName: 'Kroger — 200 Main St, Monroe, MI 48161, United States of America — corner entrance' },
      new Date('2026-03-21T12:00:00.000Z'),
    );
    for (const line of ics.split('\r\n')) expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75);
    expect(ics).toContain('\r\n ');
  });

  it('names the download after the signup it belongs to', () => {
    expect(inviteFileName(inviteData)).toBe('show-and-sell-SSE#library-SLOT#first.ics');
  });

  it('hands the file to the browser and leaves no reference behind', () => {
    const createObjectURL = vi.fn(() => 'blob:invite');
    const revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    vi.stubGlobal('URL', Object.assign(Object.create(URL), URL, { createObjectURL, revokeObjectURL }));
    try {
      downloadInvite('show-and-sell.ics', 'BEGIN:VCALENDAR');
      expect(createObjectURL).toHaveBeenCalled();
      expect(click).toHaveBeenCalled();
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:invite');
      expect(document.querySelector('a[href="blob:invite"]')).toBeNull();
    } finally {
      vi.unstubAllGlobals();
      click.mockRestore();
    }
  });
});

// --- refusal copy ----------------------------------------------------------

describe('failure copy', () => {
  it('names each Show & Sell refusal, and falls back to the transport sentence', () => {
    const coded = (errorCode: string) => new GraphQLError('server said', { extensions: { errorCode } });
    expect(describeShowAndSellFailure(coded('CONFLICT'), 'fallback')).toContain('already moved');
    expect(describeShowAndSellFailure(coded('RESOURCE_BUSY'), 'fallback')).toContain('nothing was changed');
    expect(describeShowAndSellFailure(coded('FORBIDDEN'), 'fallback')).toContain('Unit Admin');
    expect(describeShowAndSellFailure(coded('NOT_FOUND'), 'fallback')).toContain('not one you can reach');
    expect(describeShowAndSellFailure(coded('INVALID_INPUT'), 'fallback')).toContain('refused what was entered');
    expect(describeShowAndSellFailure(coded('SOMETHING_NEW'), 'fallback')).toBe('server said');
    expect(describeShowAndSellFailure(new Error('plain'), 'fallback')).toBe('plain');
    expect(describeShowAndSellFailure(undefined, 'fallback')).toBe('fallback');
  });

  it('recognizes the cross-event commitment collision as distinct from a version conflict', () => {
    const overlap = new GraphQLError('This slot overlaps a place this Scout already holds', {
      extensions: { errorCode: 'CONFLICT' },
    });
    expect(isSignupConflictError(overlap)).toBe(true);
    const stale = new GraphQLError('expectedVersion 4 does not match 7', { extensions: { errorCode: 'CONFLICT' } });
    expect(isSignupConflictError(stale)).toBe(false);
    expect(isSignupConflictError(undefined)).toBe(false);
  });
});

// --- fixture-shape sanity for the §3.5 screens -----------------------------

describe('the SS-SM-06 fixture shape', () => {
  it('holds the three slots of different length the scenario is built from', () => {
    const slots = [
      { slotId: 'SLOT#first', label: 'First Sales', startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T16:30:00.000Z', capacity: 1 },
      { slotId: 'SLOT#midday', label: 'Midday', startAt: '2026-03-28T16:30:00.000Z', endAt: '2026-03-28T18:30:00.000Z', capacity: 1 },
      { slotId: 'SLOT#booth', label: 'Full Booth', startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T18:00:00.000Z', capacity: 1 },
    ];
    expect(slots.map((slot) => minutesBetween(slot.startAt, slot.endAt))).toEqual([90, 120, 180]);
    // Avery holds First Sales and Midday: adjacent, so both are allowed.
    expect(collidingCommitments(slots[0], [slots[1]])).toHaveLength(0);
    // Full Booth overlaps both, which is what step 5 refuses.
    expect(collidingCommitments(slots[2], [slots[0], slots[1]])).toHaveLength(2);
  });
});

// --- the answers that only appear when something else went wrong ------------
//
// Every case here is a path a screen takes only when the row, the zone or the
// server's answer is not what the happy path assumes. They are tested because a
// label that prints `undefined`, or a stamp that prints `Invalid Date`, is a
// screen that lies about a Scout's money and time.

describe('degenerate answers', () => {
  it('labels a status or split method the client has never seen, instead of blanking it', () => {
    expect(showAndSellStatusLabel('SCHEDULED')).toBe('Scheduled');
    expect(showAndSellStatusLabel('NOT_IN_THE_CLIENT_ENUM' as never)).toBe('NOT_IN_THE_CLIENT_ENUM');
    expect(splitMethodLabel('EQUAL')).toBe('Split equally');
    expect(splitMethodLabel('NOT_IN_THE_CLIENT_ENUM' as never)).toBe('NOT_IN_THE_CLIENT_ENUM');
  });

  it('reads a wall clock that carries seconds, and refuses an instant that is not a real date', () => {
    expect(zonedWallClockToUtc('2026-03-14T09:00:30', ZONE)?.toISOString()).toBe('2026-03-14T15:00:30.000Z');
    // Shaped like a stored instant, but no such month: the field refuses it rather
    // than sending an instant the server can only answer INVALID_INPUT for.
    expect(parseInterval('2026-13-45T00:00:00Z', '2026-03-14T18:30:00Z', ZONE).error).toContain('Enter a start and an end');
    expect(minutesUntil('not a time')).toBeNull();
  });

  it('settles a wall clock that falls on the daylight-saving boundary itself', () => {
    // 2026-03-08 is when Denver jumps from UTC-7 to UTC-6. 02:30 that morning never
    // happens, and 01:30 happens twice: the two-pass conversion is what keeps the
    // answer on one side of the jump rather than inventing an hour.
    const spring = zonedWallClockToUtc('2026-03-08T02:30', ZONE);
    expect(spring).not.toBeNull();
    expect(zoneOffsetMinutes(spring as Date, ZONE)).toBe(-360);
    const autumn = zonedWallClockToUtc('2026-11-01T01:30', ZONE);
    expect(autumn).not.toBeNull();
    const again = zonedWallClockToUtc('2026-11-01T01:30:00', ZONE);
    expect(again?.toISOString()).toBe(autumn?.toISOString());
  });

  it('refuses a slot whose two boxes are not dates at all', () => {
    const event = { startAt: '2026-03-21T15:00:00.000Z', endAt: '2026-03-21T18:30:00.000Z' };
    const parsed = parseSlotInterval({ label: 'First Sales', startAt: 'March 21', endAt: 'later', capacity: '4' }, event, ZONE);
    expect(parsed.error).toContain('Enter a start and an end');
  });

  it('treats a product the event does not hold as holding nothing', () => {
    const targets = allocationTargets(new Map(), new Map([['PROD#caramel', '3']]));
    expect(targets).toEqual([{ productId: 'PROD#caramel', quantity: 3 } satisfies AllocationTarget]);
  });

  it('offers a place only while the event takes places and the slot has room', () => {
    const slot = { slotId: 'SLOT#first', startAt: '2026-03-21T15:00:00.000Z', endAt: '2026-03-21T16:30:00.000Z', capacity: 2, openCapacity: 2 };
    expect(isSlotAvailable(slot, 'SCHEDULED')).toBe(true);
    expect(isSlotAvailable({ ...slot, openCapacity: 0 }, 'SCHEDULED')).toBe(false);
    expect(isSlotAvailable(slot, 'ACTIVE')).toBe(false);
  });

  it('never writes an Invalid Date stamp, and names the Unit when its display name is missing', () => {
    const broken = buildInvite(inviteData, new Date('not a time'));
    expect(broken).toContain('DTSTAMP:19700101T000000Z');
    const anonymous = buildInvite({ ...inviteData, unitDisplayName: null, slotLabel: null }, new Date('2026-03-21T12:00:00.000Z'));
    const description = anonymous.split('\r\n ').join('').split('\r\n').find((line) => line.startsWith('DESCRIPTION:')) ?? '';
    expect(description).toContain('Unit: UNIT#pack-3149');
    expect(description).not.toContain('Slot:');
  });

  it('only calls a refusal a signup conflict when the code and the sentence both say so', () => {
    const overlap = new GraphQLError('This Scout already holds a place in an overlapping slot', {
      extensions: { errorCode: 'CONFLICT' },
    });
    expect(isSignupConflictError(overlap)).toBe(true);
    expect(isSignupConflictError({ message: undefined, extensions: { errorCode: 'CONFLICT' } })).toBe(false);
    expect(isSignupConflictError(new GraphQLError('The row already moved', { extensions: { errorCode: 'CONFLICT' } }))).toBe(false);
    expect(isSignupConflictError(undefined)).toBe(false);
  });
});

beforeEach(() => {
  document.body.innerHTML = '';
});

afterEach(() => {
  vi.useRealTimers();
});
