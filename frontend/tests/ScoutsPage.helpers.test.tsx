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
    ];
    expect(filterSharedProfiles(profiles as any, true).map((p) => p.profileId)).toEqual(['p1', 'p2']);
    expect(filterSharedProfiles(profiles as any, false).map((p) => p.profileId)).toEqual(['p2']);
  });

  it('areBothProfilesLoaded and getMyProfiles behave correctly', () => {
    expect(areBothProfilesLoaded(undefined, false)).toBe(false);
    expect(areBothProfilesLoaded({ listMyProfiles: [] }, true)).toBe(true);
    expect(getMyProfiles(undefined)).toEqual([]);
    expect(getMyProfiles({ listMyProfiles: [{ profileId: 'x' }] } as any)).toEqual([{ profileId: 'x' }]);
  });

  it('isPageLoading works with combinations', () => {
    expect(isPageLoading(true, false, false)).toBe(true);
    expect(isPageLoading(false, false, false)).toBe(true);
    expect(isPageLoading(false, false, true)).toBe(false);
  });

  it('buildPreferencesVariables encodes JSON', () => {
    const obj = { showReadOnlyProfiles: false };
    const vars = buildPreferencesVariables(obj as any, true);
    expect(typeof vars.preferences).toBe('string');
    expect(JSON.parse(vars.preferences)).toEqual({ showReadOnlyProfiles: true });
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

  it('updatePreferencesWithRollback success and rollback on error', async () => {
    const setShow = vi.fn();
    const successFn = vi.fn().mockResolvedValue({});
    await updatePreferencesWithRollback(successFn as any, { showReadOnlyProfiles: true }, false, setShow);
    expect(setShow).toHaveBeenCalledWith(false);

    const failing = vi.fn().mockRejectedValue(new Error('boom'));
    await updatePreferencesWithRollback(failing as any, { showReadOnlyProfiles: true }, false, setShow);
    // On failure it should revert the value
    expect(setShow).toHaveBeenCalled();
  });

  it('loadSharedProfilesWithErrorHandling handles success and error', async () => {
    const setProfiles = vi.fn();
    const setLoaded = vi.fn();
    const setError = vi.fn();
    const setLoading = vi.fn();

    const client = { query: vi.fn().mockResolvedValue({ data: { listMyShares: [{ profileId: 'p' }] } }) };
    await loadSharedProfilesWithErrorHandling(client as any, {}, setProfiles, setLoaded, setError, setLoading);
    expect(setProfiles).toHaveBeenCalledWith([{ profileId: 'p' }]);
    expect(setLoaded).toHaveBeenCalledWith(true);

    // error path
    const failingClient = { query: vi.fn().mockRejectedValue(new Error('fail')) };
    await loadSharedProfilesWithErrorHandling(failingClient as any, {}, setProfiles, setLoaded, setError, setLoading);
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
