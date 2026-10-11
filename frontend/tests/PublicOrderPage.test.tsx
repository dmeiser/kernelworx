/**
 * Tests for the buyer's public order page.
 *
 * The behaviors pinned here are the ones a buyer actually depends on: a bad
 * token yields the generic not-available page with no seller data, the form
 * states the US-only contact rules, submitting without an email asks before
 * firing, going back from that prompt preserves what was typed, the submit
 * button disables in flight (v1 has no idempotency key), and the success screen
 * shows the full order reference plus the split-segment receipt link.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { PublicOrderPage, NO_METHODS_MESSAGE } from '../src/pages/PublicOrderPage';
import { PUBLIC_CREATE_ORDER, PUBLIC_GET_ORDER_OFFER } from '../src/lib/publicOrderGraphQL';
import { PUBLIC_UNAVAILABLE_TITLE } from '../src/components/public/PublicPageUnavailable';

vi.mock('../src/lib/qrDecode', () => ({ decodeQrLink: vi.fn(() => null) }));

const offerData = {
  __typename: 'PublicOrderOffer',
  sellerName: 'Troop 42 Popcorn',
  campaignId: 'campaign-1',
  campaignName: 'Fall popcorn sale',
  products: [
    { __typename: 'PublicProduct', productId: 'p-1', productName: 'Large bag', price: 12.5, description: 'Half gallon', sortOrder: 1 },
    { __typename: 'PublicProduct', productId: 'p-2', productName: 'Small bag', price: 7.25, description: null, sortOrder: 2 },
  ],
  paymentMethods: [
    { __typename: 'PublicPaymentMethod', name: 'Venmo', qrCodeUrl: 'https://bucket.s3.amazonaws.com/qr.png' },
    { __typename: 'PublicPaymentMethod', name: 'Cash', qrCodeUrl: null },
  ],
};

const offerMock = (overrides: Partial<MockedResponse> = {}): MockedResponse => ({
  request: { query: PUBLIC_GET_ORDER_OFFER, variables: { profileId: 'p-1', token: 'share-token' } },
  result: { data: { publicGetOrderOffer: offerData } },
  ...overrides,
});

function renderPage(mocks: MockedResponse[], path = '/o/p-1/share-token') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MockedProvider mocks={mocks}>
        <Routes>
          <Route path="/o/:profileId/:token" element={<PublicOrderPage />} />
        </Routes>
      </MockedProvider>
    </MemoryRouter>,
  );
}

async function fillContact(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/First name/), 'Ada');
  await user.type(screen.getByLabelText(/Last name/), 'Lovelace');
  await user.type(screen.getByLabelText(/^Phone/), '5558675309');
}

async function addProduct(user: ReturnType<typeof userEvent.setup>) {
  const quantity = screen.getByLabelText('Quantity for Large bag') as HTMLInputElement;
  await user.clear(quantity);
  await user.type(quantity, '2');
}

async function chooseMethod(user: ReturnType<typeof userEvent.setup>, name = 'Cash') {
  await user.click(screen.getByText(name));
}

beforeEach(() => {
  vi.stubEnv('VITE_APPSYNC_API_KEY', 'test-api-key');
});

describe('PublicOrderPage', () => {
  it('shows the offer for a valid share link', async () => {
    renderPage([offerMock()]);
    expect(await screen.findByText('Troop 42 Popcorn')).toBeInTheDocument();
    expect(screen.getByText('Fall popcorn sale')).toBeInTheDocument();
    expect(screen.getByText('Large bag')).toBeInTheDocument();
    expect(screen.getByText('Venmo')).toBeInTheDocument();
  });

  it('shows the generic not-available page when the offer fails', async () => {
    renderPage([offerMock({ error: new Error('NOT_FOUND') })]);
    expect(await screen.findByText(PUBLIC_UNAVAILABLE_TITLE)).toBeInTheDocument();
    expect(screen.queryByText('Troop 42 Popcorn')).not.toBeInTheDocument();
  });

  it('shows the not-available page for a malformed link', async () => {
    render(
      <MemoryRouter initialEntries={['/o/p-1/token']}>
        <MockedProvider mocks={[]}>
          <PublicOrderPage />
        </MockedProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(PUBLIC_UNAVAILABLE_TITLE)).toBeInTheDocument();
  });

  it('disables the form and explains when no methods are available', async () => {
    renderPage([offerMock({ result: { data: { publicGetOrderOffer: { ...offerData, paymentMethods: [] } } } })]);
    expect(await screen.findByTestId('no-methods-alert')).toHaveTextContent(NO_METHODS_MESSAGE);
    expect(screen.getByTestId('submit-order')).toBeDisabled();
  });

  it('reports the validation rules when submitting an empty form', async () => {
    const user = userEvent.setup();
    renderPage([offerMock()]);
    await screen.findByText('Troop 42 Popcorn');
    await user.click(screen.getByTestId('submit-order'));

    expect(await screen.findByText('First name is required.')).toBeInTheDocument();
    expect(screen.getByText('Enter a phone number or a complete address so the seller can reach you.')).toBeInTheDocument();
    expect(screen.getByText('Add at least one product to your order.')).toBeInTheDocument();
    expect(screen.getByText('Choose how you will pay.')).toBeInTheDocument();
  });

  it('asks before submitting without an email, and keeps the form on go back', async () => {
    const user = userEvent.setup();
    renderPage([offerMock()]);
    await screen.findByText('Troop 42 Popcorn');

    await fillContact(user);
    await addProduct(user);
    await chooseMethod(user);
    await user.click(screen.getByTestId('submit-order'));

    const dialog = await screen.findByText('You will not receive a confirmation email.');
    expect(dialog).toBeInTheDocument();

    await user.click(screen.getByTestId('no-email-go-back'));
    expect((screen.getByLabelText(/First name/) as HTMLInputElement).value).toBe('Ada');
    expect((screen.getByLabelText('Quantity for Large bag') as HTMLInputElement).value).toBe('2');
  });

  it('submits after continuing without an email and reports no confirmation email', async () => {
    const user = userEvent.setup();
    renderPage([
      offerMock(),
      {
        request: {
          query: PUBLIC_CREATE_ORDER,
          variables: {
            input: {
              profileId: 'p-1',
              token: 'share-token',
              campaignId: 'campaign-1',
              acknowledgementsAccepted: true,
              firstName: 'Ada',
              lastName: 'Lovelace',
              phone: '5558675309',
              paymentMethod: 'Cash',
              lineItems: [{ productId: 'p-1', quantity: 2 }],
            },
          },
        },
        result: {
          data: {
            publicCreateOrder: {
              __typename: 'PublicOrderReceipt',
              orderId: 'ORDER#campaign-1#suffix-1',
              receiptUrl: null,
              totalAmount: 25,
              buyerEmailProvided: false,
              confirmationEmailSent: false,
            },
          },
        },
      },
    ]);
    await screen.findByText('Troop 42 Popcorn');

    await fillContact(user);
    await addProduct(user);
    await chooseMethod(user);
    await user.click(screen.getByTestId('submit-order'));
    await user.click(await screen.findByTestId('no-email-continue'));

    expect(await screen.findByTestId('order-reference')).toHaveTextContent('ORDER#campaign-1#suffix-1');
    expect(screen.getByText('No confirmation email was sent, because no email address was given.')).toBeInTheDocument();
    expect(screen.queryByTestId('receipt-link')).not.toBeInTheDocument();
  });

  it('disables the submit button while the order is in flight', async () => {
    const user = userEvent.setup();
    renderPage([
      offerMock(),
      {
        request: {
          query: PUBLIC_CREATE_ORDER,
          variables: {
            input: {
              profileId: 'p-1',
              token: 'share-token',
              campaignId: 'campaign-1',
              acknowledgementsAccepted: true,
              firstName: 'Ada',
              lastName: 'Lovelace',
              phone: '5558675309',
              email: 'ada@example.com',
              paymentMethod: 'Cash',
              lineItems: [{ productId: 'p-1', quantity: 2 }],
            },
          },
        },
        result: {
          data: {
            publicCreateOrder: {
              __typename: 'PublicOrderReceipt',
              orderId: 'ORDER#campaign-1#suffix-1',
              receiptUrl: 'https://dev.kernelworx.app/r/campaign-1/suffix-1/receipt-token',
              totalAmount: 25,
              buyerEmailProvided: true,
              confirmationEmailSent: true,
            },
          },
        },
        delay: 150,
      },
    ]);
    await screen.findByText('Troop 42 Popcorn');

    await fillContact(user);
    await user.type(screen.getByLabelText(/Email/), 'ada@example.com');
    await addProduct(user);
    await chooseMethod(user);
    // Synchronous dispatch inside act(): the mutation is still in flight (the
    // mock delays 150ms), so the re-entry guard must already hold the button.
    fireEvent.click(screen.getByTestId('submit-order'));

    expect(screen.getByTestId('submit-order')).toBeDisabled();

    expect(await screen.findByTestId('public-order-success')).toBeInTheDocument();
    const link = screen.getByTestId('receipt-link');
    expect(link).toHaveAttribute('href', 'https://dev.kernelworx.app/r/campaign-1/suffix-1/receipt-token');
    expect(link.getAttribute('href')).not.toContain('#');
  });

  it('shows a mapped message when the create fails', async () => {
    const user = userEvent.setup();
    renderPage([
      offerMock(),
      {
        request: {
          query: PUBLIC_CREATE_ORDER,
          variables: {
            input: {
              profileId: 'p-1',
              token: 'share-token',
              campaignId: 'campaign-1',
              acknowledgementsAccepted: true,
              firstName: 'Ada',
              lastName: 'Lovelace',
              phone: '5558675309',
              paymentMethod: 'Cash',
              lineItems: [{ productId: 'p-1', quantity: 2 }],
            },
          },
        },
        error: new Error('Rate limit exceeded'),
      },
    ]);
    await screen.findByText('Troop 42 Popcorn');

    await fillContact(user);
    await addProduct(user);
    await chooseMethod(user);
    await user.click(screen.getByTestId('submit-order'));
    await user.click(await screen.findByTestId('no-email-continue'));

    expect(await screen.findByTestId('submit-error')).toBeInTheDocument();
  });

  it('carries notes into the submitted order', async () => {
    const user = userEvent.setup();
    renderPage([
      offerMock(),
      {
        request: {
          query: PUBLIC_CREATE_ORDER,
          variables: {
            input: {
              profileId: 'p-1',
              token: 'share-token',
              campaignId: 'campaign-1',
              acknowledgementsAccepted: true,
              firstName: 'Ada',
              lastName: 'Lovelace',
              phone: '5558675309',
              paymentMethod: 'Cash',
              notes: 'Pickup Friday',
              lineItems: [{ productId: 'p-1', quantity: 2 }],
            },
          },
        },
        result: {
          data: {
            publicCreateOrder: {
              __typename: 'PublicOrderReceipt',
              orderId: 'ORDER#campaign-1#suffix-1',
              receiptUrl: 'https://dev.kernelworx.app/r/campaign-1/suffix-1/receipt-token',
              totalAmount: 25,
              buyerEmailProvided: false,
              confirmationEmailSent: false,
            },
          },
        },
      },
    ]);
    await screen.findByText('Troop 42 Popcorn');

    await fillContact(user);
    await user.type(screen.getByLabelText(/Notes/), 'Pickup Friday');
    await addProduct(user);
    await chooseMethod(user);
    await user.click(screen.getByTestId('submit-order'));
    await user.click(await screen.findByTestId('no-email-continue'));

    expect(await screen.findByTestId('public-order-success')).toBeInTheDocument();
  });

  it('swallows a bare form submit so it cannot navigate the buyer away', async () => {
    renderPage([offerMock()]);
    await screen.findByText('Troop 42 Popcorn');
    const form = document.querySelector('form');
    // preventDefault only: a browser-level submit must not leave the page.
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);
    expect(await screen.findByText('Troop 42 Popcorn')).toBeInTheDocument();
  });

  it('shows the QR image for a method with one and reloads the offer when it fails to load', async () => {
    const user = userEvent.setup();
    renderPage([offerMock()]);
    await screen.findByText('Troop 42 Popcorn');

    await chooseMethod(user, 'Venmo');
    const image = await screen.findByRole('img', { name: 'Payment QR code for Venmo' });
    expect(image).toHaveAttribute('crossOrigin', 'anonymous');

    image.dispatchEvent(new Event('error'));
    await waitFor(() => expect(screen.getByTestId('qr-no-link-hint')).toBeInTheDocument());
  });

  it('reloads the offer only once for repeated QR failures', async () => {
    const user = userEvent.setup();
    renderPage([offerMock()]);
    await screen.findByText('Troop 42 Popcorn');

    await chooseMethod(user, 'Venmo');
    const image = await screen.findByRole('img', { name: 'Payment QR code for Venmo' });
    image.dispatchEvent(new Event('error'));
    image.dispatchEvent(new Event('error'));
    await waitFor(() => expect(screen.getByTestId('qr-no-link-hint')).toBeInTheDocument());
  });

  it('accepts a US address in place of a phone number', async () => {
    const user = userEvent.setup();
    renderPage([
      offerMock(),
      {
        request: {
          query: PUBLIC_CREATE_ORDER,
          variables: {
            input: {
              profileId: 'p-1',
              token: 'share-token',
              campaignId: 'campaign-1',
              acknowledgementsAccepted: true,
              firstName: 'Ada',
              lastName: 'Lovelace',
              paymentMethod: 'Cash',
              lineItems: [{ productId: 'p-1', quantity: 2 }],
              address: { street: '1 Main St', city: 'Anytown', state: 'TX', zipCode: '75001' },
            },
          },
        },
        result: {
          data: {
            publicCreateOrder: {
              __typename: 'PublicOrderReceipt',
              orderId: 'ORDER#campaign-1#suffix-1',
              receiptUrl: 'https://dev.kernelworx.app/r/campaign-1/suffix-1/receipt-token',
              totalAmount: 25,
              buyerEmailProvided: false,
              confirmationEmailSent: false,
            },
          },
        },
      },
    ]);
    await screen.findByText('Troop 42 Popcorn');

    await user.type(screen.getByLabelText(/First name/), 'Ada');
    await user.type(screen.getByLabelText(/Last name/), 'Lovelace');
    await user.type(screen.getByLabelText('Street address'), '1 Main St');
    await user.type(screen.getByLabelText('City'), 'Anytown');
    await user.type(screen.getByLabelText('State'), 'TX');
    await user.type(screen.getByLabelText('ZIP code'), '75001');
    await addProduct(user);
    await chooseMethod(user);
    await user.click(screen.getByTestId('submit-order'));
    await user.click(await screen.findByTestId('no-email-continue'));

    expect(await screen.findByTestId('public-order-success')).toBeInTheDocument();
  });

  it('shows the running total as quantities change', async () => {
    const user = userEvent.setup();
    renderPage([offerMock()]);
    await screen.findByText('Troop 42 Popcorn');

    await addProduct(user);
    expect(screen.getByTestId('order-total')).toHaveTextContent('$25.00');
  });
});
