/**
 * UserDataPage tests
 *
 * Uses the repo-standard vi.mock of '@apollo/client/react' (operation-name
 * dispatch) so both queries and mutations can be driven per test, per
 * ScoutManagementPage.interactions.test.tsx.
 */
import { useCallback, useState } from 'react';
import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { UserDataPage } from '../src/pages/UserDataPage';

const state = vi.hoisted(() => ({
  profiles: [] as any[],
  catalogs: [] as any[],
  campaigns: [] as any[],
  sharedCampaigns: [] as any[],
  shares: [] as any[],
  searchResults: [] as any[],
  profilesError: null as Error | null,
  catalogsError: null as Error | null,
  campaignsError: null as Error | null,
  sharedCampaignsError: null as Error | null,
  profilesLoading: false,
  transferResult: { data: {} } as any,
  deleteShareResult: { data: {} } as any,
  updateCodeResult: { data: {} } as any,
  searchResult: { data: { adminSearchUser: [] } } as any,
  transferMock: vi.fn().mockResolvedValue({ data: {} }),
  deleteShareMock: vi.fn().mockResolvedValue({ data: {} }),
  updateCodeMock: vi.fn().mockResolvedValue({ data: {} }),
  searchExecuted: null as { variables: { query: string } } | null,
  transferOptions: null as any,
  deleteShareOptions: null as any,
  updateCodeOptions: null as any,
}));

vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual<typeof import('@apollo/client/react')>('@apollo/client/react');

  const getOpName = (doc: any): string | undefined =>
    doc?.definitions?.find((d: any) => d?.kind === 'OperationDefinition')?.name?.value;

  const queryHandlers: Record<string, () => any> = {
    AdminGetUserProfiles: () =>
      state.profilesLoading
        ? { data: undefined, loading: true, error: undefined, refetch: vi.fn() }
        : state.profilesError
          ? { data: undefined, loading: false, error: state.profilesError, refetch: vi.fn() }
          : { data: { adminGetUserProfiles: state.profiles }, loading: false, error: undefined, refetch: vi.fn() },
    AdminGetUserCatalogs: () =>
      state.catalogsError
        ? { data: undefined, loading: false, error: state.catalogsError }
        : { data: { adminGetUserCatalogs: state.catalogs }, loading: false, error: undefined },
    AdminGetUserCampaigns: () =>
      state.campaignsError
        ? { data: undefined, loading: false, error: state.campaignsError, refetch: vi.fn() }
        : { data: { adminGetUserCampaigns: state.campaigns }, loading: false, error: undefined, refetch: vi.fn() },
    AdminGetUserSharedCampaigns: () =>
      state.sharedCampaignsError
        ? { data: undefined, loading: false, error: state.sharedCampaignsError }
        : { data: { adminGetUserSharedCampaigns: state.sharedCampaigns }, loading: false, error: undefined },
    AdminGetProfileShares: () => ({
      data: { adminGetProfileShares: state.shares },
      loading: false,
      error: undefined,
      refetch: vi.fn(),
    }),
  };

  const useQuery = (query: any, options?: any) => {
    if (options?.skip) {
      return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
    }
    const handler = queryHandlers[getOpName(query) ?? ''] ?? (() => ({ data: undefined, loading: false }));
    return handler();
  };

  const useLazyQuery = () => {
    const [data, setData] = useState<any>(undefined);
    const [loading, setLoading] = useState(false);
    const execute = useCallback(async (args: { variables: { query: string } }) => {
      state.searchExecuted = args;
      setLoading(true);
      const res = await Promise.resolve(state.searchResult);
      setLoading(false);
      setData(res.data);
      return res;
    }, []);
    return [execute, { data, loading }];
  };

  const makeMutationHandler =
    (mockFn: any, capture: (opts: any) => void) =>
    (mutation: any, opts: any) => {
      capture(opts);
      const run = async (args: any) => {
        const res = await mockFn(args);
        if (res.error) {
          opts?.onError?.(res.error);
        } else {
          opts?.onCompleted?.(res.data);
        }
        return res;
      };
      return [run, { loading: false, data: null }];
    };

  const useMutation = (mutation: any, opts: any) => {
    const name = getOpName(mutation) ?? '';
    if (name === 'TransferProfileOwnership') {
      return makeMutationHandler(state.transferMock, (o: any) => {
        state.transferOptions = o;
      })(mutation, opts);
    }
    if (name === 'AdminDeleteShare') {
      return makeMutationHandler(state.deleteShareMock, (o: any) => {
        state.deleteShareOptions = o;
      })(mutation, opts);
    }
    if (name === 'AdminUpdateCampaignSharedCode') {
      return makeMutationHandler(state.updateCodeMock, (o: any) => {
        state.updateCodeOptions = o;
      })(mutation, opts);
    }
    return [vi.fn().mockResolvedValue({ data: {} }), { loading: false, data: null }];
  };

  return { ...actual, useQuery, useLazyQuery, useMutation };
});

