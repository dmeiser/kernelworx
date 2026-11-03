import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock auth. isAdmin from useAuth is the ONLY thing that gates the Admin Console
// button. There is deliberately no Apollo/useQuery mock: the component must not
// issue a GraphQL query for admin status (GET_MY_ACCOUNT has no isAdmin field).
// If the component regressed to useQuery(GET_MY_ACCOUNT), rendering without an
// ApolloProvider would throw and these tests would fail.
const mockLogout = vi.fn().mockResolvedValue(undefined);
let mockIsAdmin = true;
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ logout: mockLogout, isAdmin: mockIsAdmin }),
}));

import { SettingsPage } from '../src/pages/SettingsPage';

describe('SettingsPage (unit)', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockLogout.mockClear();
    mockIsAdmin = true;
  });

  test('shows Admin Console when useAuth().isAdmin is true and navigates', async () => {
    mockIsAdmin = true;

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Account Settings/i)).toBeTruthy();
    const adminBtn = await screen.findByRole('button', { name: /Admin Console/i });
    expect(adminBtn).toBeTruthy();

    await userEvent.click(adminBtn);
    expect(mockNavigate).toHaveBeenCalledWith('/admin');
  });

  test('does not show Admin Console when useAuth().isAdmin is false and signs out', async () => {
    mockIsAdmin = false;

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Account Settings/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Admin Console/i })).not.toBeInTheDocument();

    const signOut = await screen.findByRole('button', { name: /Sign Out/i });
    await userEvent.click(signOut);
    expect(mockLogout).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });
});
