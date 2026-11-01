/**
 * CampaignSettingsPage public-orders section tests.
 *
 * The campaign settings page hosts the public-order settings UI
 * (share link, capacity notice, both mandated acknowledgement checkboxes,
 * the payment-method checklist driven by the seller's real methods, and the
 * save/enable/disable/rotate actions) driven by
 * useCampaignPublicOrderSettings against the campaign-keyed API.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CampaignSettingsPage } from '../src/pages/CampaignSettingsPage';
import {
  GET_CAMPAIGN,
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  GET_MY_PAYMENT_METHODS,
  GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
  UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
} from '../src/lib/graphql';
import {
  PAYMENT_ACK_TEXT,
  DISCLOSURE_ACK_TEXT,
} from '../src/components/public/PublicSettingsAckCheckboxes';
import type { GqlCampaign as Campaign } from '../src/types';

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,mockqrcode'),
  },
}));

const PROFILE_ID_RAW = 'profile-123';
const CAMPAIGN_ID_RAW = 'campaign-456';
const PROFILE_ID = `PROFILE#${PROFILE_ID_RAW}`;
const CAMPAIGN_ID = `CAMPAIGN#${CAMPAIGN_ID_RAW}`;
const CATALOG_ID = `CATALOG#catalog-1`;

const shareUrlFor = (token: string) => `${window.location.origin}/o/${CAMPAIGN_ID_RAW}/${token}`;

type CampaignFixture = Omit<Campaign, 'sharedCampaignCode' | 'catalogId' | 'startDate' | 'endDate'> & {
  __typename?: string;
  sharedCampaignCode?: string | null;
  catalogId?: string | null;
  startDate?: string | null;
  endDate?: string | null;
};

const mockCampaign: CampaignFixture = {
  __typename: 'Campaign',
  campaignId: CAMPAIGN_ID,
  profileId: PROFILE_ID,
  campaignName: 'Spring Sale',
  campaignYear: 2025,
  startDate: '2025-03-01T00:00:00.000Z',
  endDate: '2025-03-31T00:00:00.000Z',
  catalogId: CATALOG_ID,
  unitType: 'Pack',
  unitNumber: 101,
  city: 'Springfield',
  state: 'IL',
  sharedCampaignCode: null,
  isActive: true,
  totalOrders: 0,
  totalRevenue: 0,
  createdAt: '2025-01-01T00:00:00.000Z',
  updatedAt: '2025-01-01T00:00:00.000Z',
};

const mockCatalog = {
  __typename: 'Catalog',
  catalogId: CATALOG_ID,
  catalogName: 'Official Catalog',
  catalogType: 'ADMIN_MANAGED',
  isPublic: true,
  isDeleted: false,
  products: [],
};

const makeSettings = (overrides: Record<string, unknown> = {}) => ({
  __typename: 'CampaignPublicOrderSettings',
  enabled: true,
  shareToken: 'tok-1',
  allowedPaymentMethods: ['Cash'],
  acknowledgedAt: '2025-01-01T00:00:00.000Z',
  ackVersion: 1,
  publicOrderCount: 3,
  campaignId: CAMPAIGN_ID,
  campaignName: 'Spring Sale',
  campaignState: 'IL',
  ...overrides,
});

const baseMocks = (settings = makeSettings()): MockedResponse[] => [
  {
    request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_ID } },
    result: { data: { getCampaign: mockCampaign } },
  },
  {
    request: { query: LIST_MANAGED_CATALOGS },
    result: { data: { listManagedCatalogs: [mockCatalog] } },
  },
  {
    request: { query: LIST_MY_CATALOGS },
    result: { data: { listMyCatalogs: [] } },
  },
  {
    request: { query: GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS, variables: { campaignId: CAMPAIGN_ID } },
    result: { data: { getCampaignPublicOrderSettings: settings } },
  },
  {
    request: { query: GET_MY_PAYMENT_METHODS },
    result: {
      data: {
        myPaymentMethods: [
          { __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: null },
          { __typename: 'PaymentMethod', name: 'Cash', qrCodeUrl: null },
        ],
      },
    },
  },
];

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter
        initialEntries={[`/scouts/${PROFILE_ID_RAW}/campaigns/${CAMPAIGN_ID_RAW}/settings`]}
      >
        <Routes>
          <Route
            path="/scouts/:profileId/campaigns/:campaignId/settings"
            element={<CampaignSettingsPage />}
          />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

const settingsVisible = async () => {
  await waitFor(() => {
    expect(screen.getByText('Public Orders')).toBeInTheDocument();
  });
  await waitFor(() => {
    expect(screen.getByTestId('share-url')).toHaveTextContent(shareUrlFor('tok-1'));
  });
};

describe('CampaignSettingsPage public orders section', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the share link, capacity notice, and controls once settings load', async () => {
    renderPage(baseMocks());
    await settingsVisible();

    // The bare campaign id is used — a raw CAMPAIGN# prefix would break the URL.
    expect(screen.getByTestId('share-url').textContent).not.toContain('CAMPAIGN#');
    expect(screen.getByText(/3 out of 500 maximum orders/)).toBeInTheDocument();
    // Both mandated acknowledgement texts render.
    expect(screen.getByText(PAYMENT_ACK_TEXT)).toBeInTheDocument();
    expect(screen.getByText(DISCLOSURE_ACK_TEXT)).toBeInTheDocument();
    // The checklist lists the seller's real methods (Venmo from payment methods).
    expect(screen.getByRole('checkbox', { name: 'Venmo' })).toBeEnabled();
    expect(screen.getByRole('checkbox', { name: 'Check' })).toBeEnabled();
    expect(screen.queryByRole('checkbox', { name: 'Visa' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Disable' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Enable' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rotate Share Token' })).toBeEnabled();
  });

  it('explains the missing share link when public orders were never enabled', async () => {
    renderPage(baseMocks(makeSettings({ shareToken: null })));
    await waitFor(() => {
      expect(screen.getByText('Public Orders')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText(/Share link not available/)).toBeInTheDocument();
    });
  });

  it('keeps the draft controls editable while public orders are disabled', async () => {
    renderPage(baseMocks(makeSettings({
      enabled: false,
      shareToken: null,
      acknowledgedAt: null,
      ackVersion: null,
    })));
    await waitFor(() => {
      expect(screen.getByText('Public Orders')).toBeInTheDocument();
    });
    // F1 regression: the seller must be able to pick methods and acks BEFORE
    // enabling — the server rejects an enable with an empty method list.
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: 'Venmo' })).toBeEnabled();
    });
    expect(screen.getByRole('checkbox', { name: 'Cash' })).toBeEnabled();
    // Enable stays gated until both acks are checked and a method is chosen.
    expect(screen.getByRole('button', { name: 'Enable' })).toBeDisabled();
    // FUNC-3: Save and Rotate are enabled while parked so sellers can save config or rotate leaked token.
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Rotate Share Token' })).toBeEnabled();
  });

  it('enables public orders end-to-end: acks + method first, then Enable', async () => {
    const mocks = [
      ...baseMocks(makeSettings({ enabled: false, shareToken: null, acknowledgedAt: null, ackVersion: null })),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: true,
              allowedPaymentMethods: ['Cash', 'Venmo'],
              acknowledgementsAccepted: true,
            },
          },
        },
        result: {
          data: {
            updateCampaignPublicOrderSettings: makeSettings({
              allowedPaymentMethods: ['Cash', 'Venmo'],
            }),
          },
        },
      },
    ];
    renderPage(mocks);
    await waitFor(() => {
      expect(screen.getByText('Public Orders')).toBeInTheDocument();
    });
    // The section body renders only once the settings query lands, so the
    // action and the method list are awaited, not assumed.
    const enableButton = await screen.findByRole('button', { name: 'Enable' });
    expect(enableButton).toBeDisabled();

    await userEvent.click(await screen.findByRole('checkbox', { name: PAYMENT_ACK_TEXT }));
    await userEvent.click(await screen.findByRole('checkbox', { name: DISCLOSURE_ACK_TEXT }));
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Venmo' }));
    expect(screen.getByRole('button', { name: 'Enable' })).toBeEnabled();

    await userEvent.click(screen.getByRole('button', { name: 'Enable' }));

    await waitFor(() => {
      expect(screen.getByTestId('share-url')).toHaveTextContent(shareUrlFor('tok-1'));
    });
  });

  it('saves a draft edit of the allowed payment methods', async () => {
    const mocks = [
      ...baseMocks(),
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
        result: {
          data: {
            updateCampaignPublicOrderSettings: makeSettings({
              allowedPaymentMethods: ['Cash', 'Check'],
            }),
          },
        },
      },
    ];
    renderPage(mocks);
    await settingsVisible();

    await userEvent.click(screen.getByRole('checkbox', { name: 'Check' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: 'Check' })).toBeChecked();
    });
  });

  it('sends rotateToken when the rotate action is clicked', async () => {
    const mocks = [
      ...baseMocks(),
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
        result: {
          data: { updateCampaignPublicOrderSettings: makeSettings({ shareToken: 'tok-2' }) },
        },
      },
    ];
    renderPage(mocks);
    await settingsVisible();

    await userEvent.click(screen.getByRole('button', { name: 'Rotate Share Token' }));

    await waitFor(() => {
      expect(screen.getByTestId('share-url')).toHaveTextContent(shareUrlFor('tok-2'));
    });
  });

  it('sends enabled=false when the disable action is clicked', async () => {
    const mocks = [
      ...baseMocks(),
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
        result: {
          data: {
            updateCampaignPublicOrderSettings: makeSettings({ enabled: false, shareToken: null }),
          },
        },
      },
    ];
    renderPage(mocks);
    await settingsVisible();

    await userEvent.click(screen.getByRole('button', { name: 'Disable' }));

    await waitFor(() => {
      expect(screen.getByText(/Share link not available/)).toBeInTheDocument();
    });
  });

  it('FUNC-2: displays actionable error alert when token rotation fails, stating token is STILL ACTIVE', async () => {
    const mocks = [
      ...baseMocks(),
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
        error: new Error('Network error during rotation'),
      },
    ];
    renderPage(mocks);
    await settingsVisible();

    await userEvent.click(screen.getByRole('button', { name: 'Rotate Share Token' }));

    await waitFor(() => {
      const alertMsg = screen.getByText(/the token is STILL ACTIVE/);
      expect(alertMsg).toBeInTheDocument();
      expect(alertMsg.textContent).toContain('Failed to rotate share token');
    });
  });

  it('FUNC-2: displays actionable error alert when save fails', async () => {
    const mocks = [
      ...baseMocks(),
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
        error: new Error('Database write failed'),
      },
    ];
    renderPage(mocks);
    await settingsVisible();

    await userEvent.click(screen.getByRole('checkbox', { name: 'Check' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      const alertMsg = screen.getByText(/Failed to save public order settings/);
      expect(alertMsg).toBeInTheDocument();
      expect(alertMsg.textContent).toContain('Database write failed');
    });
  });

  it('FUNC-3: allows saving configuration and rotating token while parked (enabled=false)', async () => {
    const parkedSettings = makeSettings({
      enabled: false,
      shareToken: 'leaked-tok',
      allowedPaymentMethods: ['Cash'],
    });
    const mocks = [
      ...baseMocks(parkedSettings),
      {
        request: {
          query: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              enabled: false,
              allowedPaymentMethods: ['Cash'],
              acknowledgementsAccepted: true,
              rotateToken: true,
            },
          },
        },
        result: {
          data: {
            updateCampaignPublicOrderSettings: makeSettings({
              enabled: false,
              shareToken: 'rotated-parked-tok',
            }),
          },
        },
      },
    ];
    renderPage(mocks);
    await waitFor(() => {
      expect(screen.getByTestId('share-url')).toHaveTextContent(shareUrlFor('leaked-tok'));
    });

    const rotateButton = screen.getByRole('button', { name: 'Rotate Share Token' });
    const saveButton = screen.getByRole('button', { name: 'Save' });
    expect(rotateButton).toBeEnabled();
    expect(saveButton).toBeEnabled();

    await userEvent.click(rotateButton);

    await waitFor(() => {
      expect(screen.getByTestId('share-url')).toHaveTextContent(shareUrlFor('rotated-parked-tok'));
    });
  });

  it('SEC-7: gates pre-checks on ackVersion; requires explicit re-acceptance before Save/Enable when outdated', async () => {
    const outdatedSettings = makeSettings({
      enabled: true,
      acknowledgedAt: '2024-01-01T00:00:00.000Z',
      ackVersion: 0, // Outdated
      allowedPaymentMethods: ['Cash'],
    });
    renderPage(baseMocks(outdatedSettings));
    await settingsVisible();

    const paymentAck = screen.getByRole('checkbox', { name: PAYMENT_ACK_TEXT });
    const disclosureAck = screen.getByRole('checkbox', { name: DISCLOSURE_ACK_TEXT });
    expect(paymentAck).not.toBeChecked();
    expect(disclosureAck).not.toBeChecked();

    // Save must be disabled because acknowledgements are behind
    const saveButton = screen.getByRole('button', { name: 'Save' });
    expect(saveButton).toBeDisabled();

    // After re-acknowledging both terms, Save becomes enabled
    await userEvent.click(paymentAck);
    expect(saveButton).toBeDisabled();
    await userEvent.click(disclosureAck);
    expect(saveButton).toBeEnabled();
  });

  it('FUNC-10a: distinguishes transient query errors from NOT_FOUND with a retryable alert', async () => {
    const transientError = new Error('Network connection lost');
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_ID } },
        result: { data: { getCampaign: mockCampaign } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
      {
        request: { query: LIST_MY_CATALOGS },
        result: { data: { listMyCatalogs: [] } },
      },
      {
        request: { query: GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS, variables: { campaignId: CAMPAIGN_ID } },
        error: transientError,
      },
      {
        request: { query: GET_MY_PAYMENT_METHODS },
        result: { data: { myPaymentMethods: [] } },
      },
      {
        request: { query: GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS, variables: { campaignId: CAMPAIGN_ID } },
        result: { data: { getCampaignPublicOrderSettings: makeSettings() } },
      },
    ];
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByText(/Failed to load public order settings/)).toBeInTheDocument();
    });

    const retryButton = screen.getByRole('button', { name: /retry/i });
    expect(retryButton).toBeInTheDocument();

    await userEvent.click(retryButton);

    await waitFor(() => {
      expect(screen.getByTestId('share-url')).toBeInTheDocument();
    });
  });

  it('FUNC-10a: distinguishes NOT_FOUND query error with unavailable message', async () => {
    const notFoundError = new Error('Not found');
    (notFoundError as unknown as { graphQLErrors: Array<{ extensions: { errorCode: string } }> }).graphQLErrors = [
      { extensions: { errorCode: 'NOT_FOUND' } },
    ];
    const mocks: MockedResponse[] = [
      {
        request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_ID } },
        result: { data: { getCampaign: mockCampaign } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
      {
        request: { query: LIST_MY_CATALOGS },
        result: { data: { listMyCatalogs: [] } },
      },
      {
        request: { query: GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS, variables: { campaignId: CAMPAIGN_ID } },
        error: notFoundError,
      },
      {
        request: { query: GET_MY_PAYMENT_METHODS },
        result: { data: { myPaymentMethods: [] } },
      },
    ];
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByText('Public order settings not available for this campaign.')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });

  it('ARCH-6: hides public orders section for non-owners (isOwner=false)', async () => {
    render(
      <MockedProvider mocks={baseMocks()}>
        <MemoryRouter
          initialEntries={[`/scouts/${PROFILE_ID_RAW}/campaigns/${CAMPAIGN_ID_RAW}/settings`]}
        >
          <Routes>
            <Route
              path="/scouts/:profileId/campaigns/:campaignId/settings"
              element={<CampaignSettingsPage isOwner={false} />}
            />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    // Basic Information should still be visible
    await waitFor(() => {
      expect(screen.getByText('Basic Information')).toBeInTheDocument();
    });

    // Public Orders must NOT be in the document
    expect(screen.queryByText('Public Orders')).not.toBeInTheDocument();
  });
});
