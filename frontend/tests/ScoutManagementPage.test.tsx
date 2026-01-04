import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// Route parameter and DB id for test
const RAW_ID = 'dd69b3bd-5978-419e-9e55-f7c85817e020';
const DB_ID = `PROFILE#${RAW_ID}`;

// Mock useQuery before importing component
// Test-controlled fixtures for queries and mutation spies
let testInvites: any[] = [];
let testShares: any[] = [];
let testProfileData: any = {
  profileId: DB_ID,
  sellerName: 'Tom Test',
  ownerAccountId: 'ACCOUNT#abc',
  createdAt: new Date().toISOString(),
  isOwner: true,
  permissions: ['READ', 'WRITE'],
};
let testLoading = false;

const updateProfileMock = vi.fn().mockResolvedValue({ data: {} });
const deleteProfileMock = vi.fn().mockResolvedValue({ data: {} });
const createInviteMock = vi.fn().mockResolvedValue({ data: { createProfileInvite: { inviteCode: 'INV123' } } });
const deleteInviteMock = vi.fn().mockResolvedValue({ data: {} });

vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual('@apollo/client/react');

  // Helper: Create profile query result based on test state
  const getProfileResult = () => {
    if (testLoading) return { data: null, loading: true, refetch: vi.fn() };
    if (!testProfileData) return { data: null, loading: false, refetch: vi.fn() };
    return { data: { getProfile: testProfileData }, loading: false, refetch: vi.fn() };
  };

  const queryHandlers: Record<string, () => any> = {
    GetProfile: getProfileResult,
    ListInvitesByProfile: () => ({ data: { listInvitesByProfile: testInvites }, loading: false, refetch: vi.fn() }),
    ListSharesByProfile: () => ({ data: { listSharesByProfile: testShares }, loading: false }),
  };

  // Helper: Extract operation name from query/mutation
  const getOpName = (query: any): string | undefined =>
    query?.definitions?.find((d: any) => d?.kind === 'OperationDefinition')?.name?.value;

  // Default query response
  const defaultQueryResult = () => ({ data: null, loading: false });

  const useQuery = (query: any) => {
    const handler = queryHandlers[getOpName(query) ?? ''] ?? defaultQueryResult;
    return handler();
  };

  const createMutationHandler =
    (mockFn: any, onCompletedData: any = {}) =>
    (opts: any) => [
      async (optsVars: any) => {
        const res = await mockFn(optsVars);
        opts?.onCompleted?.(res?.data ?? onCompletedData);
        return res;
      },
      { loading: false, data: null },
    ];

  const mutationHandlers: Record<string, (opts: any) => any> = {
    UpdateSellerProfile: (opts) => createMutationHandler(updateProfileMock, {})(opts),
    DeleteSellerProfile: (opts) => createMutationHandler(deleteProfileMock, {})(opts),
    CreateProfileInvite: (opts) => createMutationHandler(createInviteMock)(opts),
    DeleteProfileInvite: (opts) => createMutationHandler(deleteInviteMock, {})(opts),
  };

  // Default mutation handler
  const defaultMutationHandler = () => [vi.fn().mockResolvedValue({ data: {} }), { loading: false, data: null }];

  const useMutation = (mutation: any, opts: any) => {
    const handler = mutationHandlers[getOpName(mutation) ?? ''];
    return handler ? handler(opts) : defaultMutationHandler();
  };

  return {
    ...actual,
    useQuery,
    useMutation,
  };
});

import { ScoutManagementPage } from '../src/pages/ScoutManagementPage';

