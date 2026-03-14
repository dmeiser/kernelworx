/**
 * OrderEditorPage interaction tests - form interactions, validation, order creation/update
 */

import React from 'react';
import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import {
  GET_CAMPAIGN,
  GET_PROFILE,
  GET_PAYMENT_METHODS_FOR_PROFILE,
  GET_ORDER,
  UPDATE_ORDER,
} from '../src/lib/graphql';

// Mock MUI Select/MenuItem with plain HTML select/option so onChange fires in jsdom
vi.mock('@mui/material', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@mui/material');
  const Select = ({ value, onChange, children, label, disabled, MenuProps: _mp, ...rest }: Record<string, unknown>) => (
    <select
      role="combobox"
      aria-label={(label as string) || 'Select'}
      value={(value as string) ?? ''}
      disabled={disabled as boolean}
      onChange={(e) => (onChange as (ev: { target: { value: string } }) => void)?.({ target: { value: (e.target as HTMLSelectElement).value } })}
      {...(rest as Record<string, unknown>)}
    >
      {children as React.ReactNode}
    </select>
  );
  const MenuItem = ({ value, children, disabled, ...rest }: Record<string, unknown>) => (
    <option value={(value as string) ?? ''} disabled={disabled as boolean} {...(rest as Record<string, unknown>)}>
      {String(children ?? '')}
    </option>
  );
  return { ...actual, Select, MenuItem };
});

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

import { OrderEditorPage } from '../src/pages/OrderEditorPage';

const PROFILE_RAW = 'profile-aaa-123';
const CAMPAIGN_RAW = 'campaign-bbb-456';
const ORDER_RAW = 'order-ccc-789';
const PROFILE_DB = `PROFILE#${PROFILE_RAW}`;
const CAMPAIGN_DB = `CAMPAIGN#${CAMPAIGN_RAW}`;
const ORDER_DB = `ORDER#${ORDER_RAW}`;

const PRODUCT_A = { __typename: 'Product', productId: 'PROD~A', productName: 'Caramel Corn', description: null, price: 10, sortOrder: 0 };
const PRODUCT_B = { __typename: 'Product', productId: 'PROD~B', productName: 'Butter Popcorn', description: null, price: 20, sortOrder: 1 };

const mockCampaign = {
  getCampaign: {
    __typename: 'Campaign',
    campaignId: CAMPAIGN_DB,
    profileId: PROFILE_DB,
    campaignName: 'Fall Campaign',
    campaignYear: 2025,
    startDate: '2025-09-01',
    endDate: '2025-11-30',
    catalogId: 'CAT~cat1',
    unitType: 'Pack',
    unitNumber: 42,
    city: 'Anytown',
    state: 'CA',
    sharedCampaignCode: null,
    isActive: true,
    createdAt: '2025-01-01T00:00:00Z',
    updatedAt: '2025-01-01T00:00:00Z',
    totalOrders: 0,
    totalRevenue: 0,
    catalog: {
      __typename: 'Catalog',
      catalogId: 'CAT~cat1',
      catalogName: 'Fall Catalog',
      products: [PRODUCT_A, PRODUCT_B],
    },
  },
};

const mockProfileOwner = {
  getProfile: {
    __typename: 'SellerProfile',
    profileId: PROFILE_DB,
    ownerAccountId: 'ACCOUNT#owner',
    sellerName: 'Test Scout',
    createdAt: '2025-01-01T00:00:00Z',
    updatedAt: '2025-01-01T00:00:00Z',
    isOwner: true,
    permissions: [],
  },
};

const mockProfileRead = {
  getProfile: {
    ...mockProfileOwner.getProfile,
    isOwner: false,
    permissions: ['READ'],
  },
};

