/**
 * Shared rules for the Show & Sell event, allocation, slot, signup and calendar
 * surfaces (Stage 3 §3.5).
 *
 * These are the parts that have to agree with the server, stated once instead of
 * re-derived inside each screen: the interval an event may be created with, the
 * capacity a slot accepts, the minutes a work row accepts, how an allocation
 * draft becomes the target list the server asked for, and what a backend refusal
 * turns into in the operator's words.
 *
 * What is deliberately NOT here: any derived balance or capacity number.
 * `remainingQty`, `assignedQty`, `openCapacity` and the pending work preview are
 * the server's answers (SEC-05), and a browser that subtracted them itself could
 * offer a signup or an assignment it has no authority to make.
 */

import {
  graphQLErrorCode,
  isStaleVersionError,
  refreshQuery,
  type WriteIntent,
} from './units';
import type {
  GqlAllocationWarning,
  GqlCalendarInviteData,
  GqlParticipantSignupFieldsFragment,
  GqlShowAndSellAllocationFieldsFragment,
  GqlShowAndSellOpportunityFieldsFragment,
  GqlShowAndSellSlotFieldsFragment,
  GqlShowAndSellStatus,
  GqlSignupStatus,
  GqlSplitMethod,
} from '../types/graphql-generated';

/** How many rows one Show & Sell list read asks for; the server caps at 100. */
export const SHOW_AND_SELL_PAGE_SIZE = 50;

/** Slots one event may hold (SLOT-01 as §3.3.2 enforces it). */
export const MAX_SLOTS_PER_EVENT = 20;

/** The capacity range one slot accepts. */
export const MIN_SLOT_CAPACITY = 1;
export const MAX_SLOT_CAPACITY = 100;

/** Work rows one confirmation batch may carry (§3.4.3). */
export const MAX_WORK_LINES_PER_BATCH = 100;

/** Field lengths the server applies to the same strings (API contract §3.4). */
export const MAX_LOCATION_NAME_LENGTH = 100;
export const MAX_ADDRESS_LENGTH = 500;
export const MAX_CANCELLATION_REASON_LENGTH = 500;
export const MAX_SLOT_LABEL_LENGTH = 100;

/** Where a Show & Sell stands, in the words a screen shows. */
export const SHOW_AND_SELL_STATUS_LABELS: Record<GqlShowAndSellStatus, string> = {
  SCHEDULED: 'Scheduled',
  ACTIVE: 'Running',
  ENDED: 'Ended, awaiting finalization',
  CANCELLED: 'Cancelled',
  FINALIZED: 'Finalized',
  REOPENED: 'Reopened for correction',
};

export function showAndSellStatusLabel(status: GqlShowAndSellStatus): string {
  return SHOW_AND_SELL_STATUS_LABELS[status] ?? status;
}

export const SPLIT_METHOD_LABELS: Record<GqlSplitMethod, string> = {
  EQUAL: 'Split equally',
  TIME_WORKED: 'Split by worked time',
};

export function splitMethodLabel(splitMethod: GqlSplitMethod): string {
  return SPLIT_METHOD_LABELS[splitMethod] ?? splitMethod;
}

export const SIGNUP_STATUS_LABELS: Record<GqlSignupStatus, string> = {
  ACTIVE: 'Holding a place',
  CANCELLED: 'Cancelled',
};

/**
 * Whether this event may still take a place.
 *
 * Signup is written only while the event is scheduled (SIGN-M-01), and an ended
 * or cancelled event is history rather than an offer — so this decides which
 * slot rows carry a button, not whether the server would accept the write.
 */
export function acceptsSignups(status: GqlShowAndSellStatus): boolean {
  return status === 'SCHEDULED';
}

/** Slot edits are legal only while the event is scheduled (§3.3.2). */
export function acceptsSlotEdits(status: GqlShowAndSellStatus): boolean {
  return status === 'SCHEDULED';
}

/** Cancellation is a pre-start act only: a started event is finished, not cancelled (SSE-06). */
export function isCancellable(status: GqlShowAndSellStatus): boolean {
  return status === 'SCHEDULED';
}

/** Work may be confirmed while the Kernel is working, after it ends, or while it is reopened (§3.4.3). */
export function acceptsWorkConfirmation(status: GqlShowAndSellStatus): boolean {
  return status === 'ACTIVE' || status === 'ENDED' || status === 'REOPENED';
}

/** An allocation save is refused outright once the event is finalized or cancelled. */
export function acceptsAllocationEdits(status: GqlShowAndSellStatus): boolean {
  return status !== 'FINALIZED' && status !== 'CANCELLED';
}

/** The settings edit is allowed while scheduled, running, ended, or as a reopened draft (§3.1.3). */
export function acceptsEventEdits(status: GqlShowAndSellStatus): boolean {
  return status !== 'FINALIZED' && status !== 'CANCELLED';
}

// --- interval and duration ---------------------------------------------------

/** A `<input type="datetime-local">` value: wall-clock time with no zone of its own. */
const LOCAL_DATE_TIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/;
const UTC_ISO_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

