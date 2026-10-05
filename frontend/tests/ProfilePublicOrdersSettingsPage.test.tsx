/**
 * Tests for the per-profile public order settings page.
 *
 * The gate that matters most is the acknowledgement pair: Save must stay
 * disabled with only one box checked, because the server stamps the acceptance
 * as liability evidence and rejects an enable that has not accepted both. The
 * rest of the surface is the seller's control over the capability: rotate,
 * disable, re-pick campaign, change methods, and a share view that re-renders
 * from the returned token at any time while enabled.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { ProfilePublicOrdersSettingsPage } from '../src/pages/ProfilePublicOrdersSettingsPage';
import {
  GET_MY_PAYMENT_METHODS,
  GET_PROFILE,
  GET_PROFILE_PUBLIC_ORDER_SETTINGS,
  LIST_CAMPAIGNS_BY_PROFILE,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
} from '../src/lib/graphql';
import { PUBLIC_ORDER_CAP } from '../src/constants/publicOrders';

vi.mock('../src/components/public/ShareQrPanel', () => ({
  ShareQrPanel: ({ shareUrl }: { shareUrl: string }) => <div data-testid="share-panel">{shareUrl}</div>,
}));

const DB_PROFILE_ID = 'PROFILE#p-1';

const settingsFor = (overrides: Record<string, unknown> = {}) => ({
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
  ...overrides,
});

const campaign = {
  __typename: 'Campaign',
  campaignId: 'CAMPAIGN#c-1',
  profileId: DB_PROFILE_ID,
  campaignName: 'Fall popcorn',
  campaignYear: 2026,
  startDate: '2026-09-01',
  endDate: '2026-12-01',
  catalogId: 'CATALOG#cat-1',
  unitType: 'Scouts BSA Troop',
  unitNumber: '42',
  city: 'Anytown',
  state: 'TX',
  sharedCampaignCode: null,
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  totalOrders: 3,
  totalRevenue: 40,
};

const baseMocks = (settings: Record<string, unknown>): MockedResponse[] => [
  {
    request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
    // Every save refetches the whole read set, so all four reads must repeat.
    maxUsageCount: 10,
    result: {
      data: {
        getProfile: {
          __typename: 'SellerProfile',
          profileId: DB_PROFILE_ID,
          ownerAccountId: 'ACCOUNT#a-1',
          sellerName: 'Troop 42',
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:00:00Z',
          isOwner: true,
          permissions: [],
        },
      },
    },
  },
  {
    request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
    result: { data: { getProfilePublicOrderSettings: settings } },
    // The page refetches after every save, so this mock must survive repeats.
    maxUsageCount: 10,
  },
  {
    request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: DB_PROFILE_ID, limit: 100 } },
    maxUsageCount: 10,
    result: { data: { listCampaignsByProfile: { __typename: 'CampaignConnection', campaigns: [campaign], nextToken: null } } },
  },
  {
    request: { query: GET_MY_PAYMENT_METHODS },
    maxUsageCount: 10,
    result: {
      data: { myPaymentMethods: [{ __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'qr-key' }] },
    },
  },
];

// A save refetches the settings, so tests that mutate need the refetch to
// return the NEW state rather than the original. The holder makes the mock
// read like a server: the mutation writes it, the query reads it.
type SettingsHolder = { current: Record<string, unknown> };

function liveSettingsMock(holder: SettingsHolder): MockedResponse {
  return {
    request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
    maxUsageCount: 10,
    result: () => ({ data: { getProfilePublicOrderSettings: holder.current } }),
  };
}

function baseMocksWith(holder: SettingsHolder): MockedResponse[] {
  return [
    { ...baseMocks({})[0], maxUsageCount: 10 },
    liveSettingsMock(holder),
    { ...baseMocks({})[2], maxUsageCount: 10 },
    { ...baseMocks({})[3], maxUsageCount: 10 },
  ];
}

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MemoryRouter initialEntries={['/scouts/p-1/public-orders']}>
      <MockedProvider mocks={mocks}>
        <Routes>
          <Route path="/scouts/:profileId/public-orders" element={<ProfilePublicOrdersSettingsPage />} />
        </Routes>
      </MockedProvider>
    </MemoryRouter>,
  );
}

async function openPage(mocks: MockedResponse[]) {
  renderPage(mocks);
  return screen.findByText('Accept public orders');
}

async function pickCampaign(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByText('Fall popcorn (2026)'));
}

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
});

describe('ProfilePublicOrdersSettingsPage', () => {
  it('renders the settings surface for the profile', async () => {
    await openPage(baseMocks(settingsFor()));
    expect(await screen.findByText(/Share link for Troop 42|Let buyers order from a shared link/)).toBeInTheDocument();
    expect(screen.getByText('Accept public orders')).toBeInTheDocument();
    expect(await screen.findByTestId('cap-notice')).toHaveTextContent(`0 of ${PUBLIC_ORDER_CAP}`);
  });

  it('shows the staleness flag when the anchor campaign is gone', async () => {
    await openPage(baseMocks(settingsFor({ enabled: true, campaignState: 'MISSING', shareToken: 'tok' })));
    expect(await screen.findByTestId('campaign-missing')).toBeInTheDocument();
  });

  it('shows the staleness flag when the anchor campaign is deactivated', async () => {
    await openPage(baseMocks(settingsFor({ enabled: true, campaignState: 'INACTIVE', shareToken: 'tok' })));
    expect(await screen.findByTestId('campaign-inactive')).toBeInTheDocument();
  });

  it('surfaces a settings load failure', async () => {
    renderPage([
      ...baseMocks(settingsFor()).slice(0, 1),
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        error: new Error('boom'),
      },
      baseMocks(settingsFor())[2],
      baseMocks(settingsFor())[3],
    ]);
    expect(await screen.findByText(/Failed to load public order settings/)).toBeInTheDocument();
  });

  it('requires both acknowledgements before Save is enabled', async () => {
    const user = userEvent.setup();
    await openPage(baseMocks(settingsFor()));

    await user.click(await screen.findByRole('switch'));
    await pickCampaign(user);
    await user.click(await screen.findByRole('checkbox', { name: 'Venmo' }));

    const ackBlock = await screen.findByTestId('ack-block');
    const [ackPayment, ackDisclosure] = within(ackBlock).getAllByRole('checkbox');
    expect(screen.getByTestId('save-settings')).toBeDisabled();

    await user.click(ackPayment);
    expect(screen.getByTestId('save-settings')).toBeDisabled();

    await user.click(ackDisclosure);
    await waitFor(() => expect(screen.getByTestId('save-settings')).toBeEnabled());
  });

  it('saves an enable with the campaign, methods and acknowledgement', async () => {
    const user = userEvent.setup();
    const mutationMock: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
        variables: {
          profileId: DB_PROFILE_ID,
          enabled: true,
          campaignId: 'CAMPAIGN#c-1',
          allowedPaymentMethods: ['Venmo'],
          acknowledgementsAccepted: true,
        },
      },
      result: { data: { updateProfilePublicOrderSettings: settingsFor({ enabled: true, campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'], shareToken: 'tok', ackVersion: 1, campaignState: 'OK' }) } },
    };
    renderPage([...baseMocks(settingsFor()), mutationMock]);
    await screen.findByText('Public Orders');

    await user.click(await screen.findByRole('switch'));
    await pickCampaign(user);
    await user.click(await screen.findByRole('checkbox', { name: 'Venmo' }));
    const ackBlock = await screen.findByTestId('ack-block');
    const [ackPayment, ackDisclosure] = within(ackBlock).getAllByRole('checkbox');
    await user.click(ackPayment);
    await user.click(ackDisclosure);
    await user.click(screen.getByTestId('save-settings'));

    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
  });

  it('re-prompts the acknowledgements when the stored version is behind', async () => {
    await openPage(baseMocks(settingsFor({ enabled: true, ackVersion: 0, shareToken: 'tok', campaignId: 'CAMPAIGN#c-1' })));
    expect(await screen.findByTestId('ack-block')).toBeInTheDocument();
    expect(screen.getByTestId('save-settings')).toBeDisabled();
  });

  it('does not re-prompt when the stored acknowledgement is current', async () => {
    await openPage(baseMocks(settingsFor({ enabled: true, ackVersion: 1, shareToken: 'tok', campaignId: 'CAMPAIGN#c-1' })));
    await screen.findByTestId('cap-notice');
    expect(screen.queryByTestId('ack-block')).not.toBeInTheDocument();
    expect(screen.getByTestId('save-settings')).toBeEnabled();
  });

  it('shows the share view with the URL built from the returned token', async () => {
    await openPage(baseMocks(settingsFor({ enabled: true, shareToken: 'share-token', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' })));
    expect(await screen.findByTestId('share-panel')).toHaveTextContent(`${window.location.origin}/o/p-1/share-token`);
  });

  it('hides the share view once disabled', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'share-token', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const mutationMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: false } },
      result: () => {
        holder.current = { ...holder.current, enabled: false };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    renderPage([...baseMocksWith(holder), mutationMock]);
    await screen.findByTestId('share-panel');

    await user.click(await screen.findByTestId('disable-public-orders'));
    await waitFor(() => expect(screen.queryByTestId('share-panel')).not.toBeInTheDocument());
  });

  it('rotates the token, minting a new share URL', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'old-token', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const mutationMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true } },
      result: () => {
        holder.current = { ...holder.current, shareToken: 'rotated-token' };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    renderPage([...baseMocksWith(holder), mutationMock]);
    await screen.findByTestId('share-panel');

    await user.click(await screen.findByTestId('rotate-token'));
    await waitFor(() => expect(screen.getByTestId('share-panel')).toHaveTextContent('rotated-token'));
  });

  it('surfaces a rejected save with the mapped error message', async () => {
    const user = userEvent.setup();
    const mutationMock: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
        variables: {
          profileId: DB_PROFILE_ID,
          enabled: true,
          campaignId: 'CAMPAIGN#c-1',
          allowedPaymentMethods: ['Venmo'],
          acknowledgementsAccepted: true,
        },
      },
      error: new Error('Invalid input provided.'),
    };
    renderPage([...baseMocks(settingsFor()), mutationMock]);
    await screen.findByText('Public Orders');

    await user.click(await screen.findByRole('switch'));
    await pickCampaign(user);
    await user.click(await screen.findByRole('checkbox', { name: 'Venmo' }));
    const ackBlock = await screen.findByTestId('ack-block');
    const [ackPayment, ackDisclosure] = within(ackBlock).getAllByRole('checkbox');
    await user.click(ackPayment);
    await user.click(ackDisclosure);
    await user.click(screen.getByTestId('save-settings'));

    expect(await screen.findByText('Invalid input provided.')).toBeInTheDocument();
  });

  it('shows no share view when the token is missing despite being enabled', async () => {
    await openPage(baseMocks(settingsFor({ enabled: true, ackVersion: 1, campaignId: 'CAMPAIGN#c-1', shareToken: null })));
    await screen.findByTestId('cap-notice');
    expect(screen.queryByTestId('share-panel')).not.toBeInTheDocument();
  });

  it('drops a stored method when the seller unchecks it', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({
        enabled: true,
        ackVersion: 1,
        campaignId: 'CAMPAIGN#c-1',
        shareToken: 'tok',
        allowedPaymentMethods: ['Venmo'],
      }),
    };
    const mutationMock: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
        variables: {
          profileId: DB_PROFILE_ID,
          enabled: true,
          campaignId: 'CAMPAIGN#c-1',
          allowedPaymentMethods: [],
          // Acks are not re-required here, so the hook omits the flag entirely.
          acknowledgementsAccepted: undefined,
        },
      },
      result: () => ({ data: { updateProfilePublicOrderSettings: holder.current } }),
    };
    renderPage([...baseMocksWith(holder), mutationMock]);

    await user.click(await screen.findByRole('checkbox', { name: 'Venmo' }));
    await user.click(await screen.findByTestId('save-settings'));
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
  });

  it('sends no campaign when the seller saves without picking one', async () => {
    const user = userEvent.setup();
    const mutationMock: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
        variables: {
          profileId: DB_PROFILE_ID,
          enabled: true,
          campaignId: undefined,
          allowedPaymentMethods: [],
          acknowledgementsAccepted: true,
        },
      },
      result: () => ({ data: { updateProfilePublicOrderSettings: settingsFor() } }),
    };
    renderPage([...baseMocks(settingsFor()), mutationMock]);
    await screen.findByText('Accept public orders');

    await user.click(screen.getByRole('switch'));
    const ackBlock = await screen.findByTestId('ack-block');
    const [ackPayment, ackDisclosure] = within(ackBlock).getAllByRole('checkbox');
    await user.click(ackPayment);
    await user.click(ackDisclosure);
    await user.click(screen.getByTestId('save-settings'));

    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
  });

  it('renders the loading state rather than crashing when the route has no profile id', async () => {
    render(
      <MemoryRouter initialEntries={['/scouts/public-orders']}>
        <MockedProvider mocks={[]}>
          <Routes>
            <Route path="/scouts/public-orders" element={<ProfilePublicOrdersSettingsPage />} />
          </Routes>
        </MockedProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByText('Accept public orders')).not.toBeInTheDocument();
  });

  it('offers Cash and Check alongside the account methods', async () => {
    await openPage(baseMocks(settingsFor()));
    expect(await screen.findByRole('checkbox', { name: 'Venmo' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Cash' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Check' })).toBeInTheDocument();
  });
});
