/**
 * Tests for the API-key-only public Apollo client.
 *
 * The header assertion is the load-bearing one: AppSync's auth directives are
 * an exclusive allow-list, so a request that attaches the Amplify session is
 * refused outright on a key-only field. A signed-in seller previewing their own
 * share link must still produce an anonymous request.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ServerError } from '@apollo/client/errors';
import {
  API_KEY_HEADER,
  RATE_LIMIT_ERROR_TYPE,
  createApiKeyLink,
  createPublicApolloClient,
  createRateLimitRetryLink,
  isRateLimited,
  publicRequestHeaders,
} from '../../src/lib/publicApollo';
import { PUBLIC_GET_ORDER_OFFER } from '../../src/lib/publicOrderGraphQL';
import { fetchAuthSession } from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(() => Promise.resolve({ tokens: { idToken: 'should-never-be-sent' } })),
}));

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const offerBody = {
  data: {
    publicGetOrderOffer: {
      sellerName: 'Troop 42',
      campaignId: 'c-1',
      campaignName: 'Fall popcorn',
      products: [],
      paymentMethods: [],
    },
  },
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv('VITE_APPSYNC_API_KEY', 'test-api-key');
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('publicRequestHeaders', () => {
  it('sends the API key and never an Authorization header', () => {
    const headers = publicRequestHeaders();
    expect(headers[API_KEY_HEADER]).toBe('test-api-key');
    expect(Object.keys(headers)).toEqual([API_KEY_HEADER]);
    expect(headers.Authorization).toBeUndefined();
  });

  it('sends nothing when no key is configured', () => {
    vi.stubEnv('VITE_APPSYNC_API_KEY', '');
    expect(publicRequestHeaders()).toEqual({});
  });
});

describe('isRateLimited', () => {
  const serverError = (status: number, bodyText: string) =>
    new ServerError('Response not successful', {
      response: new Response(bodyText, { status }),
      bodyText,
    });

  it('recognizes the 429 throttle by status', () => {
    expect(isRateLimited(serverError(429, '{"errors":[]}'))).toBe(true);
  });

  it('recognizes the throttle by its error type when the status differs', () => {
    const body = `{"errors":[{"errorType":"${RATE_LIMIT_ERROR_TYPE}","message":"Rate limit exceeded"}]}`;
    expect(isRateLimited(serverError(500, body))).toBe(true);
  });

  it('does not treat an ordinary server error as a throttle', () => {
    expect(isRateLimited(serverError(500, '{"errors":[{"message":"boom"}]}'))).toBe(false);
  });

  it('recognizes a transport-level rate limit message', () => {
    expect(isRateLimited(new Error('Rate limit exceeded'))).toBe(true);
    expect(isRateLimited(new Error('network down'))).toBe(false);
    expect(isRateLimited('not an error')).toBe(false);
  });
});

describe('link chain', () => {
  it('builds an api-key context link and a retry link', () => {
    expect(createApiKeyLink()).toBeDefined();
    expect(createRateLimitRetryLink()).toBeDefined();
  });
});

describe('public client requests', () => {
  it('attaches x-api-key and no Authorization header, and never reads the session', async () => {
    fetchMock.mockResolvedValue(jsonResponse(offerBody));
    const client = createPublicApolloClient();

    const result = await client.query({
      query: PUBLIC_GET_ORDER_OFFER,
      variables: { profileId: 'p-1', token: 'secret-token' },
    });

    const offer = (result.data as { publicGetOrderOffer: { sellerName: string } }).publicGetOrderOffer;
    expect(offer.sellerName).toBe('Troop 42');
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers[API_KEY_HEADER]).toBe('test-api-key');
    const headerNames = Object.keys(headers).map((name) => name.toLowerCase());
    expect(headerNames).not.toContain('authorization');
    expect(fetchAuthSession).not.toHaveBeenCalled();
  });

  it('does not cache a token-bearing query', async () => {
    fetchMock.mockResolvedValue(jsonResponse(offerBody));
    const client = createPublicApolloClient();
    const variables = { profileId: 'p-1', token: 'secret-token' };

    await client.query({ query: PUBLIC_GET_ORDER_OFFER, variables });
    await client.query({ query: PUBLIC_GET_ORDER_OFFER, variables });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('retries a 429 on its own timer and succeeds', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse('{"errors":[{"errorType":"LimitExceededException","message":"Rate limit exceeded"}]}', 429))
      .mockResolvedValueOnce(jsonResponse(offerBody));
    const client = createPublicApolloClient();

    const result = await client.query({
      query: PUBLIC_GET_ORDER_OFFER,
      variables: { profileId: 'p-1', token: 'secret-token' },
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const offer = (result.data as { publicGetOrderOffer: { campaignName: string } }).publicGetOrderOffer;
    expect(offer.campaignName).toBe('Fall popcorn');
  });
});
