import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { vi, describe, it, expect, beforeEach } from 'vitest';

// Mock AuthContext (authenticated admin)
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, loading: false, isAdmin: true, account: { accountId: 'admin-account' } }),
}));

// Partially mock apollo hooks to return empty lists so AdminPage can render
vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual<any>('@apollo/client/react');
  return {
    ...actual,
    useLazyQuery: () => [vi.fn(), { data: { listMyProfiles: [] } }],
    useQuery: () => ({ data: { listMyProfiles: [], listManagedCatalogs: [] }, loading: false }),
    useMutation: () => [vi.fn()],
  };
});

import { AdminPage } from '../src/pages/AdminPage';

describe('AdminPage (smoke test)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders admin console header', async () => {
    render(
      <BrowserRouter>
        <AdminPage />
      </BrowserRouter>,
    );

    await waitFor(() => expect(screen.getByText(/Admin Console/i)).toBeInTheDocument());
  }, 10000);
});
