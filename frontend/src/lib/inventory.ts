/**
 * Shared rules for the Show & Sell inventory, custody, and fulfillment screens
 * (Stage 2 §2.6).
 *
 * These are the parts that must agree with the server, stated once instead of
 * re-derived inside each screen: the integer a quantity field will accept, the
 * reason an adjustment cannot be submitted without, the date window a movement
 * read can ask for, and the wording a backend refusal turns into.
 *
 * What is deliberately NOT here: any derived balance. Sellable, assigned,
 * unassigned, overage, With Scout, and total unit-owned stock are computed
 * server-side from the balance row plus the open allocations and custody rows
 * (spec §7). A browser that added them up itself could show a number the audit
 * trail does not support, which is the failure the whole derived-balance design
 * exists to prevent.
 */

import type { ApolloClient } from '@apollo/client';
import { GET_PARTICIPANT_ORDER_FULFILLMENTS, LIST_UNIT_SCOUT_ORDERS } from './graphql';
import { graphQLErrorCode } from './units';
import type {
  GqlDateRangeFilter,
  GqlGetParticipantOrderFulfillmentsQuery,
  GqlListUnitScoutOrdersQuery,
  GqlInventoryMovement,
  GqlInventoryMovementType,
  GqlOrderFulfillment,
  GqlPageInput,
  GqlParticipantOrderFulfillmentFieldsFragment,
  GqlUnitOrderFieldsFragment,
} from '../types/graphql-generated';

/** Largest quantity the API accepts in one line (API contract §3.4). */
export const MAX_QUANTITY = 1_000_000;

/** Widest movement-history window the API accepts, in days (API contract §3.4). */
export const MAX_MOVEMENT_RANGE_DAYS = 366;

/** How many rows one list page asks for; the server caps at 100. */
export const INVENTORY_PAGE_SIZE = 50;

interface QuantityRules {
  /** Allow a leading `-`, for the two signed adjustments. */
  signed?: boolean;
  /** Allow `0`, which is meaningful for a Council on-order change and a return line. */
  zeroAllowed?: boolean;
}

export interface QuantityParse {
  value: number | null;
  error: string | null;
}

const UNSIGNED_PATTERN = /^\d+$/;
const SIGNED_PATTERN = /^-?\d+$/;

/** The shape refusal: a field that accepted `2.5` would round it away in silence. */
function quantityShapeError(text: string, rules: QuantityRules): string | null {
  if (text === '') return 'Enter a quantity.';
  const pattern = rules.signed ? SIGNED_PATTERN : UNSIGNED_PATTERN;
  if (!pattern.test(text)) {
    return rules.signed ? 'Enter a whole number, positive or negative.' : 'Enter a whole number.';
  }
  return null;
}

/** The bound refusal: the same limits the server applies to the same integer. */
function zeroError(rules: QuantityRules): string | null {
  return rules.signed ? 'Enter a change other than zero.' : 'Enter a quantity above zero.';
}

function maxError(rules: QuantityRules): string {
  return rules.signed
    ? `Enter a change between -${MAX_QUANTITY} and ${MAX_QUANTITY}.`
    : `Enter a quantity of ${MAX_QUANTITY} or less.`;
}

// No sign check here: an unsigned field refuses a leading `-` as a shape, so a
// negative never reaches the bounds.
function quantityBoundsError(value: number, rules: QuantityRules): string | null {
  if (Math.abs(value) > MAX_QUANTITY) return maxError(rules);
  if (value === 0) return rules.zeroAllowed ? null : zeroError(rules);
  return null;
}

/**
 * Parse a quantity field as the integer the server expects.
 *
 * The server rejects `2.5`, `"two"`, and a signed zero; a field that accepted
 * either would send a write that can only fail, and an admin who typed a
 * fraction would have no way to tell that the app rounded it away. So the field
 * refuses exactly the shapes the server refuses, in the field's own words.
 */
export function parseQuantity(raw: string, rules: QuantityRules = {}): QuantityParse {
  const text = raw.trim();
  const shape = quantityShapeError(text, rules);
  if (shape) return { value: null, error: shape };
  const value = Number(text);
  const bounds = quantityBoundsError(value, rules);
  if (bounds) return { value: null, error: bounds };
  return { value, error: null };
}

/**
 * Validate the reason an adjustment must carry.
 *
 * A stock adjustment with no reason is an unexplainable change in the audit
 * trail, so the reason is required before the write is offered — and its length
 * limit is the server's (API contract §3.4), stated here so the admin learns it
 * from the field rather than from a refusal.
 */
export function parseReason(raw: string, required = true): string | null {
  const text = raw.trim();
  if (text === '') return required ? 'Say why the stock changed.' : null;
  if (text.length > 500) return 'Keep the reason under 500 characters.';
  return null;
}

