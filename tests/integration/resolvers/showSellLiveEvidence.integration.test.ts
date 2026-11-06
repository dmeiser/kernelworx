import '../setup.ts';
/**
 * Show & Sell live evidence tests (ephemeral stack).
 * Evidence-only; no product surface changes.
 */

import { describe, it, expect } from 'vitest';
import { ApolloClient, gql, HttpLink, InMemoryCache } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';

const createUnauthClient = () => new ApolloClient({
  link: new HttpLink({ uri: process.env.VITE_APPSYNC_ENDPOINT }),
  cache: new InMemoryCache(),
});

describe('Show & Sell live evidence (smoke)', () => {
  it('endpoint responds', async () => {
    const client = createUnauthClient();
    const res = await client.query({ query: gql`query { __typename }` });
    expect(res.data).toBeTruthy();
  });

  it('authenticated client can be created', async () => {
    const r = await createAuthenticatedClient('owner');
    expect(r).toBeTruthy();
  });
});
