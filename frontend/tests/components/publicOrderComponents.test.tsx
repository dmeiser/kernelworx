/**
 * Tests for the buyer-facing public order building blocks: the product picker,
 * the contact fields, the no-email choice, the success screen, the receipt
 * status chip and the generic unavailable state.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProductPicker } from '../../src/components/public/ProductPicker';
import { BuyerContactFields } from '../../src/components/public/BuyerContactFields';
import { NoEmailConfirmDialog, NO_EMAIL_WARNING } from '../../src/components/public/NoEmailConfirmDialog';
import { PublicOrderSuccess } from '../../src/components/public/PublicOrderSuccess';
import { PublicPageUnavailable } from '../../src/components/public/PublicPageUnavailable';
import { ReceiptStatusChip } from '../../src/components/public/ReceiptStatusChip';

const products = [
  { productId: 'p-1', productName: 'Large bag', price: 12.5, description: 'Half gallon' },
  { productId: 'p-2', productName: 'Small bag', price: 7.25 },
];

describe('ProductPicker', () => {
  it('lists every product with its price and quantity control', () => {
    render(<ProductPicker products={products} quantities={{ 'p-1': 2 }} onQuantityChange={vi.fn()} />);
    expect(screen.getByText('Large bag')).toBeInTheDocument();
    expect(screen.getByText('Half gallon')).toBeInTheDocument();
    expect(screen.getByText('$12.50')).toBeInTheDocument();
    expect((screen.getByLabelText('Quantity for Small bag') as HTMLInputElement).value).toBe('0');
  });

  it('reports a change in quantity', async () => {
    const onQuantityChange = vi.fn();
    render(<ProductPicker products={products} quantities={{}} onQuantityChange={onQuantityChange} />);
    await userEvent.clear(screen.getByLabelText('Quantity for Large bag'));
    await userEvent.type(screen.getByLabelText('Quantity for Large bag'), '3');
    expect(onQuantityChange).toHaveBeenCalledWith('p-1', 3);
  });

  it('shows the empty-catalog message and the line item error', () => {
    render(<ProductPicker products={[]} quantities={{}} onQuantityChange={vi.fn()} errorText="Add at least one product." />);
    expect(screen.getByText('This seller has no products listed right now.')).toBeInTheDocument();
    expect(screen.getByText('Add at least one product.')).toBeInTheDocument();
  });
});

describe('BuyerContactFields', () => {
  it('states the US-only contact rules inline', () => {
    render(
      <BuyerContactFields
        firstName=""
        lastName=""
        phone=""
        email=""
        address={{ street: '', city: '', state: '', zipCode: '' }}
        errors={{}}
        onFieldChange={vi.fn()}
        onAddressChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/10-digit US phone number/)).toBeInTheDocument();
    expect(screen.getByText('5 or 9 digits.')).toBeInTheDocument();
  });

  it('reports field changes', async () => {
    const onFieldChange = vi.fn();
    const onAddressChange = vi.fn();
    render(
      <BuyerContactFields
        firstName=""
        lastName=""
        phone=""
        email=""
        address={{ street: '', city: '', state: '', zipCode: '' }}
        errors={{}}
        onFieldChange={onFieldChange}
        onAddressChange={onAddressChange}
      />,
    );
    await userEvent.type(screen.getByLabelText(/First name/), 'Ada');
    await userEvent.type(screen.getByLabelText(/Street address/), '1 Main St');
    expect(onFieldChange).toHaveBeenCalledWith('firstName', 'A');
    expect(onAddressChange).toHaveBeenCalledWith('street', '1');
  });

  it('reports every address field change', async () => {
    const onAddressChange = vi.fn();
    render(
      <BuyerContactFields
        firstName=""
        lastName=""
        phone=""
        email=""
        address={{ street: '', city: '', state: '', zipCode: '' }}
        errors={{}}
        onFieldChange={vi.fn()}
        onAddressChange={onAddressChange}
      />,
    );
    await userEvent.type(screen.getByLabelText('City'), 'Anytown');
    await userEvent.type(screen.getByLabelText('State'), 'TX');
    await userEvent.type(screen.getByLabelText('ZIP code'), '75001');
    expect(onAddressChange).toHaveBeenCalledWith('city', 'A');
    expect(onAddressChange).toHaveBeenCalledWith('state', 'T');
    expect(onAddressChange).toHaveBeenCalledWith('zipCode', '7');
  });

  it('shows the validation messages it is given', () => {
    render(
      <BuyerContactFields
        firstName=""
        lastName=""
        phone=""
        email=""
        address={{ street: '', city: '', state: '', zipCode: '' }}
        errors={{ firstName: 'First name is required.', contact: 'Enter a phone number or a complete address.', email: 'Enter a valid email address.', lastName: 'Last name is required.' }}
        onFieldChange={vi.fn()}
        onAddressChange={vi.fn()}
      />,
    );
    expect(screen.getByText('First name is required.')).toBeInTheDocument();
    expect(screen.getByText('Enter a phone number or a complete address.')).toBeInTheDocument();
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument();
  });
});

describe('NoEmailConfirmDialog', () => {
  it('offers both a go-back path and a continue path', async () => {
    const onGoBack = vi.fn();
    const onContinue = vi.fn();
    render(<NoEmailConfirmDialog open onGoBack={onGoBack} onContinue={onContinue} />);
    expect(screen.getByText(NO_EMAIL_WARNING)).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('no-email-continue'));
    expect(onContinue).toHaveBeenCalled();
    await userEvent.click(screen.getByTestId('no-email-go-back'));
    expect(onGoBack).toHaveBeenCalled();
  });

  it('renders nothing when closed', () => {
    render(<NoEmailConfirmDialog open={false} onGoBack={vi.fn()} onContinue={vi.fn()} />);
    expect(screen.queryByTestId('no-email-continue')).not.toBeInTheDocument();
  });
});

describe('PublicOrderSuccess', () => {
  const receipt = {
    orderId: 'ORDER#c-1#s-1',
    receiptUrl: 'https://dev.kernelworx.app/r/c-1/s-1/token',
    totalAmount: 25,
    buyerEmailProvided: true,
    confirmationEmailSent: true,
  };
  const summary = {
    firstName: 'Ada',
    lastName: 'Lovelace',
    paymentMethod: 'Venmo',
    phone: '5558675309',
    email: 'ada@example.com',
    lineItems: [{ productName: 'Large bag', quantity: 2, subtotal: 25 }],
  };

  it('shows the full order reference and what was submitted', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    expect(screen.getByTestId('order-reference')).toHaveTextContent('ORDER#c-1#s-1');
    expect(screen.getByText('Large bag')).toBeInTheDocument();
    expect(screen.getByText('Buyer: Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Phone: 5558675309')).toBeInTheDocument();
  });

  it('shows the receipt link in its split-segment form', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={summary} />);
    const link = screen.getByTestId('receipt-link');
    expect(link).toHaveAttribute('href', 'https://dev.kernelworx.app/r/c-1/s-1/token');
    expect(link.getAttribute('href')).not.toContain('#');
  });

  it('does not render a receipt link that carries a raw order id', () => {
    render(<PublicOrderSuccess receipt={{ ...receipt, receiptUrl: 'https://x/r/ORDER#c-1#s-1/t' }} summary={summary} />);
    expect(screen.queryByTestId('receipt-link')).not.toBeInTheDocument();
  });

  it('says no email was sent when none was given', () => {
    render(
      <PublicOrderSuccess
        receipt={{ ...receipt, buyerEmailProvided: false, confirmationEmailSent: false, receiptUrl: null }}
        summary={{ ...summary, email: undefined }}
      />,
    );
    expect(screen.getByText('No confirmation email was sent, because no email address was given.')).toBeInTheDocument();
    expect(screen.queryByTestId('receipt-link')).not.toBeInTheDocument();
  });

  it('shows the receipt link for a no-email buyer when the server composed one', () => {
    render(
      <PublicOrderSuccess
        receipt={{ ...receipt, buyerEmailProvided: false, confirmationEmailSent: false }}
        summary={{ ...summary, email: undefined }}
      />,
    );
    expect(screen.getByText('No confirmation email was sent, because no email address was given.')).toBeInTheDocument();
    expect(screen.getByTestId('receipt-link')).toHaveAttribute('href', 'https://dev.kernelworx.app/r/c-1/s-1/token');
  });

  it('distinguishes a failed send from no email given', () => {
    render(<PublicOrderSuccess receipt={{ ...receipt, confirmationEmailSent: false }} summary={summary} />);
    expect(screen.getByText(/could not send the confirmation email/i)).toBeInTheDocument();
  });

  it('says the email was sent without naming an address when none was captured', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={{ ...summary, email: undefined }} />);
    expect(screen.getByText('A confirmation email was sent.')).toBeInTheDocument();
  });
  it('omits the phone line when the buyer gave none', () => {
    render(<PublicOrderSuccess receipt={receipt} summary={{ ...summary, phone: '' }} />);
    expect(screen.queryByText(/^Phone:/)).not.toBeInTheDocument();
    expect(screen.getByText(/Email:/)).toBeInTheDocument();
  });

  it('omits the email line when the buyer gave none', () => {
    render(<PublicOrderSuccess receipt={{ ...receipt, buyerEmailProvided: false, confirmationEmailSent: false }} summary={{ ...summary, email: '' }} />);
    expect(screen.queryByText(/^Email:/)).not.toBeInTheDocument();
  });
});

describe('PublicPageUnavailable', () => {
  it('gives the generic not-available copy without leaking seller data', () => {
    render(<PublicPageUnavailable />);
    expect(screen.getByText('This order link is not available.')).toBeInTheDocument();
    expect(screen.getByText(/ask the seller for a new link/i)).toBeInTheDocument();
  });
});

describe('ReceiptStatusChip', () => {
  it('labels a NEW order as awaiting payment confirmation', () => {
    render(<ReceiptStatusChip status="NEW" />);
    expect(screen.getByTestId('receipt-status-chip')).toHaveTextContent('Awaiting payment confirmation');
  });

  it('labels a CONFIRMED order as payment confirmed', () => {
    render(<ReceiptStatusChip status="CONFIRMED" />);
    expect(screen.getByTestId('receipt-status-chip')).toHaveTextContent('Payment confirmed');
  });

  it('falls back to the raw value for a status the labels do not cover', () => {
    render(<ReceiptStatusChip status={'FUTURE' as never} />);
    expect(screen.getByTestId('receipt-status-chip')).toHaveTextContent('FUTURE');
  });
});
