import React from 'react';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { MockedProvider } from '@apollo/client/testing/react';

// Mock AuthContext (authenticated admin)
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, loading: false, isAdmin: true, account: { accountId: 'admin-account' } }),
}));

import { AdminPage } from '../src/pages/AdminPage';
import { LIST_MY_PROFILES, LIST_MANAGED_CATALOGS, ADMIN_LIST_USERS } from '../src/lib/graphql';

describe('AdminPage (smoke test)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders admin console header', async () => {
    const mocks = [
      { request: { query: LIST_MY_PROFILES }, result: { data: { listMyProfiles: [] } } },
      { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: [] } } },
      {
        request: { query: ADMIN_LIST_USERS, variables: { limit: 20 } },
        result: { data: { adminListUsers: { users: [], nextToken: null } } },
      },
    ];

    render(
      <MockedProvider mocks={mocks} addTypename={false}>
        <BrowserRouter>
          <AdminPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(screen.getByText(/Admin Console/i)).toBeInTheDocument();
  });
});
