import { describe, it, expect } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedProviderProps } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { GraphQLError } from 'graphql';
import { usePublicOrderSettings } from '../../src/hooks/usePublicOrderSettings';
import {
  GET_MY_PAYMENT_METHODS,
  GET_PROFILE,
  GET_PROFILE_PUBLIC_ORDER_SETTINGS,
  LIST_CAMPAIGNS_BY_PROFILE,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
} from '../../src/lib/graphql';

const PROFILE_ID = 'p-1';
const DB_PROFILE_ID = 'PROFILE#p-1';

const defaultSettings = {
  __typename: 'PublicOrderSettings',
  enabled: true,
  campaignId: 'CAMPAIGN#c-1',
  campaignName: 'Fall Sale',
  campaignState: 'OK',
  allowedPaymentMethods: ['Venmo'],
  shareToken: 'tok-1',
  publicOrderCount: 5,
  acknowledgedAt: '2026-01-01T00:00:00Z',
  ackVersion: 1,
};

const mocks: MockedResponse[] = [
  {
    request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
    result: { data: { getProfile: { sellerName: 'Scout Troop' } } },
  },
  {
    request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
    result: { data: { getProfilePublicOrderSettings: defaultSettings } },
  },
  {
    request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: DB_PROFILE_ID, limit: 100 } },
    result: { data: { listCampaignsByProfile: { campaigns: [] } } },
  },
  {
    request: { query: GET_MY_PAYMENT_METHODS },
    result: { data: { getMyAccount: { preferences: { paymentMethods: [] } } } },
  },
];

describe('usePublicOrderSettings unit tests for internal branches', () => {
  it('drops actions issued when an action is already in flight', async () => {
    let resolveMutation: (val: any) => void;
    const mutationPromise = new Promise((resolve) => {
      resolveMutation = resolve;
    });

    const slowMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: () => mutationPromise as any,
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={[...mocks, slowMutation]}>
        {children}
      </MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });

    // The reads must land before the action: the seed effect that arms the
    // form also resets the action message, so a fixed sleep races it.
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    // First action starts and remains in flight
    act(() => {
      void result.current.disable();
    });

    expect(result.current.submitting).toBe(true);

    // Second action issued while in flight must be dropped immediately (line 390)
    act(() => {
      void result.current.rotateToken();
    });

    // Resolve first mutation
    await act(async () => {
      resolveMutation({
        data: {
          updateProfilePublicOrderSettings: {
            ...defaultSettings,
            enabled: false,
          },
        },
      });
    });

    await waitFor(() => expect(result.current.submitting).toBe(false));
  });

  it('handles empty update response data returning error message', async () => {
    const emptyResponseMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: { data: { updateProfilePublicOrderSettings: null } },
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={[...mocks, emptyResponseMutation]}>
        {children}
      </MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });

    // The reads must land before the action: the seed effect that arms the
    // form also resets the action message, so a fixed sleep races it.
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    await act(async () => {
      await result.current.disable();
    });

    expect(result.current.actionMessage.kind).toBe('failed');
    if (result.current.actionMessage.kind === 'failed') {
      expect(result.current.actionMessage.message).toContain('returned no data');
    }
  });

  it('handles graphQL error in update response without thrown exception', async () => {
    const errorResponseMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: {
        errors: [new GraphQLError('Profile not found')],
      },
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={[...mocks, errorResponseMutation]}>
        {children}
      </MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });

    // The reads must land before the action: the seed effect that arms the
    // form also resets the action message, so a fixed sleep races it.
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    await act(async () => {
      await result.current.disable();
    });

    expect(result.current.actionMessage.kind).toBe('failed');
    if (result.current.actionMessage.kind === 'failed') {
      expect(result.current.actionMessage.message).toBe('Profile not found');
    }
  });

  it('handles null profile settings gracefully', async () => {
    const nullSettingsMocks: MockedResponse[] = [
      {
        request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
        result: { data: { getProfile: { sellerName: 'Scout Troop' } } },
      },
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        result: { data: { getProfilePublicOrderSettings: null } },
      },
      {
        request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: DB_PROFILE_ID, limit: 100 } },
        result: { data: { listCampaignsByProfile: { campaigns: [] } } },
      },
      {
        request: { query: GET_MY_PAYMENT_METHODS },
        result: { data: { getMyAccount: { preferences: { paymentMethods: [] } } } },
      },
    ];

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={nullSettingsMocks}>
        {children}
      </MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });

    // The reads must land before the action: the seed effect that arms the
    // form also resets the action message, so a fixed sleep races it.
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    expect(result.current.stored.enabled).toBe(false);
    expect(result.current.stored.campaignId).toBe(null);
  });

  it('sets held snapshot when post-save refetch rejects', async () => {
    const successMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: {
        data: {
          updateProfilePublicOrderSettings: {
            ...defaultSettings,
            enabled: false,
          },
        },
      },
    };

    let refetchCount = 0;
    const settingsMockWithFailingRefetch: MockedResponse = {
      request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
      result: () => {
        refetchCount++;
        if (refetchCount > 1) {
          throw new Error('Refetch network error');
        }
        return { data: { getProfilePublicOrderSettings: defaultSettings } };
      },
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider
        mocks={[
          mocks[0],
          settingsMockWithFailingRefetch,
          mocks[2],
          mocks[3],
          successMutation,
        ]}
      >
        {children}
      </MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });

    // The reads must land before the action: the seed effect that arms the
    // form also resets the action message, so a fixed sleep races it.
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    await act(async () => {
      await result.current.disable();
    });

    expect(result.current.actionMessage.kind).toBe('saved');
    if (result.current.actionMessage.kind === 'saved') {
      expect(result.current.actionMessage.refreshFailed).toBe(true);
    }
  });

  it('drops action outcome and refresh if profileId unmounts/switches while action in flight', async () => {
    let resolveMutation: (val: any) => void;
    const mutationPromise = new Promise((resolve) => {
      resolveMutation = resolve;
    });

    const slowMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: () => mutationPromise as any,
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={[...mocks, slowMutation]}>
        {children}
      </MockedProvider>
    );

    const { result, unmount } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });

    // The reads must land before the action: the seed effect that arms the
    // form also resets the action message, so a fixed sleep races it.
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    act(() => {
      void result.current.disable();
    });

    // Unmount before mutation resolves
    unmount();

    await act(async () => {
      resolveMutation({
        data: {
          updateProfilePublicOrderSettings: {
            ...defaultSettings,
            enabled: false,
          },
        },
      });
      await new Promise((r) => setTimeout(r, 50));
    });
  });
});

