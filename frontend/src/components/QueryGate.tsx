/**
 * The loading/failed/ready decision for one query, in one place.
 *
 * Each screen used to spell this out with two early returns, and the three
 * branches of "still loading", "the query failed", and "there is no data to show"
 * drifted between files — one screen offered a retry, another showed a stale list,
 * another claimed the record was missing when the network was down. Those are
 * different facts and the reader deserves the difference, so it is stated once.
 *
 * `children` renders eagerly. That is safe here because every caller passes data it
 * has already defaulted (an empty list is a valid list), and it keeps the gate from
 * needing a render-prop shape every caller would have to type.
 */

import React, { type ReactNode } from 'react';

export interface GateQuery {
  loading: boolean;
  data?: unknown;
  error?: unknown;
}

interface QueryGateProps {
  query: GateQuery;
  loading: ReactNode;
  failure: ReactNode;
  children: ReactNode;
}

export const QueryGate: React.FC<QueryGateProps> = ({ query, loading, failure, children }) => {
  if (query.loading && !query.data) return <>{loading}</>;
  if (!query.data) return <>{failure}</>;
  return <>{children}</>;
};

