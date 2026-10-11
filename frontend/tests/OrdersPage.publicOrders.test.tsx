/**
 * Tests for the public-order columns on the seller's Orders page.
 *
 * Public orders arrive with orderSource PUBLIC, a buyer email and status NEW;
 * authenticated orders carry none of the three (no backfill), so the badge,
 * the email line and the status chip must render only what the row actually
 * has — an authenticated order must not grow an empty "New" chip.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';
import { OrdersPage } from '../src/pages/OrdersPage';
import { GET_PROFILE, LIST_ORDERS_BY_CAMPAIGN, DELETE_ORDER } from '../src/lib/graphql';
import type { MockedResponse } from '@apollo/client/testing';

const DB_CAMPAIGN_ID = 'CAMPAIGN#c-1';
const DB_PROFILE_ID = 'PROFILE#p-1';

const order = (overrides: Record<string, unknown>) => ({
  __typename: 'Order',
  orderId: 'ORDER#c-1#o-1',
  profileId: DB_PROFILE_ID,
  campaignId: DB_CAMPAIGN_ID,
  customerName: 'Ada Parent',
  customerPhone: '+15555550123',
  customerAddress: { __typename: 'Address', street: '1 Main', city: 'Anytown', state: 'TX', zipCode: '75001' },
  orderDate: '2026-03-01T00:00:00Z',
  paymentMethod: 'CASH',
  lineItems: [{ __typename: 'LineItem', productId: 'P1', productName: 'Cookies', quantity: 2, pricePerUnit: 5, subtotal: 10 }],
  totalAmount: 10,
  notes: null,
  createdAt: '2026-03-01T00:00:00Z',
  updatedAt: '2026-03-01T00:00:00Z',
  customerEmail: null,
  orderSource: null,
  status: null,
  ...overrides,
});

// Records that the delete mutation actually reached the network layer.
let deleteCalls = 0;

const makeMocks = (): MockedResponse[] => [
  {
    request: { query: DELETE_ORDER, variables: { orderId: 'ORDER#c-1#pub' } },
    result: () => {
      deleteCalls += 1;
      return { data: { deleteOrder: true } };
    },
  },
  {
    request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
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
    request: { query: LIST_ORDERS_BY_CAMPAIGN, variables: { campaignId: DB_CAMPAIGN_ID } },
    maxUsageCount: 10,
    result: {
      data: {
        listOrdersByCampaign: {
          __typename: 'OrderConnection',
          orders: [
            order({
              orderId: 'ORDER#c-1#pub',
              customerName: 'Public Buyer',
              customerEmail: 'buyer@example.com',
              orderSource: 'PUBLIC',
              status: 'NEW',
            }),
            order({ orderId: 'ORDER#c-1#auth', customerName: 'Signed In Buyer' }),
            order({
              orderId: 'ORDER#c-1#conf',
              customerName: 'Confirmed Buyer',
              customerEmail: 'paid@example.com',
              orderSource: 'PUBLIC',
              status: 'CONFIRMED',
            }),
          ],
          nextToken: null,
        },
      },
    },
  },
];

// Shows where the router actually is, so navigation assertions are real.
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage(explicitMocks?: MockedResponse[]) {
  const mocks = explicitMocks ?? makeMocks();
  return render(
    <MemoryRouter initialEntries={[`/scouts/p-1/campaigns/c-1/orders`]}>
      <MockedProvider mocks={mocks}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/orders" element={<OrdersPage />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MockedProvider>
    </MemoryRouter>,
  );
}

describe('OrdersPage public order columns', () => {
  beforeEach(() => {
    deleteCalls = 0;
  });

  it('badges a public order and shows the buyer email', async () => {
    renderPage();
    expect(await screen.findByText('Public Buyer')).toBeInTheDocument();
    const badges = screen.getAllByTestId('public-order-badge');
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveTextContent('Public order');
    expect(screen.getByText('buyer@example.com')).toBeInTheDocument();
    expect(screen.getByText('paid@example.com')).toBeInTheDocument();
  });

  it('leaves an authenticated order without badge, email or status chip', async () => {
    renderPage();
    await screen.findByText('Public Buyer');
    const authRow = screen.getByText('Signed In Buyer').closest('tr');
    expect(authRow?.querySelector('[data-testid="public-order-badge"]')).toBeNull();
    expect(authRow?.querySelector('[data-testid="order-status-chip"]')).toBeNull();
    // Two public rows carry the chip; the authenticated row does not.
    expect(screen.getAllByTestId('order-status-chip')).toHaveLength(2);
    // Only the authenticated row's status cell falls back to the em dash.
    expect(screen.getAllByText('—')).toHaveLength(1);
  });

  it('shows NEW as pending and CONFIRMED as confirmed', async () => {
    renderPage();
    const chips = await screen.findAllByTestId('order-status-chip');
    expect(chips.map((chip) => chip.textContent)).toEqual(['New', 'Payment confirmed']);
  });

  it('opens the editor for a public order through its encoded id', async () => {
    renderPage();
    await screen.findByText('Public Buyer');
    await userEvent.click(screen.getByLabelText('Edit order for Public Buyer'));
    // The raw order id contains '#', so it must reach the path percent-encoded.
    expect(await screen.findByTestId('location')).toHaveTextContent(
      '/scouts/p-1/campaigns/c-1/orders/ORDER%23c-1%23pub/edit',
    );
  });

  it('deletes an order after confirmation and refetches', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();
    await screen.findByText('Public Buyer');
    await userEvent.click(screen.getByLabelText('Delete order for Public Buyer'));
    await waitFor(() => expect(deleteCalls).toBe(1));
    // The list refetches after the delete rather than editing the cache locally.
    await waitFor(() => expect(screen.getAllByTestId('public-order-badge')).toHaveLength(2));
    confirmSpy.mockRestore();
  });

  it('does not delete when the confirmation is declined', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderPage();
    await screen.findByText('Public Buyer');
    await userEvent.click(screen.getByLabelText('Delete order for Signed In Buyer'));
    expect(deleteCalls).toBe(0);
    confirmSpy.mockRestore();
  });

  it('offers the new-order route to a writer', async () => {
    renderPage();
    await screen.findByText('Public Buyer');
    await userEvent.click(screen.getByRole('button', { name: 'New Order' }));
    expect(await screen.findByTestId('location')).toHaveTextContent('/scouts/p-1/campaigns/c-1/orders/new');
  });

  it('surfaces a failed orders load', async () => {
    renderPage([
      {
        request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
        error: new Error('boom'),
      },
      {
        request: { query: LIST_ORDERS_BY_CAMPAIGN, variables: { campaignId: DB_CAMPAIGN_ID } },
        error: new Error('boom'),
      },
    ]);
    expect(await screen.findByText(/Failed to load orders/)).toBeInTheDocument();
  });

  it('shows the empty-state alert when the campaign has no orders', async () => {
    renderPage([
      {
        request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
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
        request: { query: LIST_ORDERS_BY_CAMPAIGN, variables: { campaignId: DB_CAMPAIGN_ID } },
        result: { data: { listOrdersByCampaign: { __typename: 'OrderConnection', orders: [], nextToken: null } } },
      },
    ]);
    expect(await screen.findByText(/No orders yet/)).toBeInTheDocument();
  });

  it('falls back to dashes for an order with no phone and no date', async () => {
    renderPage([
      {
        request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
        result: {
          data: {
            getProfile: {
              __typename: 'SellerProfile',
              profileId: DB_PROFILE_ID,
              ownerAccountId: 'ACCOUNT#a-1',
              sellerName: 'Troop 42',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: false,
              permissions: ['WRITE'],
            },
          },
        },
      },
      {
        request: { query: LIST_ORDERS_BY_CAMPAIGN, variables: { campaignId: DB_CAMPAIGN_ID } },
        result: {
          data: {
            listOrdersByCampaign: {
              __typename: 'OrderConnection',
              orders: [order({ orderId: 'ORDER#c-1#bare', customerName: 'Bare Buyer', customerPhone: null, orderDate: '' })],
              nextToken: null,
            },
          },
        },
      },
    ]);
    await screen.findByText('Bare Buyer');
    // Date, phone and status all fall back to the em dash for this row.
    expect(screen.getAllByText('—')).toHaveLength(3);
    expect(screen.getByRole('button', { name: 'New Order' })).toBeInTheDocument();
  });

  it('renders a shared writer without permissions and an unknown payment label', async () => {
    renderPage([
      {
        request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
        result: {
          data: {
            getProfile: {
              __typename: 'SellerProfile',
              profileId: DB_PROFILE_ID,
              ownerAccountId: 'ACCOUNT#a-1',
              sellerName: 'Troop 42',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: false,
              permissions: null,
            },
          },
        },
      },
      {
        request: { query: LIST_ORDERS_BY_CAMPAIGN, variables: { campaignId: DB_CAMPAIGN_ID } },
        result: {
          data: {
            listOrdersByCampaign: {
              __typename: 'OrderConnection',
              orders: [order({ orderId: 'ORDER#c-1#odd', customerName: 'Odd Buyer', paymentMethod: 'CUSTOM' })],
              nextToken: null,
            },
          },
        },
      },
    ]);
    await screen.findByText('Odd Buyer');
    // A non-owner with no permissions gets no write affordances.
    expect(screen.queryByRole('button', { name: 'New Order' })).not.toBeInTheDocument();
    expect(screen.getByText('CUSTOM')).toBeInTheDocument();
  });

  it('toggles the campaign summary tiles', async () => {
    renderPage();
    await screen.findByText('Public Buyer');
    await userEvent.click(screen.getByRole('button', { name: /Hide Summary|Show Summary/ }));
    expect(screen.getByRole('button', { name: /Hide Summary|Show Summary/ })).toBeInTheDocument();
  });
});
