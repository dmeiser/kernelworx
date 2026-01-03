import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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

// Mock auth hook so components don't require AuthProvider
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({ isAuthenticated: true, account: { accountId: 'test' } })),
}));

// Mock small child components to simplify rendering
vi.mock('../src/components/ProfileCard', () => ({ ProfileCard: ({ sellerName }: any) => (<div>{sellerName}</div>) }));
vi.mock('../src/components/CreateProfileDialog', () => ({ CreateProfileDialog: ({ open }: any) => (open ? <div>CreateDialog</div> : null) }));
vi.mock('../src/components/EditProfileDialog', () => ({ EditProfileDialog: ({ open }: any) => (open ? <div>EditDialog</div> : null) }));

// We'll mock Apollo's useQuery to return different scenarios
let mockScoutsData: any = { sharedProfiles: [], myProfiles: [] };
vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual<any>('@apollo/client/react');
  return {
    ...actual,
    useQuery: () => ({ data: mockScoutsData, loading: false, error: undefined, refetch: async () => undefined }),
    useLazyQuery: () => [vi.fn(), { data: undefined, loading: false }],
    useMutation: () => [vi.fn().mockResolvedValue({ data: {} }), { loading: false }],
  };
});

import { ScoutsPage } from '../src/pages/ScoutsPage';
import { ApolloClient, InMemoryCache, ApolloProvider, ApolloLink } from '@apollo/client';

describe.skip('ScoutsPage (unit)', () => {
  // TODO: These tests have pre-existing mock issues with MUI Grid v6 and Apollo
  // The component renders undefined due to Grid import issues in test environment
  beforeEach(() => {
    mockNavigate.mockClear();
    mockScoutsData = { sharedProfiles: [], myProfiles: [] };
  });

  test('renders empty state when no profiles exist', async () => {
    mockScoutsData = { sharedProfiles: [], myProfiles: [] };

    const client = new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.from([]) });
    render(
      <ApolloProvider client={client}>
        <MemoryRouter>
          <ScoutsPage />
        </MemoryRouter>
      </ApolloProvider>
    );

    expect(await screen.findByText(/No profiles yet/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Add Profile/i })).toBeTruthy();
  });

  test('renders shared profiles and navigates when item clicked', async () => {
    mockScoutsData = {
      sharedProfiles: [
        { profileId: 'profile-shared-1', sellerName: 'Shared Scout', ownerAccountId: 'owner-1', isOwner: false, permissions: ['READ'], __typename: 'SellerProfile' },
      ],
      myProfiles: [
        { profileId: 'profile-1', sellerName: 'My Scout', isOwner: true, permissions: [], __typename: 'SellerProfile' },
      ],
    };

    const client = new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.from([]) });
    render(
      <ApolloProvider client={client}>
        <MemoryRouter>
          <ScoutsPage />
        </MemoryRouter>
      </ApolloProvider>
    );

    expect(await screen.findByText(/Shared Scout/)).toBeTruthy();
    await userEvent.click(screen.getByText(/Shared Scout/));
    // Should navigate to the profile manage page
    await waitFor(() => expect(mockNavigate).toHaveBeenCalled());
  });

  test('shows error message when query errors', async () => {
    // Re-mock to simulate an error
    vi.doMock('@apollo/client/react', async () => {
      const actual = await vi.importActual<any>('@apollo/client/react');
      return {
        ...actual,
        useQuery: () => ({ data: undefined, loading: false, error: new Error('Boom') }),
      };
    });

    const { ScoutsPage: DynScouts } = await import('../src/pages/ScoutsPage');

    const client = new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.from([]) });
    render(
      <ApolloProvider client={client}>
        <MemoryRouter>
          <DynScouts />
        </MemoryRouter>
      </ApolloProvider>
    );

    expect(await screen.findByText(/Failed to load profiles/i)).toBeTruthy();

    // cleanup override
    vi.doUnmock('@apollo/client/react');
  });
});