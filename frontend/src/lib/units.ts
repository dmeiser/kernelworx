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
