import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apolloClient, mapErrorCodeToMessage, getAuthContext, handleApolloError } from '../../src/lib/apollo';
import { fetchAuthSession } from 'aws-amplify/auth';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { ApolloClient, gql, InMemoryCache } from '@apollo/client';
import { MockLink } from '@apollo/client/testing';

vi.mock('aws-amplify/auth', async () => ({
  fetchAuthSession: vi.fn(),
}));

describe('lib/apollo', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('mapErrorCodeToMessage', () => {
    it('returns mapped message for known error code', () => {
      const msg = mapErrorCodeToMessage('FORBIDDEN', 'default');
      expect(msg).toBe('You do not have permission to perform this action.');
    });

    it('returns default message when error code is undefined', () => {
      const msg = mapErrorCodeToMessage(undefined, 'default message');
      expect(msg).toBe('default message');
    });

    it('returns default when unknown code', () => {
      const msg = mapErrorCodeToMessage('UNKNOWN_CODE', 'fallback');
      expect(msg).toBe('fallback');
    });
  });

  describe('getAuthContext', () => {
    it('adds Authorization header when token present', async () => {
      (fetchAuthSession as any).mockResolvedValue({ tokens: { idToken: { toString: () => 'jwt-token' } } });

      const result = await getAuthContext(null as any, { headers: { 'x-test': 'ok' } } as any);
      expect(result).toHaveProperty('headers');
      expect(result.headers).toMatchObject({ 'x-test': 'ok', Authorization: 'Bearer jwt-token' });
    });

    it('throws when token is missing', async () => {
      (fetchAuthSession as any).mockResolvedValue({ tokens: {} });

      await expect(getAuthContext(null as any, { headers: {} } as any)).rejects.toThrow('No valid auth token available');
    });
  });

  describe('handleApolloError', () => {
    let originalConsole: any;

    beforeEach(() => {
      originalConsole = console.error;
      console.error = vi.fn();
    });

    afterEach(() => {
      console.error = originalConsole;
    });

    it('dispatches graphql-error event for GraphQL errors with mapped message', () => {
      const handler = vi.fn();
      window.addEventListener('graphql-error', handler as any);

      const graphQLErrors = [
        {
          message: 'Not allowed',
          locations: [{ line: 1, column: 2 }],
          path: ['some', 'path'],
          extensions: { errorCode: 'FORBIDDEN' },
        },
      ];

      // Create a CombinedGraphQLErrors object like Apollo v4 does
      const error = new CombinedGraphQLErrors({
        errors: graphQLErrors,
      });

      handleApolloError({
        error,
        operation: { operationName: 'MyOp' },
      } as any);

      expect(handler).toHaveBeenCalledTimes(1);
      const ev = (handler.mock.calls[0] as any)[0];
      expect(ev.detail).toMatchObject({ errorCode: 'FORBIDDEN', operation: 'MyOp' });
      expect(ev.detail.message).toContain('You do not have permission');

      window.removeEventListener('graphql-error', handler as any);
    });

    it('dispatches network error event for generic errors', () => {
      const handler = vi.fn();
      window.addEventListener('graphql-error', handler as any);

      const error = new Error('Network down');

      handleApolloError({
        error,
        operation: { operationName: 'FetchStuff' },
      } as any);

      expect(handler).toHaveBeenCalledTimes(1);
      const ev = (handler.mock.calls[0] as any)[0];
      expect(ev.detail).toMatchObject({ errorCode: 'NETWORK_ERROR', operation: 'FetchStuff' });
      expect(ev.detail.message).toContain('Network error');

      window.removeEventListener('graphql-error', handler as any);
    });
  });

  describe('apolloClient defaultOptions behavior', () => {
    it('mutations reject when the server returns GraphQL errors', async () => {
      const mutation = gql`
        mutation Fail {
          fail
        }
      `;
      const link = new MockLink([
        {
          request: { query: mutation },
          result: {
            errors: [{ message: 'Mutation failed', extensions: { errorCode: 'INTERNAL_ERROR' } }],
          },
        },
      ]);
      const client = new ApolloClient({
        link,
        cache: new InMemoryCache(),
        defaultOptions: apolloClient.defaultOptions,
      });

      await expect(client.mutate({ mutation })).rejects.toThrow('Mutation failed');
    });

    it('queries still resolve with data when the server returns GraphQL errors', async () => {
      const query = gql`
        query Partial {
          partial
        }
      `;
      const link = new MockLink([
        {
          request: { query },
          result: {
            data: { partial: 'some data' },
            errors: [{ message: 'Field error', extensions: { errorCode: 'INTERNAL_ERROR' } }],
          },
        },
      ]);
      const client = new ApolloClient({
        link,
        cache: new InMemoryCache(),
        defaultOptions: apolloClient.defaultOptions,
      });

      const result = await client.query({ query });
      expect(result.data).toEqual({ partial: 'some data' });
    });
  });
});