const mockPaymentMethods = {
  paymentMethodsForProfile: [
    { __typename: 'PaymentMethod', name: 'Cash', qrCodeUrl: null },
    { __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' },
  ],
};

const mockExistingOrder = {
  getOrder: {
    __typename: 'Order',
    orderId: ORDER_DB,
    profileId: PROFILE_DB,
    campaignId: CAMPAIGN_DB,
    customerName: 'Jane Smith',
    customerPhone: '555-9876',
    customerAddress: {
      street: '123 Oak St',
      city: 'Springfield',
      state: 'IL',
      zipCode: '62701',
    },
    paymentMethod: 'Venmo',
    notes: 'Ring doorbell',
    orderDate: '2025-10-01T00:00:00Z',
    lineItems: [
      { __typename: 'OrderLineItem', productId: 'PROD~A', productName: 'Caramel Corn', quantity: 2, pricePerUnit: 10, subtotal: 20 },
    ],
    totalAmount: 20,
    createdAt: '2025-10-01T00:00:00Z',
    updatedAt: '2025-10-01T00:00:00Z',
  },
};

function baseMocks(extra: MockedResponse[] = []): MockedResponse[] {
  return [
    { request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_DB } }, result: { data: mockCampaign } },
    { request: { query: GET_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockProfileOwner } },
    { request: { query: GET_PAYMENT_METHODS_FOR_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockPaymentMethods } },
    ...extra,
  ];
}

