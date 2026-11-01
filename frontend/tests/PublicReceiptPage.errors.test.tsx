/**
 * PublicReceiptPage error-state tests (FUNC-10b).
 *
 * A receipt link is a capability URL the buyer has no way to re-derive, and the
 * order behind it is already placed. Telling them "this link is unavailable" for
 * a network blip sends them to support over an order that exists and a link that
 * still works, so a transient failure gets its own retryable screen while only a
 * genuine NOT_FOUND reads as a dead link.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { PublicReceiptPage } from '../src/pages/PublicReceiptPage';
import { PUBLIC_UNAVAILABLE_TITLE } from '../src/components/public/PublicPageUnavailable';
import type { GqlPublicGetOrderReceiptQuery } from '../src/types/graphql-generated';
import type { ApolloLikeError } from '../src/lib/api-utils';

const { queryState } = vi.hoisted(() => ({
  queryState: {
    current: { loading: false, error: undefined as unknown, data: undefined as unknown, refetch: vi.fn() },
  },
}));

vi.mock('@apollo/client/react', () => ({
  useQuery: () => queryState.current,
}));

type ReceiptData = GqlPublicGetOrderReceiptQuery['publicGetOrderReceipt'];

const receiptFixture = {
  __typename: 'PublicOrderReceiptLookup',
  sellerName: 'Acme Troop',
  orderId: 'ORDER#c1#abc',
  orderDate: '2026-03-01T12:00:00.000Z',
  totalAmount: 20,
  paymentMethodName: 'Cash',
  status: 'PENDING' as unknown as ReceiptData['status'],
  buyerFirstName: 'Ada',
  buyerLastName: 'Lovelace',
  lineItems: [
    { __typename: 'PublicLineItem', productId: 'PROD#1', productName: 'Cookie Box', quantity: 2, pricePerUnit: 10, subtotal: 20 },
  ],
} as unknown as ReceiptData;

/** An Apollo-shaped error carrying a GraphQL error code. */
const gqlError = (code: string): ApolloLikeError =>
  ({ graphQLErrors: [{ message: 'server said so', extensions: { code } }], networkError: undefined }) as unknown as ApolloLikeError;

const renderReceiptPage = (path = '/r/c1/abc/tok-1') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/r/:campaignId/:orderSuffix/:receiptToken" element={<PublicReceiptPage />} />
        <Route path="/r/:campaignId/:orderSuffix" element={<PublicReceiptPage />} />
      </Routes>
    </MemoryRouter>,
  );

const deadLinkVisible = () => Boolean(screen.queryByText(PUBLIC_UNAVAILABLE_TITLE));

describe('PublicReceiptPage success path', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryState.current = { loading: false, error: undefined, data: undefined, refetch: vi.fn() };
  });

  it('renders the order the seller recorded', () => {
    queryState.current = {
      loading: false,
      error: undefined,
      refetch: vi.fn(),
      data: { __typename: 'Query', publicGetOrderReceipt: receiptFixture },
    };
    renderReceiptPage();
    expect(screen.getByText('Seller: Acme Troop')).toBeInTheDocument();
    expect(screen.getByText('Buyer: Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Cookie Box')).toBeInTheDocument();
    expect(screen.getByText('Total (Cash)')).toBeInTheDocument();
  });

  it('shows the loading state on the first read', () => {
    queryState.current = { loading: true, error: undefined, data: undefined, refetch: vi.fn() };
    renderReceiptPage();
    expect(screen.queryByTestId('receipt-load-error')).toBeNull();
    expect(deadLinkVisible()).toBe(false);
  });
});

describe('PublicReceiptPage error states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryState.current = { loading: false, error: undefined, data: undefined, refetch: vi.fn() };
  });

  it('offers a retry for a transport failure instead of a dead-link message', () => {
    queryState.current = {
      loading: false,
      error: { graphQLErrors: [], networkError: new Error('Network request failed') },
      data: undefined,
      refetch: vi.fn(),
    };
    renderReceiptPage();
    expect(screen.getByTestId('receipt-load-error')).toBeInTheDocument();
    expect(screen.getByTestId('receipt-retry')).toBeInTheDocument();
    expect(deadLinkVisible()).toBe(false);
  });

  it('re-reads the receipt when the buyer retries', () => {
    const refetch = vi.fn();
    queryState.current = {
      loading: false,
      error: { graphQLErrors: [], networkError: new Error('Network request failed') },
      data: undefined,
      refetch,
    };
    renderReceiptPage();
    fireEvent.click(screen.getByTestId('receipt-retry'));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('offers a retry for an unrecognized server error rather than echoing it', () => {
    queryState.current = {
      loading: false,
      error: gqlError('InternalServerError'),
      data: undefined,
      refetch: vi.fn(),
    };
    renderReceiptPage();
    expect(screen.getByTestId('receipt-load-error')).toBeInTheDocument();
    expect(screen.queryByText('server said so')).toBeNull();
  });

  it('treats a throttled read as retryable', () => {
    queryState.current = { loading: false, error: gqlError('RESOURCE_BUSY'), data: undefined, refetch: vi.fn() };
    renderReceiptPage();
    expect(screen.getByTestId('receipt-retry')).toBeInTheDocument();
  });

  it('reports the link as unavailable for a NOT_FOUND', () => {
    queryState.current = { loading: false, error: gqlError('NOT_FOUND'), data: undefined, refetch: vi.fn() };
    renderReceiptPage();
    expect(screen.getByText(PUBLIC_UNAVAILABLE_TITLE)).toBeInTheDocument();
    expect(screen.queryByTestId('receipt-load-error')).toBeNull();
  });

  it('reports the link as unavailable for the order-not-found spelling', () => {
    queryState.current = { loading: false, error: gqlError('ORDER_NOT_FOUND'), data: undefined, refetch: vi.fn() };
    renderReceiptPage();
    expect(screen.getByText(PUBLIC_UNAVAILABLE_TITLE)).toBeInTheDocument();
    expect(screen.queryByTestId('receipt-retry')).toBeNull();
  });

  it('reports the link as unavailable when the URL is missing a segment', () => {
    // A skipped query leaves no loading flag and no error at all.
    renderReceiptPage('/r/c1/abc');
    expect(screen.getByText(PUBLIC_UNAVAILABLE_TITLE)).toBeInTheDocument();
    expect(screen.queryByTestId('receipt-load-error')).toBeNull();
  });

  it('keeps showing a receipt that arrived even if a later read errored', () => {
    queryState.current = {
      loading: false,
      error: { graphQLErrors: [], networkError: new Error('blip') },
      refetch: vi.fn(),
      data: { __typename: 'Query', publicGetOrderReceipt: receiptFixture },
    };
    renderReceiptPage();
    expect(screen.getByText('Seller: Acme Troop')).toBeInTheDocument();
    expect(screen.queryByTestId('receipt-load-error')).toBeNull();
  });
});
