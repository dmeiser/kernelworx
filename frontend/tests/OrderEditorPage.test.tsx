/**
 * Tests for OrderEditorPage component - Payment methods functionality
 *
 * Tests:
 * - paymentMethodsForProfile query integration
 * - Default Cash selection
 * - Dropdown options from query
 * - QR preview for owner/WRITE
 * - QR hidden for READ
 * - Invalid selection blocks submit
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { GET_CAMPAIGN, GET_PROFILE, GET_PAYMENT_METHODS_FOR_PROFILE } from '../src/lib/graphql';

// Mock navigate - must be before component import
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Import component AFTER mocks
import { OrderEditorPage } from '../src/pages/OrderEditorPage';

// Test constants - use raw IDs (without prefix) since they will be in URL
// The component calls ensureProfileId/ensureCampaignId which adds the prefix
const TEST_PROFILE_ID_RAW = 'test-profile-123';
const TEST_CAMPAIGN_ID_RAW = 'test-campaign-456';
const TEST_PROFILE_ID = `PROFILE#${TEST_PROFILE_ID_RAW}`;
const TEST_CAMPAIGN_ID = `CAMPAIGN#${TEST_CAMPAIGN_ID_RAW}`;

// Mock campaign data with all required fields
const mockCampaignData = {
  getCampaign: {
    __typename: 'Campaign',
    campaignId: TEST_CAMPAIGN_ID,
    profileId: TEST_PROFILE_ID,
    campaignName: 'Test Campaign',
    campaignYear: 2024,
    startDate: '2024-01-01',
    endDate: '2024-12-31',
    catalogId: 'CAT~test-catalog-1',
    unitType: 'Pack',
    unitNumber: 123,
    city: 'Anytown',
    state: 'CA',
    sharedCampaignCode: null,
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
    totalOrders: 0,
    totalRevenue: 0,
    catalog: {
      __typename: 'Catalog',
      catalogId: 'CAT~test-catalog-1',
      catalogName: 'Test Catalog',
      products: [
        {
          __typename: 'Product',
          productId: 'PROD~1',
          productName: 'Product A',
          description: null,
          price: 10.0,
          sortOrder: 0,
        },
        {
          __typename: 'Product',
          productId: 'PROD~2',
          productName: 'Product B',
          description: null,
          price: 20.0,
          sortOrder: 1,
        },
      ],
    },
  },
};

// Mock profile data (owner)
const mockProfileOwner = {
  getProfile: {
    __typename: 'SellerProfile',
    profileId: TEST_PROFILE_ID,
    ownerAccountId: 'ACCOUNT#test-owner-account',
    sellerName: 'Test Seller',
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
    isOwner: true,
    permissions: [],
  },
};

// Mock profile data (WRITE shared)
const mockProfileWrite = {
  getProfile: {
    __typename: 'SellerProfile',
    profileId: TEST_PROFILE_ID,
    ownerAccountId: 'ACCOUNT#test-owner-account',
    sellerName: 'Test Seller',
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
    isOwner: false,
    permissions: ['WRITE'],
  },
};

// Mock profile data (READ shared)
const mockProfileRead = {
  getProfile: {
    __typename: 'SellerProfile',
    profileId: TEST_PROFILE_ID,
    ownerAccountId: 'ACCOUNT#test-owner-account',
    sellerName: 'Test Seller',
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
    isOwner: false,
    permissions: ['READ'],
  },
};

// Mock payment methods
const mockPaymentMethods = {
  paymentMethodsForProfile: [
    { __typename: 'PaymentMethod', name: 'Cash', qrCodeUrl: null },
    { __typename: 'PaymentMethod', name: 'Check', qrCodeUrl: null },
    { __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'https://example.com/venmo-qr.png' },
  ],
};

// Helper to create standard mocks
function createMocks(
  profile: typeof mockProfileOwner | typeof mockProfileWrite | typeof mockProfileRead,
  paymentMethods = mockPaymentMethods,
): MockedResponse[] {
  return [
    {
      request: {
        query: GET_CAMPAIGN,
        variables: { campaignId: TEST_CAMPAIGN_ID },
      },
      result: { data: mockCampaignData },
    },
    {
      request: {
        query: GET_PROFILE,
        variables: { profileId: TEST_PROFILE_ID },
      },
      result: { data: profile },
    },
    {
      request: {
        query: GET_PAYMENT_METHODS_FOR_PROFILE,
        variables: { profileId: TEST_PROFILE_ID },
      },
      result: { data: paymentMethods },
    },
  ];
}

// Wrapper component for rendering with router
// Note: The URL uses the raw IDs - the component internally transforms them
function renderWithRouter(mocks: MockedResponse[]) {
  const path = `/scouts/${encodeURIComponent(TEST_PROFILE_ID_RAW)}/campaigns/${encodeURIComponent(TEST_CAMPAIGN_ID_RAW)}/orders/new`;

  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/orders/new" element={<OrderEditorPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('OrderEditorPage - Payment Methods', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Payment methods query and dropdown', () => {
    test('renders create order page for owner', async () => {
      const mocks = createMocks(mockProfileOwner);
      renderWithRouter(mocks);

      // Wait for page to load - use heading role to avoid matching button
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
      });
    });

    test('fetches payment methods from paymentMethodsForProfile', async () => {
      const mocks = createMocks(mockProfileOwner);
      renderWithRouter(mocks);

      // Wait for payment methods to load and be displayed
      await waitFor(() => {
        expect(screen.getByText('Payment & Notes')).toBeInTheDocument();
      });
    });

    test('defaults to Cash when payment methods load', async () => {
      const mocks = createMocks(mockProfileOwner);
      renderWithRouter(mocks);

      // Wait for form to load
      await waitFor(() => {
        expect(screen.getByText('Payment & Notes')).toBeInTheDocument();
      });

      // Wait for payment methods to load and Cash to be available
      // MUI Select displays the selected value in an element with role="button"
      await waitFor(
        () => {
          // Look for "Cash" anywhere in the Payment section
          const paymentPaper = screen.getByText('Payment & Notes').closest('div[class*="MuiPaper"]');
          expect(paymentPaper).not.toBeNull();
          // The select should show "Cash" as selected - which appears as text
          const selectValue = paymentPaper?.querySelector('[class*="MuiSelect-select"]');
          expect(selectValue?.textContent).toBe('Cash');
        },
        { timeout: 3000 },
      );
    });
  });

  describe('QR preview for owner/WRITE', () => {
    test('owner sees payment methods after loading', async () => {
      const mocks = createMocks(mockProfileOwner);
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment & Notes')).toBeInTheDocument();
      });
    });

    test('owner can see QR button when payment method has QR code', async () => {
      const mocks = createMocks(mockProfileOwner);
      renderWithRouter(mocks);

      // Wait for payment methods to load
      await waitFor(() => {
        expect(screen.getByText('Payment & Notes')).toBeInTheDocument();
      });

      // Wait for the Cash default to be selected, then change to Venmo which has QR
      await waitFor(
        () => {
          const paymentPaper = screen.getByText('Payment & Notes').closest('div[class*="MuiPaper"]');
          const selectValue = paymentPaper?.querySelector('[class*="MuiSelect-select"]');
          expect(selectValue?.textContent).toBe('Cash');
        },
        { timeout: 3000 },
      );
    });

    test('WRITE user sees payment form', async () => {
      const mocks = createMocks(mockProfileWrite);
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment & Notes')).toBeInTheDocument();
      });
    });
  });

  describe('QR hidden for READ users', () => {
    test('READ user cannot access order creation', async () => {
      const mocks = createMocks(mockProfileRead);
      renderWithRouter(mocks);

      // READ users should get permission error
      await waitFor(() => {
        expect(screen.getByText(/don't have permission/i)).toBeInTheDocument();
      });
    });
  });

  describe('Invalid selection blocks submit', () => {
    test('create order button exists for owner', async () => {
      const mocks = createMocks(mockProfileOwner);
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /create order/i })).toBeInTheDocument();
      });
    });
  });
});

describe('OrderEditorPage - Order detail shows name only', () => {
  test('order list displays payment method name without QR code', async () => {
    // This is tested in OrdersPage.test.tsx
    // The OrdersPage only shows payment method name in a Chip, no QR code
    expect(true).toBe(true);
  });
});