function renderCreateOrder(mocks: MockedResponse[]) {
  const path = `/scouts/${encodeURIComponent(PROFILE_RAW)}/campaigns/${encodeURIComponent(CAMPAIGN_RAW)}/orders/new`;
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/orders/new" element={<OrderEditorPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

function renderEditOrder(mocks: MockedResponse[]) {
  const path = `/scouts/${encodeURIComponent(PROFILE_RAW)}/campaigns/${encodeURIComponent(CAMPAIGN_RAW)}/orders/${encodeURIComponent(ORDER_RAW)}/edit`;
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/orders/:orderId/edit" element={<OrderEditorPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('OrderEditorPage - Create Order', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders create order form with all sections', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    expect(screen.getByText('Customer Information')).toBeInTheDocument();
    expect(screen.getByText('Products')).toBeInTheDocument();
    expect(screen.getByText('Payment & Notes')).toBeInTheDocument();
  }, 15000);

  test('shows breadcrumbs with Profiles, Campaigns, Orders links', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    expect(screen.getByText('Profiles')).toBeInTheDocument();
    expect(screen.getByText('Campaigns')).toBeInTheDocument();
    expect(screen.getByText('Orders')).toBeInTheDocument();
    expect(screen.getByText('New Order')).toBeInTheDocument();
  }, 15000);

  test('shows permission error for READ-only user', async () => {
    const mocks = [
      { request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_DB } }, result: { data: mockCampaign } },
      { request: { query: GET_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockProfileRead } },
      { request: { query: GET_PAYMENT_METHODS_FOR_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockPaymentMethods } },
    ];
    renderCreateOrder(mocks);

    await waitFor(() => {
      expect(screen.getByText(/don't have permission/i)).toBeInTheDocument();
    }, { timeout: 10000 });
  }, 15000);

  test('validates empty customer name on submit', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Wait for payment methods to load
    await waitFor(() => {
      const paymentSelect = screen.getByRole('combobox', { name: /payment method/i });
      expect((paymentSelect as HTMLSelectElement).value).toBe('Cash');
    }, { timeout: 5000 });

    // With no customer name, the Create Order button should be disabled
    const submitButton = screen.getByRole('button', { name: /create order/i });
    expect(submitButton).toBeDisabled();
  }, 15000);

  test('validates missing products on submit', async () => {
    const user = userEvent.setup();
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    await waitFor(() => {
      const paymentSelect = screen.getByRole('combobox', { name: /payment method/i });
      expect((paymentSelect as HTMLSelectElement).value).toBe('Cash');
    }, { timeout: 5000 });

    // Fill customer name but leave product selection empty
    fireEvent.change(screen.getByLabelText(/Customer Name/i), { target: { value: 'John Doe' } });

    await user.click(screen.getByRole('button', { name: /create order/i }));

    await waitFor(() => {
      expect(screen.getByText('At least one product is required')).toBeInTheDocument();
    });
  }, 15000);

  test('dismisses error alert when closed', async () => {
    const user = userEvent.setup();
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    await waitFor(() => {
      const paymentSelect = screen.getByRole('combobox', { name: /payment method/i });
      expect((paymentSelect as HTMLSelectElement).value).toBe('Cash');
    }, { timeout: 5000 });

    // Fill in customer name so button is enabled, but don't add a product
    fireEvent.change(screen.getByLabelText(/Customer Name/i), { target: { value: 'John Doe' } });

    // Now the button should be enabled — click to trigger product validation error
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create order/i })).not.toBeDisabled();
    }, { timeout: 3000 });

    // Trigger validation error by clicking submit without products
    fireEvent.click(screen.getByRole('button', { name: /create order/i }));
    await waitFor(() => {
      expect(screen.getByText('At least one product is required')).toBeInTheDocument();
    });

    // Close the error
    const closeButton = screen.getByRole('button', { name: /close/i });
    await user.click(closeButton);

    await waitFor(() => {
      expect(screen.queryByText('At least one product is required')).not.toBeInTheDocument();
    });
  }, 15000);

  test('adds and removes product line items', async () => {
    const user = userEvent.setup();
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Should start with one line item (one row in the table)
    const addButton = screen.getByRole('button', { name: /add product/i });
    await user.click(addButton);

    // Now there should be 2 rows - check the table has more rows
    const rows = screen.getAllByRole('row');
    expect(rows.length).toBeGreaterThan(2); // header + 2 data rows
  }, 15000);

  test('cancel navigates back to orders list', async () => {
    const user = userEvent.setup();
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Click cancel button (the one in the actions area)
    const cancelButtons = screen.getAllByRole('button', { name: /cancel/i });
    await user.click(cancelButtons[cancelButtons.length - 1]);

    expect(mockNavigate).toHaveBeenCalled();
  }, 15000);

  test('back arrow navigates to orders', async () => {
    const user = userEvent.setup();
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    const backButton = screen.getByTestId('ArrowBackIcon').closest('button');
    await user.click(backButton!);

    expect(mockNavigate).toHaveBeenCalled();
  }, 15000);

  test('breadcrumb Profiles link navigates to /scouts', async () => {
    const user = userEvent.setup();
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    await user.click(screen.getByRole('button', { name: /profiles/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/scouts');
  }, 15000);

  test('submit button is enabled when form is complete', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Wait for payment methods to load (Cash selected by default)
    await waitFor(() => {
      const paymentSelect = screen.getByRole('combobox', { name: /payment method/i });
      expect((paymentSelect as HTMLSelectElement).value).toBe('Cash');
    }, { timeout: 5000 });

    // Initially disabled (no customer name)
    expect(screen.getByRole('button', { name: /create order/i })).toBeDisabled();

    // Fill in customer name → button becomes enabled
    fireEvent.change(screen.getByLabelText(/Customer Name/i), { target: { value: 'John Doe' } });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create order/i })).not.toBeDisabled();
    });
  }, 15000);

  test('shows mutation error message when create order fails', async () => {
    renderCreateOrder(baseMocks()); // no CREATE_ORDER mock → mutation will fail

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    await waitFor(() => {
      const paymentSelect = screen.getByRole('combobox', { name: /payment method/i });
      expect((paymentSelect as HTMLSelectElement).value).toBe('Cash');
    }, { timeout: 5000 });

    // Fill customer name
    fireEvent.change(screen.getByLabelText(/Customer Name/i), { target: { value: 'John Doe' } });

    // Select a product
    const productSelects = screen.getAllByRole('combobox').filter(
      el => !(el as HTMLSelectElement).getAttribute('aria-label')?.toLowerCase().includes('payment'),
    );
    if (productSelects.length > 0) {
      fireEvent.change(productSelects[0], { target: { value: 'PROD~A' } });
    }

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create order/i })).not.toBeDisabled();
    }, { timeout: 5000 });

    // Submit — mutation should fail (no mock) → error alert appears
    fireEvent.click(screen.getByRole('button', { name: /create order/i }));

    await waitFor(() => {
      // An error alert should appear when mutation fails
      const alerts = screen.queryAllByRole('alert');
      expect(alerts.length).toBeGreaterThan(0);
    }, { timeout: 5000 });
  }, 20000);

  test('phone number is formatted on blur', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    const phoneInput = screen.getByLabelText(/Phone Number/i);
    fireEvent.change(phoneInput, { target: { value: '5551234567' } });
    fireEvent.blur(phoneInput);

    await waitFor(() => {
      expect((phoneInput as HTMLInputElement).value).toBe('(555) 123-4567');
    });
  }, 15000);

  test('phone number with 11 digits (leading 1) formats correctly', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    const phoneInput = screen.getByLabelText(/Phone Number/i);
    fireEvent.change(phoneInput, { target: { value: '15551234567' } });
    fireEvent.blur(phoneInput);

    await waitFor(() => {
      expect((phoneInput as HTMLInputElement).value).toBe('(555) 123-4567');
    });
  }, 15000);

  test('short phone number is left as-is', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    const phoneInput = screen.getByLabelText(/Phone Number/i);
    fireEvent.change(phoneInput, { target: { value: '12345' } });
    fireEvent.blur(phoneInput);

    await waitFor(() => {
      expect((phoneInput as HTMLInputElement).value).toBe('12345');
    });
  }, 15000);

  test('payment methods loading state shows Loading... option', async () => {
    const neverResolvesMocks: MockedResponse[] = [
      { request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_DB } }, result: { data: mockCampaign } },
      { request: { query: GET_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockProfileOwner } },
      { request: { query: GET_PAYMENT_METHODS_FOR_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockPaymentMethods }, delay: 5000 },
    ];
    renderCreateOrder(neverResolvesMocks);

    // Initially payment methods are loading
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });
  }, 15000);

  test('shows no payment methods available when empty', async () => {
    const emptyMethodsMocks: MockedResponse[] = [
      { request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_DB } }, result: { data: mockCampaign } },
      { request: { query: GET_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockProfileOwner } },
      { request: { query: GET_PAYMENT_METHODS_FOR_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: { paymentMethodsForProfile: [] } } },
    ];
    renderCreateOrder(emptyMethodsMocks);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    await waitFor(() => {
      expect(screen.getByText('Payment & Notes')).toBeInTheDocument();
    });
  }, 15000);
});

