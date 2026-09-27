/**
 * End-to-end contract for the share-revocation permission failure (#571).
 *
 * The deleteShare pipeline function (delete_share_fn.js) turns a failed
 * DynamoDB owner condition into a util.error() call. This test runs that real
 * resolver code, converts the error it throws into the GraphQL error payload
 * AppSync returns to the client, pushes it through the real Apollo error link
 * and asserts on the text the user actually reads in the toast.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { GraphQLError } from 'graphql';
import { CombinedGraphQLErrors } from '@apollo/client/errors';

const { response } = await import('../../../tofu/application/appsync/js-resolvers/delete_share_fn.js');
const { handleApolloError } = await import('../../src/lib/apollo');
const { Toast } = await import('../../src/components/Toast');

/**
 * AppSync returns util.error(message, type) as a GraphQL error whose
 * `message` is the resolver message and whose `extensions.errorType` is the
 * error type. The runtime mock encodes both in the thrown Error's text as
 * `${type}: ${message}`.
 */
const appsyncGraphQLError = (error: unknown): GraphQLError => {
  const text = (error as Error).message;
  const separator = text.indexOf(': ');
  return new GraphQLError(text.slice(separator + 2), {
    path: ['deleteShare'],
    extensions: { errorType: text.slice(0, separator) },
  });
};

const revokeShareAsNonOwner = (): GraphQLError => {
  try {
    response({
      error: {
        type: 'DynamoDB:ConditionalCheckFailedException',
        message: 'The conditional request failed',
      },
    });
  } catch (error) {
    return appsyncGraphQLError(error);
  }
  throw new Error('expected the owner condition to fail');
};

const renderedToastText = async (error: GraphQLError): Promise<string> => {
  render(<Toast />);
  await act(async () => {
    handleApolloError({
      operation: { operationName: 'DeleteShare' } as never,
      error: new CombinedGraphQLErrors({ errors: [error] }) as never,
      // The error link contract requires forward; this handler only reports the
      // error, so reaching for it would be a bug worth surfacing loudly.
      forward: () => {
        throw new Error('handleApolloError must not forward a failed operation');
      },
    });
  });
  const alert = await screen.findByRole('alert');
  return alert.textContent ?? '';
};

describe('deleteShare ownership failure surfaced to the user', () => {
  it('reports the error type as FORBIDDEN so the session is not treated as invalid', () => {
    const error = revokeShareAsNonOwner();

    expect(error.extensions?.errorType).toBe('FORBIDDEN');
    expect(error.message).toBe('Not authorized to revoke this share or share not found');
  });

  it('tells the user they lack permission instead of asking them to sign in again', async () => {
    const toastText = await renderedToastText(revokeShareAsNonOwner());

    expect(toastText).toContain('You do not have permission to perform this action.');
    expect(toastText).not.toContain('sign in');
  });
});
