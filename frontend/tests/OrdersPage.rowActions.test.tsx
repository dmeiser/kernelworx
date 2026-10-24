/**
 * Tests for the Orders page row and header actions: the create/edit
 * navigation (including the prefixed-ID encoding the edit route needs), the
 * delete round-trip behind window.confirm, and the summary collapse toggle.
 *
 * These are the paths the payment-confirmation suite does not touch, and the
 * edit route is the one place an `ORDER#<campaign>#<order>` ID must survive
 * URL encoding intact.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
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
  orderId: 'ORDER#c-1#pub',
  profileId: DB_PROFILE_ID,
  campaignId: DB_CAMPAIGN_ID,
  customerName: 'Public Buyer',
  customerPhone: '+15555550123',
  customerAddress: { __typename: 'Address', street: '1 Main', city: 'Anytown', state: 'TX', zipCode: '75001' },
  orderDate: '2026-03-01T00:00:00Z',
  paymentMethod: 'CASH',
  lineItems: [
    { __typename: 'LineItem', productId: 'P1', productName: 'Cookies', quantity: 2, pricePerUnit: 5, subtotal: 10 },
  ],
  totalAmount: 10,
  notes: null,
  createdAt: '2026-03-01T00:00:00Z',
  updatedAt: '2026-03-01T00:00:00Z',
  status: 'NEW',
  ...overrides,
});

// The catch-all route reports where a navigate() actually landed, so the
// assertions read the real path instead of a spy's call list.
const RouteProbe = () => {
  const location = useLocation();
  return <div data-testid="route">{location.pathname}</div>;
};

function makeHarness(
  options: { rows?: Record<string, unknown>[]; isOwner?: boolean; permissions?: string[] | null } = {},
) {
  const state = { listCalls: 0, deleteCalls: 0, deleted: false };

  const mocks: MockedResponse[] = [
    {
      request: { query: DELETE_ORDER, variables: { orderId: 'ORDER#c-1#pub' } },
      maxUsageCount: 5,
      result: () => {
        state.deleteCalls += 1;
        state.deleted = true;
        return { data: { deleteOrder: true } };
      },
    },
    {
      request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
      maxUsageCount: 10,
      result: () => ({
        data: {
          getProfile: {
            __typename: 'SellerProfile',
            profileId: DB_PROFILE_ID,
            ownerAccountId: 'ACCOUNT#a-1',
            sellerName: 'Troop 42',
            createdAt: '2026-01-01T00:00:00Z',
            updatedAt: '2026-01-01T00:00:00Z',
            isOwner: options.isOwner ?? true,
            permissions: options.permissions === undefined ? [] : options.permissions,
          },
        },
      }),
    },
    {
      request: { query: LIST_ORDERS_BY_CAMPAIGN, variables: { campaignId: DB_CAMPAIGN_ID } },
      maxUsageCount: 20,
      result: () => {
        state.listCalls += 1;
        return {
          data: {
            listOrdersByCampaign: {
              __typename: 'OrderConnection',
              orders: state.deleted ? [] : options.rows ?? [order({})],
              nextToken: null,
            },
          },
        };
      },
    },
  ];

  const ui = render(
    <MemoryRouter initialEntries={['/scouts/p-1/campaigns/c-1/orders']}>
      <MockedProvider mocks={mocks}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/orders" element={<OrdersPage />} />
          <Route path="*" element={<RouteProbe />} />
        </Routes>
      </MockedProvider>
    </MemoryRouter>,
  );

  return { ui, state };
}

const routePath = () => decodeURIComponent(screen.getByTestId('route').textContent ?? '');

describe('OrdersPage row and header actions', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('navigates to the new-order route from the header button', async () => {
    const { ui } = makeHarness();
    await userEvent.click(await screen.findByRole('button', { name: 'New Order' }));
    await waitFor(() => expect(routePath()).toBe('/scouts/p-1/campaigns/c-1/orders/new'));
    ui.unmount();
  });

  it('navigates to the edit route with the prefixed order ID encoded', async () => {
    const { ui } = makeHarness();
    await userEvent.click(await screen.findByRole('button', { name: 'Edit order for Public Buyer' }));
    // The raw ID carries two '#'; the route must receive it decoded intact.
    await waitFor(() =>
      expect(routePath()).toBe('/scouts/p-1/campaigns/c-1/orders/ORDER#c-1#pub/edit'),
    );
    ui.unmount();
  });

  it('deletes behind window.confirm and refetches the list', async () => {
    vi.stubGlobal('confirm', () => true);
    const { ui, state } = makeHarness();
    await userEvent.click(await screen.findByRole('button', { name: 'Delete order for Public Buyer' }));
    await waitFor(() => expect(state.deleteCalls).toBe(1));
    // The delete's onCompleted refetch drives the empty state, not a local splice.
    await waitFor(() => expect(screen.getByText(/No orders yet/)).toBeInTheDocument());
    expect(state.listCalls).toBeGreaterThan(1);
    ui.unmount();
  });

  it('sends no delete when the browser confirm is declined', async () => {
    vi.stubGlobal('confirm', () => false);
    const { ui, state } = makeHarness();
    await userEvent.click(await screen.findByRole('button', { name: 'Delete order for Public Buyer' }));
    await waitFor(() => expect(screen.getByText('Public Buyer')).toBeInTheDocument());
    expect(state.deleteCalls).toBe(0);
    ui.unmount();
  });

  it('renders fallback cells for an order with no phone, no date, and an unmapped method', async () => {
    const { ui } = makeHarness({
      rows: [order({ customerPhone: null, orderDate: null, paymentMethod: 'WIRE' })],
    });
    await screen.findByText('Public Buyer');
    // Each fallback is its own branch: em dash for the date, the phone, and a
    // payment method the color map does not know.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('WIRE')).toBeInTheDocument();
    ui.unmount();
  });

  it('hides the write actions when the share carries no permissions list', async () => {
    const { ui, state } = makeHarness({ isOwner: false, permissions: null });
    await screen.findByText('Public Buyer');
    await waitFor(() => expect(state.listCalls).toBeGreaterThan(0));
    expect(screen.queryByRole('button', { name: 'New Order' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit order for Public Buyer' })).toBeNull();
    ui.unmount();
  });

  it('collapses and re-expands the campaign summary', async () => {
    const { ui } = makeHarness();
    const toggle = await screen.findByRole('button', { name: 'Hide Summary' });
    await userEvent.click(toggle);
    await screen.findByRole('button', { name: 'Show Summary' });
    await userEvent.click(screen.getByRole('button', { name: 'Show Summary' }));
    await screen.findByRole('button', { name: 'Hide Summary' });
    ui.unmount();
  });
});