export interface DateRangeParse {
  dateRange: GqlDateRangeFilter | undefined;
  error: string | null;
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** One end of the window, or null when the admin left it open. */
function endpointOf(text: string, endOfDay: boolean): Date | null {
  if (text === '') return null;
  return new Date(`${text}${endOfDay ? 'T23:59:59Z' : 'T00:00:00Z'}`);
}

/** A date the server can take, in the one spelling it asks for. */
function usableEndpoint(text: string): boolean {
  if (text === '') return true;
  if (!DATE_PATTERN.test(text)) return false;
  return !Number.isNaN(Date.parse(`${text}T00:00:00Z`));
}

function endpointsUsable(startAt: string, endAt: string): boolean {
  return usableEndpoint(startAt) && usableEndpoint(endAt);
}

/** The window's own condition: ordered, and no wider than the server answers. */
function windowError(start: Date | null, end: Date | null): string | null {
  if (!start || !end) return null;
  if (end.getTime() <= start.getTime()) return 'The end date must be after the start date.';
  if ((end.getTime() - start.getTime()) / 86_400_000 > MAX_MOVEMENT_RANGE_DAYS) {
    return `The history window can be at most ${MAX_MOVEMENT_RANGE_DAYS} days wide.`;
  }
  return null;
}

function filterOf(start: Date | null, end: Date | null): GqlDateRangeFilter {
  const range: GqlDateRangeFilter = {};
  if (start) range.startAt = start.toISOString();
  if (end) range.endAt = end.toISOString();
  return range;
}

/**
 * The inclusive window a movement history read may ask for.
 *
 * Both ends are optional, but the pair has to be ordered and at most 366 days
 * wide, which is the window the server will answer. An unbounded "everything"
 * is refused server-side, so the field says so before the request.
 */
export function parseDateRange(startRaw: string, endRaw: string): DateRangeParse {
  const startAt = startRaw.trim();
  const endAt = endRaw.trim();
  if (startAt === '' && endAt === '') return { dateRange: undefined, error: null };
  if (!endpointsUsable(startAt, endAt)) return { dateRange: undefined, error: 'Enter both dates as YYYY-MM-DD.' };
  const start = endpointOf(startAt, false);
  const end = endpointOf(endAt, true);
  const ordered = windowError(start, end);
  if (ordered) return { dateRange: undefined, error: ordered };
  return { dateRange: filterOf(start, end), error: null };
}

/**
 * What a failed inventory write means in the operator's words.
 *
 * `CONFLICT` is the version or stock invariant the server refused, and the next
 * step is to re-read rather than to press the same button again; `RESOURCE_BUSY`
 * is the retryable one. Both are named, because an admin who is told only
 * "something went wrong" will retry a stale write and be told no again.
 */
const INVENTORY_FAILURE_COPY: Record<string, string> = {
  CONFLICT:
    'That change was refused because the stock or a version has already moved. Reload this screen and check the quantities before trying again.',
  RESOURCE_BUSY: 'The server was busy and nothing was changed. Try again.',
  FORBIDDEN: 'Only a Unit Admin of this Unit can make this change.',
  NOT_FOUND: 'This campaign, product, or record is not one you can reach.',
};

export function describeInventoryFailure(error: unknown, fallback: string): string {
  const coded = INVENTORY_FAILURE_COPY[graphQLErrorCode(error) ?? ''];
  if (coded) return coded;
  return serverMessageOf(error) || fallback;
}

/** The server's own words, when it answered with none of the named codes. */
function serverMessageOf(error: unknown): string {
  return String((error as { message?: string } | undefined)?.message ?? '');
}

/**
 * The copy every stock-only write carries.
 *
 * `INV-03` is a product requirement, not an implementation detail: a stock-only
 * adjustment must not create an Order, sale, payment, trade record, fulfillment,
 * or Scout credit. Stating it where the write is offered is what stops an admin
 * from using a stock adjustment as a way to record money that belongs elsewhere.
 */
export const STOCK_ONLY_NOTE =
  'This changes stock only. It creates no order, sale, payment, trade record, fulfillment, or Scout credit.';

/** Human labels for the movement types a history read can filter to. */
export const MOVEMENT_TYPE_LABELS: Record<GqlInventoryMovementType, string> = {
  RECEIPT: 'Received',
  STOCK_ADJUSTMENT: 'Stock adjustment',
  COUNCIL_ON_ORDER_ADJUST: 'Council on order',
  EVENT_ASSIGN: 'Assigned to an event',
  EVENT_MANUAL_REDUCE: 'Event assignment reduced',
  EVENT_AUTO_REDUCE: 'Event assignment auto-reduced',
  EVENT_IMMEDIATE_SALE: 'Sold at the event',
  EVENT_RELEASE: 'Event assignment released',
  EVENT_RETURN_RECONCILE: 'Event stock returned',
  EVENT_RE_FINALIZE_ADJUST: 'Re-finalization adjustment',
  SCOUT_ISSUE: 'Issued to Scout',
  SCOUT_SALE_CONSUME: 'Scout sale consumed custody',
  SCOUT_RETURN: 'Returned by Scout',
  INDIVIDUAL_FULFILL: 'Individual order fulfilled',
  WE_OWE_RESERVE: 'Reserved for We Owe',
  WE_OWE_RELEASE: 'We Owe reservation released',
  WE_OWE_FULFILL: 'We Owe fulfilled',
  REVERSAL: 'Reversal',
};

export function movementTypeLabel(movementType: GqlInventoryMovementType): string {
  return MOVEMENT_TYPE_LABELS[movementType] ?? movementType;
}

/**
 * The signed deltas one movement carries, in the order a reader scans them.
 *
 * A movement records five different quantities; showing all five for every row
 * would bury the one that moved. Only the non-zero deltas are named.
 */
export function movementDeltas(
  movement: Pick<
    GqlInventoryMovement,
    'kernelPhysicalDelta' | 'soldPossessionDelta' | 'withScoutDelta' | 'assignedDelta' | 'councilOnOrderDelta'
  >,
): string {
  const parts: string[] = [];
  pushDelta(parts, 'Kernel', movement.kernelPhysicalDelta);
  pushDelta(parts, 'We Owe held', movement.soldPossessionDelta);
  pushDelta(parts, 'With Scout', movement.withScoutDelta);
  pushDelta(parts, 'Assigned', movement.assignedDelta);
  pushDelta(parts, 'Council on order', movement.councilOnOrderDelta);
  return parts.length === 0 ? '—' : parts.join(' · ');
}

function pushDelta(parts: string[], label: string, delta: number): void {
  if (!delta) return;
  parts.push(`${delta > 0 ? '+' : ''}${delta} ${label}`);
}

/** A product's name when the catalog is known, its id when it is not. */
export function productLabel(nameById: ReadonlyMap<string, string>, productId: string): string {
  return nameById.get(productId) ?? productId;
}

/** The page every Show & Sell connection read asks for. */
export function page(limit: number = INVENTORY_PAGE_SIZE): GqlPageInput {
  return { limit };
}

/** How much of an Order line still owes stock: never below zero, never above the line. */
export function unfulfilledQuantity(quantity: number, fulfilledQuantity?: number | null): number {
  const fulfilled = fulfilledQuantity ?? 0;
  return Math.max(0, quantity - fulfilled);
}

/**
 * The version a fulfillment write has to condition on, or null when there is none.
 *
 * `Order.fulfillmentVersion` is nullable because a row written before Wave 3 carries
 * no value. Without it the server has nothing to condition the write on and nothing to
 * re-read, so the screen withholds the button rather than sending a write that can only
 * be refused.
 */
export function fulfillmentVersionOf(order: { fulfillmentVersion?: number | null }): number | null {
  return typeof order.fulfillmentVersion === 'number' ? order.fulfillmentVersion : null;
}

/** True when this Order's history shows custody was consumed for it (a door-to-door sale). */
export function isCustodySale(records: readonly Pick<GqlOrderFulfillment, 'source'>[]): boolean {
  return records.some((record) => record.source === 'SCOUT_CUSTODY');
}

/**
 * The fulfillments that already have a reversal.
 *
 * At most one reversal exists per fulfillment, and the server enforces it with a
 * deterministic key. The screen reads that state off the history it was given, so
 * a second Reverse button is never offered for a fulfillment that has one.
 */
export function reversedFulfillmentIds(
  records: readonly Pick<GqlOrderFulfillment, 'reversalOfFulfillmentId'>[],
): Set<string> {
  const reversed = new Set<string>();
  for (const record of records) {
    if (record.reversalOfFulfillmentId) reversed.add(record.reversalOfFulfillmentId);
  }
  return reversed;
}

/** Only a FULFILL record without a reversal can be reversed. */
export function canReverse(
  record: Pick<GqlOrderFulfillment, 'recordType' | 'fulfillmentId'>,
  reversed: ReadonlySet<string>,
): boolean {
  return record.recordType === 'FULFILL' && !reversed.has(record.fulfillmentId);
}

export const FULFILLMENT_SOURCE_LABELS: Record<string, string> = {
  KERNEL_STOCK: 'Kernel stock',
  SCOUT_CUSTODY: "Scout's custody",
  EXTERNAL_COUNCIL: 'Direct from Council',
};

export function fulfillmentSourceLabel(source: string): string {
  return FULFILLMENT_SOURCE_LABELS[source] ?? source;
}

/**
 * The stock consequence of one fulfillment, in words.
 *
 * An `EXTERNAL_COUNCIL` fulfillment consumes no Kernel stock at all, and a
 * reversal restores only the source that fulfillment took. Saying "no Kernel
 * stock changed" for those records is the difference between an audit the Kernel
 * can reconcile and one that looks like a missing movement.
 */
export function fulfillmentStockNote(record: Pick<GqlOrderFulfillment, 'source'>): string {
  return record.source === 'EXTERNAL_COUNCIL' ? 'No Kernel stock changed' : 'Kernel stock moved';
}

/** How many Orders one legacy list page asks for. */
export const ORDER_PAGE_SIZE = 50;

/** Where a walk through paged reads stops, whatever the server keeps answering. */
const MAX_PAGES_PER_WALK = 50;

interface OrderPage {
  orders: GqlUnitOrderFieldsFragment[];
  nextToken: string | null;
}

async function readOrderPage(
  client: ApolloClient,
  campaignId: string,
  limit: number,
  token: string | null,
): Promise<OrderPage> {
  const { data, error } = await client.query<GqlListUnitScoutOrdersQuery>({
    query: LIST_UNIT_SCOUT_ORDERS,
    variables: { campaignId, limit, nextToken: token },
    fetchPolicy: 'network-only',
  });
  if (error) throw error;
  const page = data?.listOrdersByCampaign;
  if (!page) throw new Error('the Order list returned no payload');
  return { orders: page.orders, nextToken: page.nextToken ?? null };
}

/**
 * Every individual Order of one Scout Campaign, in the fulfillment projection.
 *
 * This is the legacy `nextToken` shape, not the Show & Sell cursor shape, so it is
 * walked by its own token. Stopping at the first page would hide Orders whose lines
 * still owe stock, which is the whole reason the screen exists.
 */
export async function fetchAllCampaignOrders(
  client: ApolloClient,
  campaignId: string,
  limit: number = ORDER_PAGE_SIZE,
): Promise<GqlUnitOrderFieldsFragment[]> {
  const orders: GqlUnitOrderFieldsFragment[] = [];
  let token: string | null = null;
  for (let pages = 0; pages < MAX_PAGES_PER_WALK; pages += 1) {
    const page = await readOrderPage(client, campaignId, limit, token);
    orders.push(...page.orders);
    token = page.nextToken;
    if (!token) return orders;
  }
  throw new Error('the Order list did not finish within the page limit');
}

type ParticipantConnection = NonNullable<
  NonNullable<GqlGetParticipantOrderFulfillmentsQuery['getOrder']>['fulfillments']
>;

async function readFulfillmentPage(
  client: ApolloClient,
  orderId: string,
  limit: number,
  cursor: string | null,
): Promise<ParticipantConnection> {
  const { data, error } = await client.query<GqlGetParticipantOrderFulfillmentsQuery>({
    query: GET_PARTICIPANT_ORDER_FULFILLMENTS,
    variables: { orderId, page: { limit, cursor } },
    fetchPolicy: 'network-only',
  });
  if (error) throw error;
  const connection = data?.getOrder?.fulfillments;
  if (!connection) throw new Error('the Order answered no fulfillment history');
  return connection;
}

/**
 * The next cursor of one fulfillment page.
 *
 * A page that claims more without naming a cursor, or a cursor that does not move,
 * throws instead of handing back a prefix that would read as the whole history.
 */
function nextFulfillmentCursor(connection: ParticipantConnection, readCursor: string | null): string | null {
  const info = connection.pageInfo;
  if (!info || !info.hasNextPage) return null;
  const next = info.endCursor;
  if (!next) throw new Error('the fulfillment history reports a next page with no cursor');
  if (next === readCursor) throw new Error('the fulfillment cursor did not advance');
  return next;
}

/**
 * The fulfillment history in the projection a Scout is allowed to read.
 *
 * The participant connection hangs off `getOrder`, not off a top-level connection
 * field, so the shared cursor walker — which reads one field — cannot walk it.
 */
export async function fetchParticipantFulfillments(
  client: ApolloClient,
  orderId: string,
  limit: number = INVENTORY_PAGE_SIZE,
): Promise<GqlParticipantOrderFulfillmentFieldsFragment[]> {
  const items: GqlParticipantOrderFulfillmentFieldsFragment[] = [];
  let cursor: string | null = null;
  for (let pages = 0; pages < MAX_PAGES_PER_WALK; pages += 1) {
    const connection = await readFulfillmentPage(client, orderId, limit, cursor);
    items.push(...connection.items);
    cursor = nextFulfillmentCursor(connection, cursor);
    if (!cursor) return items;
  }
  throw new Error('the fulfillment history did not finish within the page limit');
}