describe('ScoutManagementPage', () => {
  beforeEach(() => {
    // reset fixtures & mocks
    testInvites = [];
    testShares = [];
    testProfileData = {
      profileId: DB_ID,
      sellerName: 'Tom Test',
      ownerAccountId: 'ACCOUNT#abc',
      createdAt: new Date().toISOString(),
      isOwner: true,
      permissions: ['READ', 'WRITE'],
    };
    testLoading = false;

    updateProfileMock.mockClear();
    deleteProfileMock.mockClear();
    createInviteMock.mockClear();
    deleteInviteMock.mockClear();

    // Ensure clipboard is available for tests; spy if it exists otherwise define it
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined as any);
    } else {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: vi.fn().mockResolvedValue(undefined) },
        configurable: true,
      });
    }
  });

  it('loads and displays profile when route provides raw id (page normalizes to PROFILE#)', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // Wait for seller name to populate the Seller Name input
    await waitFor(() => expect((screen.getByLabelText('Seller Name') as HTMLInputElement).value).toBe('Tom Test'));
  });

  it('creates an invite and allows copying the generated code', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    const createButton = await screen.findByRole('button', { name: /Generate New Invite/i });
    expect(createButton).toBeInTheDocument();

    await user.click(createButton);

    // createInviteMock should have been called
    await waitFor(() => expect(createInviteMock).toHaveBeenCalled());

    // New invite alert should show invite code
    expect(await screen.findByText(/New Invite Code:/i)).toBeInTheDocument();
    expect(screen.getByText(/INV123/)).toBeInTheDocument();

    // Click the Copy button — ensure the UI shows the copy state
    const copyButton = screen.getByRole('button', { name: /Copy/i });
    await user.click(copyButton);

    // Button should display 'Copied!' while copied
    expect(await screen.findByRole('button', { name: /Copied!/i })).toBeTruthy();
  });

  it('shows invites table with Active and Expired statuses and can delete an invite', async () => {
    // Prepare invites: one active, one expired
    const now = Date.now();
    const future = new Date(now + 1000 * 60 * 60 * 24).toISOString();
    const past = new Date(now - 1000 * 60 * 60 * 24).toISOString();

    testInvites = [
      { inviteCode: 'INV-ACTIVE', permissions: ['READ'], createdAt: new Date().toISOString(), expiresAt: future },
      { inviteCode: 'INV-EXPIRED', permissions: ['READ'], createdAt: new Date().toISOString(), expiresAt: past },
    ];

    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // Both invite codes should be visible
    expect(await screen.findByText('INV-ACTIVE')).toBeInTheDocument();
    expect(await screen.findByText('INV-EXPIRED')).toBeInTheDocument();

    // Status chips should show Active and Expired
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Expired')).toBeInTheDocument();

    // Click delete on INV-ACTIVE row
    const user = userEvent.setup();
    const row = screen.getByText('INV-ACTIVE').closest('tr') as HTMLElement;
    const buttons = Array.from(row.querySelectorAll('button'));
    const deleteBtn = buttons[buttons.length - 1];
    expect(deleteBtn).toBeTruthy();
    await user.click(deleteBtn as HTMLElement);

    // Confirmation dialog should appear
    expect(await screen.findByText(/Delete Invite Code\?/i)).toBeInTheDocument();

    // Click Delete in dialog
    const confirmDelete = screen.getByRole('button', { name: /^Delete$/i });
    await user.click(confirmDelete);

    // deleteInviteMock should have been called
    await waitFor(() => expect(deleteInviteMock).toHaveBeenCalled());
  });

  it('allows deleting the profile', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // Delete profile flow: open danger dialog and confirm
    const user = userEvent.setup();
    const deleteScoutBtn = await screen.findByRole('button', { name: /Delete Scout/i });
    await user.click(deleteScoutBtn);

    expect(await screen.findByText(/Delete Seller Profile\?/i)).toBeInTheDocument();

    const confirmDelete = screen.getByRole('button', { name: /Delete Permanently/i });
    await user.click(confirmDelete);

    await waitFor(() => expect(deleteProfileMock).toHaveBeenCalled());
  });

  it('renders shares section when there are shares', async () => {
    testShares = [
      {
        shareId: 's1',
        profileId: DB_ID,
        targetAccountId: 'acct#1',
        targetAccount: { email: 'jane@example.com', givenName: 'Jane', familyName: 'Doe' },
        permissions: ['READ'],
        createdAt: new Date().toISOString(),
      },
    ];

    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Who Has Access/i)).toBeInTheDocument();
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
  });

  it('disables Save Changes when name is unchanged', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const saveBtn = await screen.findByRole('button', { name: /Save Changes/i });
    expect(saveBtn).toBeDisabled();
  });

  it('disables Generate New Invite when no permissions selected', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    const readCheckbox = await screen.findByLabelText('Read (view campaigns and orders)');
    await user.click(readCheckbox);

    const createButton = screen.getByRole('button', { name: /Generate New Invite/i });
    expect(createButton).toBeDisabled();
  });

  it('create invite resets permissions to default READ', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    const readCheckbox = (await screen.findByLabelText('Read (view campaigns and orders)')) as HTMLInputElement;
    const writeCheckbox = screen.getByLabelText('Write (edit campaigns and orders)') as HTMLInputElement;

    // Make permissions = [WRITE]
    if (readCheckbox.checked) await user.click(readCheckbox);
    if (!writeCheckbox.checked) await user.click(writeCheckbox);

    const createButton = screen.getByRole('button', { name: /Generate New Invite/i });
    await user.click(createButton);
    await waitFor(() => expect(createInviteMock).toHaveBeenCalled());

    // After create, defaults should be reset to READ only
    expect((screen.getByLabelText('Read (view campaigns and orders)') as HTMLInputElement).checked).toBeTruthy();
    expect((screen.getByLabelText('Write (edit campaigns and orders)') as HTMLInputElement).checked).toBeFalsy();
  });

  it('copies invite code from table row to clipboard', async () => {
    testInvites = [
      {
        inviteCode: 'INV-ROW',
        permissions: ['READ'],
        createdAt: new Date().toISOString(),
        expiresAt: new Date(Date.now() + 100000).toISOString(),
      },
    ];
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // Find the row and click the first icon (copy)
    const row = await screen.findByText('INV-ROW');
    const tr = row.closest('tr') as HTMLElement;
    const buttons = Array.from(tr.querySelectorAll('button')) as HTMLButtonElement[];
    const copyBtn = buttons[0];
    await userEvent.click(copyBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('INV-ROW');
  });

  it('cancelling delete invite does not call delete mutation', async () => {
    testInvites = [
      {
        inviteCode: 'INV-DEL',
        permissions: ['READ'],
        createdAt: new Date().toISOString(),
        expiresAt: new Date(Date.now() + 100000).toISOString(),
      },
    ];

    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    const row = await screen.findByText('INV-DEL');
    const tr = row.closest('tr') as HTMLElement;
    const buttons = Array.from(tr.querySelectorAll('button')) as HTMLButtonElement[];
    const deleteBtn = buttons[buttons.length - 1];
    await user.click(deleteBtn);

    // Click Cancel
    const cancelBtn = await screen.findByRole('button', { name: /^Cancel$/i });
    await user.click(cancelBtn);

    expect(deleteInviteMock).not.toHaveBeenCalled();
  });

  it('cancelling delete profile does not call delete mutation', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    const deleteScoutBtn = await screen.findByRole('button', { name: /Delete Scout/i });
    await user.click(deleteScoutBtn);

    // Confirm dialog is open
    expect(await screen.findByText(/Delete Seller Profile\?/i)).toBeInTheDocument();

    // Click Cancel
    const cancelBtn = screen.getByRole('button', { name: /^Cancel$/i });
    await user.click(cancelBtn);

    // Dialog should close
    await waitFor(() => {
      expect(screen.queryByText(/Delete Seller Profile\?/i)).not.toBeInTheDocument();
    });

    // Delete mutation should not have been called
    expect(deleteProfileMock).not.toHaveBeenCalled();
  });

  it('shows no active invites message when there are none', async () => {
    testInvites = [];
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/No active invites/i)).toBeInTheDocument();
  });

  it('displays loading spinner when profile load is in-progress', async () => {
    testLoading = true;
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole('progressbar')).toBeTruthy();
  });

  it('shows Profile not found when profile is missing', async () => {
    testProfileData = null;
    testLoading = false;

    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Profile not found/i)).toBeInTheDocument();
  });

  it('navigates to /scouts after deleting profile', async () => {
    render(
      <MemoryRouter initialEntries={[`/scouts/${encodeURIComponent(RAW_ID)}/manage`]}>
        <Routes>
          <Route path="/scouts/:profileId/manage" element={<ScoutManagementPage />} />
          <Route path="/scouts" element={<div>ScoutList</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    const deleteScoutBtn = await screen.findByRole('button', { name: /Delete Scout/i });
    await user.click(deleteScoutBtn);

    const confirmDelete = await screen.findByRole('button', { name: /Delete Permanently/i });
    await user.click(confirmDelete);

    // After completion, we should have navigated to the /scouts route
    expect(await screen.findByText('ScoutList')).toBeInTheDocument();
  });
});