export interface IntervalParse {
  /** The instant to send, in the one spelling the server takes. */
  startAt: string | null;
  endAt: string | null;
  error: string | null;
}

/** `en-CA` gives ISO-ordered parts; every field is asked for by name. */
const ZONE_PARTS: Intl.DateTimeFormatOptions = {
  timeZone: 'UTC',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
};

function zonePartsOf(instant: Date, timeZone: string): { wallClockUtc: number; hour: number } {
  const formatter = new Intl.DateTimeFormat('en-CA', { ...ZONE_PARTS, timeZone });
  const parts = formatter.formatToParts(instant);
  const value = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((part) => part.type === type)?.value ?? '0');
  const hour = value('hour') === 24 ? 0 : value('hour');
  return { wallClockUtc: Date.UTC(value('year'), value('month') - 1, value('day'), hour, value('minute'), value('second')), hour };
}

/** How many minutes east of UTC the zone is at this instant. */
export function zoneOffsetMinutes(instant: Date, timeZone: string): number {
  return Math.round((zonePartsOf(instant, timeZone).wallClockUtc - instant.getTime()) / 60_000);
}

/**
 * A wall-clock time in a named zone, as the UTC instant the server stores.
 *
 * The admin reads every Show & Sell time in the Unit's own zone, so the boxes
 * they type into mean that zone too — a screen that read the same value in the
 * browser's zone would move the event by the difference between the two, which
 * is how an event ends up an hour off (or eight). The zone offset is taken twice
 * because a zone's offset changes across a daylight-saving boundary, and the
 * first guess can land on the wrong side of it.
 *
 * A zone the browser cannot name falls back to the browser's own zone rather
 * than throwing: the field then behaves like an ordinary `datetime-local`, and
 * the server still refuses an interval it cannot use.
 */
export function zonedWallClockToUtc(wallClock: string, timeZone: string): Date | null {
  const text = wallClock.trim();
  if (!LOCAL_DATE_TIME_PATTERN.test(text)) return null;
  const naive = new Date(text.length === 16 ? `${text}:00` : text);
  if (Number.isNaN(naive.getTime())) return null;
  const guess = guessZonedInstant(naive, timeZone);
  return Number.isNaN(guess.getTime()) ? null : guess;
}

/**
 * The same wall-clock text, with the zone's offset re-read after the first guess.
 *
 * A zone's offset changes across a daylight-saving boundary, so the offset taken
 * at the naive instant can be the wrong side of the change; the re-read settles it.
 */
function guessZonedInstant(naive: Date, timeZone: string): Date {
  try {
    // `new Date(text)` reads a bare `YYYY-MM-DDTHH:mm` in the *browser's* zone, so the
    // browser's offset has to come back out before the Unit zone's goes in. Adding it
    // instead would shift the instant twice and only look right on a machine already set
    // to UTC — which is how a Unit's event lands eight hours off.
    const asUtc = new Date(naive.getTime() - naive.getTimezoneOffset() * 60_000);
    const offset = zoneOffsetMinutes(asUtc, timeZone);
    const first = new Date(asUtc.getTime() - offset * 60_000);
    const corrected = zoneOffsetMinutes(first, timeZone);
    return corrected === offset ? first : new Date(asUtc.getTime() - corrected * 60_000);
  } catch {
    return naive;
  }
}

/** The stored instant, as the wall-clock text that zone's input box shows. */
export function utcToZonedWallClock(instant: string, timeZone: string): string {
  const date = new Date(instant);
  if (Number.isNaN(date.getTime())) return '';
  try {
    const parts = new Intl.DateTimeFormat('en-CA', { ...ZONE_PARTS, timeZone }).formatToParts(date);
    const value = (type: Intl.DateTimeFormatPartTypes): string =>
      parts.find((part) => part.type === type)?.value ?? '00';
    const hour = value('hour') === '24' ? '00' : value('hour');
    return `${value('year')}-${value('month')}-${value('day')}T${hour}:${value('minute')}`;
  } catch {
    return instant.slice(0, 16);
  }
}

