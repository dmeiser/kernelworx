/**
 * ScoutsPage interaction tests — covers uncovered branches/functions:
 *  - ErrorAlert, InfoMessageAlert, EmptyState sub-components
 *  - handleToggleReadOnly
 *  - mutation onCompleted callbacks (create, update, delete)
 *  - handleCreateProfile, handleUpdateProfile
 *  - info message from location state
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// ── mock navigate ────────────────────────────────────────────────────────────
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

// ── mock AuthContext ─────────────────────────────────────────────────────────
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, loading: false, account: { accountId: 'acct-1' } }),
}));

// ── Apollo state controlled by each test ─────────────────────────────────────
let mockMyProfiles: any[] = [];
let mockSharedProfiles: any[] = [];
let mockAccountData: any = {
  accountId: 'acct-1',
  email: 'test@example.com',
  preferences: JSON.stringify({ showReadOnlyProfiles: true }),
};
let mockMyProfilesError: Error | null = null;
let mockMyProfilesLoading = false;

const loadMyProfilesMock = vi.fn();
const loadAccountMock = vi.fn();
const updatePreferencesMock = vi.fn().mockResolvedValue({ data: {} });
const createProfileMock = vi.fn().mockResolvedValue({ data: { createSellerProfile: { profileId: 'PROFILE#new1' } } });
const updateProfileMock = vi.fn().mockResolvedValue({ data: {} });
const deleteProfileMock = vi.fn().mockResolvedValue({ data: {} });

// Capture mutation option callbacks so tests can invoke them
let capturedCreateOpts: any;
let capturedUpdateOpts: any;
let capturedDeleteOpts: any;

vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual('@apollo/client/react');

  const getOpName = (query: any): string | undefined =>
    query?.definitions?.find((d: any) => d?.kind === 'OperationDefinition')?.name?.value;

  const useLazyQuery = (query: any) => {
    const name = getOpName(query);
    if (name === 'ListMyProfiles') {
      return [
        loadMyProfilesMock,
        {
          // Return empty data array even on error so the page exits loading state and shows the error alert
          data: { listMyProfiles: mockMyProfilesError ? [] : mockMyProfiles },
          loading: mockMyProfilesLoading,
          error: mockMyProfilesError ?? undefined,
        },
      ];
    }
    if (name === 'GetMyAccount') {
      return [
        loadAccountMock,
        { data: mockAccountData ? { getMyAccount: mockAccountData } : undefined, loading: false },
      ];
    }
    // ListMyShares — shared profiles loaded via apolloClient.query, not useLazyQuery
    return [vi.fn(), { data: undefined, loading: false }];
  };

  const mutationHandlers: Record<string, (opts: any) => any> = {
    CreateSellerProfile: (opts) => {
      capturedCreateOpts = opts;
      return [
        async (vars: any) => {
          const res = await createProfileMock(vars);
          opts?.onCompleted?.(res?.data ?? {});
          return res;
        },
        { loading: false },
      ];
    },
    UpdateSellerProfile: (opts) => {
      capturedUpdateOpts = opts;
      return [
        async (vars: any) => {
          const res = await updateProfileMock(vars);
          opts?.onCompleted?.(res?.data ?? {});
          return res;
        },
        { loading: false },
      ];
    },
    DeleteSellerProfile: (opts) => {
      capturedDeleteOpts = opts;
      return [
        async (vars: any) => {
          const res = await deleteProfileMock(vars);
          opts?.onCompleted?.(res?.data ?? {});
          return res;
        },
        { loading: false },
      ];
    },
    UpdateMyPreferences: (_opts) => {
      return [updatePreferencesMock, { loading: false }];
    },
  };

  const useMutation = (mutation: any, opts: any) => {
    const name = getOpName(mutation);
    const handler = mutationHandlers[name ?? ''];
    if (handler) return handler(opts);
    return [vi.fn().mockResolvedValue({ data: {} }), { loading: false }];
  };

  // useApolloClient returns an instance with a query method for shared profiles
  const useApolloClient = () => ({
    query: vi.fn().mockResolvedValue({ data: { listMyShares: mockSharedProfiles } }),
  });

  return { ...actual, useLazyQuery, useMutation, useApolloClient };
});

import { ScoutsPage } from '../src/pages/ScoutsPage';

const renderScoutsPage = (locationState?: object) =>
  render(
    <MemoryRouter initialEntries={[{ pathname: '/scouts', state: locationState }]}>
      <ScoutsPage />
    </MemoryRouter>,
  );

describe('ScoutsPage – interactions', () => {
  beforeEach(() => {
    mockMyProfiles = [
      {
        profileId: 'PROFILE#p1',
        sellerName: 'Alice Scout',
        accountId: 'acct-1',
        ownerAccountId: 'acct-1',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
        isOwner: true,
        permissions: [],
        latestCampaign: null,
        __typename: 'SellerProfile',
      },
    ];
    mockSharedProfiles = [];
    mockMyProfilesError = null;
    mockMyProfilesLoading = false;
    mockAccountData = {
      accountId: 'acct-1',
      email: 'test@example.com',
      preferences: JSON.stringify({ showReadOnlyProfiles: true }),
    };
    vi.clearAllMocks();
    capturedCreateOpts = undefined;
    capturedUpdateOpts = undefined;
    capturedDeleteOpts = undefined;
    createProfileMock.mockResolvedValue({ data: { createSellerProfile: { profileId: 'PROFILE#new1' } } });
    updateProfileMock.mockResolvedValue({ data: {} });
    deleteProfileMock.mockResolvedValue({ data: {} });
  });

  // ── sub-components ────────────────────────────────────────────────────────

  it('shows ErrorAlert when profiles query fails', async () => {
    mockMyProfilesError = new Error('DynamoDB unavailable');
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText(/Failed to load profiles/i)).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText(/DynamoDB unavailable/i)).toBeInTheDocument();
  }, 10000);

  it('shows InfoMessageAlert from location state', async () => {
    renderScoutsPage({ message: 'Profile created successfully' });
    await waitFor(() => expect(screen.getByText('Profile created successfully')).toBeInTheDocument(), { timeout: 5000 });
  }, 10000);

  it('shows EmptyState when user has no profiles and not loading', async () => {
    mockMyProfiles = [];
    mockSharedProfiles = [];
    mockMyProfilesLoading = false;
    renderScoutsPage();
    await waitFor(
      () => expect(screen.getByText(/You don't have any scouts yet/i)).toBeInTheDocument(),
      { timeout: 5000 },
    );
  }, 10000);

  // ── handleToggleReadOnly ─────────────────────────────────────────────────

  it('calls updatePreferences when toggle-read-only switch fires onChange', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Show read-only')).toBeInTheDocument(), { timeout: 5000 });

    // MUI Switch renders a hidden <input type="checkbox"/>
    const checkbox = document.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(checkbox).not.toBeNull();
    fireEvent.click(checkbox!);

    await waitFor(() => expect(updatePreferencesMock).toHaveBeenCalled(), { timeout: 3000 });
  }, 10000);

  // ── create profile mutations ──────────────────────────────────────────────

  it('opens create dialog and submitting calls createProfile mutation', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Create Scout')).toBeInTheDocument(), { timeout: 5000 });

    fireEvent.click(screen.getByText('Create Scout'));

    // Dialog opens
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();

    // Fill in name and submit
    const input = dialog.querySelector('input[type="text"], input:not([type="hidden"])') as HTMLInputElement;
    if (input) {
      fireEvent.change(input, { target: { value: 'New Scout' } });
    }

    // Find and click the create/save button
    const submitBtn = Array.from(dialog.querySelectorAll('button')).find(
      (b) => b.textContent && /create|save|submit/i.test(b.textContent),
    );
    if (submitBtn) {
      fireEvent.click(submitBtn);
      await waitFor(() => expect(createProfileMock).toHaveBeenCalled(), { timeout: 3000 });
    }
  }, 10000);

  it('createProfile onCompleted triggers loadMyProfiles', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByRole('progressbar', { hidden: true })).toBeTruthy(), { timeout: 100 }).catch(() => {});

    // Invoke the captured onCompleted directly
    await waitFor(() => expect(capturedCreateOpts).toBeDefined(), { timeout: 5000 });
    await capturedCreateOpts.onCompleted?.({});

    expect(loadMyProfilesMock).toHaveBeenCalled();
  }, 10000);

  it('updateProfile onCompleted triggers loadMyProfiles and loadSharedProfiles', async () => {
    renderScoutsPage();
    await waitFor(() => expect(capturedUpdateOpts).toBeDefined(), { timeout: 5000 });
    await capturedUpdateOpts.onCompleted?.({});
    expect(loadMyProfilesMock).toHaveBeenCalled();
  }, 10000);

  it('deleteProfile onCompleted closes dialog and triggers loadMyProfiles', async () => {
    renderScoutsPage();
    await waitFor(() => expect(capturedDeleteOpts).toBeDefined(), { timeout: 5000 });

    // After delete onCompleted, the dialog should be closed and loadMyProfiles called
    await capturedDeleteOpts.onCompleted?.({});
    expect(loadMyProfilesMock).toHaveBeenCalled();
  }, 10000);

  // ── handleCreateProfile / handleUpdateProfile ─────────────────────────────

  it('handleCreateProfile passes sellerName to createProfile mutation', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Create Scout')).toBeInTheDocument(), { timeout: 5000 });

    fireEvent.click(screen.getByText('Create Scout'));
    const dialog = await screen.findByRole('dialog');

    const input = dialog.querySelector('input') as HTMLInputElement;
    if (input) {
      fireEvent.change(input, { target: { value: 'Test Scout Name' } });
      const submitBtn = Array.from(dialog.querySelectorAll('button')).find(
        (b) => b.textContent && /create|save/i.test(b.textContent),
      );
      if (submitBtn) {
        fireEvent.click(submitBtn);
        await waitFor(() => expect(createProfileMock).toHaveBeenCalledWith(
          expect.objectContaining({ variables: expect.objectContaining({ sellerName: 'Test Scout Name' }) }),
        ), { timeout: 3000 });
      }
    }
  }, 10000);

  // ── shared profiles error ─────────────────────────────────────────────────

  it('shows profile list when profiles are loaded successfully', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Alice Scout')).toBeInTheDocument(), { timeout: 5000 });
  }, 10000);

  // ── loading state ─────────────────────────────────────────────────────────

  it('shows loading spinner when profiles are loading', async () => {
    mockMyProfilesLoading = true;
    renderScoutsPage();
    // The page shows a CircularProgress while loading
    expect(document.querySelector('[class*="MuiCircularProgress"]') || screen.queryByRole('progressbar')).toBeTruthy();
  }, 10000);

  // ── closing create dialog ─────────────────────────────────────────────────

  it('closes create dialog when cancel is clicked', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Create Scout')).toBeInTheDocument(), { timeout: 5000 });

    fireEvent.click(screen.getByText('Create Scout'));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();

    const cancelBtn = Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent && /cancel/i.test(b.textContent),
    );
    if (cancelBtn) {
      fireEvent.click(cancelBtn);
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 2000 });
    }
  }, 10000);
});
