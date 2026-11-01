/**
 * Tests for PublicOrderSuccess.
 *
 * Covers the "What you submitted" table actually rendering the buyer's items
 * (it used to be an empty table for every order), the total row naming the
 * payment method the buyer chose, the three-way confirmation-email copy, and
 * the receipt link. The link assertion also pins the single
 * `resolveReceiptUrl` call per render: calling it more than once lets the
 * href and the visible text disagree if the guard ever stops being a pure
 * function.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  PublicOrderSuccess,
  type PublicOrderReceiptView,
  type PublicOrderSubmittedSummary,
} from '../../../src/components/public/PublicOrderSuccess';
import { resolveReceiptUrl } from '../../../src/lib/publicOrders';

vi.mock('../../../src/lib/publicOrders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../src/lib/publicOrders')>();
  return { ...actual, resolveReceiptUrl: vi.fn(actual.resolveReceiptUrl) };
});

const mockedResolve = vi.mocked(resolveReceiptUrl);

const receipt: PublicOrderReceiptView = {
  orderId: 'ORDER#c1#abc',
  receiptUrl: '/r/c1/abc/rtok',
  totalAmount: 29,
  buyerEmailProvided: true,
  confirmationEmailSent: true,
};

const summary: PublicOrderSubmittedSummary = {
  firstName: 'Ada',
  lastName: 'Lovelace',
  paymentMethod: 'Cash',
  phone: '555-123-4567',
  email: 'ada@example.com',
  lineItems: [
    { productId: 'PROD#1', productName: 'Cookie Box', quantity: 2, pricePerUnit: 12.5, subtotal: 25 },
    { productId: 'PROD#2', productName: 'Magazine', quantity: 1, pricePerUnit: 4, subtotal: 4 },
  ],
};

describe('PublicOrderSuccess', () => {
  beforeEach(() => {
    mockedResolve.mockClear();
  });

  it('renders one row per submitted item with qty, unit price, and line total', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    expect(screen.getByTestId('summary-item-PROD#1')).toBeInTheDocument();
    expect(screen.getByTestId('summary-item-PROD#2')).toBeInTheDocument();
    expect(screen.getByText('Cookie Box')).toBeInTheDocument();
    expect(screen.getByText('$12.50')).toBeInTheDocument();
    expect(screen.getByText('$25.00')).toBeInTheDocument();
    // The magazine's unit price and its line total are the same amount.
    expect(screen.getAllByText('$4.00')).toHaveLength(2);
  });

  it('shows the order total and the payment method the buyer chose', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    expect(screen.getByText('Total (Cash)')).toBeInTheDocument();
    // $29.00 total plus the two line subtotals and two unit prices.
    expect(screen.getAllByText('$29.00')).toHaveLength(1);
  });

  it('still renders the table shell when there are no items', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={{ ...summary, lineItems: [] }} />);
    expect(screen.getByText('What you submitted')).toBeInTheDocument();
    expect(screen.queryByTestId(/summary-item-/)).toBeNull();
  });

  it('shows the full order reference', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    expect(screen.getByTestId('order-reference')).toHaveTextContent('ORDER#c1#abc');
  });

  it('renders the receipt link once, resolving the url a single time per render', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    const link = screen.getByTestId('receipt-link');
    expect(link).toHaveAttribute('href', '/r/c1/abc/rtok');
    expect(link).toHaveTextContent('/r/c1/abc/rtok');
    expect(mockedResolve).toHaveBeenCalledTimes(1);
  });

  it('omits the receipt link block when the url does not resolve', () => {
    mockedResolve.mockReturnValueOnce(null);
    render(<PublicOrderSuccess receipt={{ ...receipt, receiptUrl: 'ORDER#c1#abc' }} summary={summary} />);
    expect(screen.queryByTestId('receipt-link')).toBeNull();
    expect(screen.getByTestId('order-reference')).toBeInTheDocument();
  });

  it('says no email was given when the buyer supplied none', () => {
    const noEmail: PublicOrderReceiptView = { ...receipt, buyerEmailProvided: false, confirmationEmailSent: false };
    render(<PublicOrderSuccess receipt={noEmail} summary={{ ...summary, email: undefined }} />);
    expect(screen.getByText(/no confirmation email/i)).toBeInTheDocument();
  });

  it('says the email was sent when it was', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    expect(screen.getByText(/confirmation email/i)).toBeInTheDocument();
  });

  it('says the send failed without blaming the buyer when an email was provided', () => {
    const failed: PublicOrderReceiptView = { ...receipt, confirmationEmailSent: false };
    render(<PublicOrderSuccess receipt={failed} summary={summary} />);
    expect(screen.getByText(/could not send the confirmation email/i)).toBeInTheDocument();
    expect(screen.getByText(/your order was still placed/i)).toBeInTheDocument();
  });

  it('lists the buyer, phone, and email channels the form carried', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    expect(screen.getByText('Buyer: Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Phone: 555-123-4567')).toBeInTheDocument();
    expect(screen.getByText('Email: ada@example.com')).toBeInTheDocument();
  });

  it('omits the phone and email lines when those channels are absent', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={{ ...summary, phone: undefined, email: undefined }} />);
    expect(screen.queryByText(/^Phone:/)).toBeNull();
    expect(screen.queryByText(/^Email:/)).toBeNull();
  });
});
