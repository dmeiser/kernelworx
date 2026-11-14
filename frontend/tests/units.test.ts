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
  drainConnection,
  isDuplicateUnitError,
  isStaleVersionError,
  joinableProfiles,
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


  it('lists the profiles a Scout may join with: owned, plus WRITE shares once', () => {
    const owned = [{ profileId: 'PROFILE#devon' }];
    const write = { profileId: 'PROFILE#shared', permissions: ['WRITE'] };
    const read = { profileId: 'PROFILE#reader', permissions: ['READ'] };
    const duplicate = { profileId: 'PROFILE#devon', permissions: ['WRITE'] };

    expect(joinableProfiles(owned, [write, read, duplicate]).map((profile) => profile.profileId)).toEqual([
      'PROFILE#devon',
      'PROFILE#shared',
    ]);
    expect(joinableProfiles(undefined, undefined)).toEqual([]);
  });


  it('treats a share with no permission list as not joinable', () => {
    const owned = [{ profileId: 'PROFILE#own', displayName: 'Owned' }];
    expect(joinableProfiles(owned, [{ profileId: 'PROFILE#share', permissions: null }])).toEqual(owned);
  });

  it('walks a connection by cursor until the server stops handing one out', async () => {
    const reads: unknown[] = [];
    const pages: Record<string, unknown> = {
      'cursor-1': { items: ['a'], pageInfo: { endCursor: 'cursor-2', hasNextPage: true } },
      'cursor-2': { items: ['b'], pageInfo: { endCursor: null, hasNextPage: false } },
    };
    const client = {
      query: async (options: { variables: unknown }) => {
        reads.push(options.variables);
        const cursor = (options.variables as { page: { cursor: string } }).page.cursor;
        return { data: { myUnits: pages[cursor] } };
      },
    };

    const items = await drainConnection(client as never, { query: {} as never, field: 'myUnits', limit: 50, variables: { unitId: 'UNIT#x' } }, 'cursor-1');

    expect(items).toEqual(['a', 'b']);
    expect(reads).toEqual([
      { unitId: 'UNIT#x', page: { limit: 50, cursor: 'cursor-1' } },
      { unitId: 'UNIT#x', page: { limit: 50, cursor: 'cursor-2' } },
    ]);
  });

  it('stops a cursor walk on a page that cannot name the next one, and refuses one that failed', async () => {
    const answers: unknown[] = [
      // A page that claims more but issues no cursor cannot be walked further.
      { myUnits: { items: ['a'], pageInfo: { hasNextPage: true } } },
    ];
    const client = { query: async () => ({ data: answers.shift() }) };
    await expect(drainConnection(client as never, { query: {} as never, field: 'myUnits', limit: 50 }, 'cursor-1')).resolves.toEqual(['a']);

    // A connection that is not in the response at all ends the walk rather than
    // inventing an empty page.
    const missing = { query: async () => ({ data: {} }) };
    await expect(drainConnection(missing as never, { query: {} as never, field: 'myUnits', limit: 50 }, 'cursor-1')).resolves.toEqual([]);

    // A page that carries no items contributes nothing rather than throwing.
    const noItems = { query: async () => ({ data: { myUnits: { pageInfo: { hasNextPage: false } } } }) };
    await expect(drainConnection(noItems as never, { query: {} as never, field: 'myUnits', limit: 50 }, 'cursor-1')).resolves.toEqual([]);

    // A response with no data at all ends the walk rather than fabricating a page.
    const noData = { query: async () => ({}) };
    await expect(drainConnection(noData as never, { query: {} as never, field: 'myUnits', limit: 50 }, 'cursor-1')).resolves.toEqual([]);

    // A failed read is an error, not a short list: the caller has to be able to tell
    // "there is no more" from "I could not find out".
    const failed = { query: async () => ({ error: new Error('offline') }) };
    await expect(drainConnection(failed as never, { query: {} as never, field: 'myUnits', limit: 50 }, 'cursor-1')).rejects.toThrow('offline');
  });
});