const accountId = 'user-123';
const profileIdA = 'PROFILE#alpha';
const profileIdB = 'PROFILE#beta';

const profile = (id: string, sellerName: string) => ({
  profileId: id,
  sellerName,
  ownerAccountId: `ACCOUNT#${accountId}`,
  isOwner: true,
  permissions: [],
  createdAt: '2025-01-15T00:00:00Z',
  updatedAt: '2025-01-15T00:00:00Z',
});

const adminUser = (id: string, email: string, displayName: string) => ({
  accountId: id,
  email,
  displayName,
});

const renderPage = (path = `/admin/user-data/${accountId}`) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin/user-data/:accountId?" element={<UserDataPage />} />
      </Routes>
    </MemoryRouter>,
  );

describe('UserDataPage', () => {
  beforeEach(() => {
    state.profiles = [];
    state.catalogs = [];
    state.campaigns = [];
    state.sharedCampaigns = [];
    state.shares = [];
    state.searchResults = [];
    state.profilesError = null;
    state.catalogsError = null;
    state.campaignsError = null;
    state.sharedCampaignsError = null;
    state.profilesLoading = false;
    state.transferResult = { data: {} };
    state.deleteShareResult = { data: {} };
    state.updateCodeResult = { data: {} };
    state.searchResult = { data: { adminSearchUser: [] } };
    state.searchExecuted = null;
    state.transferOptions = null;
    state.deleteShareOptions = null;
    state.updateCodeOptions = null;
    state.transferMock.mockReset().mockResolvedValue({ data: {} });
    state.deleteShareMock.mockReset().mockResolvedValue({ data: {} });
    state.updateCodeMock.mockReset().mockResolvedValue({ data: {} });
  });

  test('renders user data page initially', async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/User Data:/i)).toBeInTheDocument();
    });
  });

  test('shows an error alert when no account ID is provided', async () => {
    renderPage('/admin/user-data/');

    expect(await screen.findByText('No account ID provided')).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });

  test('shows MFA setup required state when profiles query returns MFA required error', async () => {
    state.profilesError = new Error('MFA required');
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
      expect(screen.getByText('MFA Setup Required')).toBeInTheDocument();
    });
  });

  test('shows MFA setup required state when catalogs query returns MFA required error', async () => {
    state.catalogsError = new Error('MFA required');
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
    });
  });

  test('shows MFA setup required state when campaigns query returns MFA required error', async () => {
    state.campaignsError = new Error('MFA required');
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
    });
  });

  test('shows MFA setup required state when shared campaigns query returns MFA required error', async () => {
    state.sharedCampaignsError = new Error('MFA required');
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
    });
  });

  test('gracefully degrades to MFA setup required state when mfa-required event fires', async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/User Data:/i)).toBeInTheDocument();
    });

    window.dispatchEvent(
      new CustomEvent('mfa-required', {
        detail: { message: 'MFA required' },
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
      expect(screen.getByText('MFA Setup Required')).toBeInTheDocument();
    });
  });

  test('shows a loading spinner while profiles are loading', async () => {
    state.profilesLoading = true;
    renderPage();

    await screen.findByRole('tab', { name: /Profiles/ });
    // The loading spinner inside the profiles panel; no settled state yet
    const panel = document.getElementById('user-data-tabpanel-0');
    expect(panel).toContainElement(document.querySelector('.MuiCircularProgress-root'));
    expect(screen.queryByText('No profiles found for this user.')).not.toBeInTheDocument();
  });

  test('renders the profiles table with seller names and created dates', async () => {
    state.profiles = [profile(profileIdA, 'Scout Alpha'), profile(profileIdB, 'Scout Beta')];
    renderPage();

    await screen.findByRole('tab', { name: 'Profiles (2)' });
    expect(screen.getByText('Scout Alpha')).toBeInTheDocument();
    expect(screen.getByText('Scout Beta')).toBeInTheDocument();
    expect(screen.getByText(profileIdA)).toBeInTheDocument();
    expect(screen.getByText(profileIdB)).toBeInTheDocument();
    expect(screen.getAllByText(/1\/15\/2025/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: /Transfer/i })).toHaveLength(2);
  });

  test('shows the empty state when the user has no profiles', async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('No profiles found for this user.')).toBeInTheDocument();
    });
  });

  test('shows an error alert when the profiles query fails with a non-MFA error', async () => {
    state.profilesError = new Error('boom profiles');
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Error loading profiles: boom profiles')).toBeInTheDocument();
    });
  });

  test('renders the catalogs tab with type and public chips', async () => {
    state.catalogs = [
      {
        catalogId: 'CAT#managed-1',
        catalogName: 'Managed Catalog',
        catalogType: 'ADMIN_MANAGED',
        isPublic: true,
        products: [1, 2],
      },
      {
        catalogId: 'CAT#user-1',
        catalogName: 'User Catalog',
        catalogType: 'USER',
        isPublic: false,
        products: [],
      },
    ];
    renderPage();

    const catalogsTab = await screen.findByRole('tab', { name: 'Catalogs (2)' });
    fireEvent.click(catalogsTab);

    expect(await screen.findByText('Managed Catalog')).toBeInTheDocument();
    expect(screen.getByText('User Catalog')).toBeInTheDocument();
    expect(screen.getByText('Managed')).toBeInTheDocument();
    expect(screen.getByText('User')).toBeInTheDocument();
    expect(screen.getByText('Yes')).toBeInTheDocument();
    expect(screen.getByText('No')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  test('shows the empty state when the user has no catalogs', async () => {
    renderPage();

    const catalogsTab = await screen.findByRole('tab', { name: 'Catalogs (0)' });
    fireEvent.click(catalogsTab);

    expect(await screen.findByText('No catalogs found for this user.')).toBeInTheDocument();
  });

  test('shows an error alert when the catalogs query fails', async () => {
    state.catalogsError = new Error('boom catalogs');
    renderPage();

    const catalogsTab = await screen.findByRole('tab', { name: 'Catalogs (0)' });
    fireEvent.click(catalogsTab);

    await waitFor(() => {
      expect(screen.getByText('Error loading catalogs: boom catalogs')).toBeInTheDocument();
    });
  });

  test('filters campaigns by the selected profile and renders the campaigns table', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.campaigns = [
      {
        campaignId: 'CAMP#one',
        profileId: profileIdA,
        campaignName: 'Alpha 2025',
        campaignYear: 2025,
        catalogId: 'CAT#user-1',
        startDate: '2025-01-01T00:00:00Z',
        endDate: '2025-12-31T00:00:00Z',
        sharedCampaignCode: 'CODE-ONE',
      },
    ];
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);

    // No profile selected yet: nothing to filter
    expect(await screen.findByText('Total campaigns loaded: 1')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    // Select the profile: its campaign shows up
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));
    expect(await screen.findByText('Alpha 2025')).toBeInTheDocument();
    expect(screen.getByText('2025')).toBeInTheDocument();
    expect(screen.getByText('CAT#user-1')).toBeInTheDocument();
    expect(screen.getByText('CODE-ONE')).toBeInTheDocument();
  });

  test('shows the no-profiles empty state in the campaigns tab', async () => {
    const user = userEvent.setup();
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);

    expect(await screen.findByText('No profiles to manage campaigns for.')).toBeInTheDocument();
  });

  test('shows an error alert when the campaigns query fails', async () => {
    const user = userEvent.setup();
    state.campaignsError = new Error('boom campaigns');
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);

    await waitFor(() => {
      expect(screen.getByText('Error loading campaigns: boom campaigns')).toBeInTheDocument();
    });
  });

  test('shows the empty state when the selected profile has no campaigns', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha'), profile(profileIdB, 'Scout Beta')];
    state.campaigns = [
      {
        campaignId: 'CAMP#two',
        profileId: profileIdB,
        campaignName: 'Beta 2025',
        campaignYear: 2025,
        catalogId: 'CAT#user-1',
        startDate: undefined,
        endDate: undefined,
        sharedCampaignCode: undefined,
      },
    ];
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    expect(
      await screen.findByText('No campaigns found for this profile. (Total campaigns in system: 1)'),
    ).toBeInTheDocument();
  });

  test('edits a campaign shared code and saves it', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.campaigns = [
      {
        campaignId: 'CAMP#one',
        profileId: profileIdA,
        campaignName: 'Alpha 2025',
        campaignYear: 2025,
        catalogId: 'CAT#user-1',
        startDate: undefined,
        endDate: undefined,
        sharedCampaignCode: 'CODE-ONE',
      },
    ];
    state.updateCodeResult = {
      data: { adminUpdateCampaignSharedCode: { campaignId: 'CAMP#one', sharedCampaignCode: 'NEW-CODE' } },
    };
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    const editButton = await screen.findByRole('button', { name: /Edit/ });
    await user.click(editButton);

    const input = screen.getByPlaceholderText(/Enter code or leave blank to remove/i);
    expect(input).toHaveValue('CODE-ONE');

    // Clear button appears once a value is present; clearing empties the field
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(input).toHaveValue('');
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();

    await user.type(input, 'NEW-CODE');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(state.updateCodeMock).toHaveBeenCalledWith({
        variables: { campaignId: 'CAMP#one', sharedCampaignCode: 'NEW-CODE' },
      });
    });
    // onCompleted closes the editor and restores the code cell
    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/Enter code or leave blank to remove/i)).not.toBeInTheDocument();
    });
    expect(screen.getByText('CODE-ONE')).toBeInTheDocument();
  });

  test('saves a cleared shared code as null', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.campaigns = [
      {
        campaignId: 'CAMP#one',
        profileId: profileIdA,
        campaignName: 'Alpha 2025',
        campaignYear: 2025,
        catalogId: 'CAT#user-1',
        startDate: undefined,
        endDate: undefined,
        sharedCampaignCode: 'CODE-ONE',
      },
    ];
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    await user.click(await screen.findByRole('button', { name: /Edit/ }));
    const input = screen.getByPlaceholderText(/Enter code or leave blank to remove/i);
    await user.clear(input);
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(state.updateCodeMock).toHaveBeenCalledWith({
        variables: { campaignId: 'CAMP#one', sharedCampaignCode: null },
      });
    });
  });

  test('cancels a shared code edit and restores the original value', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.campaigns = [
      {
        campaignId: 'CAMP#one',
        profileId: profileIdA,
        campaignName: 'Alpha 2025',
        campaignYear: 2025,
        catalogId: 'CAT#user-1',
        startDate: undefined,
        endDate: undefined,
        sharedCampaignCode: 'CODE-ONE',
      },
    ];
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    await user.click(await screen.findByRole('button', { name: /Edit/ }));
    await user.type(screen.getByPlaceholderText(/Enter code or leave blank to remove/i), 'X');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByPlaceholderText(/Enter code or leave blank to remove/i)).not.toBeInTheDocument();
    expect(screen.getByText('CODE-ONE')).toBeInTheDocument();
    expect(state.updateCodeMock).not.toHaveBeenCalled();
  });

  test('renders the shared campaigns table', async () => {
    const user = userEvent.setup();
    state.sharedCampaigns = [
      {
        sharedCampaignCode: 'SHARED-1',
        catalogId: 'CAT#managed-1',
        campaignName: 'Shared 2025',
        campaignYear: 2025,
        startDate: '2025-06-01T00:00:00Z',
        endDate: '2025-08-31T00:00:00Z',
        unitType: 'Unit',
        unitNumber: 7,
        city: 'Burlington',
        state: 'VT',
        createdBy: 'ACCOUNT#creator',
        createdByName: 'Creator Name',
      },
    ];
    renderPage();

    const sharedTab = await screen.findByRole('tab', { name: 'Shared Campaigns (1)' });
    await user.click(sharedTab);

    expect(await screen.findByText('SHARED-1')).toBeInTheDocument();
    expect(screen.getByText('Shared 2025')).toBeInTheDocument();
    expect(screen.getByText(/Unit #7/)).toBeInTheDocument();
    expect(screen.getByText(/Burlington, VT/)).toBeInTheDocument();
  });

  test('shows the empty state when there are no shared campaigns', async () => {
    const user = userEvent.setup();
    renderPage();

    const sharedTab = await screen.findByRole('tab', { name: 'Shared Campaigns (0)' });
    await user.click(sharedTab);

    expect(await screen.findByText('No shared campaigns found for this user.')).toBeInTheDocument();
  });

  test('shows an error alert when the shared campaigns query fails', async () => {
    const user = userEvent.setup();
    state.sharedCampaignsError = new Error('boom shared');
    renderPage();

    const sharedTab = await screen.findByRole('tab', { name: 'Shared Campaigns (0)' });
    await user.click(sharedTab);

    await waitFor(() => {
      expect(screen.getByText('Error loading shared campaigns: boom shared')).toBeInTheDocument();
    });
  });

  test('lists shares for a profile and revokes access after confirmation', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.shares = [
      {
        shareId: 'SHARE#1',
        profileId: profileIdA,
        targetAccountId: 'ACCOUNT#reader-1',
        targetAccount: {
          accountId: 'ACCOUNT#reader-1',
          email: 'reader@example.com',
          givenName: 'Rita',
          familyName: 'Reader',
        },
        permissions: ['READ', 'WRITE'],
        createdAt: '2025-04-01T00:00:00Z',
      },
      {
        shareId: 'SHARE#2',
        profileId: profileIdA,
        targetAccountId: 'ACCOUNT#reader-2',
        targetAccount: { accountId: 'ACCOUNT#reader-2', email: 'ghost@example.com' },
        permissions: ['READ'],
        createdAt: undefined,
      },
    ];
    renderPage();

    const sharesTab = await screen.findByRole('tab', { name: 'Shares' });
    await user.click(sharesTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    expect(await screen.findByText('reader@example.com')).toBeInTheDocument();
    expect(screen.getByText('Rita Reader')).toBeInTheDocument();
    expect(screen.getAllByText('READ').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('WRITE')).toBeInTheDocument();
    expect(screen.getAllByText('ghost@example.com').length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole('button', { name: /Revoke/i })[0]);
    expect(
      await screen.findByText(/Are you sure you want to revoke reader@example.com's access/i),
    ).toBeInTheDocument();

    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Revoke' }));

    await waitFor(() => {
      expect(state.deleteShareMock).toHaveBeenCalledWith({
        variables: { profileId: profileIdA, targetAccountId: 'ACCOUNT#reader-1' },
      });
    });
  });

  test('cancels the revoke share dialog', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.shares = [
      {
        shareId: 'SHARE#1',
        profileId: profileIdA,
        targetAccountId: 'ACCOUNT#reader-1',
        targetAccount: { accountId: 'ACCOUNT#reader-1', email: 'reader@example.com' },
        permissions: ['READ'],
        createdAt: '2025-04-01T00:00:00Z',
      },
    ];
    renderPage();

    const sharesTab = await screen.findByRole('tab', { name: 'Shares' });
    await user.click(sharesTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    await user.click((await screen.findAllByRole('button', { name: /Revoke/i }))[0]);
    expect(await screen.findByText(/Are you sure you want to revoke/i)).toBeInTheDocument();

    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(screen.queryByText(/Are you sure you want to revoke/i)).not.toBeInTheDocument();
    });
    expect(state.deleteShareMock).not.toHaveBeenCalled();
  });

  test('shows the no-profiles state in the shares tab', async () => {
    const user = userEvent.setup();
    renderPage();

    const sharesTab = await screen.findByRole('tab', { name: 'Shares' });
    await user.click(sharesTab);

    expect(await screen.findByText('No profiles to manage shares for.')).toBeInTheDocument();
  });

  test('transfers profile ownership to the selected user', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.searchResult = {
      data: {
        adminSearchUser: [
          adminUser('ACCOUNT#new-owner', 'new@example.com', 'New Owner'),
          adminUser(accountId, 'self@example.com', 'Self'),
        ],
      },
    };
    renderPage();

    await user.click(await screen.findByRole('button', { name: /Transfer/i }));
    expect(await screen.findByText('Transfer Profile Ownership')).toBeInTheDocument();

    // The search button is disabled until the field has a value
    expect(screen.getByRole('button', { name: 'Search new owner' })).toBeDisabled();

    await user.type(screen.getByLabelText(/New Owner Email/i), 'new@example.com');
    await user.click(screen.getByRole('button', { name: 'Search new owner' }));

    // Search results render; the user's own account is filtered out
    expect(await screen.findByText('new@example.com')).toBeInTheDocument();
    expect(screen.queryByText('self@example.com')).not.toBeInTheDocument();
    expect(screen.getByText('New Owner')).toBeInTheDocument();

    // Confirm transfer is disabled until a user is selected
    expect(screen.getByRole('button', { name: /Confirm Transfer/i })).toBeDisabled();

    await user.click(screen.getByText('new@example.com'));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Confirm Transfer/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /Confirm Transfer/i }));

    await waitFor(() => {
      expect(state.transferMock).toHaveBeenCalledWith({
        variables: { input: { profileId: profileIdA, newOwnerAccountId: 'ACCOUNT#new-owner' } },
      });
    });
    // onCompleted closes the dialog
    await waitFor(() => {
      expect(screen.queryByText('Transfer Profile Ownership')).not.toBeInTheDocument();
    });
  });

  test('supports triggering the owner search with the Enter key', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.searchResult = {
      data: {
        adminSearchUser: [adminUser('ACCOUNT#enter-owner', 'enter@example.com', 'Enter Owner')],
      },
    };
    renderPage();

    await user.click(await screen.findByRole('button', { name: /Transfer/i }));
    const input = await screen.findByLabelText(/New Owner Email/i);
    await user.type(input, 'enter@example.com');
    await user.keyboard('{Enter}');

    expect(await screen.findByText('Enter Owner')).toBeInTheDocument();
    expect(state.searchExecuted).toEqual({ variables: { query: 'enter@example.com' } });
  });

  test('cancels the transfer dialog', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    renderPage();

    await user.click(await screen.findByRole('button', { name: /Transfer/i }));
    expect(await screen.findByText('Transfer Profile Ownership')).toBeInTheDocument();

    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => {
      expect(screen.queryByText('Transfer Profile Ownership')).not.toBeInTheDocument();
    });
  });

  test('logs transfer failures and leaves the dialog open', async () => {
    const user = userEvent.setup();
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.searchResult = {
      data: {
        adminSearchUser: [adminUser('ACCOUNT#new-owner', 'new@example.com', 'New Owner')],
      },
    };
    state.transferMock.mockResolvedValue({ error: new Error('transfer failed'), data: {} });
    renderPage();

    await user.click(await screen.findByRole('button', { name: /Transfer/i }));
    const input = await screen.findByLabelText(/New Owner Email/i);
    await user.type(input, 'new@example.com');
    await user.click(screen.getByRole('button', { name: 'Search new owner' }));
    await user.click(await screen.findByText('New Owner'));
    await user.click(screen.getByRole('button', { name: /Confirm Transfer/i }));

    await waitFor(() => {
      expect(state.transferMock).toHaveBeenCalled();
    });
    // The mutation failed; the dialog remains open and the failure was logged
    expect(screen.getByText('Transfer Profile Ownership')).toBeInTheDocument();
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test('logs shared code update failures and keeps the field in edit mode', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.campaigns = [
      {
        campaignId: 'CAMP#one',
        profileId: profileIdA,
        campaignName: 'Alpha 2025',
        campaignYear: 2025,
        catalogId: 'CAT#user-1',
        startDate: undefined,
        endDate: undefined,
        sharedCampaignCode: 'CODE-ONE',
      },
    ];
    state.updateCodeMock.mockResolvedValue({ data: {}, error: new Error('code update failed') });
    renderPage();

    const campaignsTab = await screen.findByRole('tab', { name: 'Campaigns (0)' });
    await user.click(campaignsTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    await user.click(await screen.findByRole('button', { name: /Edit/ }));
    const input = screen.getByPlaceholderText(/Enter code or leave blank to remove/i);
    await user.clear(input);
    await user.type(input, 'BROKEN');

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(errorSpy).toHaveBeenCalledWith('Update shared code failed:', expect.anything());
    });
    // Edit mode is preserved so the user can retry
    expect(screen.getByPlaceholderText(/Enter code or leave blank to remove/i)).toBeInTheDocument();
    errorSpy.mockRestore();
  });

  test('shows Unknown for shares without a resolvable target account', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.shares = [
      {
        shareId: 'SHARE#ghost',
        profileId: profileIdA,
        targetAccountId: 'ACCOUNT#ghost',
        targetAccount: null,
        permissions: ['READ'],
        createdAt: '2026-01-05T00:00:00Z',
      },
    ];
    renderPage();

    const sharesTab = await screen.findByRole('tab', { name: 'Shares' });
    await user.click(sharesTab);
    await user.click(screen.getByRole('button', { name: 'Scout Alpha' }));

    expect(await screen.findByText('Unknown')).toBeInTheDocument();
    expect(screen.getByText('READ')).toBeInTheDocument();
  });

  test('renders No name for transfer candidates without a display name', async () => {
    const user = userEvent.setup();
    state.profiles = [profile(profileIdA, 'Scout Alpha')];
    state.searchResult = {
      data: {
        adminSearchUser: [
          { accountId: 'ACCOUNT#anon', email: 'anon@example.com', displayName: undefined },
        ],
      },
    };
    renderPage();

    await user.click(await screen.findByRole('button', { name: /Transfer/i }));
    const input = await screen.findByLabelText(/New Owner Email/i);
    await user.type(input, 'anon');
    await user.click(screen.getByRole('button', { name: 'Search new owner' }));

    expect(await screen.findByText('anon@example.com')).toBeInTheDocument();
    expect(screen.getByText('No name')).toBeInTheDocument();
  });
});
