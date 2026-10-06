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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { GraphQLError } from 'graphql';
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

const RouteSwitcher: React.FC<{ to: string; testId: string }> = ({ to, testId }) => {
  const navigate = useNavigate();
  const go = () => void navigate(to);
  return <button type="button" data-testid={testId} onClick={go} />;
};

type MockedProviderProps = Parameters<typeof MockedProvider>[0];

// The real client's watchQuery defaults (frontend/src/lib/apollo.ts): under
// errorPolicy 'all' a refetch that comes back with GraphQL errors RESOLVES and
// applies its partial payload, and a rejected read clears query data the way a
// real fault does. MockedProvider's own defaults hide both shapes, so the live
// post-action refresh-failure contract is only reproducible with these set.
const LIVE_QUERY_OPTIONS: MockedProviderProps['defaultOptions'] = {
  watchQuery: { fetchPolicy: 'cache-and-network', errorPolicy: 'all' },
};

function renderPage(mocks: MockedResponse[], defaultOptions?: MockedProviderProps['defaultOptions']) {
  return render(
    <MemoryRouter initialEntries={['/scouts/p-1/public-orders']}>
      <MockedProvider mocks={mocks} defaultOptions={defaultOptions}>
        <Routes>
          <Route
            path="/scouts/:profileId/public-orders"
            element={
              <div>
                <RouteSwitcher to="/scouts/p-2/public-orders" testId="switch-profile" />
                <ProfilePublicOrdersSettingsPage />
              </div>
            }
          />
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
    await openPage(
      baseMocks(settingsFor({ enabled: true, campaignId: 'CAMPAIGN#gone', campaignState: 'MISSING', shareToken: 'tok' })),
    );
    expect(await screen.findByTestId('campaign-missing')).toBeInTheDocument();
    const select = screen.getByTestId('campaign-select');
    expect(select).toHaveTextContent('Unavailable campaign');
    expect(select).not.toHaveTextContent('CAMPAIGN#gone');
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

  it('hides the share view once disabled, toggles the switch off, and keeps unsaved edits', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({
        enabled: true,
        shareToken: 'share-token',
        ackVersion: 1,
        campaignId: 'CAMPAIGN#c-1',
        allowedPaymentMethods: ['Venmo'],
      }),
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

    // An unsaved method edit made before the disable must survive it.
    await user.click(await screen.findByRole('checkbox', { name: 'Venmo' }));
    await user.click(await screen.findByTestId('disable-public-orders'));

    await waitFor(() => expect(screen.queryByTestId('share-panel')).not.toBeInTheDocument());
    expect(screen.getByRole('switch')).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Venmo' })).not.toBeChecked();
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

  it('keeps unsaved draft edits through a rotate and submits them on the next save', async () => {
    // Anchor enforcement only applies to enabling and re-picking, so rotate
    // and a method edit must both work while the stored anchor is stale
    // (campaignState MISSING).
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({
        enabled: true,
        ackVersion: 1,
        campaignId: 'CAMPAIGN#c-1',
        shareToken: 'tok',
        campaignState: 'MISSING',
        allowedPaymentMethods: ['Venmo', 'Cash'],
      }),
    };
    const rotateMock: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
        variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true },
      },
      result: () => {
        holder.current = { ...holder.current, shareToken: 'rotated-token' };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    const saveMock: MockedResponse = {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
        variables: {
          profileId: DB_PROFILE_ID,
          enabled: true,
          campaignId: undefined,
          allowedPaymentMethods: ['Venmo'],
          acknowledgementsAccepted: undefined,
        },
      },
      result: () => {
        holder.current = { ...holder.current, allowedPaymentMethods: ['Venmo'] };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    renderPage([...baseMocksWith(holder), rotateMock, saveMock]);

    await screen.findByTestId('campaign-missing');

    await user.click(await screen.findByTestId('rotate-token'));
    await waitFor(() => expect(screen.getByTestId('share-panel')).toHaveTextContent('rotated-token'));

    // The unsaved edit (unchecking Cash) must survive the rotate's refetch,
    // and the save must still show the staleness banner.
    await user.click(await screen.findByRole('checkbox', { name: 'Cash' }));
    await user.click(screen.getByTestId('save-settings'));
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(screen.getByTestId('campaign-missing')).toBeInTheDocument();
  });

  // The settled contract for an action that SUCCEEDED whose post-action
  // refresh failed, in AppSync's HTTP 200 + errors[] shape: the resolver fault
  // nulls the settings field, and under errorPolicy 'all' that payload lands on
  // the query. The server-confirmed blob must stay authoritative — saved
  // confirmation + retryable refresh-failed notice + share link intact — never
  // a spurious unsaved-changes downgrade with the share panel collapsed.
  it('keeps the confirmation and share link when the refresh resolves with a null field and GraphQL errors', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'old-token', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const rotateMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true } },
      result: () => {
        holder.current = { ...holder.current, shareToken: 'rotated-token' };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    const mocks: MockedResponse[] = [
      baseMocksWith(holder)[0],
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        maxUsageCount: 1,
        result: () => ({ data: { getProfilePublicOrderSettings: holder.current } }),
      },
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        maxUsageCount: 1,
        result: () => ({
          data: { getProfilePublicOrderSettings: null },
          errors: [new GraphQLError('resolver fault', { extensions: { code: 'INTERNAL_SERVER_ERROR' } })],
        }),
      },
      baseMocksWith(holder)[2],
      baseMocksWith(holder)[3],
      rotateMock,
    ];
    renderPage(mocks, LIVE_QUERY_OPTIONS);
    await screen.findByTestId('share-panel');

    await user.click(screen.getByTestId('rotate-token'));

    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(await screen.findByTestId('refresh-failed')).toBeInTheDocument();
    expect(screen.getByTestId('share-panel')).toHaveTextContent('rotated-token');
    expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  // Same contract when the post-action refresh is REJECTED (HTTP 500): the
  // failed read clears the query's data, which must not strand the page on an
  // endless loading spinner hiding both the confirmation and the notice.
  it('keeps the confirmation rendered when the refresh is rejected and clears the read', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'old-token', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const rotateMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true } },
      result: () => {
        holder.current = { ...holder.current, shareToken: 'rotated-token' };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    const mocks: MockedResponse[] = [
      baseMocksWith(holder)[0],
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        maxUsageCount: 1,
        result: () => ({ data: { getProfilePublicOrderSettings: holder.current } }),
      },
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        error: new Error('refetch fault'),
      },
      baseMocksWith(holder)[2],
      baseMocksWith(holder)[3],
      rotateMock,
    ];
    renderPage(mocks, LIVE_QUERY_OPTIONS);
    await screen.findByTestId('share-panel');

    await user.click(screen.getByTestId('rotate-token'));

    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(await screen.findByTestId('refresh-failed')).toBeInTheDocument();
    expect(screen.getByTestId('share-panel')).toHaveTextContent('rotated-token');
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByText('refetch fault')).not.toBeInTheDocument();
  });

  it('shows the failure and no stale success when a failed action follows a successful one', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'tok', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const rotateMock = (result: 'ok' | 'fail'): MockedResponse => ({
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
        variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true },
      },
      ...(result === 'ok'
        ? {
            result: () => {
              holder.current = { ...holder.current, shareToken: 'rotated-token' };
              return { data: { updateProfilePublicOrderSettings: holder.current } };
            },
          }
        : { error: new Error('Invalid input provided.') }),
    });
    renderPage([...baseMocksWith(holder), rotateMock('ok'), rotateMock('fail')]);
    await screen.findByTestId('share-panel');

    await user.click(await screen.findByTestId('rotate-token'));
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    // One action at a time: wait for the span's controls to come back.
    await waitFor(() => expect(screen.getByTestId('rotate-token')).toBeEnabled());

    await user.click(screen.getByTestId('rotate-token'));
    expect(await screen.findByText('Invalid input provided.')).toBeInTheDocument();
    expect(screen.queryByTestId('settings-saved')).not.toBeInTheDocument();
  });

  it('serializes actions: rotate cannot fire while a disable is outstanding', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'tok', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const disableMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: false } },
      delay: 300,
      result: () => {
        holder.current = { ...holder.current, enabled: false };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    // The rotate mock fails loudly if a second mutation is ever issued.
    const rotateMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true } },
      error: new Error('ROTATE_MUST_NOT_FIRE'),
    };
    renderPage([...baseMocksWith(holder), disableMock, rotateMock]);
    await screen.findByTestId('share-panel');

    await user.click(await screen.findByTestId('disable-public-orders'));
    expect(screen.getByTestId('rotate-token')).toBeDisabled();
    expect(screen.getByTestId('rotate-token')).toHaveTextContent('Working…');
    // Fired while the disable is outstanding: the control is disabled, and the
    // hook's in-flight guard must swallow the event either way.
    fireEvent.click(screen.getByTestId('rotate-token'));
    expect(screen.getByTestId('save-settings')).toHaveTextContent('Saving…');

    // The disable is the accepted action: only one request may go out (a fired
    // rotate would paint its error text), the feature ends up off, and the
    // controls come back once the whole span settles.
    await waitFor(() => expect(screen.queryByTestId('share-panel')).not.toBeInTheDocument());
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(screen.queryByText('ROTATE_MUST_NOT_FIRE')).not.toBeInTheDocument();
    expect(screen.getByRole('switch')).not.toBeChecked();
    await waitFor(() => expect(screen.getByTestId('rotate-token')).toBeEnabled());
    expect(screen.getByTestId('rotate-token')).toHaveTextContent('Rotate link');
  });

  it('derives success from the mutation result and reports a failed refresh separately', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'old-token', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const rotateMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true } },
      result: () => {
        holder.current = { ...holder.current, shareToken: 'rotated-token' };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    const mocks: MockedResponse[] = [
      baseMocksWith(holder)[0],
      // The opening read succeeds once; the action's refetch hits the failing
      // next mock.
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        maxUsageCount: 1,
        result: () => ({ data: { getProfilePublicOrderSettings: holder.current } }),
      },
      { request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } }, error: new Error('refetch fault') },
      baseMocksWith(holder)[2],
      baseMocksWith(holder)[3],
      rotateMock,
    ];
    renderPage(mocks);
    await screen.findByTestId('share-panel');
    expect(screen.getByTestId('share-panel')).toHaveTextContent('old-token');

    await user.click(screen.getByTestId('rotate-token'));

    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    // Even with the refetch dead, the share view re-renders from the mutation's
    // own returned settings, and the success is not turned into a failure.
    expect(await screen.findByTestId('refresh-failed')).toBeInTheDocument();
    expect(screen.getByTestId('share-panel')).toHaveTextContent('rotated-token');
    await waitFor(() => expect(screen.getByTestId('rotate-token')).toBeEnabled());
    expect(screen.queryByText('refetch fault')).not.toBeInTheDocument();

    // The seller's own edit must still downgrade the confirmation to the
    // unsaved indicator even though the refresh failed, and the retryable
    // notice must survive the downgrade.
    await user.click(screen.getByRole('checkbox', { name: 'Venmo' }));
    expect(await screen.findByTestId('unsaved-changes')).toBeInTheDocument();
    expect(screen.queryByTestId('settings-saved')).not.toBeInTheDocument();
    expect(screen.getByTestId('refresh-failed')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Venmo' }));
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument();
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

  it('keeps the confirmation across the unedited post-save refetch', async () => {
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
          campaignId: undefined,
          allowedPaymentMethods: ['Venmo'],
          acknowledgementsAccepted: undefined,
        },
      },
      result: () => ({ data: { updateProfilePublicOrderSettings: holder.current } }),
    };
    renderPage([...baseMocksWith(holder), mutationMock]);

    await user.click(await screen.findByTestId('save-settings'));
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument();
  });

  it('replaces the confirmation with the unsaved indicator when the seller edits the draft', async () => {
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
          campaignId: undefined,
          allowedPaymentMethods: [],
          acknowledgementsAccepted: undefined,
        },
      },
      result: () => {
        holder.current = { ...holder.current, allowedPaymentMethods: [] };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    renderPage([...baseMocksWith(holder), mutationMock]);

    await user.click(await screen.findByRole('checkbox', { name: 'Venmo' }));
    await user.click(await screen.findByTestId('save-settings'));
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    // Wait for the action's span to settle before the seller edits again.
    await waitFor(() => expect(screen.getByTestId('save-settings')).toHaveTextContent('Save'));

    // A later edit invalidates the confirmation and shows the indicator; undo
    // the edit and the confirmation comes back.
    await user.click(screen.getByRole('checkbox', { name: 'Venmo' }));
    expect(await screen.findByTestId('unsaved-changes')).toBeInTheDocument();
    expect(screen.queryByTestId('settings-saved')).not.toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Venmo' }));
    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument();
  });

  // The route keeps one settings-page instance across profile params, so an
  // in-flight action resolved for the previous identity must never repaint the
  // new profile's form or share panel, and its feedback must not survive the
  // switch.
  it('drops an in-flight action resolved for the previous profile identity', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'tok-1', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const disableMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: false } },
      delay: 500,
      result: () => ({ data: { updateProfilePublicOrderSettings: { ...holder.current, enabled: false } } }),
    };
    const PROFILE_TWO = 'PROFILE#p-2';
    const profileTwoMocks: MockedResponse[] = [
      {
        request: { query: GET_PROFILE, variables: { profileId: PROFILE_TWO } },
        maxUsageCount: 10,
        result: {
          data: {
            getProfile: {
              __typename: 'SellerProfile',
              profileId: PROFILE_TWO,
              ownerAccountId: 'ACCOUNT#a-1',
              sellerName: 'Troop 99',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: true,
              permissions: [],
            },
          },
        },
      },
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: PROFILE_TWO } },
        maxUsageCount: 10,
        result: {
          data: {
            getProfilePublicOrderSettings: settingsFor({
              enabled: true,
              shareToken: 'tok-2',
              ackVersion: 1,
              campaignId: 'CAMPAIGN#c-1',
            }),
          },
        },
      },
      {
        request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: PROFILE_TWO, limit: 100 } },
        maxUsageCount: 10,
        result: { data: { listCampaignsByProfile: { __typename: 'CampaignConnection', campaigns: [campaign], nextToken: null } } },
      },
    ];
    renderPage([...baseMocksWith(holder), disableMock, ...profileTwoMocks]);
    await screen.findByTestId('share-panel');

    await user.click(await screen.findByTestId('disable-public-orders'));
    await user.click(await screen.findByTestId('switch-profile'));

    // Profile two's own persisted truth stands: its token, its toggle, and no
    // residue of the dropped action.
    expect(await screen.findByText(/Troop 99/)).toBeInTheDocument();
    expect(await screen.findByTestId('share-panel')).toHaveTextContent('tok-2');
    expect(screen.getByRole('switch')).toBeChecked();
    expect(screen.queryByTestId('settings-saved')).not.toBeInTheDocument();
    expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument();
    expect(screen.queryByTestId('refresh-failed')).not.toBeInTheDocument();
    // The dropped span released its page-wide slot: actions work again.
    await waitFor(() => expect(screen.getByTestId('rotate-token')).toBeEnabled());
  });

  // A hard settings failure on a SECOND profile must surface as the error
  // alert: profile A's success must not carry its ever-loaded marker into
  // profile B's page, or B's failure renders an endless spinner.
  it("shows the error alert when a later profile's settings read fails", async () => {
    const user = userEvent.setup();
    const PROFILE_TWO = 'PROFILE#p-2';
    const profileTwoMocks: MockedResponse[] = [
      {
        request: { query: GET_PROFILE, variables: { profileId: PROFILE_TWO } },
        maxUsageCount: 10,
        result: {
          data: {
            getProfile: {
              __typename: 'SellerProfile',
              profileId: PROFILE_TWO,
              ownerAccountId: 'ACCOUNT#a-1',
              sellerName: 'Troop 99',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: true,
              permissions: [],
            },
          },
        },
      },
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: PROFILE_TWO } },
        maxUsageCount: 10,
        error: new Error('settings fault'),
      },
      {
        request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: PROFILE_TWO, limit: 100 } },
        maxUsageCount: 10,
        result: { data: { listCampaignsByProfile: { __typename: 'CampaignConnection', campaigns: [], nextToken: null } } },
      },
    ];
    renderPage([...baseMocks(settingsFor()), ...profileTwoMocks]);
    await screen.findByText('Accept public orders');

    await user.click(screen.getByTestId('switch-profile'));

    expect(await screen.findByText(/Failed to load public order settings/)).toBeInTheDocument();
  });

  // AppSync answers resolver faults over HTTP 200 + errors[], so a refresh
  // can RESOLVE with GraphQL errors under the main client's errorPolicy:'all'
  // instead of rejecting: that shape is still a failed refresh, reported as
  // the retryable notice without negating the action's own success.
  it('reports a refresh that resolves riding GraphQL errors', async () => {
    const user = userEvent.setup();
    const holder: SettingsHolder = {
      current: settingsFor({ enabled: true, shareToken: 'old-token', ackVersion: 1, campaignId: 'CAMPAIGN#c-1' }),
    };
    const rotateMock: MockedResponse = {
      request: { query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true } },
      result: () => {
        holder.current = { ...holder.current, shareToken: 'rotated-token' };
        return { data: { updateProfilePublicOrderSettings: holder.current } };
      },
    };
    const mocks: MockedResponse[] = [
      baseMocksWith(holder)[0],
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        maxUsageCount: 1,
        result: () => ({ data: { getProfilePublicOrderSettings: holder.current } }),
      },
      {
        request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
        maxUsageCount: 1,
        result: () => ({
          data: { getProfilePublicOrderSettings: holder.current },
          errors: [new GraphQLError('resolver fault', { extensions: { code: 'INTERNAL_SERVER_ERROR' } })],
        }),
      },
      baseMocksWith(holder)[2],
      baseMocksWith(holder)[3],
      rotateMock,
    ];
    renderPage(mocks);
    await screen.findByTestId('share-panel');

    await user.click(screen.getByTestId('rotate-token'));

    expect(await screen.findByTestId('settings-saved')).toBeInTheDocument();
    expect(await screen.findByTestId('refresh-failed')).toBeInTheDocument();
    expect(screen.getByTestId('share-panel')).toHaveTextContent('rotated-token');
    await waitFor(() => expect(screen.getByTestId('rotate-token')).toBeEnabled());
    expect(screen.queryByText('resolver fault')).not.toBeInTheDocument();
    expect(screen.queryByTestId('unsaved-changes')).not.toBeInTheDocument();
  });

  it('shows no share view when the token is missing despite being enabled', async () => {
    await openPage(baseMocks(settingsFor({ enabled: true, ackVersion: 1, campaignId: 'CAMPAIGN#c-1', shareToken: null })));
    await screen.findByTestId('cap-notice');
    expect(screen.queryByTestId('share-panel')).not.toBeInTheDocument();
  });

  it('drops a stored method when the seller unchecks it, naming no campaign', async () => {
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
          // The picked campaign did not change, so the save names no anchor and
          // stays clear of anchor enforcement.
          campaignId: undefined,
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
