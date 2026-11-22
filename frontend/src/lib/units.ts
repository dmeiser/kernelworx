/**
 * Shared rules for the Show & Sell Unit surfaces (Stage 1 §1.6).
 *
 * These are the parts that must agree with the server, stated once instead of
 * re-derived inside each screen: the display name a Unit gets when its admin
 * chose none, the idempotency key a mutation must reuse (and must NOT reuse for
 * a different body), and how a backend denial is recognized well enough to give
 * the user the next step rather than a stack of red text.
 */

import { extractErrorCode, type GraphQLErrorExtensions } from './errorCodes';
import type { GqlUnit } from '../types/graphql-generated';

/** Page size every Unit list asks for; the server caps at 100 (§ PageInput). */
export const UNIT_PAGE_SIZE = 50;

type UnitLabelFields = Pick<GqlUnit, 'unitType' | 'unitNumber' | 'city' | 'state'> & { displayName?: string | null };

/**
 * The name a Unit is shown by.
 *
 * `displayName` is optional storage: an admin may leave it unset, in which case
 * the metadata every Unit must carry forms the name. This mirrors the server's
 * own fallback so the create form can show the admin what they are about to get
 * without asking them to invent a label they may not want.
 */
export function unitDisplayName(unit: UnitLabelFields): string {
  const stored = unit.displayName?.trim();
  if (stored) return stored;
  return `${unit.unitType} ${unit.unitNumber} (${unit.city}, ${unit.state})`;
}

/**
 * A fresh idempotency key.
 *
 * One key per *intent*, not per click: a retry of the same body must reuse it to
 * replay the original write, while a body that has meaningfully changed (a
 * duplicate warning the user has now confirmed) is a different request and must
 * carry a new key — the backend refuses a reused key with a different
 * fingerprint rather than silently overwriting either one.
 */