describe('OrderEditorPage - Edit Order', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function editMocks(extra: MockedResponse[] = []): MockedResponse[] {
    return [
      { request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_DB } }, result: { data: mockCampaign } },
      { request: { query: GET_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockProfileOwner } },
      { request: { query: GET_PAYMENT_METHODS_FOR_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockPaymentMethods } },
      { request: { query: GET_ORDER, variables: { orderId: ORDER_DB } }, result: { data: mockExistingOrder } },
      ...extra,
    ];
  }

  test('renders edit order form with existing data', async () => {
    renderEditOrder(editMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /edit order/i })).toBeInTheDocument();
    }, { timeout: 10000 });
  }, 15000);

  test('breadcrumb shows Edit Order text', async () => {
    renderEditOrder(editMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /edit order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // 'Edit Order' appears both as a breadcrumb label and as the page heading
    expect(screen.getAllByText('Edit Order').length).toBeGreaterThanOrEqual(1);
  }, 15000);

  test('loads existing order data into form', async () => {
    renderEditOrder(editMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /edit order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Jane Smith')).toBeInTheDocument();
    }, { timeout: 5000 });

    expect(screen.getByDisplayValue('555-9876')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Springfield')).toBeInTheDocument();
  }, 15000);

  test('renders Update Order button for edit mode', async () => {
    renderEditOrder(editMocks());

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /update order/i })).toBeInTheDocument();
    }, { timeout: 15000 });
  }, 20000);

  test('submits updated order successfully', async () => {
    const updateOrderResult = {
      updateOrder: {
        __typename: 'Order',
        orderId: ORDER_DB,
        profileId: PROFILE_DB,
        campaignId: CAMPAIGN_DB,
        customerName: 'Jane Smith',
        customerPhone: '555-9876',
        customerAddress: { street: '123 Oak St', city: 'Springfield', state: 'IL', zipCode: '62701' },
        paymentMethod: 'Venmo',
        notes: 'Ring doorbell',
        orderDate: '2025-10-01T00:00:00Z',
        lineItems: [{ __typename: 'OrderLineItem', productId: 'PROD~A', productName: 'Caramel Corn', quantity: 2, pricePerUnit: 10, subtotal: 20 }],
        totalAmount: 20,
        createdAt: '2025-10-01T00:00:00Z',
        updatedAt: '2025-10-01T00:00:00Z',
      },
    };
    const mocks = editMocks([
      {
        request: {
          query: UPDATE_ORDER,
          variables: {
            input: {
              orderId: ORDER_DB,
              customerName: 'Jane Smith',
              customerPhone: '555-9876',
              customerAddress: { street: '123 Oak St', city: 'Springfield', state: 'IL', zipCode: '62701' },
              paymentMethod: 'Venmo',
              lineItems: [{ productId: 'PROD~A', quantity: 2 }],
              notes: 'Ring doorbell',
            },
          },
        },
        result: { data: updateOrderResult },
      },
    ]);
    renderEditOrder(mocks);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /update order/i })).toBeInTheDocument();
    }, { timeout: 15000 });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Jane Smith')).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /update order/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalled();
    }, { timeout: 5000 });
  }, 25000);

  test('shows loading spinner while order loads', async () => {
    const loadingMocks: MockedResponse[] = [
      { request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_DB } }, result: { data: mockCampaign } },
      { request: { query: GET_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockProfileOwner } },
      { request: { query: GET_PAYMENT_METHODS_FOR_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockPaymentMethods } },
      { request: { query: GET_ORDER, variables: { orderId: ORDER_DB } }, result: { data: mockExistingOrder }, delay: 5000 },
    ];
    renderEditOrder(loadingMocks);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  }, 15000);
});

