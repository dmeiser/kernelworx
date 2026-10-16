/**
 * Tests for useCampaignPublicOrderSettings.
 *
 * The hook owns the campaign-keyed public-order settings state machine:
 * initial mapping from the settings query, draft editing, and the four
 * mutations (save / rotate / disable / enable), each with its own input
 * shape. These tests drive it through a mocked Apollo client.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import type { ReactNode } from 'react';
import {
  GET_CAMPAIGN,
  GET_MY_PAYMENT_METHODS,
  GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
  UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
} from '../../src/lib/graphql';
import {
  useCampaignPublicOrderSettings,
  PUBLIC_ORDER_ACK_VERSION,
} from '../../src/hooks/useCampaignPublicOrderSettings';

const CAMPAIGN_ID_RAW = 'campaign-456';
const CAMPAIGN_ID = `CAMPAIGN#${CAMPAIGN_ID_RAW}`;

const makeSettings = (overrides: Record<string, unknown> = {}) => ({
  __typename: 'CampaignPublicOrderSettings',
  enabled: true,
  shareToken: 'tok-1',
  allowedPaymentMethods: ['Cash'],
  acknowledgedAt: '2025-01-01T00:00:00.000Z',
  ackVersion: PUBLIC_ORDER_ACK_VERSION,
  publicOrderCount: 3,
  campaignId: CAMPAIGN_ID,
  campaignName: 'Spring Sale',
  campaignState: 'IL',
  ...overrides,
});

const settingsMock = (settings = makeSettings()): MockedResponse => ({
  request: {
    query: GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
    variables: { campaignId: CAMPAIGN_ID },
  },
  result: {
    data: { getCampaignPublicOrderSettings: settings },
  },
});

const campaignMock: MockedResponse = {
  request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_ID } },
  result: { data: { getCampaign: null } },
};

const paymentMethodsMock = (
  methods: { __typename: string; name: string; qrCodeUrl: string | null }[] = [],
): MockedResponse => ({
  request: { query: GET_MY_PAYMENT_METHODS },
  result: { data: { myPaymentMethods: methods } },
});

const makeWrapper = (mocks: MockedResponse[]) => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MockedProvider mocks={mocks}>{children}</MockedProvider>
  );
  return wrapper;
};

describe('useCampaignPublicOrderSettings', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('initializes from the settings query and builds the payment method list', async () => {
    const mocks = [
      campaignMock,
      settingsMock(),
      paymentMethodsMock([
        { __typename: 'PaymentMethod', name: 'Zelle', qrCodeUrl: null },
        { __typename: 'PaymentMethod', name: 'Cash', qrCodeUrl: null },
      ]),
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    expect(result.current.updating).toBe(false);
    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    expect(result.current.settings).toEqual({
      enabled: true,
      token: 'tok-1',
      allowedPaymentMethods: ['Cash'],
      acknowledgedAt: '2025-01-01T00:00:00.000Z',
      ackVersion: PUBLIC_ORDER_ACK_VERSION,
      publicOrderCount: 3,
      campaignId: CAMPAIGN_ID,
      campaignName: 'Spring Sale',
      campaignState: 'IL',
    });
    // 'Cash' appears once even though it is also in the seller's methods.
    expect(result.current.availablePaymentMethods).toEqual(['Zelle', 'Cash', 'Check']);
    expect(result.current.saved).toBe(true);
    expect(result.current.dirty).toBe(false);
    expect(result.current.acknowledgementsAccepted).toBe(true);
    expect(result.current.paymentAckAccepted).toBe(true);
    expect(result.current.disclosureAckAccepted).toBe(true);
    expect(result.current.draft).toEqual(result.current.settings);
  });

  it('maps null/empty settings fields onto their view defaults', async () => {
    const mocks = [
      campaignMock,
      settingsMock(
        makeSettings({
          enabled: false,
          shareToken: null,
          allowedPaymentMethods: null,
          acknowledgedAt: '',
          ackVersion: null,
          publicOrderCount: null,
          campaignId: null,
          campaignName: null,
          campaignState: null,
        }),
      ),
      paymentMethodsMock(),
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    expect(result.current.settings).toEqual({
      enabled: false,
      token: null,
      allowedPaymentMethods: [],
      acknowledgedAt: '',
      ackVersion: null,
      publicOrderCount: 0,
      campaignId: '',
      campaignName: '',
      campaignState: '',
    });
    expect(result.current.availablePaymentMethods).toEqual(['Cash', 'Check']);
    expect(result.current.acknowledgementsAccepted).toBe(false);
    expect(result.current.paymentAckAccepted).toBe(false);
    expect(result.current.disclosureAckAccepted).toBe(false);
  });

  it('marks the draft dirty when a field changes', async () => {
    const mocks = [campaignMock, settingsMock(), paymentMethodsMock()];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });
    expect(result.current.dirty).toBe(false);

    act(() => {
      result.current.setField('allowedPaymentMethods', ['Cash', 'Check']);
    });
    expect(result.current.dirty).toBe(true);
    expect(result.current.draft.allowedPaymentMethods).toEqual(['Cash', 'Check']);
  });

  it('save sends the draft and applies the mutation response', async () => {
    const updated = makeSettings({
      shareToken: 'tok-1',
      allowedPaymentMethods: ['Cash', 'Check'],
      acknowledgedAt: null,
      ackVersion: null,
    });
    const mocks = [
      campaignMock,
      settingsMock(),
      paymentMethodsMock(),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: true,
              allowedPaymentMethods: ['Cash', 'Check'],
              acknowledgementsAccepted: true,
            },
          },
        },
        result: { data: { updateCampaignPublicOrderSettings: updated } },
      },
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    act(() => {
      result.current.setField('allowedPaymentMethods', ['Cash', 'Check']);
    });

    await act(async () => {
      await result.current.save();
    });

    await waitFor(() => {
      expect(result.current.updating).toBe(false);
    });
    expect(result.current.settings?.allowedPaymentMethods).toEqual(['Cash', 'Check']);
    // The response carried no acknowledgement, so the ack state follows it.
    expect(result.current.acknowledgementsAccepted).toBe(false);
    expect(result.current.saved).toBe(true);
    expect(result.current.dirty).toBe(false);
  });

  it('rotateToken requests a new share token', async () => {
    const rotated = makeSettings({ shareToken: 'tok-2' });
    const mocks = [
      campaignMock,
      settingsMock(),
      paymentMethodsMock(),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: true,
              allowedPaymentMethods: ['Cash'],
              acknowledgementsAccepted: true,
              rotateToken: true,
            },
          },
        },
        result: { data: { updateCampaignPublicOrderSettings: rotated } },
      },
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    await act(async () => {
      await result.current.rotateToken();
    });

    await waitFor(() => {
      expect(result.current.settings?.token).toBe('tok-2');
    });
    expect(result.current.updating).toBe(false);
  });

  it('disable sends enabled=false without the acknowledgement flag', async () => {
    const disabled = makeSettings({ enabled: false, shareToken: null });
    const mocks = [
      campaignMock,
      settingsMock(),
      paymentMethodsMock(),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: false,
              allowedPaymentMethods: ['Cash'],
            },
          },
        },
        result: { data: { updateCampaignPublicOrderSettings: disabled } },
      },
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    await act(async () => {
      await result.current.disable();
    });

    await waitFor(() => {
      expect(result.current.settings?.enabled).toBe(false);
    });
  });

  it('enable sends enabled=true with the acknowledgement flag', async () => {
    const enabledAgain = makeSettings({ enabled: true });
    const mocks = [
      campaignMock,
      settingsMock(
        makeSettings({ enabled: false, shareToken: null, acknowledgedAt: null, ackVersion: null }),
      ),
      paymentMethodsMock(),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: true,
              allowedPaymentMethods: ['Cash'],
              acknowledgementsAccepted: false,
            },
          },
        },
        result: { data: { updateCampaignPublicOrderSettings: enabledAgain } },
      },
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    await act(async () => {
      await result.current.enable();
    });

    await waitFor(() => {
      expect(result.current.settings?.enabled).toBe(true);
    });
  });

  it('derives acknowledgementsAccepted from both checkbox states', async () => {
    const mocks = [
      campaignMock,
      settingsMock(
        makeSettings({ enabled: false, shareToken: null, acknowledgedAt: null, ackVersion: null }),
      ),
      paymentMethodsMock(),
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });
    expect(result.current.acknowledgementsAccepted).toBe(false);

    act(() => {
      result.current.setPaymentAckAccepted(true);
    });
    expect(result.current.paymentAckAccepted).toBe(true);
    expect(result.current.acknowledgementsAccepted).toBe(false);

    act(() => {
      result.current.setDisclosureAckAccepted(true);
    });
    expect(result.current.acknowledgementsAccepted).toBe(true);

    act(() => {
      result.current.setPaymentAckAccepted(false);
    });
    expect(result.current.acknowledgementsAccepted).toBe(false);
  });

  it('enable sends acknowledgementsAccepted=true when both acks are checked', async () => {
    const enabledFresh = makeSettings({
      enabled: true,
      shareToken: 'tok-new',
      acknowledgedAt: '2025-06-01T00:00:00.000Z',
    });
    const mocks = [
      campaignMock,
      settingsMock(
        makeSettings({ enabled: false, shareToken: null, acknowledgedAt: null, ackVersion: null }),
      ),
      paymentMethodsMock(),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: true,
              allowedPaymentMethods: ['Cash'],
              acknowledgementsAccepted: true,
            },
          },
        },
        result: { data: { updateCampaignPublicOrderSettings: enabledFresh } },
      },
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    act(() => {
      result.current.setPaymentAckAccepted(true);
      result.current.setDisclosureAckAccepted(true);
    });

    await act(async () => {
      await result.current.enable();
    });

    await waitFor(() => {
      expect(result.current.settings?.enabled).toBe(true);
    });
    // The response carried an acknowledgement, so both checkbox states follow it.
    expect(result.current.acknowledgementsAccepted).toBe(true);
    expect(result.current.settings?.token).toBe('tok-new');
  });

  it('swallows mutation errors and settles the updating flag', async () => {
    const mocks = [
      campaignMock,
      settingsMock(),
      paymentMethodsMock(),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: true,
              allowedPaymentMethods: ['Cash'],
              acknowledgementsAccepted: true,
            },
          },
        },
        error: new Error('boom'),
      },
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    await act(async () => {
      await result.current.save();
    });

    expect(result.current.updating).toBe(false);
    expect(console.error).toHaveBeenCalled();
    // The stored view survives the failed mutation.
    expect(result.current.settings?.token).toBe('tok-1');
  });

  it('leaves state untouched when the mutation returns no blob', async () => {
    const mocks = [
      campaignMock,
      settingsMock(),
      paymentMethodsMock(),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: true,
              allowedPaymentMethods: ['Cash'],
              acknowledgementsAccepted: true,
            },
          },
        },
        result: { data: { updateCampaignPublicOrderSettings: null } },
      },
    ];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: CAMPAIGN_ID_RAW }),
      { wrapper: makeWrapper(mocks) },
    );

    await waitFor(() => {
      expect(result.current.settings).not.toBeNull();
    });

    await act(async () => {
      await result.current.save();
    });

    expect(result.current.updating).toBe(false);
    expect(result.current.settings?.token).toBe('tok-1');
  });

  it('no-ops the actions when campaignId is null', async () => {
    const mocks = [campaignMock, settingsMock(), paymentMethodsMock()];
    const { result } = renderHook(
      () => useCampaignPublicOrderSettings({ campaignId: null }),
      { wrapper: makeWrapper(mocks) },
    );

    expect(result.current.settings).toBeNull();
    await act(async () => {
      await result.current.save();
      await result.current.rotateToken();
      await result.current.disable();
      await result.current.enable();
    });
    expect(result.current.updating).toBe(false);
  });
});
