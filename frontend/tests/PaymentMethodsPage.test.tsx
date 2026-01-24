/**
 * Tests for PaymentMethodsPage component
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { BrowserRouter } from 'react-router-dom';
import { PaymentMethodsPage } from '../src/pages/PaymentMethodsPage';
import { GET_MY_PAYMENT_METHODS } from '../src/lib/graphql';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock child components to simplify testing
vi.mock('../src/components/PaymentMethodCard', () => ({
  PaymentMethodCard: ({ method }: { method: { name: string } }) => (
    <div data-testid={`card-${method.name}`}>{method.name}</div>
  ),
}));

vi.mock('../src/components/CreatePaymentMethodDialog', () => ({
  CreatePaymentMethodDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Create Payment Method</div> : null,
}));

vi.mock('../src/components/EditPaymentMethodDialog', () => ({
  EditPaymentMethodDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Edit Payment Method</div> : null,
}));

vi.mock('../src/components/DeletePaymentMethodDialog', () => ({
  DeletePaymentMethodDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Delete Payment Method</div> : null,
}));

vi.mock('../src/components/QRUploadDialog', () => ({
  QRUploadDialog: ({ open }: { open: boolean }) => (open ? <div role="dialog">QR Upload</div> : null),
}));

const successMock = {
  request: { query: GET_MY_PAYMENT_METHODS },
  result: {
    data: {
      myPaymentMethods: [
        { __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' },
        { __typename: 'PaymentMethod', name: 'PayPal', qrCodeUrl: null },
        { __typename: 'PaymentMethod', name: 'Zelle', qrCodeUrl: null },
      ],
    },
  },
};

const emptyMock = {
  request: { query: GET_MY_PAYMENT_METHODS },
  result: {
    data: {
      myPaymentMethods: [],
    },
  },
};

const errorMock = {
  request: { query: GET_MY_PAYMENT_METHODS },
  error: new Error('Network error'),
};

describe('PaymentMethodsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders page title after loading', async () => {
    render(
      <MockedProvider mocks={[successMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Payment Methods' })).toBeInTheDocument();
    });
  });

  test('renders loading state initially', () => {
    render(
      <MockedProvider mocks={[successMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  test('renders payment methods after loading', async () => {
    render(
      <MockedProvider mocks={[successMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('PayPal')).toBeInTheDocument();
    });
    expect(screen.getByText('Venmo')).toBeInTheDocument();
    expect(screen.getByText('Zelle')).toBeInTheDocument();
  });

  test('renders add button', async () => {
    render(
      <MockedProvider mocks={[successMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add payment method/i })).toBeInTheDocument();
    });
  });

  test('renders info box about Cash and Check', async () => {
    render(
      <MockedProvider mocks={[successMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Cash and Check are always available/i)).toBeInTheDocument();
    });
  });

  test('renders empty state when no payment methods', async () => {
    render(
      <MockedProvider mocks={[emptyMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/No payment methods yet/i)).toBeInTheDocument();
    });
  });

  test('navigates back to settings when back button clicked', async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider mocks={[successMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText('Back to settings')).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText('Back to settings'));
    expect(mockNavigate).toHaveBeenCalledWith('/settings');
  });

  test('opens create dialog when add button clicked', async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider mocks={[successMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add payment method/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /add payment method/i }));

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByText('Create Payment Method')).toBeInTheDocument();
    });
  });

  test('displays error message when query fails', async () => {
    render(
      <MockedProvider mocks={[errorMock]} addTypename={false}>
        <BrowserRouter>
          <PaymentMethodsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Failed to load payment methods/i)).toBeInTheDocument();
    });
  });
});