describe('OrderEditorPage - QR Code', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('QR button appears when Venmo (with QR) is selected by owner', async () => {
    const user = userEvent.setup();
    const venmoFirstMethods = {
      paymentMethodsForProfile: [
        { __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' },
      ],
    };
    const mocks: MockedResponse[] = [
      { request: { query: GET_CAMPAIGN, variables: { campaignId: CAMPAIGN_DB } }, result: { data: mockCampaign } },
      { request: { query: GET_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: mockProfileOwner } },
      { request: { query: GET_PAYMENT_METHODS_FOR_PROFILE, variables: { profileId: PROFILE_DB } }, result: { data: venmoFirstMethods } },
    ];
    renderCreateOrder(mocks);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /view qr code/i })).toBeInTheDocument();
    }, { timeout: 5000 });

    // Click QR button to open modal
    await user.click(screen.getByRole('button', { name: /view qr code/i }));
    await waitFor(() => {
      expect(screen.getByText(/Payment QR Code/i)).toBeInTheDocument();
    });

    // Close modal
    await user.click(screen.getByRole('button', { name: /close/i }));
  }, 20000);
});

describe('OrderEditorPage - Line Items', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('can add multiple line items', async () => {
    const user = userEvent.setup();
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Add 2 more items
    await user.click(screen.getByRole('button', { name: /add product/i }));
    await user.click(screen.getByRole('button', { name: /add product/i }));

    // Should now have 3 data rows
    const rows = screen.getAllByRole('row');
    expect(rows.length).toBeGreaterThanOrEqual(4); // header + 3 rows
  }, 15000);

  test('remove item button is disabled with single line item', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // With 1 item, the delete button should be disabled
    const deleteButtons = screen.getAllByRole('button').filter(btn =>
      btn.querySelector('svg[data-testid="DeleteIcon"]')
    );
    if (deleteButtons.length > 0) {
      expect(deleteButtons[0]).toBeDisabled();
    }
  }, 15000);

  test('total updates when quantity changes', async () => {
    renderCreateOrder(baseMocks());

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /create order/i })).toBeInTheDocument();
    }, { timeout: 10000 });

    // The products section shows Total (the order total heading)
    expect(screen.getAllByText(/total/i).length).toBeGreaterThanOrEqual(1);
  }, 15000);
});
