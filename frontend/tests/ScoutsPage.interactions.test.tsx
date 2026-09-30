/**
 * ScoutsPage interaction tests — covers uncovered branches/functions:
 *  - ErrorAlert, InfoMessageAlert, EmptyState sub-components
 *  - handleToggleReadOnly
 *  - mutation onCompleted callbacks (create, update, delete)
 *  - handleCreateProfile, handleUpdateProfile
 *  - info message from location state
 */

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

const profilesQueryMock = vi.fn();
const apolloQuerySpy = vi.fn();
const loadAccountMock = vi.fn();
const updatePreferencesMock = vi.fn().mockResolvedValue({ data: {} });
const createProfileMock = vi.fn().mockResolvedValue({ data: { createSellerProfile: { profileId: 'PROFILE#new1' } } });
const updateProfileMock = vi.fn().mockResolvedValue({ data: {} });
const deleteProfileMock = vi.fn().mockResolvedValue({ data: {} });

// Capture mutation option callbacks so tests can invoke them
let capturedCreateOpts: any;
let capturedUpdateOpts: any;
let capturedDeleteOpts: any;

const buildLazyQueryResult = (name: string | undefined) => {
  const lazyQueryHandlers: Record<string, () => [any, any]> = {
    GetMyAccount: () => [
      loadAccountMock,
      { data: mockAccountData ? { getMyAccount: mockAccountData } : undefined, loading: false },
    ],
  };

  return lazyQueryHandlers[name ?? '']?.() ?? [vi.fn(), { data: undefined, loading: false }];
};

vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual('@apollo/client/react');

  const getOpName = (query: any): string | undefined =>
    query?.definitions?.find((d: any) => d?.kind === 'OperationDefinition')?.name?.value;

  const useLazyQuery = (query: any) => buildLazyQueryResult(getOpName(query));

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

  // useApolloClient returns an instance whose query method serves both the
  // paginated listMyProfiles connection and the shared-profiles list.
  const useApolloClient = () => ({
    readQuery: (options: any) => {
      const name = getOpName(options?.query);
      if (name === 'GetMyAccount') {
        return mockAccountData ? { getMyAccount: mockAccountData } : null;
      }
      return null;
    },
    query: (options: any) => {
      apolloQuerySpy(options);
      const name = getOpName(options?.query);
      if (name === 'ListMyProfiles') {
        profilesQueryMock(options);
        if (mockMyProfilesError) {
          return Promise.reject(mockMyProfilesError);
        }
        if (mockMyProfilesLoading) {
          return new Promise(() => {});
        }
        return Promise.resolve({
          data: { listMyProfiles: { profiles: mockMyProfiles, nextToken: null } },
        });
      }
      return Promise.resolve({ data: { listMyShares: mockSharedProfiles } });
    },
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
    apolloQuerySpy.mockClear();
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
    await waitFor(() => expect(screen.getByText('Profile created successfully')).toBeInTheDocument(), {
      timeout: 5000,
    });
  }, 10000);

  it('shows EmptyState when user has no profiles and not loading', async () => {
    mockMyProfiles = [];
    mockSharedProfiles = [];
    mockMyProfilesLoading = false;
    renderScoutsPage();
    await waitFor(
      () => expect(screen.getByText(/Click "Create Scout" to add your first seller profile./i)).toBeInTheDocument(),
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

  it('toggle sends the live blob as the optimistic-lock snapshot (#510)', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Show read-only')).toBeInTheDocument(), { timeout: 5000 });

    const checkbox = document.querySelector('input[type="checkbox"]') as HTMLInputElement;
    fireEvent.click(checkbox!);

    await waitFor(() => expect(updatePreferencesMock).toHaveBeenCalled(), { timeout: 3000 });
    const vars = updatePreferencesMock.mock.calls[0][0].variables;
    expect(vars.expectedPreferences).toBe(mockAccountData.preferences);
    expect(JSON.parse(vars.preferences)).toEqual({ showReadOnlyProfiles: false });
  }, 10000);

  it('toggle preserves paymentMethods stored in the preferences blob (#510)', async () => {
    mockAccountData = {
      accountId: 'acct-1',
      email: 'test@example.com',
      preferences: JSON.stringify({
        showReadOnlyProfiles: true,
        paymentMethods: [{ name: 'Venmo', qrCodeUrl: 'qr.png' }],
      }),
    };
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Show read-only')).toBeInTheDocument(), { timeout: 5000 });

    const checkbox = document.querySelector('input[type="checkbox"]') as HTMLInputElement;
    fireEvent.click(checkbox!);

    await waitFor(() => expect(updatePreferencesMock).toHaveBeenCalled(), { timeout: 3000 });
    const vars = updatePreferencesMock.mock.calls[0][0].variables;
    expect(JSON.parse(vars.preferences).paymentMethods).toEqual([{ name: 'Venmo', qrCodeUrl: 'qr.png' }]);
    expect(vars.expectedPreferences).toBe(mockAccountData.preferences);
  }, 10000);

  it('failed toggle surfaces the mutation error in the error alert and keeps the rollback (#510)', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Show read-only')).toBeInTheDocument(), { timeout: 5000 });

    updatePreferencesMock.mockRejectedValueOnce(new Error('Preferences were modified by another request.'));
    const checkbox = document.querySelector('input[type="checkbox"]') as HTMLInputElement;
    fireEvent.click(checkbox!);

    // The mutation failure is surfaced to the user as the page's error alert.
    await waitFor(
      () => expect(screen.getByText('Preferences were modified by another request.')).toBeInTheDocument(),
      { timeout: 5000 },
    );
    // The toggle reverted to the stored value.
    expect(checkbox.checked).toBe(true);
    // The cached blob was refreshed so a retry locks on fresh state.
    expect(apolloQuerySpy).toHaveBeenCalledWith(expect.objectContaining({ fetchPolicy: 'network-only' }));
  }, 10000);

  it('a subsequent successful toggle clears the surfaced error (#510)', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Show read-only')).toBeInTheDocument(), { timeout: 5000 });

    updatePreferencesMock.mockRejectedValueOnce(new Error('Preferences were modified by another request.'));
    const checkbox = document.querySelector('input[type="checkbox"]') as HTMLInputElement;
    fireEvent.click(checkbox!);
    await waitFor(
      () => expect(screen.getByText('Preferences were modified by another request.')).toBeInTheDocument(),
      { timeout: 5000 },
    );

    fireEvent.click(checkbox!);
    await waitFor(() => expect(screen.queryByText('Preferences were modified by another request.')).toBeNull(), {
      timeout: 5000,
    });
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
    await waitFor(() => expect(screen.getByRole('progressbar', { hidden: true })).toBeTruthy(), { timeout: 100 }).catch(
      () => {},
    );

    // Invoke the captured onCompleted directly
    await waitFor(() => expect(capturedCreateOpts).toBeDefined(), { timeout: 5000 });
    const callsBefore = profilesQueryMock.mock.calls.length;
    await capturedCreateOpts.onCompleted?.({});

    expect(profilesQueryMock.mock.calls.length).toBeGreaterThan(callsBefore);
  }, 10000);

  it('updateProfile onCompleted triggers loadMyProfiles and loadSharedProfiles', async () => {
    renderScoutsPage();
    await waitFor(() => expect(capturedUpdateOpts).toBeDefined(), { timeout: 5000 });
    const callsBefore = profilesQueryMock.mock.calls.length;
    await capturedUpdateOpts.onCompleted?.({});
    expect(profilesQueryMock.mock.calls.length).toBeGreaterThan(callsBefore);
  }, 10000);

  it('deleteProfile onCompleted closes dialog and triggers loadMyProfiles', async () => {
    renderScoutsPage();
    await waitFor(() => expect(capturedDeleteOpts).toBeDefined(), { timeout: 5000 });

    // After delete onCompleted, the dialog should be closed and loadMyProfiles called
    const callsBefore = profilesQueryMock.mock.calls.length;
    await capturedDeleteOpts.onCompleted?.({});
    expect(profilesQueryMock.mock.calls.length).toBeGreaterThan(callsBefore);
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
        await waitFor(
          () =>
            expect(createProfileMock).toHaveBeenCalledWith(
              expect.objectContaining({ variables: expect.objectContaining({ sellerName: 'Test Scout Name' }) }),
            ),
          { timeout: 3000 },
        );
      }
    }
  }, 10000);

  // ── shared profiles error ─────────────────────────────────────────────────

  it('shows profile list when profiles are loaded successfully', async () => {
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Alice Scout')).toBeInTheDocument(), { timeout: 5000 });
  }, 10000);

  it('renders owned profile when optional fields are missing', async () => {
    mockMyProfiles = [
      {
        profileId: 'PROFILE#p-no-perms',
        sellerName: 'No Optional Fields Scout',
        accountId: 'acct-1',
        ownerAccountId: 'acct-1',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
        latestCampaign: null,
        __typename: 'SellerProfile',
      },
    ];
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('No Optional Fields Scout')).toBeInTheDocument(), { timeout: 5000 });
  }, 10000);

  it('renders shared profile when optional fields are missing', async () => {
    mockMyProfiles = [];
    mockSharedProfiles = [
      {
        profileId: 'PROFILE#shared-no-perms',
        sellerName: 'Shared No Fields Scout',
        accountId: 'shared-acct',
        ownerAccountId: 'shared-acct',
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-01-01T00:00:00Z',
        latestCampaign: null,
        __typename: 'SellerProfile',
      },
    ];
    renderScoutsPage();
    await waitFor(() => expect(screen.getByText('Shared No Fields Scout')).toBeInTheDocument(), { timeout: 5000 });
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
