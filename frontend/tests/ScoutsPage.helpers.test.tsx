import { describe, it, expect, vi, beforeEach } from 'vitest';

import {
  parsePreferences,
  getPreferencesFromAccount,
  filterSharedProfiles,
  areBothProfilesLoaded,
  getMyProfiles,
  isPageLoading,
  buildPreferencesVariables,
  shouldAutoOpenDialog,
  maybeOpenDialog,
  getInitialPreferenceValue,
  shouldTriggerQueries,
  maybeTriggerQueries,
  handleReturnNavigation,
  canDeleteCurrentProfile,
  maybeDeleteProfile,
  updatePreferencesWithRollback,
  loadSharedProfilesWithErrorHandling,
  handleSharedProfilesError,
  getSharedProfilesFromResult,
  shouldShowEmptyState,
} from '../src/pages/ScoutsPage';

describe('ScoutsPage helpers', () => {
  beforeEach(() => vi.clearAllMocks());

  it('parsePreferences returns default for undefined, empty, invalid, and parses valid JSON', () => {
    expect(parsePreferences(undefined)).toEqual({ showReadOnlyProfiles: true });
    expect(parsePreferences('')).toEqual({ showReadOnlyProfiles: true });
    expect(parsePreferences('{invalid')).toEqual({ showReadOnlyProfiles: true });
    expect(parsePreferences('{"showReadOnlyProfiles":false}')).toEqual({ showReadOnlyProfiles: false });
  });

  it('getPreferencesFromAccount parses account data or returns default', () => {
    expect(getPreferencesFromAccount(undefined)).toEqual({ showReadOnlyProfiles: true });
    const acc = { getMyAccount: { accountId: 'a', preferences: '{"showReadOnlyProfiles":false}' } };
    expect(getPreferencesFromAccount(acc)).toEqual({ showReadOnlyProfiles: false });
  });

  it('filterSharedProfiles respects read-only flag', () => {
    const profiles = [
      { profileId: 'p1', permissions: ['READ'] },
      { profileId: 'p2', permissions: ['WRITE'] },
      { profileId: 'p3', permissions: undefined },
    ];
    expect(filterSharedProfiles(profiles as any, true).map((p) => p.profileId)).toEqual(['p1', 'p2', 'p3']);
    expect(filterSharedProfiles(profiles as any, false).map((p) => p.profileId)).toEqual(['p2']);
  });

  it('areBothProfilesLoaded and getMyProfiles behave correctly', () => {
    expect(areBothProfilesLoaded(undefined, false)).toBe(false);
    expect(areBothProfilesLoaded({ listMyProfiles: { profiles: [] } }, true)).toBe(true);
    expect(getMyProfiles(undefined)).toEqual([]);
    expect(getMyProfiles({ listMyProfiles: { profiles: [{ profileId: 'x' }] } } as any)).toEqual([{ profileId: 'x' }]);
  });

  it('isPageLoading works with combinations', () => {
    expect(isPageLoading(true, false, false)).toBe(true);
    expect(isPageLoading(false, false, false)).toBe(true);
    expect(isPageLoading(false, false, true)).toBe(false);
  });

  it('buildPreferencesVariables merges the toggle into the live blob and locks on it (#510)', () => {
    const blob = JSON.stringify({ showReadOnlyProfiles: false, paymentMethods: [{ name: 'Cash' }] });
    const vars = buildPreferencesVariables(blob, true);
    expect(typeof vars.preferences).toBe('string');
    expect(JSON.parse(vars.preferences)).toEqual({ showReadOnlyProfiles: true, paymentMethods: [{ name: 'Cash' }] });
    // The lock must compare against the raw stored blob verbatim, not a
    // re-serialization of it.
    expect(vars.expectedPreferences).toBe(blob);
  });

  it('buildPreferencesVariables merges extra blob keys into the write, not defaults (#510)', () => {
    const blob = '{"showReadOnlyProfiles":true,"paymentMethods":[{"name":"Venmo"}],"uiDensity":"compact"}';
    const vars = buildPreferencesVariables(blob, false);
    expect(vars.expectedPreferences).toBe(blob);
    const written = JSON.parse(vars.preferences);
    expect(written.showReadOnlyProfiles).toBe(false);
    expect(written.uiDensity).toBe('compact');
    expect(written.paymentMethods).toEqual([{ name: 'Venmo' }]);
  });

  it('buildPreferencesVariables locks on the snapshot the resolver would reject on when the blob is stale (#510)', () => {
    // The user read this blob earlier; the server since stored a different one.
    const staleSnapshot = JSON.stringify({ showReadOnlyProfiles: true });
    const freshStoredBlob = JSON.stringify({ showReadOnlyProfiles: false, paymentMethods: [{ name: 'Cash' }] });
    // The helper is fed the snapshot from the cache read (staleSnapshot), not
    // the fresh stored blob, so expectedPreferences must be exactly the value
    // the resolver's `preferences = :readPrefs` condition rejects on.
    const vars = buildPreferencesVariables(staleSnapshot, true);
    expect(vars.expectedPreferences).toBe(staleSnapshot);
    expect(vars.expectedPreferences).not.toBe(freshStoredBlob);
    expect(JSON.parse(vars.expectedPreferences as string)).not.toEqual(JSON.parse(freshStoredBlob));
    expect(JSON.parse(vars.preferences)).toEqual({ showReadOnlyProfiles: true });
  });

  it('buildPreferencesVariables sends a null snapshot when no blob was read', () => {
    const vars = buildPreferencesVariables(undefined, false);
    expect(JSON.parse(vars.preferences)).toEqual({ showReadOnlyProfiles: false });
    expect(vars.expectedPreferences).toBeNull();
  });

  it('dialog open helpers', () => {
    expect(shouldAutoOpenDialog('/path', false)).toBe(true);
    expect(shouldAutoOpenDialog(undefined, false)).toBe(false);
    const mockSet = vi.fn();
    maybeOpenDialog(true, mockSet);
    expect(mockSet).toHaveBeenCalledWith(true);
  });

  it('initial preference and trigger helpers', () => {
    expect(getInitialPreferenceValue({ showReadOnlyProfiles: false })).toBe(false);
    expect(getInitialPreferenceValue({ showReadOnlyProfiles: undefined as unknown as boolean })).toBe(true);
    expect(shouldTriggerQueries(false, true, false)).toBe(true);
    expect(shouldTriggerQueries(false, false, false)).toBe(false);

    const a = vi.fn();
    const b = vi.fn();
    const c = vi.fn();
    const ref = { current: false } as React.MutableRefObject<boolean>;
    maybeTriggerQueries(true, ref as any, a, b, c);
    expect(ref.current).toBe(true);
    expect(a).toHaveBeenCalled();
    expect(b).toHaveBeenCalled();
    expect(c).toHaveBeenCalled();
  });

  it('handleReturnNavigation navigates after timeout when returnPath provided', () => {
    vi.useFakeTimers();
    const mockNavigate = vi.fn();
    handleReturnNavigation('/to-here', mockNavigate as any);
    vi.runAllTimers();
    expect(mockNavigate).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('canDeleteCurrentProfile and maybeDeleteProfile behavior', async () => {
    expect(canDeleteCurrentProfile(null)).toBe(false);
    expect(canDeleteCurrentProfile('p')).toBe(true);

    const deleteMock = vi.fn().mockResolvedValue({});
    await maybeDeleteProfile(true, 'p', deleteMock as any);
    expect(deleteMock).toHaveBeenCalled();

    // when cannot delete it should not call
    deleteMock.mockClear();
    await maybeDeleteProfile(false, 'p', deleteMock as any);
    expect(deleteMock).not.toHaveBeenCalled();
  });

  it('updatePreferencesWithRollback refreshes the cache on success and rollbacks on error', async () => {
    const setShow = vi.fn();
    const client = { query: vi.fn().mockResolvedValue({ data: {} }) };
    const successFn = vi.fn().mockResolvedValue({});
    await updatePreferencesWithRollback(
      successFn as any,
      '{"showReadOnlyProfiles":true}',
      false,
      setShow,
      client as any,
    );
    expect(setShow).toHaveBeenCalledWith(false);
    // On success it should refresh the cached blob so the next toggle locks
    // against fresh state (#510)
    expect(client.query).toHaveBeenCalledWith(expect.objectContaining({ fetchPolicy: 'network-only' }));

    const failing = vi.fn().mockRejectedValue(new Error('boom'));
    await updatePreferencesWithRollback(failing as any, '{"showReadOnlyProfiles":true}', false, setShow, client as any);
    // On failure it should revert the value
    expect(setShow).toHaveBeenCalledWith(true);
    // ... and refresh the cached blob so a retry reads a fresh snapshot (#510)
    expect(client.query).toHaveBeenCalledWith(expect.objectContaining({ fetchPolicy: 'network-only' }));
  });

  it('loadSharedProfilesWithErrorHandling handles success and error', async () => {
    const setProfiles = vi.fn();
    const setLoaded = vi.fn();
    const setError = vi.fn();
    const setLoading = vi.fn();

    const client = { query: vi.fn().mockResolvedValue({ data: { listMyShares: [{ profileId: 'p' }] } }) };
    await loadSharedProfilesWithErrorHandling(client as any, {} as any, setProfiles, setLoaded, setError, setLoading);
    expect(setProfiles).toHaveBeenCalledWith([{ profileId: 'p' }]);
    expect(setLoaded).toHaveBeenCalledWith(true);

    // error path
    const failingClient = { query: vi.fn().mockRejectedValue(new Error('fail')) };
    await loadSharedProfilesWithErrorHandling(
      failingClient as any,
      {} as any,
      setProfiles,
      setLoaded,
      setError,
      setLoading,
    );
    expect(setError).toHaveBeenCalled();
  });

  it('handleSharedProfilesError and getSharedProfilesFromResult', () => {
    const err = new Error('x');
    expect(handleSharedProfilesError(err)).toBe(err);
    expect(handleSharedProfilesError('y')).toBeInstanceOf(Error);

    expect(getSharedProfilesFromResult({ data: { listMyShares: [{ a: 1 }] } } as any)).toEqual([{ a: 1 }]);
    expect(getSharedProfilesFromResult({} as any)).toEqual([]);
  });

  it('shouldShowEmptyState uses arrays and loading', () => {
    expect(shouldShowEmptyState([], [], false)).toBe(true);
    expect(shouldShowEmptyState([], [], true)).toBe(false);
    expect(shouldShowEmptyState([{ id: 1 } as any], [], false)).toBe(false);
  });
});
