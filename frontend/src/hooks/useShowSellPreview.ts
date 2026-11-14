/**
 * Show & Sell preview feature gate (§1.6 constraint: the whole Unit UI stays
 * hidden behind the `show-sell-preview` Cognito group until the wave-7 reveal).
 *
 * The gate reads the same `cognito:groups` claim the admin gate reads
 * (`contexts/AuthContext.tsx`), because that claim — not a server round trip —
 * is what tells the browser which shell to draw. It is presentation only: every
 * Unit operation is still authorized server-side by the Unit grant, so a user
 * who types `/units` by hand gets the API's tenant-isolating denial, not data.
 *
 * Failure direction is deliberate. A session that cannot be read answers
 * `enabled: false`, so a token read that goes wrong hides the feature rather
 * than exposing it to accounts the owner has not opted in.
 */

import { useCallback, useEffect, useState } from 'react';
import { fetchAuthSession } from 'aws-amplify/auth';

export const SHOW_SELL_PREVIEW_GROUP = 'show-sell-preview';

interface ShowSellPreviewState {
  /** True only for accounts carrying the preview group. */
  enabled: boolean;
  /** True until the session claim has been read, so a route never flashes. */
  loading: boolean;
}

function groupsOf(payload: Record<string, unknown> | undefined): string[] {
  const groups = payload?.['cognito:groups'];
  if (Array.isArray(groups)) return groups.map(String);
  if (typeof groups === 'string') return [groups];
  return [];
}

/** Whether this account is in the Show & Sell preview cohort. */
export function useShowSellPreview(): ShowSellPreviewState {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);

  const read = useCallback(async () => {
    setLoading(true);
    try {
      const session = await fetchAuthSession();
      setEnabled(groupsOf(session.tokens?.idToken?.payload).includes(SHOW_SELL_PREVIEW_GROUP));
    } catch {
      setEnabled(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void read();
  }, [read]);

  return { enabled, loading };
}