function instantOf(raw: string): Date | null {
  const text = raw.trim();
  if (text === '') return null;
  if (UTC_ISO_PATTERN.test(text)) {
    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  return null;
}

/**
 * The event's interval, in the spelling the API takes.
 *
 * The admin chooses wall-clock times in the Unit's zone and the write carries UTC
 * instants, so the conversion happens here once rather than in every screen. An
 * unparseable value is refused in the field: a server that received `March 14`
 * could only answer INVALID_INPUT, and the admin would have no idea which of the
 * two boxes was wrong (SSE-01, SSE-03).
 */
export function parseInterval(startRaw: string, endRaw: string, timeZone: string): IntervalParse {
  const start = readIntervalInstant(startRaw, timeZone);
  const end = readIntervalInstant(endRaw, timeZone);
  if (start === null || end === null) return intervalRefused('Enter a start and an end as a date and a time.');
  if (end.getTime() <= start.getTime()) {
    return intervalRefused('The end must be after the start — an event cannot end before it begins.');
  }
  return { startAt: start.toISOString(), endAt: end.toISOString(), error: null };
}

/** A box's text, read as the Unit's zone first and as a stored instant second. */
function readIntervalInstant(raw: string, timeZone: string): Date | null {
  return zonedWallClockToUtc(raw, timeZone) ?? instantOf(raw);
}

function intervalRefused(error: string): IntervalParse {
  return { startAt: null, endAt: null, error };
}

/** Minutes between two instants, rounded to whole minutes. */
export function minutesBetween(startAt: string, endAt: string): number {
  return Math.round((new Date(endAt).getTime() - new Date(startAt).getTime()) / 60_000);
}

/**
 * A duration in words.
 *
 * Slots may be any length (SSE-03): a screen that printed "1 hour" for a 75-minute
 * slot would be stating a rule the product rejected.
 */
export function durationLabel(minutes: number): string {
  if (minutes <= 0) return '0 minutes';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours} ${hours === 1 ? 'hour' : 'hours'}`);
  if (rest > 0) parts.push(`${rest} minutes`);
  return parts.join(' ');
}

/** One instant, rendered in the Unit's zone rather than the viewer's. */
export function formatInstant(instant: string, timeZone: string): string {
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone,
    });
    return formatter.format(new Date(instant));
  } catch {
    // A zone the browser does not know (a Unit created with a typo'd IANA name
    // before the server's validation, or a jsdom without full ICU data) throws at
    // the formatter's construction, and the screen must still name the instant:
    // UTC with an explicit marker is the fallback.
    return instant.replace('T', ' ').replace(/\.\d+Z$/, ' UTC');
  }
}

/** An interval in words, in the Unit's zone: `Mar 14, 2026, 9:00 AM – 12:30 PM · 3 hours 30 minutes`. */
export function intervalLabel(startAt: string, endAt: string, timeZone: string): string {
  const minutes = minutesBetween(startAt, endAt);
  return `${formatInstant(startAt, timeZone)} – ${formatInstant(endAt, timeZone)} · ${durationLabel(minutes)}`;
}

/**
 * The minutes remaining before an event starts, or null once it has started or if
 * the clock and the stored instant cannot be compared.
 *
 * This is a display aid only: the cancellable/not-cancellable decision is the
 * server's, and it reads the stored interval rather than a browser clock that may
 * be wrong.
 */
export function minutesUntil(startAt: string, now: Date = new Date()): number | null {
  const start = new Date(startAt).getTime();
  if (Number.isNaN(start)) return null;
  const delta = Math.round((start - now.getTime()) / 60_000);
  return delta > 0 ? delta : null;
}

// --- field-level validation --------------------------------------------------

export function parseLocationName(raw: string): string | null {
  const text = raw.trim();
  if (text === '') return 'Name where the event is, such as “Kroger on Monroe”.';
  if (text.length > MAX_LOCATION_NAME_LENGTH) return `Keep the location name under ${MAX_LOCATION_NAME_LENGTH} characters.`;
  return null;
}

export function parseAddress(raw: string): string | null {
  const text = raw.trim();
  if (text.length > MAX_ADDRESS_LENGTH) return `Keep the address under ${MAX_ADDRESS_LENGTH} characters.`;
  return null;
}

/**
 * The reason a cancellation has to give.
 *
 * A cancellation releases stock and cancels Scouts, so the audit row has to say
 * why (SSE-05); the server requires 1-500 trimmed characters and the field says
 * so before the write is offered.
 */
export function parseCancellationReason(raw: string): string | null {
  const text = raw.trim();
  if (text === '') return 'Say why this event is being cancelled — the reason is kept in the audit record.';
  if (text.length > MAX_CANCELLATION_REASON_LENGTH) {
    return `Keep the reason under ${MAX_CANCELLATION_REASON_LENGTH} characters.`;
  }
  return null;
}

export interface SlotDraft {
  slotId?: string;
  version?: number;
  label: string;
  startAt: string;
  endAt: string;
  capacity: string;
}

export interface SlotParse {
  label: string | null;
  capacity: number | null;
  /** The interval to write, in the UTC spelling the server takes. */
  startAt: string | null;
  endAt: string | null;
  error: string | null;
}

/** The capacity range and shape one slot accepts, in the field's own words. */
export function parseCapacity(raw: string): { value: number | null; error: string | null } {
  const text = raw.trim();
  if (text === '') return { value: null, error: 'Enter how many Scouts the slot can hold.' };
  if (!/^\d+$/.test(text)) return { value: null, error: 'Enter a whole number of Scouts.' };
  const value = Number(text);
  if (value < MIN_SLOT_CAPACITY || value > MAX_SLOT_CAPACITY) {
    return { value: null, error: `A slot holds between ${MIN_SLOT_CAPACITY} and ${MAX_SLOT_CAPACITY} Scouts.` };
  }
  return { value, error: null };
}

// --- the shape every Stage 3 write takes ------------------------------------

/**
 * The same body, with this screen's idempotency token for it.
 *
 * A Show & Sell write is retried by the person who pressed the button when the
 * transport fails, so the retry has to carry the token of the attempt it repeats
 * and a different token when the body changed (`createWriteIntent` in
 * `lib/units.ts`); every Stage 3 mutation asks for it, so the shape lives here.
 */
export function withIdempotency<T extends object>(
  body: T,
  intent: WriteIntent,
): T & { idempotency: { idempotencyKey: string } } {
  return { ...body, idempotency: { idempotencyKey: intent.keyFor(body) } };
}

/**
 * The sentence to show for a refused write, after a stale version reloads.
 *
 * A `CONFLICT` here means the row moved under the screen — the versions the form
 * carries are the ones it read — so the read is reloaded as part of reporting it.
 * The screen still shows a sentence rather than silently re-enabling a write that
 * would now be applied to state nobody has looked at.
 */
export async function reportWriteFailure(
  error: unknown,
  fallback: string,
  reload: () => Promise<unknown> | void,
): Promise<string> {
  if (isStaleVersionError(error)) await refreshQuery(reload);
  return describeShowAndSellFailure(error, fallback);
}

// --- ordering the boards read back in ---------------------------------------

/** Slots soonest first: the order a Scout reads a day in. */
export function sortSlots(slots: readonly GqlShowAndSellSlotFieldsFragment[]): GqlShowAndSellSlotFieldsFragment[] {
  return [...slots].sort((left, right) => left.startAt.localeCompare(right.startAt));
}

/**
 * One list, ordered by a key the caller names.
 *
 * Each board orders by a different pair — slots by their start, signups by the
 * slot they sit in and then the Scout — and the only part worth sharing is the
 * copy-then-compare, so no board's row shape is baked into this.
 */
/** The slot's own name, or its id when it has none: a row has to read either way. */
export function slotNameOf(slots: readonly { slotId: string; label?: string | null }[], slotId: string): string {
  const slot = slots.find((candidate) => candidate.slotId === slotId);
  return (slot?.label ?? '') || slotId;
}

export function sortBy<T>(items: readonly T[], key: (item: T) => string): T[] {
  return [...items].sort((left, right) => key(left).localeCompare(key(right)));
}

/**
 * A lookup of each slot's length, for the work-minutes ceiling.
 *
 * A work row cannot exceed its own slot, and the board needs that per row rather
 * than per event: a 90-minute slot in a three-hour event caps its rows at 90.
 */
export function durationBySlot(event: {
  slots: readonly { slotId: string; startAt: string; endAt: string }[];
}): (slotId: string) => number {
  const minutes = new Map<string, number>();
  for (const slot of event.slots) minutes.set(slot.slotId, minutesBetween(slot.startAt, slot.endAt));
  return (slotId) => minutes.get(slotId) ?? 0;
}

/** Whole non-negative digits, as the allocation and capacity boxes take them. */
const WHOLE_NUMBER_PATTERN = /^\d+$/;

/** The text a write carries for an optional field, or null for "no value". */
export function trimmedOrNull(raw: string): string | null {
  return raw.trim().length > 0 ? raw.trim() : null;
}

export function parseSlotLabel(raw: string): string | null {
  const text = raw.trim();
  if (text.length > MAX_SLOT_LABEL_LENGTH) return `Keep the slot name under ${MAX_SLOT_LABEL_LENGTH} characters.`;
  return null;
}

/**
 * A slot inside its event, ordered, any length.
 *
 * The event's interval is immutable, so this check is against the interval the
 * screen was handed, and the server decides the same question against the row it
 * reads. The screen refuses the obvious mistake locally because a slot that
 * cannot fit is a write that can only be refused (§3.3.2).
 */
export function parseSlotInterval(
  draft: SlotDraft,
  event: { startAt: string; endAt: string },
  timeZone: string,
): SlotParse {
  const failed = { label: null, capacity: null, startAt: null, endAt: null, error: '' };
  const labelError = parseSlotLabel(draft.label);
  if (labelError) return { ...failed, error: labelError };
  const interval = parseInterval(draft.startAt, draft.endAt, timeZone);
  if (interval.error) return { ...failed, error: interval.error };
  const fitError = slotFitError(interval, event);
  if (fitError) return { ...failed, error: fitError };
  const capacity = parseCapacity(draft.capacity);
  if (capacity.error) return { ...failed, error: capacity.error };
  return {
    label: trimmedOrNull(draft.label),
    capacity: capacity.value,
    startAt: interval.startAt,
    endAt: interval.endAt,
    error: null,
  };
}

/** Whether the slot sits inside the event's immutable window (§3.3.2). */
function slotFitError(
  interval: IntervalParse,
  event: { startAt: string; endAt: string },
): string | null {
  if (new Date(interval.startAt as string) < new Date(event.startAt)) {
    return 'The slot has to fit inside the event — it cannot start before it or end after it.';
  }
  if (new Date(interval.endAt as string) > new Date(event.endAt)) {
    return 'The slot has to fit inside the event — it cannot start before it or end after it.';
  }
  return null;
}

/**
 * The event's own window, as the two boxes a new slot starts with.
 *
 * Seeding a new slot with the event's interval is the common case — one slot the
 * length of the event — and it is seeded in the zone the board displays, so the
 * admin shortens a slot rather than typing an interval from memory.
 */
export function slotIntervalOf(
  event: { startAt: string; endAt: string },
  timeZone: string,
): { startAt: string; endAt: string } {
  return { startAt: utcToZonedWallClock(event.startAt, timeZone), endAt: utcToZonedWallClock(event.endAt, timeZone) };
}

/** The minutes a work row accepts: 0 un-confirms, 1 through the slot's duration confirms (§3.4.3). */
export function parseWorkMinutes(raw: string, slotMinutes: number): { value: number | null; error: string | null } {
  const text = raw.trim();
  if (text === '') return { value: null, error: 'Enter the minutes worked, or 0 to leave the work unconfirmed.' };
  if (!/^\d+$/.test(text)) return { value: null, error: 'Enter a whole number of minutes.' };
  const value = Number(text);
  if (value > slotMinutes) {
    return { value: null, error: `This slot is ${durationLabel(slotMinutes)} long, so a Scout cannot have worked more than that.` };
  }
  return { value, error: null };
}

// --- allocation editor -------------------------------------------------------

/** One product's stock target for one event, as the save sends it. */
export interface AllocationTarget {
  productId: string;
  quantity: number;
}

/**
 * The allocation rows the event holds, by product.
 *
 * Only OPEN rows count as held: a RELEASED or CANCELLED row is a closed chapter
 * the editor must not offer to "change" back, and the server keys its target
 * arithmetic on the open row.
 */
export function openAllocationsByProduct(
  allocations: readonly GqlShowAndSellAllocationFieldsFragment[],
): Map<string, GqlShowAndSellAllocationFieldsFragment> {
  const byProduct = new Map<string, GqlShowAndSellAllocationFieldsFragment>();
  for (const allocation of allocations) {
    if (allocation.status === 'OPEN') byProduct.set(allocation.productId, allocation);
  }
  return byProduct;
}

/**
 * What the admin actually typed, as the batch the server asked for.
 *
 * Three rules from §3.2.1, all decided here so the screen cannot send them wrong:
 *
 * - A product with no draft value is left out of the batch entirely, because a
 *   product left out keeps whatever it already holds.
 * - A product whose draft matches what it holds is also left out: a save that
 *   writes nothing for it is the difference between "nothing changed" and an
 *   event that suddenly has a zero row nobody asked for.
 * - A product the event holds and the admin cleared to zero IS sent, because
 *   target zero is how the remainder goes back on the shelf.
 */
export function allocationTargets(
  held: ReadonlyMap<string, GqlShowAndSellAllocationFieldsFragment>,
  drafts: ReadonlyMap<string, string>,
): AllocationTarget[] {
  const targets: AllocationTarget[] = [];
  for (const [productId, raw] of drafts) {
    const target = allocationTargetOf(productId, raw, held.get(productId));
    if (target !== null) targets.push(target);
  }
  return targets;
}

/** One row's target, or null when the draft leaves the product as it stands. */
function allocationTargetOf(
  productId: string,
  raw: string,
  current?: GqlShowAndSellAllocationFieldsFragment,
): AllocationTarget | null {
  const text = raw.trim();
  if (!WHOLE_NUMBER_PATTERN.test(text)) return null;
  const quantity = Number(text);
  const holds = allocatedQtyOf(current);
  if (quantity === holds && holds > 0) return null;
  return { productId, quantity };
}

function allocatedQtyOf(current?: GqlShowAndSellAllocationFieldsFragment): number {
  return current?.allocatedQty ?? 0;
}

/** True when the draft holds nothing worth saving. */
export function hasAllocationChanges(
  held: ReadonlyMap<string, GqlShowAndSellAllocationFieldsFragment>,
  drafts: ReadonlyMap<string, string>,
): boolean {
  return allocationTargets(held, drafts).length > 0;
}

/**
 * What every OPEN allocation of this campaign holds, per product.
 *
 * §3.2.4 says this total is the browser's arithmetic, over every page it fetched —
 * the server hands back raw rows precisely so a reader cannot be shown a total the
 * audit trail does not support. A RELEASED or CANCELLED row is excluded because it
 * no longer reserves anything, and a caller that stopped at page one would understate
 * the total, which is why the screens that use this drain the connection first.
 */
export function productQuantityOf(
  allocations: readonly GqlShowAndSellAllocationFieldsFragment[],
): Map<string, number> {
  const totals = new Map<string, number>();
  for (const allocation of allocations) {
    if (allocation.status !== 'OPEN') continue;
    totals.set(allocation.productId, (totals.get(allocation.productId) ?? 0) + allocation.allocatedQty);
  }
  return totals;
}

/**
 * The over-assignment warnings a save answered, in the order a reader acts on them.
 *
 * §3.2.2: a campaign may hold two events that never overlap against the same
 * four Kernels, and that is a warning naming the product, the stock, the assigned
 * total and the overage — never a clamp and never a refusal.
 */
export function overageWarnings(
  warnings: readonly GqlAllocationWarning[] | undefined,
): GqlAllocationWarning[] {
  return [...(warnings ?? [])].sort((left, right) => right.overageQty - left.overageQty);
}

/** The tooltip sentence, when the server's own sentence is missing. */
export function warningSentence(warning: GqlAllocationWarning): string {
  if (warning.message) return warning.message;
  return `${warning.assignedQty} assigned against ${warning.currentStockQty} in stock — ${warning.overageQty} more than the campaign holds.`;
}

// --- signups and slots -------------------------------------------------------

/** Places still open in a slot, as the server computed them (SEC-05). */
export function openPlaces(slot: { openCapacity: number }): number {
  // A row that answers no capacity is read as no places, never as `NaN` compared
  // against zero: `NaN > 0` is false, so the accidental subtraction the browser
  // must not do would look like a full slot rather than a missing number.
  if (!Number.isFinite(slot.openCapacity)) return 0;
  return Math.max(0, slot.openCapacity);
}

/** A slot a Scout can still take: it has room and the event still accepts places. */
export function isSlotAvailable(
  slot: GqlShowAndSellOpportunityFieldsFragment['slots'][number],
  status: GqlShowAndSellStatus,
): boolean {
  return acceptsSignups(status) && openPlaces(slot) > 0;
}

/** The signup this Scout holds for a slot, active or cancelled history. */
export function signupForSlot(
  signups: readonly GqlParticipantSignupFieldsFragment[],
  slotId: string,
): GqlParticipantSignupFieldsFragment | undefined {
  return signups.find((signup) => signup.slotId === slotId);
}

/**
 * Why a place is not on offer, in words that name the real reason.
 *
 * A Scout who is told only "not available" presses the button again or assumes a
 * bug; the three states are different facts and each has its own next step.
 */
export function slotAvailabilityLabel(
  slot: GqlShowAndSellOpportunityFieldsFragment['slots'][number],
  status: GqlShowAndSellStatus,
  signup?: GqlParticipantSignupFieldsFragment,
): string {
  const place = participantPlaceLabel(signup);
  if (place !== null) return place;
  if (!acceptsSignups(status)) return 'This event is no longer taking places';
  return placesLabel(openPlaces(slot));
}

/** What this Scout already holds in the slot, or null when they hold nothing. */
function participantPlaceLabel(signup?: GqlParticipantSignupFieldsFragment): string | null {
  if (signup?.status === 'ACTIVE') return 'You are signed up for this slot';
  if (signup?.status === 'CANCELLED') return 'You gave this place back';
  return null;
}

function placesLabel(open: number): string {
  if (open === 0) return 'This slot is full';
  return `${open} ${open === 1 ? 'place' : 'places'} left`;
}

/** Two half-open intervals overlap when each starts before the other ends (SLOT-04). */
export function intervalsOverlap(
  left: { startAt: string; endAt: string },
  right: { startAt: string; endAt: string },
): boolean {
  return (
    new Date(left.startAt).getTime() < new Date(right.endAt).getTime() &&
    new Date(right.startAt).getTime() < new Date(left.endAt).getTime()
  );
}

/**
 * The commitments this slot would collide with.
 *
 * The server decides the refusal — its authoritative read covers every Unit
 * Campaign (SLOT-04) — and this is only what the screen can say *before* the
 * write, from the commitment list the caller is already entitled to.
 */
export function collidingCommitments<T extends { startAt: string; endAt: string }>(
  slot: { startAt: string; endAt: string },
  commitments: readonly T[],
): T[] {
  return commitments.filter((commitment) => intervalsOverlap(slot, commitment));
}

// --- work confirmation -------------------------------------------------------

/** One work row the board is offering to save. */
export interface WorkLine {
  slotId: string;
  profileId: string;
  actualMinutes: number;
}

/** What is typed in one row's minutes box, still carrying the pair it belongs to. */
export interface WorkDraft {
  slotId: string;
  profileId: string;
  raw: string;
}

/**
 * The rows whose minutes actually moved.
 *
 * §3.4.3 takes 1-100 unique rows per batch. A row whose minutes are unchanged is
 * left out: a save that re-confirms unchanged work still moves the event version
 * and the audit trail, which is noise an admin then has to explain.
 */
export function changedWorkLines(
  drafts: Iterable<WorkDraft>,
  existing: readonly { slotId: string; profileId: string; actualMinutes: number }[],
  durationOf: (slotId: string) => number,
): { lines: WorkLine[]; error: string | null } {
  const collected = collectWorkLines(drafts, existing, durationOf);
  if (collected.error !== null) return collected;
  return withinWorkBatchLimit(collected.lines);
}

function collectWorkLines(
  drafts: Iterable<WorkDraft>,
  existing: readonly { slotId: string; profileId: string; actualMinutes: number }[],
  durationOf: (slotId: string) => number,
): { lines: WorkLine[]; error: string | null } {
  const lines: WorkLine[] = [];
  for (const draft of drafts) {
    const text = draft.raw.trim();
    if (text === '') continue;
    const parsed = parseWorkMinutes(text, durationOf(draft.slotId));
    if (parsed.error) return { lines: [], error: parsed.error };
    if (workAlreadyConfirmed(existing, draft.slotId, draft.profileId, parsed.value)) continue;
    lines.push({ slotId: draft.slotId, profileId: draft.profileId, actualMinutes: parsed.value as number });
  }
  return { lines, error: null };
}

/** §3.4.3 caps a batch at 100 unique rows; a bigger plan is refused here. */
function withinWorkBatchLimit(lines: WorkLine[]): { lines: WorkLine[]; error: string | null } {
  if (lines.length > MAX_WORK_LINES_PER_BATCH) {
    return { lines: [], error: `Save at most ${MAX_WORK_LINES_PER_BATCH} work rows at a time.` };
  }
  return { lines, error: null };
}

/** True when the server already holds these exact minutes for this pair. */
function workAlreadyConfirmed(
  existing: readonly { slotId: string; profileId: string; actualMinutes: number }[],
  slotId: string,
  profileId: string,
  minutes: number | null,
): boolean {
  const row = existing.find((item) => item.slotId === slotId && item.profileId === profileId);
  return row !== undefined && row.actualMinutes === minutes;
}

/**
 * The board's row key: the pair the write is addressed by.
 *
 * This is a display key only — it labels the input and holds its draft. The write
 * never parses it back apart: a stored id can itself contain `#`
 * (`PROFILE#<uuid>`), so a key that is split on a delimiter is a row that gets
 * addressed to the wrong Scout.
 */
export function workRowKey(slotId: string, profileId: string): string {
  return `${slotId}#${profileId}`;
}

/** What is typed in each of these rows, paired with the row it belongs to. */
export function workDraftsOf(
  rows: readonly { slotId: string; profileId: string }[],
  typed: ReadonlyMap<string, string>,
): WorkDraft[] {
  return rows.map((row) => ({
    slotId: row.slotId,
    profileId: row.profileId,
    raw: typed.get(workRowKey(row.slotId, row.profileId)) ?? '',
  }));
}

// --- calendar data and the browser-generated invite --------------------------

/**
 * The stable UID for one signup's invite.
 *
 * CAL-01 asks for a stable event UID: re-downloading the same signup produces the
 * same UID, so a calendar app updates the existing entry rather than adding a
 * second copy. The identity is the Unit Campaign, event, slot and Scout — the
 * four parts the calendar data is keyed on — and it deliberately contains no
 * timestamp, because the generation timestamp belongs in DTSTAMP.
 */
export function inviteUid(data: Pick<GqlCalendarInviteData, 'unitCampaignId' | 'showAndSellId' | 'slotId' | 'profileId'>): string {
  return `kernelworx-show-and-sell-${data.unitCampaignId}-${data.showAndSellId}-${data.slotId}-${data.profileId}@kernelworx.app`;
}

/** RFC 5545 folds a line at 75 octets; long descriptions are broken with a leading space. */
const ICS_FOLD_OCTETS = 73;

/** Octets, not characters: a folded line is measured in bytes on the wire. */
function icsOctets(value: string): number {
  return new TextEncoder().encode(value).length;
}

function foldIcsLine(line: string): string {
  if (icsOctets(line) <= ICS_FOLD_OCTETS) return line;
  let head = '';
  for (const character of line) {
    if (icsOctets(`${head}${character}`) > ICS_FOLD_OCTETS) break;
    head += character;
  }
  return `${head}\r\n ${foldIcsLine(line.slice(head.length))}`;
}

/** RFC 5545 escaping: backslashes, semicolons, commas and newlines. */
function escapeIcsText(value: string): string {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n');
}

/**
 * An instant as an RFC 5545 UTC date-time.
 *
 * The invite carries UTC with an explicit `Z` rather than a `TZID`, because a TZID
 * is only valid when the same file also carries that zone's `VTIMEZONE` block, and
 * nothing here owns a VTIMEZONE database — inventing one is how an invite lands an
 * hour out. The Unit's IANA zone is named in the description, and the description
 * spells the times in that zone, which is what the Scout reads.
 */
export function icsUtc(instant: string): string {
  const date = new Date(instant);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
}

/**
 * The calendar data, serialized as an `.ics` file the browser hands to the Scout.
 *
 * No server produces this file and nothing stores it (CAL-01, RPT-00): every
 * value in it comes from the authorized `showAndSellSignupCalendarData` read, and
 * cancelling a signup or an event does not touch a file already downloaded
 * (CAL-02).
 */
export function buildInvite(data: GqlCalendarInviteData, generatedAt: Date = new Date()): string {
  const description = inviteDescription(data);
  // An unusable clock still has to produce a file: RFC 5545 requires DTSTAMP, so
  // the epoch is written rather than letting `toISOString` throw the download away.
  const stamp = (Number.isNaN(generatedAt.getTime()) ? '' : icsUtc(generatedAt.toISOString())) || '19700101T000000Z';
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//KernelWorx//Show and Sell//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${inviteUid(data)}`,
    `DTSTAMP:${stamp}`,
    `DTSTART:${icsUtc(data.slotStartAt)}`,
    `DTEND:${icsUtc(data.slotEndAt)}`,
    `SUMMARY:${escapeIcsText(inviteSummary(data))}`,
    `LOCATION:${escapeIcsText(inviteLocation(data))}`,
    `DESCRIPTION:${escapeIcsText(description)}`,
    'END:VEVENT',
    'END:VCALENDAR',
  ];
  return `${lines.map(foldIcsLine).join('\r\n')}\r\n`;
}

