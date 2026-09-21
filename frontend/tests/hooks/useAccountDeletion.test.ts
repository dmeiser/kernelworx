/**
 * Branch-coverage tests for the useAccountDeletion hook.
 *
 * Complements the component-level suites in tests/AccountDeletion.test.tsx
 * by driving the hook directly with a mocked Apollo client and mocked
 * profile discovery, exercising the error-shaping branches the component
 * tests cannot reach (non-Error rejections, object errors without a
 * message, mutate results carrying error, discovery item normalization).
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useAccountDeletion } from '../../src/hooks/useAccountDeletion';
import { fetchAllMyProfiles } from '../../src/lib/myProfiles';

vi.mock('@apollo/client/react', () => ({
  useApolloClient: () => mockClient,
}));

vi.mock('../../src/lib/myProfiles', () => ({
  fetchAllMyProfiles: vi.fn(),
}));

const mockClient = {
  mutate: vi.fn(),
};

vi.mocked(fetchAllMyProfiles);

const notFoundError = new Error('Profile not found');

beforeEach(() => {
  vi.resetAllMocks();
});

function setup(options?: { onSuccess?: () => void }) {
  return renderHook(() => useAccountDeletion(options));
}

describe('useAccountDeletion — loadProfiles', () => {
  test('drops entries without a profileId and defaults a missing sellerName', async () => {
    vi.mocked(fetchAllMyProfiles).mockResolvedValue([
      { profileId: 'PROFILE#a', sellerName: 'Scout Alex' },
      { profileId: null, sellerName: 'Ignored' },
      { profileId: 'PROFILE#b' },
    ] as never);

    const { result } = setup();
    let discovered: unknown;
    await act(async () => {
      discovered = await result.current.loadProfiles();
    });

    expect(discovered).toEqual([
      { profileId: 'PROFILE#a', sellerName: 'Scout Alex', status: 'pending' },
      { profileId: 'PROFILE#b', sellerName: 'Scout Profile', status: 'pending' },
    ]);
    expect(result.current.isDiscovered).toBe(true);
    expect(result.current.error).toBeNull();
  });

  test('falls back to a generic message when discovery rejects with a non-Error', async () => {
    vi.mocked(fetchAllMyProfiles).mockRejectedValue('network down');

    const { result } = setup();
    await act(async () => {
      await result.current.loadProfiles();
    });

    expect(result.current.error).toBe('Failed to load user profiles');
    expect(result.current.isDiscovered).toBe(false);
    expect(result.current.profiles).toEqual([]);
  });
});

describe('useAccountDeletion — profile deletion branches', () => {
  test('swallows not-found profile errors and completes the deletion', async () => {
    vi.mocked(fetchAllMyProfiles).mockResolvedValue([
      { profileId: 'PROFILE#a', sellerName: 'Scout Alex' },
    ] as never);
    mockClient.mutate.mockRejectedValueOnce(notFoundError).mockResolvedValue({ data: { deleteMyAccount: true } });
    const onSuccess = vi.fn();

    const { result } = setup({ onSuccess });
    await act(async () => {
      await result.current.startDeletion();
    });

    await waitFor(() => expect(result.current.step).toBe('completed'));
    expect(result.current.profiles[0].status).toBe('completed');
    expect(onSuccess).toHaveBeenCalled();
  });

  test('fails the step when mutate resolves with a result.error', async () => {
    vi.mocked(fetchAllMyProfiles).mockResolvedValue([
      { profileId: 'PROFILE#a', sellerName: 'Scout Alex' },
    ] as never);
    mockClient.mutate
      .mockResolvedValueOnce({ error: new Error('graphql failure') })
      .mockResolvedValueOnce({ data: { deleteMyAccount: true } });

    const { result } = setup();
    await act(async () => {
      await result.current.startDeletion();
    });

    expect(result.current.step).toBe('error');
    expect(result.current.profiles[0].status).toBe('failed');
    expect(result.current.profiles[0].error).toBe('graphql failure');
  });

  test('treats a rejected plain string as a non-not-found failure', async () => {
    vi.mocked(fetchAllMyProfiles).mockResolvedValue([
      { profileId: 'PROFILE#a', sellerName: 'Scout Alex' },
    ] as never);
    mockClient.mutate.mockRejectedValue('plain failure');

    const { result } = setup();
    await act(async () => {
      await result.current.startDeletion();
    });

    expect(result.current.step).toBe('error');
    expect(result.current.profiles[0].status).toBe('failed');
    expect(result.current.profiles[0].error).toBe('Failed to delete profile');
  });

  test('treats an object rejection without a message as a non-not-found failure', async () => {
    vi.mocked(fetchAllMyProfiles).mockResolvedValue([
      { profileId: 'PROFILE#a', sellerName: 'Scout Alex' },
    ] as never);
    mockClient.mutate.mockRejectedValue({ code: 'SomeException' });

    const { result } = setup();
    await act(async () => {
      await result.current.startDeletion();
    });

    expect(result.current.step).toBe('error');
    expect(result.current.profiles[0].status).toBe('failed');
    expect(result.current.profiles[0].error).toBe('Failed to delete profile');
  });
});

describe('useAccountDeletion — account finalization and discovery branches', () => {
  test('uses the generic message when account deletion rejects with a non-Error', async () => {
    vi.mocked(fetchAllMyProfiles).mockResolvedValue([
      { profileId: 'PROFILE#a', sellerName: 'Scout Alex' },
    ] as never);
    mockClient.mutate
      .mockResolvedValueOnce({ data: { deleteSellerProfile: true } })
      .mockRejectedValueOnce('account boom');

    const { result } = setup();
    await act(async () => {
      await result.current.startDeletion();
    });

    expect(result.current.step).toBe('error');
    expect(result.current.error).toBe('Failed to delete account');
  });

  test('startDeletion surfaces a generic message when discovery rejects with a non-Error', async () => {
    vi.mocked(fetchAllMyProfiles).mockRejectedValue('discover boom');

    const { result } = setup();
    await act(async () => {
      await result.current.startDeletion();
    });

    expect(result.current.step).toBe('error');
    expect(result.current.error).toBe('Failed to load user profiles');
  });
});
