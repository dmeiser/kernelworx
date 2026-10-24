/**
 * Tests for the seller's "mark payment confirmed" action on the Orders page.
 *
 * The transition is permanent, so it must never fire off a bare click: the
 * confirm dialog is the gate, the mutation carries only `status: CONFIRMED`,
 * and the row's chip flips from the refetched server state. Only the public
 * order path writes a status, so authenticated rows (no status) and already
 * CONFIRMED rows get no affordance at all.
 */

import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { OrdersPage } from '../src/pages/OrdersPage';
import { GET_PROFILE, LIST_ORDERS_BY_CAMPAIGN, UPDATE_ORDER } from '../src/lib/graphql';
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

// Drives the list result so the chip flip is observed through a real refetch
// rather than a hand-edited cache, and counts the lifecycle mutation.
function makeHarness(
  options: { isOwner?: boolean; permissions?: string[] | null; mutationError?: string; initiallyConfirmed?: boolean } = {},
) {
  const state = { listCalls: 0, confirmCalls: 0, profileCalls: 0, confirmed: options.initiallyConfirmed ?? false };

  const mocks: MockedResponse[] = [
    {
      request: {
        query: UPDATE_ORDER,
        variables: { input: { orderId: 'ORDER#c-1#pub', status: 'CONFIRMED' } },
      },
      maxUsageCount: 5,
      result: () => {
        state.confirmCalls += 1;
        if (options.mutationError) {
          return { errors: [new GraphQLError(options.mutationError)] };
        }
        state.confirmed = true;
        return { data: { updateOrder: order({ status: 'CONFIRMED' }) } };
      },
    },
    {
      request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
      maxUsageCount: 10,
      result: () => {
        state.profileCalls += 1;
        return {
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
        };
      },
    },
    {
      request: { query: LIST_ORDERS_BY_CAMPAIGN, variables: { campaignId: DB_CAMPAIGN_ID } },
      maxUsageCount: 10,
      result: () => {
        state.listCalls += 1;
        return {
          data: {
            listOrdersByCampaign: {
              __typename: 'OrderConnection',
              orders: [
                order({ status: state.confirmed ? 'CONFIRMED' : 'NEW' }),
                order({ orderId: 'ORDER#c-1#auth', customerName: 'Signed In Buyer', status: null }),
              ],
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
        </Routes>
      </MockedProvider>
    </MemoryRouter>,
  );

  return { ui, state };
}

describe('OrdersPage payment confirmation', () => {
  it('offers the confirm action only on the public order still at NEW', async () => {
    const { ui } = makeHarness();
    const buttons = await screen.findAllByTestId('confirm-payment-button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0].getAttribute('aria-label')).toBe('Confirm payment for Public Buyer');
    // The authenticated row (no status) carries no lifecycle affordance.
    const authRow = screen.getByText('Signed In Buyer').closest('tr');
    expect(authRow?.querySelector('[data-testid="confirm-payment-button"]')).toBeNull();
    ui.unmount();
  });

  it('hides the confirm action once the order is CONFIRMED (no path back)', async () => {
    const { ui, state } = makeHarness({ initiallyConfirmed: true });
    await screen.findByText('Public Buyer');
    // The permission gate is a second, independent await: wait for the profile
    // read to land before asserting an affordance is absent.
    await waitFor(() => expect(state.profileCalls).toBeGreaterThan(0));
    expect(screen.queryByTestId('confirm-payment-button')).toBeNull();
    expect(screen.getByTestId('order-status-chip')).toHaveTextContent('Payment confirmed');
    ui.unmount();
  });

  it('asks for confirmation before sending the mutation, then flips the chip', async () => {
    const { ui, state } = makeHarness();
    await userEvent.click(await screen.findByTestId('confirm-payment-button'));

    // The permanent action is gated by the house confirm dialog, not window.confirm.
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Confirm payment?');
    expect(state.confirmCalls).toBe(0);

    await userEvent.click(screen.getByRole('button', { name: 'Confirm payment' }));
    await waitFor(() => expect(state.confirmCalls).toBe(1));

    // The chip flips from the refetched row, and the dialog closes.
    await waitFor(() => expect(screen.getByTestId('order-status-chip')).toHaveTextContent('Payment confirmed'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    ui.unmount();
  });

  it('sends nothing when the confirmation is cancelled', async () => {
    const { ui, state } = makeHarness();
    await userEvent.click(await screen.findByTestId('confirm-payment-button'));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(state.confirmCalls).toBe(0);
    expect(screen.getByTestId('order-status-chip')).toHaveTextContent('New');
    ui.unmount();
  });

  it('surfaces a rejected transition inside the dialog and keeps the row pending', async () => {
    const { ui, state } = makeHarness({ mutationError: 'Order is already confirmed; there is no path back from CONFIRMED' });
    await userEvent.click(await screen.findByTestId('confirm-payment-button'));
    await screen.findByRole('dialog');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm payment' }));

    expect(await screen.findByText(/no path back from CONFIRMED/)).toBeInTheDocument();
    expect(state.confirmCalls).toBe(1);
    // The failed write must not pretend the order advanced.
    await waitFor(() => expect(screen.getByTestId('order-status-chip')).toHaveTextContent('New'));
    ui.unmount();
  });

  it('offers the action to a WRITE-share collaborator, not to a reader', async () => {
    const writer = makeHarness({ isOwner: false, permissions: ['WRITE'] });
    await writer.ui.findByTestId('confirm-payment-button');
    writer.ui.unmount();

    const reader = makeHarness({ isOwner: false, permissions: ['READ'] });
    await reader.ui.findByText('Public Buyer');
    await waitFor(() => expect(reader.state.profileCalls).toBeGreaterThan(0));
    expect(reader.ui.queryByTestId('confirm-payment-button')).toBeNull();
    reader.ui.unmount();
  });
});
