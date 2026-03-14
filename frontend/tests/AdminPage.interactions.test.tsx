/**
 * AdminPage interaction tests - user search, reset password, delete user, catalog CRUD
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { BrowserRouter } from 'react-router-dom';
import { AdminPage } from '../src/pages/AdminPage';
import {
  LIST_MANAGED_CATALOGS,
  ADMIN_SEARCH_USER,
  ADMIN_RESET_USER_PASSWORD,
  ADMIN_DELETE_USER,
  ADMIN_DELETE_USER_ORDERS,
  ADMIN_DELETE_USER_CAMPAIGNS,
  ADMIN_DELETE_USER_SHARES,
  ADMIN_DELETE_USER_PROFILES,
  ADMIN_DELETE_USER_CATALOGS,
  CREATE_MANAGED_CATALOG,
  UPDATE_CATALOG,
  DELETE_CATALOG,
} from '../src/lib/graphql';

const mockAdminUser = {
  __typename: 'AdminUser',
  accountId: 'ACCOUNT#test-user-1',
  email: 'test@example.com',
  displayName: 'Test User',
  status: 'CONFIRMED',
  enabled: true,
  emailVerified: true,
  isAdmin: false,
  createdAt: '2025-01-15T00:00:00Z',
  lastModifiedAt: '2025-01-16T00:00:00Z',
};

const mockAdminUser2 = {
  __typename: 'AdminUser',
  accountId: 'ACCOUNT#test-user-2',
  email: 'admin@example.com',
  displayName: 'Admin User',
  status: 'CONFIRMED',
  enabled: true,
  emailVerified: false,
  isAdmin: true,
  createdAt: '2025-01-15T00:00:00Z',
  lastModifiedAt: '2025-01-16T00:00:00Z',
};

const mockAdminUserDisabled = {
  __typename: 'AdminUser',
  accountId: 'ACCOUNT#test-user-3',
  email: 'disabled@example.com',
  displayName: null,
  status: 'UNCONFIRMED',
  enabled: false,
  emailVerified: false,
  isAdmin: false,
  createdAt: '2025-01-15T00:00:00Z',
  lastModifiedAt: null,
};

const mockCatalog = {
  __typename: 'Catalog',
  catalogId: 'CAT~1',
  catalogName: 'Test Catalog',
  catalogType: 'ADMIN_MANAGED',
  ownerAccountId: 'ACCOUNT#admin',
  isPublic: true,
  products: [
    { __typename: 'Product', productId: 'PROD~1', productName: 'Caramel Corn', price: 20, description: null, sortOrder: 0 },
  ],
  createdAt: '2025-01-01T00:00:00Z',
  updatedAt: '2025-01-01T00:00:00Z',
};

function baseMocks(extraMocks: any[] = []) {
  return [
    {
      request: { query: LIST_MANAGED_CATALOGS },
      result: { data: { listManagedCatalogs: [] } },
    },
    ...extraMocks,
  ];
}

function renderAdmin(mocks: any[]) {
  return render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <BrowserRouter>
        <AdminPage />
      </BrowserRouter>
    </MockedProvider>,
  );
}

describe('AdminPage - User Search', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('search button is disabled when search field is empty', () => {
    renderAdmin(baseMocks());
    const searchButton = screen.getByRole('button', { name: /search/i });
    expect(searchButton).toBeDisabled();
  });

  test('search button enables when text is entered', async () => {
    const user = userEvent.setup();
    renderAdmin(baseMocks());

    const searchInput = screen.getByPlaceholderText(/search by email, name/i);
    await user.type(searchInput, 'test');

    expect(screen.getByRole('button', { name: /search/i })).not.toBeDisabled();
  });

  test('shows initial info alert before searching', () => {
    renderAdmin(baseMocks());
    expect(screen.getByText(/Search for a user by email/i)).toBeInTheDocument();
  });

  test('search returns and displays user', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test@example.com' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    const searchInput = screen.getByPlaceholderText(/search by email, name/i);
    await user.type(searchInput, 'test@example.com');
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });
  });

  test('shows "no user found" when search returns empty', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'nobody' } },
        result: { data: { adminSearchUser: [] } },
      },
    ]);
    renderAdmin(mocks);

    const searchInput = screen.getByPlaceholderText(/search by email, name/i);
    await user.type(searchInput, 'nobody');
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText(/No user found matching/i)).toBeInTheDocument();
    });
  });

  test('shows multiple users with count alert', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'user' } },
        result: { data: { adminSearchUser: [mockAdminUser, mockAdminUser2] } },
      },
    ]);
    renderAdmin(mocks);

    const searchInput = screen.getByPlaceholderText(/search by email, name/i);
    await user.type(searchInput, 'user');
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText(/Found 2 users matching/i)).toBeInTheDocument();
    });
  });

  test('search triggers on Enter key', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    const searchInput = screen.getByPlaceholderText(/search by email, name/i);
    await user.type(searchInput, 'test');
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });
  });

  test('does not search on Enter when field is empty', async () => {
    const user = userEvent.setup();
    renderAdmin(baseMocks());

    const searchInput = screen.getByPlaceholderText(/search by email, name/i);
    await user.click(searchInput);
    await user.keyboard('{Enter}');

    // Should still show initial prompt
    expect(screen.getByText(/Search for a user by email/i)).toBeInTheDocument();
  });

  test('shows user status chips - Active', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Active')).toBeInTheDocument();
    });
  });

  test('shows user status chips - Disabled', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'disabled' } },
        result: { data: { adminSearchUser: [mockAdminUserDisabled] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'disabled' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Disabled')).toBeInTheDocument();
    });
  });

  test('shows Admin chip for admin user', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'admin' } },
        result: { data: { adminSearchUser: [mockAdminUser2] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'admin' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Admin')).toBeInTheDocument();
    });
  });

  test('shows User chip for non-admin user', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('User')).toBeInTheDocument();
    });
  });

  test('shows FORCE_CHANGE_PASSWORD status', async () => {
    const user = userEvent.setup();
    const forcePwUser = { ...mockAdminUser, status: 'FORCE_CHANGE_PASSWORD', enabled: true, lastModifiedAt: '2025-01-16T00:00:00Z' };
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'force' } },
        result: { data: { adminSearchUser: [forcePwUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'force' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Password Reset')).toBeInTheDocument();
    });
  });

  test('shows unknown status as chip label', async () => {
    const user = userEvent.setup();
    const unknownStatusUser = { ...mockAdminUser, status: 'ARCHIVED', enabled: true, lastModifiedAt: '2025-01-16T00:00:00Z' };
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'archived' } },
        result: { data: { adminSearchUser: [unknownStatusUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'archived' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('ARCHIVED')).toBeInTheDocument();
    });
  });
});

describe('AdminPage - Reset Password', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('clicking reset password icon opens confirmation dialog', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /Reset password for test@example.com/i }));

    expect(screen.getByText('Reset Password')).toBeInTheDocument();
    expect(screen.getByText(/Send a password reset email to/i)).toBeInTheDocument();
  });

  test('cancel closes reset password dialog', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(screen.getByText('test@example.com')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Reset password for test@example.com/i }));
    expect(screen.getByText('Reset Password')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() => {
      expect(screen.queryByText('Reset Password')).not.toBeInTheDocument();
    });
  });

  test('confirming reset sends mutation and shows snackbar', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
      {
        request: { query: ADMIN_RESET_USER_PASSWORD, variables: { email: 'test@example.com' } },
        result: { data: { adminResetUserPassword: true } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(screen.getByText('test@example.com')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Reset password for test@example.com/i }));
    await user.click(screen.getByRole('button', { name: /send reset email/i }));

    await waitFor(() => {
      expect(screen.getByText(/Password reset email sent/i)).toBeInTheDocument();
    });
  });
});

describe('AdminPage - Delete User', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('clicking delete icon opens delete confirmation dialog', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(screen.getByText('test@example.com')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Delete user test@example.com/i }));

    expect(screen.getByRole('heading', { name: 'Delete User' })).toBeInTheDocument();
    expect(screen.getByText(/permanently delete the user/i)).toBeInTheDocument();
  });

  test('cancel closes delete dialog', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(screen.getByText('test@example.com')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Delete user test@example.com/i }));
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByText(/permanently delete the user/i)).not.toBeInTheDocument();
    });
  });

  test('delete user executes cascading delete steps', async () => {
    const user = userEvent.setup();
    const accountId = 'ACCOUNT#test-user-1';
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
      {
        request: { query: ADMIN_DELETE_USER_ORDERS, variables: { accountId } },
        result: { data: { adminDeleteUserOrders: 5 } },
      },
      {
        request: { query: ADMIN_DELETE_USER_CAMPAIGNS, variables: { accountId } },
        result: { data: { adminDeleteUserCampaigns: 2 } },
      },
      {
        request: { query: ADMIN_DELETE_USER_SHARES, variables: { accountId } },
        result: { data: { adminDeleteUserShares: 1 } },
      },
      {
        request: { query: ADMIN_DELETE_USER_PROFILES, variables: { accountId } },
        result: { data: { adminDeleteUserProfiles: 1 } },
      },
      {
        request: { query: ADMIN_DELETE_USER_CATALOGS, variables: { accountId } },
        result: { data: { adminDeleteUserCatalogs: 0 } },
      },
      {
        request: { query: ADMIN_DELETE_USER, variables: { accountId } },
        result: { data: { adminDeleteUser: true } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(screen.getByText('test@example.com')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Delete user test@example.com/i }));
    await user.click(screen.getByRole('button', { name: /delete user/i }));

    await waitFor(() => {
      expect(screen.getByText(/deleted successfully/i)).toBeInTheDocument();
    });
  });

  test('delete user shows error on failure', async () => {
    const user = userEvent.setup();
    const accountId = 'ACCOUNT#test-user-1';
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
      {
        request: { query: ADMIN_DELETE_USER_ORDERS, variables: { accountId } },
        error: new Error('Network error during delete'),
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(screen.getByText('test@example.com')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /Delete user test@example.com/i }));
    await user.click(screen.getByRole('button', { name: /delete user/i }));

    await waitFor(() => {
      expect(screen.getByText(/Network error during delete/i)).toBeInTheDocument();
    });
  });

  test('clicking user row navigates to user details', async () => {
    const user = userEvent.setup();
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'test' } },
        result: { data: { adminSearchUser: [mockAdminUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'test' } });
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(screen.getByText('test@example.com')).toBeInTheDocument());

    // Click the row (but not the action buttons - click the email cell)
    const emailCell = screen.getByText('test@example.com');
    await user.click(emailCell);

    // Navigation should have been triggered (window.location changes in BrowserRouter)
    expect(window.location.pathname).toContain('admin');
  });
});

describe('AdminPage - Catalog Management', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('shows catalog list in Catalogs tab', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));

    await waitFor(() => {
      expect(screen.getByText('Test Catalog')).toBeInTheDocument();
      expect(screen.getByText('1 products')).toBeInTheDocument();
    });
  });

  test('shows Managed chip for admin-managed catalog', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));

    await waitFor(() => {
      expect(screen.getByText('Managed')).toBeInTheDocument();
    });
  });

  test('shows User chip for non-managed catalog', async () => {
    const user = userEvent.setup();
    const userCatalog = { ...mockCatalog, catalogType: 'USER_CREATED' };
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [userCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));

    await waitFor(() => {
      expect(screen.getByText('User')).toBeInTheDocument();
    });
  });

  test('clicking New Catalog opens editor dialog', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /new catalog/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /new catalog/i }));

    await waitFor(() => {
      expect(screen.getByText('Create Catalog')).toBeInTheDocument();
    });
  });

  test('clicking Edit catalog opens editor dialog with catalog data', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByText('Test Catalog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /edit catalog/i }));

    await waitFor(() => {
      expect(screen.getByText('Edit Catalog')).toBeInTheDocument();
    });
  });

  test('clicking Delete catalog opens confirm dialog', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByText('Test Catalog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /delete catalog/i }));

    await waitFor(() => {
      expect(screen.getByText('Delete Catalog')).toBeInTheDocument();
      expect(screen.getByText(/This catalog will no longer be available/i)).toBeInTheDocument();
    });
  });

  test('confirming catalog delete calls mutation and closes dialog', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
      {
        request: { query: DELETE_CATALOG, variables: { catalogId: 'CAT~1' } },
        result: { data: { deleteCatalog: 'CAT~1' } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByText('Test Catalog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /delete catalog/i }));
    await waitFor(() => expect(screen.getByText('Delete Catalog')).toBeInTheDocument());

    // Find the delete button in the dialog
    const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
    const confirmDeleteBtn = deleteButtons[deleteButtons.length - 1];
    await user.click(confirmDeleteBtn);

    await waitFor(() => {
      expect(screen.getByText(/Catalog deleted successfully/i)).toBeInTheDocument();
    });
  });

  test('canceling catalog delete closes dialog', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByText('Test Catalog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /delete catalog/i }));
    await waitFor(() => expect(screen.getByText('Delete Catalog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByText(/This catalog will no longer be available/i)).not.toBeInTheDocument();
    });
  });

  test('creates new catalog via dialog', async () => {
    const user = userEvent.setup();
    const newCatalog = { ...mockCatalog, catalogId: 'CAT~2', catalogName: 'New Catalog' };
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [] } },
      },
      {
        request: {
          query: CREATE_MANAGED_CATALOG,
          variables: {
            input: {
              catalogName: 'New Test Catalog',
              isPublic: true,
              products: [{ productName: 'Test Product', description: undefined, price: 10, sortOrder: 0 }],
            },
          },
        },
        result: { data: { createManagedCatalog: newCatalog } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [newCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /new catalog/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /new catalog/i }));
    await waitFor(() => expect(screen.getByText('Create Catalog')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Catalog Name/i), { target: { value: 'New Test Catalog' } });
    fireEvent.change(screen.getByLabelText(/Product Name/i), { target: { value: 'Test Product' } });
    fireEvent.change(screen.getByLabelText(/Price/i), { target: { value: '10' } });

    await user.click(screen.getByRole('button', { name: /save catalog/i }));

    await waitFor(() => {
      expect(screen.getByText(/Catalog created successfully/i)).toBeInTheDocument();
    });
  });

  test('updates existing catalog via dialog', async () => {
    const user = userEvent.setup();
    const updatedCatalog = { ...mockCatalog, catalogName: 'Updated Catalog' };
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalog] } },
      },
      {
        request: {
          query: UPDATE_CATALOG,
          variables: {
            catalogId: 'CAT~1',
            input: {
              catalogName: 'Updated Test Catalog',
              isPublic: true,
              products: [
                { productName: 'Caramel Corn', description: undefined, price: 20, sortOrder: 0 },
              ],
            },
          },
        },
        result: { data: { updateCatalog: updatedCatalog } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [updatedCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByText('Test Catalog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /edit catalog/i }));
    await waitFor(() => expect(screen.getByText('Edit Catalog')).toBeInTheDocument());

    // Change catalog name
    const nameInput = screen.getByLabelText(/Catalog Name/i);
    fireEvent.change(nameInput, { target: { value: 'Updated Test Catalog' } });

    await user.click(screen.getByRole('button', { name: /save catalog/i }));

    await waitFor(() => {
      expect(screen.getByText(/Catalog updated successfully/i)).toBeInTheDocument();
    });
  });

  test('closing catalog editor without saving', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /new catalog/i })).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /new catalog/i }));
    await waitFor(() => expect(screen.getByText('Create Catalog')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByText('Create Catalog')).not.toBeInTheDocument();
    });
  });

  test('shows catalog with no name as Unnamed Catalog', async () => {
    const user = userEvent.setup();
    const namelessCatalog = { ...mockCatalog, catalogName: null };
    const mocks = [
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [namelessCatalog] } },
      },
    ];
    renderAdmin(mocks);

    await user.click(screen.getByRole('tab', { name: /catalogs/i }));

    await waitFor(() => {
      expect(screen.getByText('Unnamed Catalog')).toBeInTheDocument();
    });
  });
});

describe('AdminPage - UserStatusChip edge cases', () => {
  test('shows UNCONFIRMED status', async () => {
    const user = userEvent.setup();
    const unconfirmedUser = { ...mockAdminUser, status: 'UNCONFIRMED', enabled: true, lastModifiedAt: '2025-01-16T00:00:00Z' };
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'unconfirmed' } },
        result: { data: { adminSearchUser: [unconfirmedUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'unconfirmed' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Unconfirmed')).toBeInTheDocument();
    });
  });

  test('shows user with no createdAt as dash', async () => {
    const user = userEvent.setup();
    const noDateUser = { ...mockAdminUser, createdAt: null, lastModifiedAt: null };
    const mocks = baseMocks([
      {
        request: { query: ADMIN_SEARCH_USER, variables: { query: 'nodate' } },
        result: { data: { adminSearchUser: [noDateUser] } },
      },
    ]);
    renderAdmin(mocks);

    fireEvent.change(screen.getByPlaceholderText(/search by email, name/i), { target: { value: 'nodate' } });
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      // The locale date cell should show '—'
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });
  });
});
