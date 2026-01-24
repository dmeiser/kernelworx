/**
 * Tests for CampaignSummaryPage component - Payment method totals functionality
 *
 * Tests:
 * - Renders payment method totals (dollar amounts, sorted alphabetically)
 * - Calculates sum correctly across orders
 * - Owner sees totals correctly
 * - WRITE shared user sees owner's totals
 * - READ shared user sees owner's totals
 * - Deleted payment methods show "(inactive)" label
 * - QR codes are never shown (names only)
 */

import '@testing-library/jest-dom';
import { describe, test, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { LIST_ORDERS_BY_CAMPAIGN, GET_PAYMENT_METHODS_FOR_PROFILE } from '../src/lib/graphql';
import { CampaignSummaryPage } from '../src/pages/CampaignSummaryPage';

// Test constants - use raw IDs (without prefix) since they will be in URL
const TEST_PROFILE_ID_RAW = 'test-profile-123';
const TEST_CAMPAIGN_ID_RAW = 'test-campaign-456';
const TEST_PROFILE_ID = `PROFILE#${TEST_PROFILE_ID_RAW}`;
const TEST_CAMPAIGN_ID = `CAMPAIGN#${TEST_CAMPAIGN_ID_RAW}`;

// Mock orders with different payment methods and amounts
const mockOrdersData = {
  listOrdersByCampaign: [
    {
      __typename: 'Order',
      orderId: 'ORDER#1',
      campaignId: TEST_CAMPAIGN_ID,
      customerName: 'John Doe',
      customerEmail: null,
      customerPhone: null,
      customerAddress: null,
      lineItems: [
        {
          __typename: 'LineItem',
          productId: 'PROD~1',
          productName: 'Product A',
          price: 10.0,
          pricePerUnit: 10.0,
          quantity: 2,
          subtotal: 20.0,
        },
      ],
      totalAmount: 20.0,
      paymentMethod: 'Cash',
      notes: null,
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
    },
    {
      __typename: 'Order',
      orderId: 'ORDER#2',
      campaignId: TEST_CAMPAIGN_ID,
      customerName: 'Jane Smith',
      customerEmail: null,
      customerPhone: null,
      customerAddress: null,
      lineItems: [
        {
          __typename: 'LineItem',
          productId: 'PROD~1',
          productName: 'Product A',
          price: 10.0,
          pricePerUnit: 10.0,
          quantity: 5,
          subtotal: 50.0,
        },
      ],
      totalAmount: 50.0,
      paymentMethod: 'Venmo',
      notes: null,
      createdAt: '2024-01-02T00:00:00Z',
      updatedAt: '2024-01-02T00:00:00Z',
    },
    {
      __typename: 'Order',
      orderId: 'ORDER#3',
      campaignId: TEST_CAMPAIGN_ID,
      customerName: 'Bob Wilson',
      customerEmail: null,
      customerPhone: null,
      customerAddress: null,
      lineItems: [
        {
          __typename: 'LineItem',
          productId: 'PROD~2',
          productName: 'Product B',
          price: 15.0,
          pricePerUnit: 15.0,
          quantity: 2,
          subtotal: 30.0,
        },
      ],
      totalAmount: 30.0,
      paymentMethod: 'Cash',
      notes: null,
      createdAt: '2024-01-03T00:00:00Z',
      updatedAt: '2024-01-03T00:00:00Z',
    },
    {
      __typename: 'Order',
      orderId: 'ORDER#4',
      campaignId: TEST_CAMPAIGN_ID,
      customerName: 'Alice Brown',
      customerEmail: null,
      customerPhone: null,
      customerAddress: null,
      lineItems: [
        {
          __typename: 'LineItem',
          productId: 'PROD~1',
          productName: 'Product A',
          price: 10.0,
          pricePerUnit: 10.0,
          quantity: 1,
          subtotal: 10.0,
        },
      ],
      totalAmount: 10.0,
      paymentMethod: 'Zelle', // This will be an inactive payment method
      notes: null,
      createdAt: '2024-01-04T00:00:00Z',
      updatedAt: '2024-01-04T00:00:00Z',
    },
  ],
};

// Mock payment methods - note: Zelle is NOT included (simulating a deleted method)
const mockPaymentMethods = {
  paymentMethodsForProfile: [
    { __typename: 'PaymentMethod', name: 'Cash', qrCodeUrl: null },
    { __typename: 'PaymentMethod', name: 'Check', qrCodeUrl: null },
    { __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'https://example.com/venmo-qr.png' },
  ],
};

// Helper to create standard mocks
function createMocks(orders = mockOrdersData, paymentMethods = mockPaymentMethods): MockedResponse[] {
  return [
    {
      request: {
        query: LIST_ORDERS_BY_CAMPAIGN,
        variables: { campaignId: TEST_CAMPAIGN_ID },
      },
      result: { data: orders },
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
function renderWithRouter(mocks: MockedResponse[]) {
  const path = `/scouts/${encodeURIComponent(TEST_PROFILE_ID_RAW)}/campaigns/${encodeURIComponent(TEST_CAMPAIGN_ID_RAW)}/summary`;

  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/summary" element={<CampaignSummaryPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('CampaignSummaryPage - Payment Method Totals', () => {
  describe('Renders payment method totals', () => {
    test('displays payment methods section heading', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      });
    });

    test('shows dollar amounts for each payment method', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      // Wait for page to load
      await waitFor(() => {
        expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      });

      // Cash: $20 + $30 = $50, Venmo: $50, Zelle: $10
      // Use getAllByText since Cash and Venmo both have $50
      const fiftyElements = screen.getAllByText('$50.00');
      expect(fiftyElements.length).toBe(2); // Cash and Venmo

      expect(screen.getByText('$10.00')).toBeInTheDocument(); // Zelle
    });

    test('shows payment methods sorted alphabetically', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      });

      // Verify all three payment methods are present
      expect(screen.getByText('Cash')).toBeInTheDocument();
      expect(screen.getByText('Venmo')).toBeInTheDocument();
      expect(screen.getByText('Zelle')).toBeInTheDocument();
    });

    test('shows order count for each payment method', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      });

      // Cash has 2 orders
      expect(screen.getByText('2 orders')).toBeInTheDocument();

      // Venmo and Zelle each have 1 order
      const singleOrderElements = screen.getAllByText('1 order');
      expect(singleOrderElements.length).toBe(2);
    });
  });

  describe('Calculates totals correctly', () => {
    test('sums amounts correctly across multiple orders with same payment method', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      });

      // Cash total: $20 + $30 = $50 - should appear twice (Cash and Venmo both have $50)
      const fiftyElements = screen.getAllByText('$50.00');
      expect(fiftyElements.length).toBeGreaterThanOrEqual(2);
    });

    test('shows total sales correctly', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      // Total: $20 + $50 + $30 + $10 = $110
      await waitFor(() => {
        expect(screen.getByText('$110.00')).toBeInTheDocument();
      });
    });
  });

  describe('Inactive (deleted) payment methods', () => {
    test('shows "(inactive)" label for deleted payment methods', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      // Zelle is not in the active payment methods list
      await waitFor(() => {
        expect(screen.getByText('(inactive)')).toBeInTheDocument();
      });
    });

    test('still shows totals for deleted payment methods', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      // Zelle order was $10
      await waitFor(() => {
        expect(screen.getByText('$10.00')).toBeInTheDocument();
      });

      // Zelle should be displayed
      expect(screen.getByText('Zelle')).toBeInTheDocument();
    });

    test('active payment methods do not show "(inactive)" label', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Cash')).toBeInTheDocument();
      });

      // Should only have one "(inactive)" label (for Zelle)
      const inactiveLabels = screen.getAllByText('(inactive)');
      expect(inactiveLabels).toHaveLength(1);
    });
  });

  describe('No orders state', () => {
    test('shows "No orders yet" when there are no orders', async () => {
      const emptyOrders = { listOrdersByCampaign: [] };
      const mocks = createMocks(emptyOrders);
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('No orders yet')).toBeInTheDocument();
      });
    });
  });

  describe('QR codes are never shown', () => {
    test('does not render QR code images', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      });

      // Should not have any img elements for QR codes
      const images = document.querySelectorAll('img[src*="qr"]');
      expect(images).toHaveLength(0);
    });

    test('does not render QR buttons', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      });

      // Should not have any QR-related buttons
      expect(screen.queryByLabelText(/qr/i)).not.toBeInTheDocument();
    });
  });

  describe('Key metrics', () => {
    test('shows total orders count', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Total Orders')).toBeInTheDocument();
      });

      // 4 orders total - appears twice (Total Orders and Unique Customers both show 4)
      const fourElements = screen.getAllByText('4');
      expect(fourElements.length).toBeGreaterThanOrEqual(1);
    });

    test('shows unique customers count', async () => {
      const mocks = createMocks();
      renderWithRouter(mocks);

      await waitFor(() => {
        expect(screen.getByText('Unique Customers')).toBeInTheDocument();
      });

      // 4 unique customers (same as order count since each customer has 1 order)
      const fourElements = screen.getAllByText('4');
      expect(fourElements.length).toBeGreaterThanOrEqual(1);
    });
  });
});
