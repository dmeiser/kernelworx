/**
 * SettingsPage component tests
 *
 * Admin Console visibility is driven by useAuth().isAdmin (derived from the
 * Cognito JWT cognito:groups claim), NOT by GET_MY_ACCOUNT — the Account type
 * has no isAdmin field. These tests gate on the auth context to guard against
 * the #703 regression where the button never rendered.
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock auth — isAdmin is the sole driver of the Admin Console button.
const mockLogout = vi.fn().mockResolvedValue(undefined);
let mockIsAdmin = false;
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    logout: mockLogout,
    isAdmin: mockIsAdmin,
  }),
}));

import { SettingsPage } from '../src/pages/SettingsPage';

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsAdmin = false;
  });

  const renderPage = () =>
    render(
      <BrowserRouter>
        <SettingsPage />
      </BrowserRouter>,
    );

  test('renders page title and quick actions', () => {
    renderPage();

    expect(screen.getByText('Account Settings')).toBeInTheDocument();
    expect(screen.getByText('Quick Actions')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /User Settings/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Manage My Scouts/i })).toBeInTheDocument();
  });

  test('shows Admin Console button for admin users', async () => {
    mockIsAdmin = true;
    renderPage();

    const adminButton = await screen.findByRole('button', { name: /Admin Console/i });
    expect(adminButton).toBeInTheDocument();
  });

  test('hides Admin Console button for non-admin users', async () => {
    mockIsAdmin = false;
    renderPage();

    await screen.findByText('Quick Actions');
    expect(screen.queryByRole('button', { name: /Admin Console/i })).not.toBeInTheDocument();
  });

  test('navigates to user settings when button clicked', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /User Settings/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/account/settings');
  });

  test('navigates to scouts page when Manage My Scouts clicked', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /Manage My Scouts/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/scouts');
  });

  test('navigates to admin page when Admin Console clicked', async () => {
    const user = userEvent.setup();
    mockIsAdmin = true;
    renderPage();

    const adminButton = await screen.findByRole('button', { name: /Admin Console/i });
    await user.click(adminButton);
    expect(mockNavigate).toHaveBeenCalledWith('/admin');
  });

  test('navigates to payment methods page when Payment Methods clicked', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /Payment Methods/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/payment-methods');
  });

  test('displays Data & Privacy section', () => {
    renderPage();

    expect(screen.getByText('Data & Privacy')).toBeInTheDocument();
    expect(screen.getByText(/encrypted at rest/i)).toBeInTheDocument();
  });

  test('displays About section with version info', () => {
    renderPage();

    expect(screen.getByText('About KernelWorx')).toBeInTheDocument();
  });

  test('displays Support KernelWorx section with GitHub Sponsors link', () => {
    renderPage();

    expect(screen.getByText('Support KernelWorx')).toBeInTheDocument();
    const sponsorLink = screen.getByRole('link', { name: /Sponsor on GitHub/i });
    expect(sponsorLink).toHaveAttribute('href', 'https://github.com/sponsors/dmeiser');
    expect(sponsorLink).toHaveAttribute('target', '_blank');
    expect(sponsorLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('calls logout and navigates home when Sign Out clicked', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /Sign Out/i }));
    expect(mockLogout).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });
});
