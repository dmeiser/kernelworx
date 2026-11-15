/**
 * The preview gate (§1.6 constraint).
 *
 * The gate decides which shell the browser draws, and it reads the same
 * `cognito:groups` claim the admin gate reads. What matters under test is the
 * failure direction: a session that cannot be read must answer "not enabled", so a
 * token problem hides the feature instead of showing it to accounts that were never
 * opted in.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useShowSellPreview, SHOW_SELL_PREVIEW_GROUP } from '../src/hooks/useShowSellPreview';

const fetchAuthSession = vi.fn();

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: () => fetchAuthSession(),
}));

function sessionWith(payload: Record<string, unknown> | undefined) {
  return { tokens: payload === undefined ? undefined : { idToken: { payload } } };
}

describe('useShowSellPreview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('enables the preview for an account in the group', async () => {
    fetchAuthSession.mockResolvedValue(sessionWith({ 'cognito:groups': [SHOW_SELL_PREVIEW_GROUP] }));
    const { result } = renderHook(() => useShowSellPreview());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.enabled).toBe(true);
  });

  it('leaves the preview off for an account outside the group', async () => {
    fetchAuthSession.mockResolvedValue(sessionWith({ 'cognito:groups': ['ADMIN'] }));
    const { result } = renderHook(() => useShowSellPreview());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.enabled).toBe(false);
  });

  it('accepts the single-string shape Cognito sometimes answers', async () => {
    fetchAuthSession.mockResolvedValue(sessionWith({ 'cognito:groups': SHOW_SELL_PREVIEW_GROUP }));
    const { result } = renderHook(() => useShowSellPreview());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.enabled).toBe(true);
  });

  it('treats a session with no groups, and no token payload, as off', async () => {
    fetchAuthSession.mockResolvedValue(sessionWith({}));
    const empty = renderHook(() => useShowSellPreview());
    await waitFor(() => expect(empty.result.current.loading).toBe(false));
    expect(empty.result.current.enabled).toBe(false);

    fetchAuthSession.mockResolvedValue(sessionWith(undefined));
    const noToken = renderHook(() => useShowSellPreview());
    await waitFor(() => expect(noToken.result.current.loading).toBe(false));
    expect(noToken.result.current.enabled).toBe(false);
  });

  it('fails closed when the session cannot be read at all', async () => {
    fetchAuthSession.mockRejectedValue(new Error('session expired'));
    const { result } = renderHook(() => useShowSellPreview());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.enabled).toBe(false);
  });
});
