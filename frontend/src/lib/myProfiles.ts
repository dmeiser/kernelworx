/**
 * Helpers for the listMyProfiles query.
 *
 * The server paginates listMyProfiles (connection shape with nextToken) and
 * caps every page server-side — default 50, maximum 100 profiles per page —
 * so a single response stays within the AppSync resolver count budget
 * (resolver_count_limit = 1000, issue #328: worst case 1 + 5 * pageSize
 * resolver invocations). Callers that need the full profile set must walk
 * the nextToken pages instead of assuming one response contains everything.
 */

import type { ApolloClient } from '@apollo/client';
import { LIST_MY_PROFILES } from './graphql';
import type { GqlListMyProfilesQuery } from '../types/graphql-generated';

export type MyProfile = GqlListMyProfilesQuery['listMyProfiles']['profiles'][number];

function normalizePage(connection: GqlListMyProfilesQuery['listMyProfiles'] | undefined) {
  return { profiles: connection?.profiles ?? [], nextToken: connection?.nextToken ?? null };
}

/**
 * Fetch a single listMyProfiles page, throwing on GraphQL error.
 * Returns a normalized page shape so callers need no null handling.
 */
async function queryProfilesPage(client: ApolloClient, nextToken: string | undefined) {
  const { data, error } = await client.query<GqlListMyProfilesQuery>({
    query: LIST_MY_PROFILES,
    variables: { nextToken },
    fetchPolicy: 'network-only',
  });
  if (error) {
    throw error;
  }
  return normalizePage(data?.listMyProfiles);
}

/**
 * Fetch every profile owned by the current user, following nextToken pages
 * until the connection is exhausted.
 */
export async function fetchAllMyProfiles(client: ApolloClient): Promise<MyProfile[]> {
  const profiles: MyProfile[] = [];
  let nextToken: string | undefined;
  do {
    const page = await queryProfilesPage(client, nextToken);
    profiles.push(...page.profiles);
    nextToken = page.nextToken ?? undefined;
  } while (nextToken);
  return profiles;
}
