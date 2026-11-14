/**
 * Unit helpers in `lib/units.ts` — the pieces the screens branch on.
 *
 * Two of these decide what a failure means to the person looking at it, so they are
 * tested as a contract rather than incidentally through a component.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { GraphQLError } from 'graphql';
import {
  bareAccountId,
  createWriteIntent,
  isDuplicateUnitError,
  isStaleVersionError,
  newIdempotencyKey,
  refreshQuery,
  unitCampaignStatusLabel,
  unitDisplayName,
} from '../src/lib/units';
import { unitFixture } from './helpers/unitFixtures';

describe('idempotency keys', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('falls back to a local key when the browser has no UUID source', () => {
    vi.stubGlobal('crypto', {});

    const key = newIdempotencyKey();

    expect(key).toMatch(/^idem-[a-z0-9]+-[a-z0-9]+$/);
    expect(newIdempotencyKey()).not.toBe(key);
  });

  it('uses the browser UUID when one is available', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' });

    expect(newIdempotencyKey()).toBe('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
  });
});

describe('reading a refused write', () => {
  it('recognizes the duplicate warning from the subcode when one is forwarded', () => {
    const error = new GraphQLError('These details match another Unit', {
      extensions: { errorCode: 'INVALID_INPUT', details: { subcode: 'DUPLICATE_UNIT_METADATA' } },
    });

    expect(isDuplicateUnitError(error)).toBe(true);
  });

  it('recognizes the duplicate warning from the message when no subcode arrives', () => {
    const error = new GraphQLError('A Unit with this type, number, city, and state already exists', {
      extensions: { code: 'INVALID_INPUT' },
    });

    expect(isDuplicateUnitError(error)).toBe(true);
  });

  it('keeps a stale version a separate answer from a duplicate', () => {
    const stale = new GraphQLError('The row changed underneath this write', { extensions: { code: 'CONFLICT' } });

    expect(isStaleVersionError(stale)).toBe(true);
    expect(isDuplicateUnitError(stale)).toBe(false);
  });

  it('treats an error with no codes as neither', () => {
    expect(isDuplicateUnitError(new Error('network'))).toBe(false);
    expect(isStaleVersionError(new Error('network'))).toBe(false);
  });
});

describe('naming', () => {
  it('calls a closed campaign closed', () => {
    expect(unitCampaignStatusLabel(true)).toBe('Active');
    expect(unitCampaignStatusLabel(false)).toBe('Closed');
  });

  it('shows the stored display name when there is one, and the generated name when there is not', () => {
    expect(unitDisplayName(unitFixture())).toBe('Pack 3149 (Springfield, IL)');
    expect(unitDisplayName(unitFixture({ displayName: 'Troop 12 Hall' }))).toBe('Troop 12 Hall');
  });

  it('compares accounts without the table prefix', () => {
    expect(bareAccountId('ACCOUNT#avery')).toBe('avery');
    expect(bareAccountId('avery')).toBe('avery');
  });


  it('reads a refusal that carries no GraphQL error at all', () => {
    expect(isDuplicateUnitError(undefined)).toBe(false);
    expect(isStaleVersionError(null)).toBe(false);
    expect(isDuplicateUnitError({})).toBe(false);
  });


  it('settles a background refresh so a torn-down screen cannot reject unhandled', async () => {
    await expect(refreshQuery(() => Promise.reject(new Error('The operation was aborted.')))).resolves.toBeUndefined();

    let refreshed = false;
    await refreshQuery(async () => {
      refreshed = true;
    });
    expect(refreshed).toBe(true);
  });


  it('keys a write by its payload, so a retry replays and a new edit does not', () => {
    const intent = createWriteIntent();
    const first = { city: 'Fairfield', version: { expectedVersion: 3 } };

    expect(intent.keyFor(first)).toBe(intent.keyFor({ city: 'Fairfield', version: { expectedVersion: 3 } }));
    expect(intent.keyFor({ city: 'Fairfield', version: { expectedVersion: 4 } })).not.toBe(intent.keyFor(first));
  });
});
