/**
 * Tests for the buyer receipt page.
 *
 * The receipt is reached only through the per-order token in the emailed link,
 * so the page must render the order the token names and fall back to the same
 * generic not-available copy for a tampered token — never a partial view.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { PublicReceiptPage } from '../src/pages/PublicReceiptPage';
import { PUBLIC_GET_ORDER_RECEIPT } from '../src/lib/publicOrderGraphQL';
import { PUBLIC_UNAVAILABLE_TITLE } from '../src/components/public/PublicPageUnavailable';

const receiptData = {
  __typename: 'PublicOrderReceipt',
  sellerName: 'Troop 42 Popcorn',
  orderId: 'ORDER#campaign-1#suffix-1',
  orderDate: '2026-03-04T15:00:00Z',
  lineItems: [
    { __typename: 'PublicOrderReceiptLine', productId: 'p-1', productName: 'Large bag', quantity: 2, pricePerUnit: 12.5, subtotal: 25 },
    { __typename: 'PublicOrderReceiptLine', productId: 'p-2', productName: 'Small bag', quantity: 1, pricePerUnit: 7.25, subtotal: 7.25 },
  ],
  totalAmount: 32.25,
  paymentMethodName: 'Venmo',
  status: 'NEW',
  buyerFirstName: 'Ada',
  buyerLastName: 'Lovelace',
};

const variables = { campaignId: 'campaign-1', orderSuffix: 'suffix-1', receiptToken: 'receipt-token' };

const receiptMock = (overrides: Partial<MockedResponse> = {}): MockedResponse => ({
  request: { query: PUBLIC_GET_ORDER_RECEIPT, variables },
  result: { data: { publicGetOrderReceipt: receiptData } },
  ...overrides,
});

function renderPage(mocks: MockedResponse[], path = '/r/campaign-1/suffix-1/receipt-token') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MockedProvider mocks={mocks}>
        <Routes>
          <Route path="/r/:campaignId/:orderSuffix/:receiptToken" element={<PublicReceiptPage />} />
        </Routes>
      </MockedProvider>
    </MemoryRouter>,
  );
}

describe('PublicReceiptPage', () => {
  it('renders the order the receipt token names', async () => {
    renderPage([receiptMock()]);
    expect(await screen.findByText('Seller: Troop 42 Popcorn')).toBeInTheDocument();
    expect(screen.getByText('Buyer: Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Large bag')).toBeInTheDocument();
    expect(screen.getByText('$32.25')).toBeInTheDocument();
    expect(screen.getByText('Total (Venmo)')).toBeInTheDocument();
    expect(document.body).toHaveTextContent('ORDER#campaign-1#suffix-1');
  });

  it('shows the status the seller recorded', async () => {
    renderPage([receiptMock()]);
    expect(await screen.findByTestId('receipt-status-chip')).toHaveTextContent('Awaiting payment confirmation');
  });

  it('shows a confirmed status once the seller marks payment', async () => {
    renderPage([receiptMock({ result: { data: { publicGetOrderReceipt: { ...receiptData, status: 'CONFIRMED' } } } })]);
    expect(await screen.findByTestId('receipt-status-chip')).toHaveTextContent('Payment confirmed');
  });

  it('shows the generic not-available page for a tampered token', async () => {
    renderPage([receiptMock({ error: new Error('NOT_FOUND') })]);
    expect(await screen.findByText(PUBLIC_UNAVAILABLE_TITLE)).toBeInTheDocument();
    expect(screen.queryByText('Seller: Troop 42 Popcorn')).not.toBeInTheDocument();
  });

  it('shows the not-available page when a path segment is missing', async () => {
    render(
      <MemoryRouter initialEntries={['/r/campaign-1/suffix-1']}>
        <MockedProvider mocks={[]}>
          <PublicReceiptPage />
        </MockedProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(PUBLIC_UNAVAILABLE_TITLE)).toBeInTheDocument();
  });
});
