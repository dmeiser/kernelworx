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
import { GET_INVENTORY_POSITIONS, LIST_UNIT_SCOUT_CAMPAIGN_ORDERS } from './graphql';
import { graphQLErrorCode } from './units';
import type {
  GqlDateRangeFilter,
  GqlGetInventoryPositionsQuery,
  GqlListUnitScoutCampaignOrdersQuery,
  GqlInventoryMovement,
  GqlInventoryMovementType,
  GqlOrderFulfillment,
  GqlOrderFulfillmentFieldsFragment,
  GqlPageInput,
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

/** Where a walk through paged reads stops, whatever the server keeps answering. */
const MAX_PAGES_PER_WALK = 50;

/**
 * The next cursor of a Show & Sell connection, or null when this page is the end.
 *
 * A page that claims more without naming a cursor, or a cursor that does not move,
 * throws instead of handing back a prefix that would read as the whole list.
 */
function nextConnectionCursor(
  connection: { pageInfo?: { endCursor?: string | null; hasNextPage?: boolean } | null },
  readCursor: string | null,
  label: string,
): string | null {
  const info = connection.pageInfo;
  if (!info || !info.hasNextPage) return null;
  const next = info.endCursor;
  if (!next) throw new Error(`${label} reports a next page with no cursor`);
  if (next === readCursor) throw new Error(`${label} cursor did not advance`);
  return next;
}

/** One page of a connection, with the fields a walk needs. */
interface PageLike<T> {
  items?: readonly T[] | null;
  pageInfo?: { endCursor?: string | null; hasNextPage?: boolean } | null;
}

/** Walk one connection from `readPage`'s first page to its end, in order. */
async function drainEveryPage<T>(
  readPage: (cursor: string | null) => Promise<PageLike<T>>,
  label: string,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  for (let pages = 0; pages < MAX_PAGES_PER_WALK; pages += 1) {
    const page = await readPage(cursor);
    items.push(...(page.items ?? []));
    cursor = nextConnectionCursor(page, cursor, label);
    if (!cursor) return items;
  }
  throw new Error(`${label} did not finish within the page limit`);
}

/**
 * The largest product set one `inventoryPositions` read may name.
 *
 * The server caps it because it answers one balance read per named product (API
 * contract §4.1 `INV-Q-01-02`), so a wider catalog is read in chunks rather than asked
 * for in one call the server would refuse.
 */
export const MAX_POSITION_PRODUCT_IDS = 15;

/** The catalog's products, split into the sets one position read may name. */
export function positionProductChunks(productIds: readonly string[]): string[][] {
  const chunks: string[][] = [];
  for (let start = 0; start < productIds.length; start += MAX_POSITION_PRODUCT_IDS) {
    chunks.push(productIds.slice(start, start + MAX_POSITION_PRODUCT_IDS));
  }
  return chunks;
}

type PositionConnection = NonNullable<GqlGetInventoryPositionsQuery['inventoryPositions']>;

/** One position row, as the board's own document answers it. */
export type InventoryPositionRow = PositionConnection['items'][number];

async function readPositionPage(
  client: ApolloClient,
  unitCampaignId: string,
  productIds: readonly string[],
  limit: number,
  cursor: string | null,
): Promise<PositionConnection> {
  const { data, error } = await client.query<GqlGetInventoryPositionsQuery>({
    query: GET_INVENTORY_POSITIONS,
    variables: { unitCampaignId, productIds, page: cursor ? { limit, cursor } : { limit } },
    fetchPolicy: 'network-only',
  });
  if (error) throw error;
  const connection = data?.inventoryPositions;
  if (!connection) throw new Error('the position board answered no payload');
  return connection;
}

/**
 * Every position of one Unit Campaign, one catalog product at a time.
 *
 * Naming the products is what makes the board complete: the resolver answers a catalog
 * product that has no balance row yet with zeros only when the read names it, so a board
 * built from the balance rows alone hides the product nothing has been received for —
 * the one product an admin most needs to see, because it is the one that looks like it
 * was never ordered. The chunks are the read's own cap, and each chunk is walked to its
 * end for the same reason a board that stopped at page one is wrong.
 */
export async function fetchInventoryPositions(
  client: ApolloClient,
  unitCampaignId: string,
  productIds: readonly string[],
  limit: number = INVENTORY_PAGE_SIZE,
): Promise<InventoryPositionRow[]> {
  const positions: InventoryPositionRow[] = [];
  for (const chunk of positionProductChunks(productIds)) {
    const readChunk = (cursor: string | null) => readPositionPage(client, unitCampaignId, chunk, limit, cursor);
    positions.push(...(await drainEveryPage(readChunk, 'the position board')));
  }
  return positions;
}

type OrderConnection = NonNullable<GqlListUnitScoutCampaignOrdersQuery['unitScoutCampaignOrders']>;

/** One Order, as the fulfillment screens' own document answers it. */
export type UnitOrderRow = OrderConnection['items'][number];

async function readOrderPage(
  client: ApolloClient,
  unitCampaignId: string,
  campaignId: string,
  limit: number,
  cursor: string | null,
): Promise<OrderConnection> {
  const { data, error } = await client.query<GqlListUnitScoutCampaignOrdersQuery>({
    query: LIST_UNIT_SCOUT_CAMPAIGN_ORDERS,
    variables: { unitCampaignId, campaignId, page: cursor ? { limit, cursor } : { limit } },
    fetchPolicy: 'network-only',
  });
  if (error) throw error;
  const connection = data?.unitScoutCampaignOrders;
  if (!connection) throw new Error('the Order list answered no payload');
  return connection;
}

/**
 * Every individual Order one Scout Campaign holds for this Unit Campaign.
 *
 * This is the Order read whose authorization is the Order's own Unit origin (§2.6.3).
 * The legacy `listOrdersByCampaign` and `getOrder` pipelines authorize Profile ownership
 * and READ shares only, so the Unit Admin who owes the stock these Orders sold — and who
 * therefore has to fulfill them — reads an empty list through them. The server narrows
 * the answer to this Unit's Orders; the cursor is walked to the end here because an Order
 * whose line still owes stock is the whole reason the screen exists, and a list that
 * stopped at page one would hide it.
 */
export async function fetchUnitScoutCampaignOrders(
  client: ApolloClient,
  unitCampaignId: string,
  campaignId: string,
  limit: number = INVENTORY_PAGE_SIZE,
): Promise<UnitOrderRow[]> {
  const readPage = (cursor: string | null) => readOrderPage(client, unitCampaignId, campaignId, limit, cursor);
  return drainEveryPage(readPage, 'the Order list');
}

/**
 * The two fields that separate the admin's audit record from what a Scout may see
 * (§10.2). This is the same denylist the server uses to build `ParticipantOrderFulfillment`
 * from `OrderFulfillment`, and it is a denylist for the same reason: the participant view
 * is what is LEFT when the audit fields go, so a future audit column cannot reach a Scout
 * because someone forgot to add it to an allow-list.
 */
const ADMIN_ONLY_FULFILLMENT_FIELDS = [
  'actorAccountId',
  'inventoryMovementId',
] as const satisfies readonly (keyof GqlOrderFulfillmentFieldsFragment)[];

/** The audit records in the projection a Scout is shown: the same rows, minus the audit. */
export type ParticipantFulfillmentRow = Omit<
  GqlOrderFulfillmentFieldsFragment,
  (typeof ADMIN_ONLY_FULFILLMENT_FIELDS)[number]
>;

/**
 * The participant projection of the records this screen already holds.
 *
 * The Scout's own history is a read the Unit Admin is not authorized to make — the
 * participant projection hangs off the Order's own reader — so the admin's preview of it
 * is built here, from the audit rows, by subtracting the two audit fields. That keeps the
 * preview honest: it shows exactly the fields the Scout's read answers, and it cannot
 * disclose an actor account or a movement id because those keys are gone from the row.
 */
export function participantProjection(
  records: readonly GqlOrderFulfillmentFieldsFragment[],
): ParticipantFulfillmentRow[] {
  return records.map((record) => {
    const row: Record<string, unknown> = { ...record };
    for (const field of ADMIN_ONLY_FULFILLMENT_FIELDS) delete row[field];
    return row as ParticipantFulfillmentRow;
  });
}
