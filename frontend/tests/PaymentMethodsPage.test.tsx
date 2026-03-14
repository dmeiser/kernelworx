/**
 * Tests for PaymentMethodsPage component
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { BrowserRouter } from 'react-router-dom';
import { PaymentMethodsPage } from '../src/pages/PaymentMethodsPage';
import {
  GET_MY_PAYMENT_METHODS,
  CREATE_PAYMENT_METHOD,
  UPDATE_PAYMENT_METHOD,
  DELETE_PAYMENT_METHOD,
  REQUEST_PAYMENT_METHOD_QR_UPLOAD,
  CONFIRM_PAYMENT_METHOD_QR_UPLOAD,
  DELETE_PAYMENT_METHOD_QR_CODE,
} from '../src/lib/graphql';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock child components with interactive callbacks
vi.mock('../src/components/PaymentMethodCard', () => ({
  PaymentMethodCard: ({
    method,
    onEdit,
    onDelete,
    onUploadQR,
    onDeleteQR,
  }: {
    method: { name: string; qrCodeUrl: string | null };
    onEdit: () => void;
    onDelete: () => void;
    onUploadQR: () => void;
    onDeleteQR: () => void;
  }) => (
    <div data-testid={`card-${method.name}`}>
      {method.name}
      <button data-testid={`edit-${method.name}`} onClick={onEdit}>
        Edit
      </button>
      <button data-testid={`delete-${method.name}`} onClick={onDelete}>
        Delete
      </button>
      <button data-testid={`upload-qr-${method.name}`} onClick={onUploadQR}>
        Upload QR
      </button>
      <button data-testid={`delete-qr-${method.name}`} onClick={onDeleteQR}>
        Delete QR
      </button>
    </div>
  ),
}));

vi.mock('../src/components/CreatePaymentMethodDialog', () => ({
  CreatePaymentMethodDialog: ({
    open,
    onCreate,
    onClose,
  }: {
    open: boolean;
    onCreate: (name: string) => Promise<void>;
    onClose: () => void;
  }) =>
    open ? (
      <div role="dialog">
        Create Payment Method
        <button
          data-testid="mock-create-submit"
          onClick={() => onCreate('NewMethod')}
        >
          Create
        </button>
        <button data-testid="mock-create-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../src/components/EditPaymentMethodDialog', () => ({
  EditPaymentMethodDialog: ({
    open,
    onClose,
    onUpdate,
    currentName,
  }: {
    open: boolean;
    onClose: () => void;
    onUpdate: (oldName: string, newName: string) => Promise<void>;
    currentName: string;
  }) =>
    open ? (
      <div role="dialog">
        Edit Payment Method: {currentName}
        <button
          data-testid="mock-edit-submit"
          onClick={() => onUpdate(currentName, 'RenamedMethod')}
        >
          Update
        </button>
        <button data-testid="mock-edit-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../src/components/DeletePaymentMethodDialog', () => ({
  DeletePaymentMethodDialog: ({
    open,
    onClose,
    onDelete,
    methodName,
  }: {
    open: boolean;
    onClose: () => void;
    onDelete: () => Promise<void>;
    methodName: string;
  }) =>
    open ? (
      <div role="dialog">
        Delete: {methodName}
        <button data-testid="mock-delete-confirm" onClick={onDelete}>
          Confirm Delete
        </button>
        <button data-testid="mock-delete-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../src/components/QRUploadDialog', () => ({
  QRUploadDialog: ({
    open,
    onClose,
    onUpload,
    methodName,
    uploadError,
  }: {
    open: boolean;
    onClose: () => void;
    onUpload: (file: File) => Promise<void>;
    methodName: string;
    uploadError: string | null;
  }) =>
    open ? (
      <div role="dialog">
        QR Upload: {methodName}
        {uploadError && <span data-testid="qr-upload-error">{uploadError}</span>}
        <button
          data-testid="mock-qr-upload"
          onClick={() => onUpload(new File(['test'], 'qr.png', { type: 'image/png' }))}
        >
          Upload
        </button>
        <button data-testid="mock-qr-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

const paymentMethods = [
  { __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' },
  { __typename: 'PaymentMethod', name: 'PayPal', qrCodeUrl: null },
  { __typename: 'PaymentMethod', name: 'Zelle', qrCodeUrl: null },
];

const successMock: MockedResponse = {
  request: { query: GET_MY_PAYMENT_METHODS },
  result: {
    data: { myPaymentMethods: paymentMethods },
  },
};

const emptyMock: MockedResponse = {
  request: { query: GET_MY_PAYMENT_METHODS },
  result: {
    data: { myPaymentMethods: [] },
  },
};

const errorMock: MockedResponse = {
  request: { query: GET_MY_PAYMENT_METHODS },
  error: new Error('Network error'),
};

function renderPage(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <BrowserRouter>
        <PaymentMethodsPage />
      </BrowserRouter>
    </MockedProvider>,
  );
}

describe('PaymentMethodsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders page title after loading', async () => {
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Payment Methods' })).toBeInTheDocument();
    });
  });

  test('renders loading state initially', () => {
    renderPage([successMock]);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  test('renders payment methods after loading', async () => {
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByText('PayPal')).toBeInTheDocument();
    });
    expect(screen.getByText('Venmo')).toBeInTheDocument();
    expect(screen.getByText('Zelle')).toBeInTheDocument();
  });

  test('renders add button', async () => {
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add payment method/i })).toBeInTheDocument();
    });
  });

  test('renders info box about Cash and Check', async () => {
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByText(/Cash and Check are always available/i)).toBeInTheDocument();
    });
  });

  test('renders empty state when no payment methods', async () => {
    renderPage([emptyMock]);
    await waitFor(() => {
      expect(screen.getByText(/No payment methods yet/i)).toBeInTheDocument();
    });
  });

  test('navigates back to settings when back button clicked', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByLabelText('Back to settings')).toBeInTheDocument();
    });
    await user.click(screen.getByLabelText('Back to settings'));
    expect(mockNavigate).toHaveBeenCalledWith('/settings');
  });

  test('opens create dialog when add button clicked', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
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
    renderPage([errorMock]);
    await waitFor(() => {
      expect(screen.getByText(/Failed to load payment methods/i)).toBeInTheDocument();
    });
  });

  test('opens edit dialog when card edit button clicked', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-Venmo')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('edit-Venmo'));
    await waitFor(() => {
      expect(screen.getByText(/Edit Payment Method: Venmo/)).toBeInTheDocument();
    });
  });

  test('opens delete dialog when card delete button clicked', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-Venmo')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('delete-Venmo'));
    await waitFor(() => {
      expect(screen.getByText(/Delete: Venmo/)).toBeInTheDocument();
    });
  });

  test('opens QR upload dialog when card upload button clicked', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-PayPal')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('upload-qr-PayPal'));
    await waitFor(() => {
      expect(screen.getByText(/QR Upload: PayPal/)).toBeInTheDocument();
    });
  });

  test('creates payment method via dialog', async () => {
    const user = userEvent.setup();
    const createMock: MockedResponse = {
      request: {
        query: CREATE_PAYMENT_METHOD,
        variables: { name: 'NewMethod' },
      },
      result: {
        data: {
          createPaymentMethod: { __typename: 'PaymentMethod', name: 'NewMethod', qrCodeUrl: null },
        },
      },
    };
    const refetchMock: MockedResponse = {
      request: { query: GET_MY_PAYMENT_METHODS },
      result: { data: { myPaymentMethods: [...paymentMethods, { __typename: 'PaymentMethod', name: 'NewMethod', qrCodeUrl: null }] } },
    };

    renderPage([successMock, createMock, refetchMock]);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add payment method/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /add payment method/i }));
    await user.click(screen.getByTestId('mock-create-submit'));
    await waitFor(() => {
      expect(screen.getByText(/created successfully/i)).toBeInTheDocument();
    });
  });

  test('updates payment method via dialog', async () => {
    const user = userEvent.setup();
    const updateMock: MockedResponse = {
      request: {
        query: UPDATE_PAYMENT_METHOD,
        variables: { currentName: 'Venmo', newName: 'RenamedMethod' },
      },
      result: {
        data: {
          updatePaymentMethod: { __typename: 'PaymentMethod', name: 'RenamedMethod', qrCodeUrl: null },
        },
      },
    };
    const refetchMock: MockedResponse = {
      request: { query: GET_MY_PAYMENT_METHODS },
      result: { data: { myPaymentMethods: paymentMethods } },
    };

    renderPage([successMock, updateMock, refetchMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-Venmo')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('edit-Venmo'));
    await user.click(screen.getByTestId('mock-edit-submit'));
    await waitFor(() => {
      expect(screen.getByText(/updated successfully/i)).toBeInTheDocument();
    });
  });

  test('deletes payment method via dialog', async () => {
    const user = userEvent.setup();
    const deleteMock: MockedResponse = {
      request: {
        query: DELETE_PAYMENT_METHOD,
        variables: { name: 'Zelle' },
      },
      result: {
        data: { deletePaymentMethod: true },
      },
    };
    const refetchMock: MockedResponse = {
      request: { query: GET_MY_PAYMENT_METHODS },
      result: { data: { myPaymentMethods: paymentMethods.filter((m) => m.name !== 'Zelle') } },
    };

    renderPage([successMock, deleteMock, refetchMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-Zelle')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('delete-Zelle'));
    await user.click(screen.getByTestId('mock-delete-confirm'));
    await waitFor(() => {
      expect(screen.getByText(/deleted successfully/i)).toBeInTheDocument();
    });
  });

  test('deletes QR code from card', async () => {
    const user = userEvent.setup();
    const deleteQRMock: MockedResponse = {
      request: {
        query: DELETE_PAYMENT_METHOD_QR_CODE,
        variables: { paymentMethodName: 'Venmo' },
      },
      result: { data: { deletePaymentMethodQRCode: true } },
    };
    const refetchMock: MockedResponse = {
      request: { query: GET_MY_PAYMENT_METHODS },
      result: { data: { myPaymentMethods: paymentMethods } },
    };

    renderPage([successMock, deleteQRMock, refetchMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-Venmo')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('delete-qr-Venmo'));
    await waitFor(() => {
      expect(screen.getByText(/QR code deleted successfully/i)).toBeInTheDocument();
    });
  });

  test('uploads QR code via dialog', async () => {
    const user = userEvent.setup();
    // Mock fetch for S3 upload
    const mockFetch = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', mockFetch);

    const requestUploadMock: MockedResponse = {
      request: {
        query: REQUEST_PAYMENT_METHOD_QR_UPLOAD,
        variables: { paymentMethodName: 'PayPal' },
      },
      result: {
        data: {
          requestPaymentMethodQRCodeUpload: {
            uploadUrl: 'https://s3.example.com/upload',
            fields: JSON.stringify({ key: 'test-key', Policy: 'test-policy' }),
            s3Key: 'qr-codes/paypal.png',
          },
        },
      },
    };
    const confirmUploadMock: MockedResponse = {
      request: {
        query: CONFIRM_PAYMENT_METHOD_QR_UPLOAD,
        variables: { paymentMethodName: 'PayPal', s3Key: 'qr-codes/paypal.png' },
      },
      result: {
        data: {
          confirmPaymentMethodQRCodeUpload: { __typename: 'PaymentMethod', name: 'PayPal', qrCodeUrl: 'https://example.com/paypal-qr.png' },
        },
      },
    };
    const refetchMock: MockedResponse = {
      request: { query: GET_MY_PAYMENT_METHODS },
      result: { data: { myPaymentMethods: paymentMethods } },
    };

    renderPage([successMock, requestUploadMock, confirmUploadMock, refetchMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-PayPal')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('upload-qr-PayPal'));
    await user.click(screen.getByTestId('mock-qr-upload'));
    await waitFor(() => {
      expect(screen.getByText(/QR code uploaded successfully/i)).toBeInTheDocument();
    });

    vi.unstubAllGlobals();
  });

  test('closes edit dialog', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-Venmo')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('edit-Venmo'));
    expect(screen.getByText(/Edit Payment Method/)).toBeInTheDocument();
    await user.click(screen.getByTestId('mock-edit-close'));
    expect(screen.queryByText(/Edit Payment Method: Venmo/)).not.toBeInTheDocument();
  });

  test('closes delete dialog', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-Venmo')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('delete-Venmo'));
    expect(screen.getByText(/Delete: Venmo/)).toBeInTheDocument();
    await user.click(screen.getByTestId('mock-delete-close'));
    expect(screen.queryByText(/Delete: Venmo/)).not.toBeInTheDocument();
  });

  test('closes QR upload dialog', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByTestId('card-PayPal')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('upload-qr-PayPal'));
    expect(screen.getByText(/QR Upload: PayPal/)).toBeInTheDocument();
    await user.click(screen.getByTestId('mock-qr-close'));
    expect(screen.queryByText(/QR Upload: PayPal/)).not.toBeInTheDocument();
  });

  test('closes create dialog', async () => {
    const user = userEvent.setup();
    renderPage([successMock]);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add payment method/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /add payment method/i }));
    expect(screen.getByText('Create Payment Method')).toBeInTheDocument();
    await user.click(screen.getByTestId('mock-create-close'));
    expect(screen.queryByText('Create Payment Method')).not.toBeInTheDocument();
  });
});
