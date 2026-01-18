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

// Mock auth
const mockLogout = vi.fn();
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ logout: mockLogout }),
}));

// We'll mock useQuery directly to avoid using MockedProvider which causes ESM issues in this env
let mockAccountData: { isAdmin: boolean } = { isAdmin: true };
vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual<any>('@apollo/client/react');
  return {
    ...actual,
    useQuery: () => ({ data: { getMyAccount: mockAccountData }, loading: false, error: undefined }),
  };
});

import { SettingsPage } from '../src/pages/SettingsPage';

describe('SettingsPage (unit)', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockLogout.mockClear();
    mockAccountData = { isAdmin: true };
  });

  test('shows Admin Console when account is admin and navigates', async () => {
    mockAccountData = { isAdmin: true };

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

  test('does not show Admin Console for non-admin and signs out', async () => {
    mockAccountData = { isAdmin: false };

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Account Settings/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Admin Console/i })).not.toBeInTheDocument();

    // Click Sign Out
    const signOut = await screen.findByRole('button', { name: /Sign Out/i });
    await userEvent.click(signOut);
    expect(mockLogout).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });
});
