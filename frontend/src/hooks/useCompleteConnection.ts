/**
 * Complete a Show & Sell list that the server answered one page at a time.
 *
 * Every Unit and Unit Campaign list query is capped and hands back a cursor, and the
 * screen's own query only ever asks for the first page. A panel that renders that page
 * and stops is showing an incomplete picture of the caller's own data — an admin with
 * more Units, admins, campaigns, or Scout memberships than fit in one page would be
 * told, by silence, that there are fewer than there are. §1.5.6 requires complete
 * pagination, so the cursor is walked for the remainder, the same obligation
 * `fetchAllMyProfiles` documents for Scout profiles.
 *
 * A continuation that fails is reported rather than hidden: a list the browser knows
 * is short has to say so, because the rows it did not fetch are the rows someone might
 * otherwise conclude do not exist.
 */

import { useEffect, useRef, useState } from 'react';
import { useApolloClient } from '@apollo/client/react';
import type { DocumentNode } from '@apollo/client';
import { drainConnection } from '../lib/units';

export interface ConnectionQuery {
  query: DocumentNode;
  field: string;
  limit: number;
  variables?: Record<string, unknown>;
}

/** The connection shape as a generated query result carries it. */
export interface ConnectionLike<T> {
  items?: readonly T[] | null;
  pageInfo?: { endCursor?: string | null; hasNextPage?: boolean | null } | null;
}

interface RestState<T> {
  items: T[];
  loading: boolean;
  failed: boolean;
}

const noRest = <T,>(): RestState<T> => ({ items: [], loading: false, failed: false });

/** Where the first page leaves off, and whether anything is left to fetch. */
function continuationOf<T>(firstPage: ConnectionLike<T> | undefined): { cursor: string | null; more: boolean } {
  const info = firstPage?.pageInfo;
  if (!info || !info.hasNextPage) return { cursor: null, more: false };
  return { cursor: info.endCursor ?? null, more: true };
}

export function useCompleteConnection<T>(
  firstPage: ConnectionLike<T> | undefined,
  read: ConnectionQuery,
): { items: T[]; loadingRest: boolean; failedRest: boolean } {
  const client = useApolloClient();
  const [rest, setRest] = useState<RestState<T>>(noRest);

  // Held in a ref so the read below is not re-issued every time the caller rebuilds
  // its variables object; the effect that fetches is keyed on the cursor and page,
  // which is what actually changed.
  const readRef = useRef(read);
  useEffect(() => {
    readRef.current = read;
  }, [read]);

  const { cursor, more } = continuationOf(firstPage);

  useEffect(() => {
    if (!more || !cursor) {
      setRest(noRest());
      return;
    }
    let active = true;
    setRest({ items: [], loading: true, failed: false });
    void drainConnection<T>(client, readRef.current, cursor)
      .then((items) => {
        if (active) setRest({ items, loading: false, failed: false });
      })
      .catch(() => {
        if (active) setRest({ items: [], loading: false, failed: true });
      });
    return () => {
      active = false;
    };
  }, [client, firstPage, cursor, more]);

  const firstItems = firstPage ? [...(firstPage.items ?? [])] : [];
  return { items: [...firstItems, ...rest.items], loadingRest: rest.loading, failedRest: rest.failed };
}