describe('the settings judge and draft owner cover the remaining arrival shapes', () => {
  it('treats GraphQL errors riding a resolved mutation response as failure', async () => {
    // The single outcome judge must fail a response that carries GraphQL errors
    // without throwing, whatever errorPolicy the client is configured with.
    const errorRidingResponse: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: { errors: [new GraphQLError('Profile not found')] },
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider
        mocks={[...mocks, errorRidingResponse]}
        // Apollo Client 4 only types defaultOptions.mutate.errorPolicy when the
        // app declares it, so the override carries the same double cast the
        // production client uses (src/lib/apollo.ts).
        defaultOptions={{ mutate: { errorPolicy: 'all' } } as unknown as MockedProviderProps['defaultOptions']}
      >
        {children}
      </MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    await act(async () => {
      await result.current.disable();
    });

    expect(result.current.actionMessage.kind).toBe('failed');
    if (result.current.actionMessage.kind === 'failed') {
      expect(result.current.actionMessage.message).toBe('Profile not found');
    }
  });

  it('still records a write that lands before the settings read has ever resolved', async () => {
    // No settings mock at all: the read never lands, so the snapshot the write
    // takes is the absent read, and the failed follow-up refresh degrades to
    // the retryable notice without invalidating the write's own success.
    const successMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: {
        data: {
          updateProfilePublicOrderSettings: {
            ...defaultSettings,
            enabled: false,
          },
        },
      },
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={[mocks[0], mocks[2], mocks[3], successMutation]}>{children}</MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });

    await act(async () => {
      await result.current.disable();
    });

    // The write itself is a success (the notice, not a failure, is what the
    // failed refresh degrades to); the draft may read as diverged only because
    // there is no stored view to match against when the read never lands.
    expect(['saved', 'unsaved']).toContain(result.current.actionMessage.kind);
    if (result.current.actionMessage.kind === 'saved' || result.current.actionMessage.kind === 'unsaved') {
      expect(result.current.actionMessage.refreshFailed).toBe(true);
    }
  });

  it('reconciles the draft to a returned blob that nulls the anchor and the methods', async () => {
    // A save that transmits campaignId and methods follows the server's blob:
    // a null anchor and a null method list land as an empty campaign and an
    // empty method list rather than keeping the previous draft values.
    const disabledSettings = {
      __typename: 'PublicOrderSettings',
      enabled: false,
      campaignId: null,
      campaignName: null,
      campaignState: null,
      allowedPaymentMethods: [],
      shareToken: null,
      publicOrderCount: null,
      acknowledgedAt: null,
      ackVersion: null,
    };
    const enableMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR,
        variables: {
          profileId: DB_PROFILE_ID,
          enabled: true,
          campaignId: 'CAMPAIGN#c-1',
          allowedPaymentMethods: ['Venmo'],
          acknowledgementsAccepted: true,
        },
      },
      result: {
        data: {
          updateProfilePublicOrderSettings: {
            ...defaultSettings,
            campaignId: null,
            allowedPaymentMethods: null,
          },
        },
      },
    };
    const settingsMock: MockedResponse = {
      request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
      maxUsageCount: 10,
      result: { data: { getProfilePublicOrderSettings: disabledSettings } },
    };

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={[mocks[0], settingsMock, mocks[2], mocks[3], enableMutation]}>{children}</MockedProvider>
    );

    const { result } = renderHook(() => usePublicOrderSettings(PROFILE_ID), { wrapper });
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    act(() => {
      result.current.setEnabled(true);
      result.current.setCampaignId('CAMPAIGN#c-1');
      result.current.toggleMethod('Venmo', true);
      result.current.setAck('ackPayment', true);
      result.current.setAck('ackDisclosure', true);
    });
    await act(async () => {
      await result.current.save();
    });

    expect(result.current.actionMessage.kind).toBe('saved');
    expect(result.current.draft.campaignId).toBe('');
    expect(result.current.draft.methods).toEqual([]);
  });
});
