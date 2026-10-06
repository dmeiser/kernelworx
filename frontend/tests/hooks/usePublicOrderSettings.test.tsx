import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { GraphQLError } from 'graphql';
import { usePublicOrderSettings } from '../../src/hooks/usePublicOrderSettings';
import {
  GET_MY_PAYMENT_METHODS,
  GET_PROFILE,
  GET_PROFILE_PUBLIC_ORDER_SETTINGS,
  LIST_CAMPAIGNS_BY_PROFILE,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
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
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
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

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

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
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.submitting).toBe(false);
  });

  it('handles empty update response data returning error message', async () => {
    const emptyResponseMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
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

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

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
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
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

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

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

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(result.current.stored.enabled).toBe(false);
    expect(result.current.stored.campaignId).toBe(null);
  });

  it('sets held snapshot when post-save refetch rejects', async () => {
    const successMutation: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
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

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

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
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
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

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

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