export function newIdempotencyKey(): string {
  const cryptoWithRandom = globalThis.crypto as Crypto | undefined;
  if (cryptoWithRandom?.randomUUID) return cryptoWithRandom.randomUUID();
  // jsdom and older contexts have no randomUUID; the shape, not the source, is
  // what the server cares about (it is an opaque string).
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * The extensions of the first GraphQL error carried by a failed operation.
 *
 * An HTTP-backed read rejects with an `ApolloError` that lists `graphQLErrors`;
 * a direct link rejection is the `GraphQLError` itself. Both hold the codes this
 * file branches on, so both shapes are read here rather than assuming one.
 */
function firstExtensions(error: unknown): GraphQLErrorExtensions | undefined {
  const carrier = (error ?? {}) as {
    graphQLErrors?: { extensions?: GraphQLErrorExtensions }[];
    extensions?: GraphQLErrorExtensions;
  };
  const first = carrier.graphQLErrors?.[0];
  return first?.extensions ?? carrier.extensions;
}

/** The backend `ErrorCode` on an Apollo error, when one is present. */
export function graphQLErrorCode(error: unknown): string | undefined {
  return extractErrorCode(firstExtensions(error));
}

function errorMessage(error: unknown): string {
  return String((error as { message?: string } | undefined)?.message ?? '');
}

/**
 * True when the refusal was the exact type/number/city/state duplicate warning.
 *
 * The backend carries `DUPLICATE_UNIT_METADATA` in `AppError.details`, which the
 * Lambda error wrapper does not forward across the boundary yet (the AppSync JS
 * resolver's forwarding is the open wiring item). Both signals are accepted so
 * this screen is already correct the day the subcode arrives, and the message
 * text is what works today.
 */
export function isDuplicateUnitError(error: unknown): boolean {
  const details = firstExtensions(error)?.['details'] as { subcode?: string } | undefined;
  if (details?.subcode === 'DUPLICATE_UNIT_METADATA') return true;
  return graphQLErrorCode(error) === 'INVALID_INPUT' && /already exists/i.test(errorMessage(error));
}

/**
 * True when a version the caller was holding went stale (VER-01).
 *
 * Every versioned mutation answers `CONFLICT` when its condition failed, which
 * is the signal to offer a re-read instead of inviting another blind retry.
 */
export function isStaleVersionError(error: unknown): boolean {
  return graphQLErrorCode(error) === 'CONFLICT';
}

/**
 * True when a `CONFLICT` on a payment-method write is the name or capacity rule,
 * not a stale version.
 *
 * The two are the same code on the wire — a duplicate name, the 50-method ceiling
 * and a failed version condition all answer `CONFLICT` — and the thing that tells
 * them apart (`DUPLICATE_PAYMENT_METHOD_NAME` / `PAYMENT_METHOD_LIMIT_REACHED` in
 * `AppError.details.subcode`) is not forwarded across the AppSync JS resolver
 * boundary. So the subcode is read where it exists and the sentence the server sent
 * is what works today. This matters because the two want different answers: a taken
 * name is fixed by typing a different one, and only a stale version is fixed by
 * re-reading the row.
 */
export function isPaymentMethodTakenError(error: unknown): boolean {
  return graphQLErrorCode(error) === 'CONFLICT' && (namesTakenMethod(error) || TAKEN_SENTENCE.test(errorMessage(error)));
}

const TAKEN_SUBCODES = ['DUPLICATE_PAYMENT_METHOD_NAME', 'PAYMENT_METHOD_LIMIT_REACHED'];

/** The sentence DynamoDB's verdict shares with a version condition, read from the server. */
const TAKEN_SENTENCE = /already has (a payment method|\d+ active payment methods)/i;

function namesTakenMethod(error: unknown): boolean {
  const details = firstExtensions(error)?.['details'] as { subcode?: string } | undefined;
  return TAKEN_SUBCODES.includes(details?.subcode ?? '');
}

/** Where the preview lives in the browser; one constant so nav links and page
 *  navigation cannot drift apart from the route the gate is mounted on. */
export const SHOW_SELL_BASE = '/show-sell';

/**
 * The bare Cognito sub behind an account id.
 *
 * `getMyAccount` answers the storage spelling (`ACCOUNT#<sub>`) while the Unit
 * grant rows and this UI's comparisons work on the sub, so the two are compared
 * through this normalizer rather than by string-matching at each call site.
 */
export function bareAccountId(accountId: string): string {
  return accountId.replace(/^ACCOUNT#/, '');
}

/** Human label for a campaign's active state; deactivation is a real state, not an error. */
export function unitCampaignStatusLabel(isActive: boolean): string {
  return isActive ? 'Active' : 'Closed';
}

/**
 * The timezones offered when a Unit is created.
 *
 * A convenience list, not the rule: the server accepts any IANA zone and
 * rejects a typo at write time, so an admin whose zone is missing here can be
 * served by a later addition rather than by a free-text field that invites the
 * exact typos the server-side validation exists to catch.
 */
export const UNIT_TIMEZONES: readonly string[] = [
  'America/New_York',
  'America/Detroit',
  'America/Toronto',
  'America/Chicago',
  'America/Winnipeg',
  'America/Denver',
  'America/Edmonton',
  'America/Boise',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Vancouver',
  'America/Anchorage',
  'Pacific/Honolulu',
  'UTC',
];

/**
 * A write is followed by a read refresh so the screen shows what changed. Apollo
 * rejects that refresh when the screen tears down mid-flight, and the caller after
 * a write has nothing left to do with the rejection; a failed read surfaces through
 * the query's own error state instead. A refresh callback may also be a plain
 * notification, so its return is not assumed to be a promise.
 */
export async function refreshQuery(refresh: () => unknown): Promise<void> {
  try {
    await refresh();
  } catch {
    // Swallowed by design: see above.
  }
}

/**
 * An idempotency key identifies one write intent, not one mounted screen: the same
 * payload sent again is the same write and must replay it, while a changed payload
 * is a different write. A screen that holds one key for its whole lifetime sends a
 * second edit under the first edit's key, and the server refuses it as a changed
 * fingerprint on a write that was never attempted.
 *
 * The key is therefore derived from the payload body: identical body, identical key.
 */
export interface WriteIntent {
  keyFor: (body: unknown) => string;
}

export const createWriteIntent = (): WriteIntent => {
  let last: { fingerprint: string; key: string } | null = null;
  return {
    keyFor: (body) => {
      const fingerprint = JSON.stringify(body);
      if (last === null || last.fingerprint !== fingerprint) {
        last = { fingerprint, key: newIdempotencyKey() };
      }
      return last.key;
    },
  };
};

/**
 * The Scout profiles the caller may join a Unit Campaign with: the ones they own,
 * plus the ones shared to them with WRITE.
 *
 * A shared WRITE profile is the normal arrangement for a family with one account
 * managing two Scouts, and the backend accepts the join for it — a picker that shows
 * only owned profiles would hide a membership the caller is entitled to make. A READ
 * share is not joinable, because joining writes to the profile. An owned profile is
 * never replaced by its share entry, and no profile appears twice.
 */
/** A share joins on the holder's behalf only when it carries WRITE. */
const isJoinableShare = (permissions?: readonly string[] | null): boolean => (permissions ?? []).includes('WRITE');

export function joinableProfiles<T extends { profileId: string }>(
  owned: readonly T[] | undefined,
  shared: readonly (ShareWithPermissions & { profileId: string })[] | undefined,
): T[] {
  const byId = new Map<string, T>((owned ?? []).map((profile) => [profile.profileId, profile]));
  const claimed = (shared ?? []).filter((share) => isJoinableShare(share.permissions));
  for (const share of claimed) {
    if (!byId.has(share.profileId)) byId.set(share.profileId, share as unknown as T);
  }
  return Array.from(byId.values());
}

interface ShareWithPermissions {
  permissions?: readonly string[] | null;
}
import type { ApolloClient, DocumentNode } from '@apollo/client';

/**
 * One page of a Show & Sell connection, in the shape every Show & Sell list query
 * answers (`items` plus `pageInfo`).
 */
export interface ConnectionPage<T> {
  items: T[];
  pageInfo: { endCursor: string | null; hasNextPage: boolean };
}

interface ConnectionRead {
  query: DocumentNode;
  field: string;
  limit: number;
  variables?: Record<string, unknown>;
}

/** One page of a connection, read by cursor; a GraphQL error is thrown, not swallowed. */
async function readConnectionPage<T>(
  client: ApolloClient,
  read: ConnectionRead,
  cursor: string,
): Promise<Partial<ConnectionPage<T>> | undefined> {
  const { data, error } = await client.query<Record<string, Partial<ConnectionPage<T>> | undefined>>({
    query: read.query,
    variables: { ...(read.variables ?? {}), page: { limit: read.limit, cursor } },
    fetchPolicy: 'network-only',
  });
  if (error) throw error;
  return data ? data[read.field] : undefined;
}

/**
 * The cursor to read next, or null when this page is the end of the connection.
 *
 * A page that claims more but cannot say how to reach it is refused, not
 * treated as the end: `hasNextPage: true` with no cursor means the drain would
 * stop with rows it has admitted exist still unfetched, and presenting that
 * partial list as complete is exactly the silence §1.5.6 rules out.
 */
function nextCursorOf(page: Partial<ConnectionPage<unknown>>, read: ConnectionRead, readCursor: string): string | null {
  const info = page.pageInfo;
  if (!info || !info.hasNextPage) return null;
  return advanceCursorOf(info.endCursor ?? null, read, readCursor);
}

/**
 * The cursor that advances this walk, or the fault that says it cannot.
 *
 * Two shapes make the walk unsound rather than merely finished: no cursor at
 * all, and a cursor that names the page already read (the same page answers
 * forever). Both throw, because a caller that renders what it collected has to
 * know that the list is not complete.
 */
function advanceCursorOf(end: string | null, read: ConnectionRead, readCursor: string): string | null {
  if (end === null) {
    throw new Error(`connection ${read.field} reports a next page with no cursor`);
  }
  if (end === readCursor) {
    // Reading the same cursor again answers the same page forever: a cursor
    // that does not advance is a broken pagination contract, not a slow one.
    throw new Error(`connection ${read.field} cursor did not advance`);
  }
  return end;
}

/**
 * Walk a connection to its end, from `cursor` onward.
 *
 * Every way the walk can come apart — a field missing from the response, a
 * page claiming a next page it cannot name, a cursor that never moves — throws
 * rather than returning what it has collected: a caller that renders the result
 * as the full list must never be handed a prefix of it and told, by silence,
 * that it is everything.
 */
export async function drainConnection<T>(client: ApolloClient, read: ConnectionRead, cursor: string): Promise<T[]> {
  const items: T[] = [];
  let next: string | null = cursor;
  while (next) {
    const page = await readConnectionPage<T>(client, read, next);
    if (!page) {
      throw new Error(`connection query returned no ${read.field} payload`);
    }
    items.push(...(page.items ?? []));
    next = nextCursorOf(page, read, next);
  }
  return items;
}