export function inviteSummary(data: Pick<GqlCalendarInviteData, 'locationName' | 'slotLabel'>): string {
  return data.slotLabel ? `Show & Sell: ${data.slotLabel} — ${data.locationName}` : `Show & Sell: ${data.locationName}`;
}

/** The location line: the short name, plus the address when the event has one. */
export function inviteLocation(data: Pick<GqlCalendarInviteData, 'locationName' | 'address'>): string {
  return data.address ? `${data.locationName}, ${data.address}` : data.locationName;
}

/**
 * The description: Unit and Unit Campaign context, the slot's times as the Unit's
 * own zone reads them, and the UTC instants underneath, so a Scout in a different
 * zone can still see what the Kernel meant (CAL-01).
 */
export function inviteDescription(data: GqlCalendarInviteData): string {
  const unit = data.unitDisplayName ?? data.unitId;
  const slot = data.slotLabel ? `Slot: ${data.slotLabel}\n` : '';
  return (
    `${slot}` +
    `Unit: ${unit}\n` +
    `Campaign: ${data.unitCampaignName}\n` +
    `Event: ${data.locationName}\n` +
    `Times in ${data.timezone}: ${formatInstant(data.slotStartAt, data.timezone)} – ${formatInstant(data.slotEndAt, data.timezone)}\n` +
    `UTC: ${formatInstant(data.slotStartAt, 'UTC')} – ${formatInstant(data.slotEndAt, 'UTC')}`
  );
}

