/**
 * AdminPage component tests
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { BrowserRouter } from 'react-router-dom';
import { AdminPage } from '../src/pages/AdminPage';
import { LIST_MY_PROFILES, LIST_MANAGED_CATALOGS } from '../src/lib/graphql';

describe('AdminPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockProfiles = [
    {
      __typename: 'SellerProfile',
      profileId: 'PROFILE#profile-1',
      sellerName: 'Scout Alpha',
      ownerAccountId: 'ACCOUNT#owner-1',
      isOwner: true,
      permissions: [],
      createdAt: '2025-01-01T00:00:00Z',
      updatedAt: '2025-01-01T00:00:00Z',
    },
    {
      __typename: 'SellerProfile',
      profileId: 'PROFILE#profile-2',
      sellerName: 'Scout Beta',
      ownerAccountId: 'ACCOUNT#owner-2',
      isOwner: false,
      permissions: ['READ'],
      createdAt: '2025-01-01T00:00:00Z',
      updatedAt: '2025-01-01T00:00:00Z',
    },
  ];

  const mockCatalogs = [
    {
      __typename: 'Catalog',
      catalogId: 'catalog-1',
      catalogName: '2025 Popcorn Catalog',
      catalogType: 'ADMIN_MANAGED',
      ownerAccountId: 'ACCOUNT#admin',
      isPublic: true,
      products: [],
      createdAt: '2025-01-01T00:00:00Z',
      updatedAt: '2025-01-01T00:00:00Z',
    },
  ];

  test('shows admin warning message', async () => {
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: [],
          },
        },
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByText('Admin Console')).toBeInTheDocument();
    expect(screen.getByText(/Administrator Access/i)).toBeInTheDocument();
    expect(screen.getByText(/elevated privileges/i)).toBeInTheDocument();
  });

  test('displays three tabs: Profiles, Catalogs, System Info', () => {
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: [],
          },
        },
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByRole('tab', { name: /profiles/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /catalogs/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /system info/i })).toBeInTheDocument();
  });

  test('shows Profiles tab content by default', async () => {
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: mockProfiles,
          },
        },
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('All Scouts')).toBeInTheDocument();
      expect(screen.getByText('Scout Alpha')).toBeInTheDocument();
      expect(screen.getByText('Scout Beta')).toBeInTheDocument();
    });
  });

  test('switches to Catalogs tab when clicked', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: [],
          },
        },
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: mockCatalogs,
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    const catalogsTab = screen.getByRole('tab', { name: /catalogs/i });
    await user.click(catalogsTab);

    await waitFor(() => {
      expect(screen.getByText('Product Catalogs')).toBeInTheDocument();
      expect(screen.getByText('2025 Popcorn Catalog')).toBeInTheDocument();
    });
  });

  test('switches to System Info tab when clicked', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: [],
          },
        },
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    const systemInfoTab = screen.getByRole('tab', { name: /system info/i });
    await user.click(systemInfoTab);

    await waitFor(() => {
      expect(screen.getByText('System Information')).toBeInTheDocument();
      expect(screen.getByText(/Application Version/i)).toBeInTheDocument();
    });
  });

  test('shows loading state for profiles', () => {
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: [],
          },
        },
        delay: Infinity, // Never resolves
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  test('shows error message when profiles query fails', async () => {
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        error: new Error('Failed to fetch profiles'),
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Failed to load: Failed to fetch profiles/i)).toBeInTheDocument();
    });
  });

  test('displays owner and shared badges for profiles', async () => {
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: mockProfiles,
          },
        },
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    await waitFor(() => {
      // Check for Owner and Shared chips (not the table header "Owner")
      const ownerChips = screen.getAllByText('Owner');
      expect(ownerChips.length).toBeGreaterThanOrEqual(1); // At least the chip
      expect(screen.getByText('Shared')).toBeInTheDocument();
    });
  });

  test('displays system information in System Info tab', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: {
          query: LIST_MY_PROFILES,
        },
        result: {
          data: {
            listMyProfiles: [],
          },
        },
      },
      {
        request: {
          query: LIST_MANAGED_CATALOGS,
        },
        result: {
          data: {
            listManagedCatalogs: [],
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>
    );

    const systemInfoTab = screen.getByRole('tab', { name: /system info/i });
    await user.click(systemInfoTab);

    await waitFor(() => {
      expect(screen.getByText('System Information')).toBeInTheDocument();
      expect(screen.getByText(/Application Version/i)).toBeInTheDocument();
      expect(screen.getByText(/Backend API/i)).toBeInTheDocument();
      expect(screen.getByText(/Database/i)).toBeInTheDocument();
    });
  });

  test('shows loading state for catalogs tab', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MY_PROFILES },
        result: { data: { listMyProfiles: [] } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [] } },
        delay: Infinity, // Never resolves
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    const catalogsTab = screen.getByRole('tab', { name: /catalogs/i });
    await user.click(catalogsTab);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  test('shows error message when catalogs query fails', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MY_PROFILES },
        result: { data: { listMyProfiles: [] } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        error: new Error('Failed to fetch catalogs'),
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    const catalogsTab = screen.getByRole('tab', { name: /catalogs/i });
    await user.click(catalogsTab);

    await waitFor(() => {
      expect(screen.getByText(/Failed to fetch catalogs/i)).toBeInTheDocument();
    });
  });

  test('shows empty catalogs message when no catalogs exist', async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: LIST_MY_PROFILES },
        result: { data: { listMyProfiles: [] } },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [] } },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    const catalogsTab = screen.getByRole('tab', { name: /catalogs/i });
    await user.click(catalogsTab);

    await waitFor(() => {
      expect(screen.getByText(/No catalogs found/i)).toBeInTheDocument();
    });
  });
});
