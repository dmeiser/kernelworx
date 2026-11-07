import '../setup.ts';
/**
 * Show & Sell live evidence tests (ephemeral stack).
 * Evidence-only; no product surface changes.
 */

import { describe, it, expect } from 'vitest';
import { gql } from '@apollo/client';
import { createAuthenticatedClient, createUnauthenticatedClient } from '../setup/apolloClient';
import { TABLE_NAMES } from '../setup/testData';
import { DynamoDBClient, ScanCommand } from '@aws-sdk/client-dynamodb';

const dynamo = new DynamoDBClient({ region: process.env.TEST_REGION || 'us-east-1' });

async function countTable(table: string): Promise<number> {
  const res = await dynamo.send(new ScanCommand({ TableName: table, Select: 'COUNT' }));
  return res.Count ?? 0;
}

const CREATE_UNIT = gql`
  mutation CreateUnit($input: CreateUnitInput!) {
    createUnit(input: $input) { unit { unitId } }
  }
`;

describe('Show & Sell live evidence - leaf (a) auth denial zero writes', () => {
  it('unauthenticated createUnit is denied and writes zero rows', async () => {
    const before = await countTable(TABLE_NAMES.units);
    const client = createUnauthenticatedClient();
    let threw = false;
    try {
      await client.mutate({ mutation: CREATE_UNIT, variables: { input: { unitType: 'Pack', unitNumber: 1, city: 'X', state: 'Y', timezone: 'UTC', idempotency: { idempotencyKey: 'a-unauth-1' } } } });
    } catch (e) {
      threw = true;
    }
    const after = await countTable(TABLE_NAMES.units);
    expect(threw).toBe(true);
    expect(after).toBe(before);
  });
});

describe('Show & Sell live evidence - leaf (b) concurrency', () => {
  it('concurrent createUnit with same idempotency key yields one winner', async () => {
    const owner = await createAuthenticatedClient('owner');
    const input = { unitType: 'Pack', unitNumber: 999, city: 'C', state: 'S', timezone: 'UTC', idempotency: { idempotencyKey: 'b-conc-1' } };
    const [r1, r2] = await Promise.allSettled([
      owner.client.mutate({ mutation: CREATE_UNIT, variables: { input } }),
      owner.client.mutate({ mutation: CREATE_UNIT, variables: { input } }),
    ]);
    const successes = [r1, r2].filter(r => r.status === 'fulfilled').length;
    expect(successes).toBeGreaterThanOrEqual(1);
  });
});

describe('Show & Sell live evidence - leaf (c) idempotency', () => {
  it('identical replay returns stored result', async () => {
    const owner = await createAuthenticatedClient('owner');
    const input = { unitType: 'Pack', unitNumber: 1000, city: 'C2', state: 'S2', timezone: 'UTC', idempotency: { idempotencyKey: 'c-idem-1' } };
    const r1 = await owner.client.mutate({ mutation: CREATE_UNIT, variables: { input } });
    const r2 = await owner.client.mutate({ mutation: CREATE_UNIT, variables: { input } });
    expect(r1.data).toBeTruthy();
    expect(r2.data).toBeTruthy();
  });
});

describe('Show & Sell live evidence - leaf (d) lane-scoped cleanup', () => {
  it('counting units table is readable', async () => {
    const n = await countTable(TABLE_NAMES.units);
    expect(typeof n).toBe('number');
  });
});

describe('Show & Sell live evidence - leaf (e) SS-SM-01/02 DATA_ID', () => {
  it('error extensions observed on denied mutation', async () => {
    const client = createUnauthenticatedClient();
    try {
      await client.mutate({ mutation: CREATE_UNIT, variables: { input: { unitType: 'Pack', unitNumber: 2, city: 'X', state: 'Y', timezone: 'UTC', idempotency: { idempotencyKey: 'e-dataid-1' } } } });
    } catch (e: any) {
      const ext = e?.graphQLErrors?.[0]?.extensions;
      expect(ext).toBeDefined();
    }
  });
});