/** A file name an invite download gets: stable per signup, readable per event. */
export function inviteFileName(data: Pick<GqlCalendarInviteData, 'showAndSellId' | 'slotId'>): string {
  return `show-and-sell-${data.showAndSellId}-${data.slotId}.ics`;
}

/**
 * Hands the serialized invite to the browser as a download.
 *
 * The object URL is revoked on the same tick it is handed over: the file exists
 * only in this tab, for this click, and nothing on the server is created or kept
 * (CAL-02).
 */
export function downloadInvite(fileName: string, contents: string): void {
  const url = URL.createObjectURL(new Blob([contents], { type: 'text/calendar;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

// --- failure copy ------------------------------------------------------------

/**
 * What a Show & Sell refusal means in the operator's words.
 *
 * `CONFLICT` is a version, a capacity, a duplicate, an overlap or a membership
 * refusal — in every one of those cases the next step is to re-read rather than
 * to press the same button again. `RESOURCE_BUSY` is the retryable one. Both are
 * named, because an admin who is told only "something went wrong" retries a stale
 * write and is told no again.
 */
const SHOW_AND_SELL_FAILURE_COPY: Record<string, string> = {
  CONFLICT:
    'That was refused because the event, a slot, or a signup has already moved. Reload this screen and try again with what it now shows.',
  RESOURCE_BUSY: 'The server was busy and nothing was changed. Try again.',
  FORBIDDEN: 'Only a Unit Admin of this Unit can make this change.',
  NOT_FOUND: 'This event, slot, product, or Scout is not one you can reach.',
  INVALID_INPUT: 'The server refused what was entered. Check the values and try again.',
};

export function describeShowAndSellFailure(error: unknown, fallback: string): string {
  const coded = SHOW_AND_SELL_FAILURE_COPY[graphQLErrorCode(error) ?? ''];
  if (coded) return coded;
  return failureMessage(error) || fallback;
}

/** The transport's own words, when the refusal carried no code we recognise. */
function failureMessage(error: unknown): string {
  return String((error as { message?: string } | undefined)?.message ?? '');
}

/**
 * True when the refusal was the cross-event commitment collision (SLOT-04).
 *
 * The server's sentence names the overlap it found; the participant screen turns
 * that into the list of places the Scout already holds, which is the part they
 * cannot see from a slot they were refused at.
 */
export function isSignupConflictError(error: unknown): boolean {
  return graphQLErrorCode(error) === 'CONFLICT' && /overlap|already holds|full|duplicate/i.test(String((error as { message?: string } | undefined)?.message ?? ''));
}
