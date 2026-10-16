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
    // Save is meaningless while the feature is off.
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
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
    const enableButton = screen.getByRole('button', { name: 'Enable' });
    expect(enableButton).toBeDisabled();

    await userEvent.click(screen.getByRole('checkbox', { name: PAYMENT_ACK_TEXT }));
    await userEvent.click(screen.getByRole('checkbox', { name: DISCLOSURE_ACK_TEXT }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Venmo' }));
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
});
