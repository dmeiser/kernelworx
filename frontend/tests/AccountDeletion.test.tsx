/**
 * Account Deletion Component and Hook Tests
 *
 * Verifies:
 * - Stepped deletion of profiles followed by account
 * - Preservation of catalogs (never deleted)
 * - Error reporting and resumption support
 * - Idempotent handling of already-deleted profiles
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { ApolloClient, InMemoryCache } from '@apollo/client';
import { ApolloProvider } from '@apollo/client/react';
import { MockLink } from '@apollo/client/testing';
import { GraphQLError } from 'graphql';
import { DeleteAccountSection } from '../src/components/settings/DeleteAccountSection';
import { apolloClient } from '../src/lib/apollo';
import { LIST_MY_PROFILES, DELETE_SELLER_PROFILE, DELETE_MY_ACCOUNT } from '../src/lib/graphql';

describe('DeleteAccountSection & AccountDeletionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const createListProfilesMock = () => ({
    request: {
      query: LIST_MY_PROFILES,
      variables: {},
    },
    result: {
      data: {
        listMyProfiles: {
          __typename: 'SellerProfileConnection',
          profiles: [
            {
              __typename: 'SellerProfile',
              profileId: 'PROFILE#scout-1',
              sellerName: 'Scout Alex',
              ownerAccountId: 'ACCOUNT#user-1',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: true,
              permissions: [],
              latestCampaign: null,
            },
            {
              __typename: 'SellerProfile',
              profileId: 'PROFILE#scout-2',
              sellerName: 'Scout Ben',
              ownerAccountId: 'ACCOUNT#user-1',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: true,
              permissions: [],
              latestCampaign: null,
            },
          ],
          nextToken: null,
        },
      },
    },
  });

  const createDeleteProfileMock = (profileId: string, error?: string) => {
    if (error) {
      return {
        request: {
          query: DELETE_SELLER_PROFILE,
          variables: { profileId },
        },
        result: {
          errors: [new GraphQLError(error)],
        },
      };
    }
    return {
      request: {
        query: DELETE_SELLER_PROFILE,
        variables: { profileId },
      },
      result: {
        data: {
          deleteSellerProfile: true,
        },
      },
    };
  };

  const createDeleteAccountMock = () => ({
    request: {
      query: DELETE_MY_ACCOUNT,
    },
    result: {
      data: {
        deleteMyAccount: true,
      },
    },
  });

  test('renders warning and notes that catalogs are preserved', () => {
    render(
      <MockedProvider>
        <DeleteAccountSection userEmail="scoutparent@example.com" />
      </MockedProvider>
    );

    expect(screen.getByText('Delete Account')).toBeInTheDocument();
    expect(screen.getByText(/Custom payment methods & QR codes/i)).toBeInTheDocument();
    expect(screen.getByText(/Custom catalogs/i)).toBeInTheDocument();
    expect(screen.getByText(/Catalogs you created will be preserved and never deleted/i)).toBeInTheDocument();
  });

  test('opens dialog and completes stepped deletion successfully', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    render(
      <MockedProvider
        mocks={[
          createListProfilesMock(),
          createDeleteProfileMock('PROFILE#scout-1'),
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="scoutparent@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    // Open dialog
    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));

    expect(screen.getByText('Confirm Account Deletion')).toBeInTheDocument();
    expect(screen.getByText(/Custom catalogs you created are preserved/i)).toBeInTheDocument();

    // Profiles are previewed in confirmation view before deletion begins
    await waitFor(() => {
      expect(screen.getByText('Seller profiles to be deleted (2):')).toBeInTheDocument();
      expect(screen.getByText('Scout Alex')).toBeInTheDocument();
      expect(screen.getByText('Scout Ben')).toBeInTheDocument();
    });

    const deleteButton = screen.getByRole('button', { name: 'Delete Account' });
    expect(deleteButton).toBeDisabled();

    // Type confirmation
    const confirmInput = screen.getByPlaceholderText('Type DELETE to confirm');
    await user.type(confirmInput, 'DELETE');
    expect(deleteButton).toBeEnabled();

    // Start deletion
    await user.click(deleteButton);

    // Should transition to progress view and show profile statuses
    await waitFor(() => {
      expect(screen.getByText('Discover account profiles')).toBeInTheDocument();
      expect(screen.getByText('Found 2 seller profile(s)')).toBeInTheDocument();
      expect(screen.getByText('Profile 1: Scout Alex')).toBeInTheDocument();
      expect(screen.getByText('Profile 2: Scout Ben')).toBeInTheDocument();
      expect(screen.getByText('Account, payment methods & credentials')).toBeInTheDocument();
    });

    // Verify all steps complete with "Deleted" status and final success banner
    await waitFor(
      () => {
        expect(screen.getByText('Account Deleted')).toBeInTheDocument();
        expect(screen.getByText(/Account successfully deleted. You will be signed out momentarily./i)).toBeInTheDocument();
        expect(screen.getAllByText('Deleted')).toHaveLength(3); // Profile 1, Profile 2, Account
        expect(onAccountDeleted).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 }
    );
  });

  test('notifies user on error and allows resuming deletion', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const failingMock = createDeleteProfileMock('PROFILE#scout-1', 'Temporary DynamoDB error');
    const retryMock = createDeleteProfileMock('PROFILE#scout-1');

    render(
      <MockedProvider
        mocks={[
          createListProfilesMock(),
          failingMock,
          retryMock,
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="scoutparent@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    // Open and confirm
    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    // Wait for failure
    await waitFor(() => {
      expect(screen.getByText('Deletion Interrupted')).toBeInTheDocument();
      expect(screen.getAllByText(/Temporary DynamoDB error/i).length).toBeGreaterThan(0);
    });

    // Verify Resume Deletion button is visible
    const resumeButton = screen.getByRole('button', { name: /Resume Deletion/i });
    expect(resumeButton).toBeInTheDocument();

    // Click resume
    await user.click(resumeButton);

    // Deletion should resume and succeed
    await waitFor(
      () => {
        expect(onAccountDeleted).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 }
    );
  });

  test('treats already-deleted profile (not found) as completed', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const notFoundMock = createDeleteProfileMock('PROFILE#scout-1', 'Profile PROFILE#scout-1 not found');

    render(
      <MockedProvider
        mocks={[
          createListProfilesMock(),
          notFoundMock,
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="scoutparent@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    // Should not stop on "not found" error, instead proceeding through scout 2 and account delete
    await waitFor(
      () => {
        expect(onAccountDeleted).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 }
    );
  });

  test('previews empty state when user has no seller profiles', async () => {
    const user = userEvent.setup();
    const emptyProfilesMock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: {},
      },
      result: {
        data: {
          listMyProfiles: {
            __typename: 'SellerProfileConnection',
            profiles: [],
            nextToken: null,
          },
        },
      },
    };

    render(
      <MockedProvider mocks={[emptyProfilesMock, createDeleteAccountMock()]}>
        <DeleteAccountSection userEmail="noprofiles@example.com" />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));

    await waitFor(() => {
      expect(screen.getByText('No seller profiles found.')).toBeInTheDocument();
    });
  });

  test('cancels confirmation view and closes dialog', async () => {
    const user = userEvent.setup();

    render(
      <MockedProvider mocks={[createListProfilesMock()]}>
        <DeleteAccountSection userEmail="cancel@example.com" />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    expect(screen.getByText('Confirm Account Deletion')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => {
      expect(screen.queryByText('Confirm Account Deletion')).not.toBeInTheDocument();
    });
  });

  test('closes dialog on error view close button', async () => {
    const user = userEvent.setup();
    const failingMock = createDeleteProfileMock('PROFILE#scout-1', 'Network error');

    render(
      <MockedProvider mocks={[createListProfilesMock(), failingMock]}>
        <DeleteAccountSection userEmail="errorclose@example.com" />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await waitFor(() => {
      expect(screen.getByText('Seller profiles to be deleted (2):')).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    await waitFor(() => {
      expect(screen.getByText('Deletion Interrupted')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => {
      expect(screen.queryByText('Deletion Interrupted')).not.toBeInTheDocument();
    });
  });

  test('handles discovery failure and displays error alert in preview', async () => {
    const user = userEvent.setup();
    const errorDiscoveryMock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: {},
      },
      result: {
        errors: [new GraphQLError('Failed to fetch profiles')],
      },
    };

    render(
      <MockedProvider mocks={[errorDiscoveryMock]}>
        <DeleteAccountSection userEmail="discfail@example.com" />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));

    await waitFor(() => {
      expect(screen.getByText(/Failed to load seller profiles: Failed to fetch profiles/i)).toBeInTheDocument();
    });
  });

  test('resumes deletion from discovery failure', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const errorDiscoveryMock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: {},
      },
      result: {
        errors: [new GraphQLError('Server down')],
      },
    };

    render(
      <MockedProvider
        mocks={[
          errorDiscoveryMock,
          errorDiscoveryMock,
          createListProfilesMock(),
          createDeleteProfileMock('PROFILE#scout-1'),
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="resumedisc@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await waitFor(() => {
      expect(screen.getByText(/Failed to load seller profiles: Server down/i)).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    await waitFor(() => {
      expect(screen.getByText('Deletion Interrupted')).toBeInTheDocument();
    });

    // Click resume to re-attempt discovery and complete
    await user.click(screen.getByRole('button', { name: /Resume Deletion/i }));

    await waitFor(
      () => {
        expect(onAccountDeleted).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 }
    );
  });

  test('resumes deletion when account finalization fails', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const failingAccountMock = {
      request: {
        query: DELETE_MY_ACCOUNT,
      },
      error: new Error('Account deletion timeout'),
    };

    render(
      <MockedProvider
        mocks={[
          createListProfilesMock(),
          createDeleteProfileMock('PROFILE#scout-1'),
          createDeleteProfileMock('PROFILE#scout-2'),
          failingAccountMock,
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="resumeaccount@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await waitFor(() => {
      expect(screen.getByText('Seller profiles to be deleted (2):')).toBeInTheDocument();
    });

    const deleteButton = screen.getByRole('button', { name: 'Delete Account' });
    const confirmInput = screen.getByPlaceholderText('Type DELETE to confirm');
    await user.type(confirmInput, 'DELETE');
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);

    await waitFor(() => {
      expect(screen.getByText('Discover account profiles')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText('Deletion Interrupted')).toBeInTheDocument();
      expect(screen.getAllByText(/Account deletion timeout/i).length).toBeGreaterThan(0);
    });

    // Resume when all profiles are completed (firstUnfinished === -1)
    await user.click(screen.getByRole('button', { name: /Resume Deletion/i }));

    await waitFor(
      () => {
        expect(onAccountDeleted).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 }
    );
  });

  test('paginates multiple pages of seller profiles', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const page1Mock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: {},
      },
      result: {
        data: {
          listMyProfiles: {
            __typename: 'SellerProfileConnection',
            profiles: [
              {
                __typename: 'SellerProfile',
                profileId: 'PROFILE#page-1',
                sellerName: 'Page 1 Scout',
                ownerAccountId: 'ACCOUNT#user-1',
                createdAt: '2026-01-01T00:00:00Z',
                updatedAt: '2026-01-01T00:00:00Z',
                isOwner: true,
                permissions: [],
                latestCampaign: null,
              },
            ],
            nextToken: 'token-page-2',
          },
        },
      },
    };

    const page2Mock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: { nextToken: 'token-page-2' },
      },
      result: {
        data: {
          listMyProfiles: {
            __typename: 'SellerProfileConnection',
            profiles: [
              {
                __typename: 'SellerProfile',
                profileId: 'PROFILE#page-2',
                sellerName: 'Page 2 Scout',
                ownerAccountId: 'ACCOUNT#user-1',
                createdAt: '2026-01-01T00:00:00Z',
                updatedAt: '2026-01-01T00:00:00Z',
                isOwner: true,
                permissions: [],
                latestCampaign: null,
              },
            ],
            nextToken: null,
          },
        },
      },
    };

    render(
      <MockedProvider
        mocks={[
          page1Mock,
          page2Mock,
          createDeleteProfileMock('PROFILE#page-1'),
          createDeleteProfileMock('PROFILE#page-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="paginated@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));

    // Verify both profiles loaded across pages
    await waitFor(() => {
      expect(screen.getByText('Seller profiles to be deleted (2):')).toBeInTheDocument();
      expect(screen.getByText('Page 1 Scout')).toBeInTheDocument();
      expect(screen.getByText('Page 2 Scout')).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    await waitFor(
      () => {
        expect(onAccountDeleted).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 }
    );
  });

  test('discovers profiles during startDeletion if initial discovery had failed', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const initialErrorMock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: {},
      },
      result: {
        errors: [new GraphQLError('Initial fetch failed')],
      },
    };

    render(
      <MockedProvider
        mocks={[
          initialErrorMock,
          createListProfilesMock(),
          createDeleteProfileMock('PROFILE#scout-1'),
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="startdisc@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await waitFor(() => {
      expect(screen.getByText(/Failed to load seller profiles: Initial fetch failed/i)).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    await waitFor(
      () => {
        expect(onAccountDeleted).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 }
    );
  });

  test('handles discovery failure during resumeDeletion', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const failDiscoveryMock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: {},
      },
      result: {
        errors: [new GraphQLError('Persistent discovery failure')],
      },
    };

    render(
      <MockedProvider
        mocks={[
          failDiscoveryMock,
          failDiscoveryMock,
          failDiscoveryMock,
        ]}
      >
        <DeleteAccountSection userEmail="persistfail@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await waitFor(() => {
      expect(screen.getByText(/Failed to load seller profiles: Persistent discovery failure/i)).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    await waitFor(() => {
      expect(screen.getByText('Deletion Interrupted')).toBeInTheDocument();
    });

    // Click resume to re-attempt discovery which also fails
    await user.click(screen.getByRole('button', { name: /Resume Deletion/i }));

    await waitFor(() => {
      expect(screen.getByText('Deletion Interrupted')).toBeInTheDocument();
      expect(screen.getAllByText(/Persistent discovery failure/i).length).toBeGreaterThan(0);
    });
    expect(onAccountDeleted).not.toHaveBeenCalled();
  });

  test('surfaces discovery GraphQL errors under production errorPolicy "all"', async () => {
    const user = userEvent.setup();

    const errorDiscoveryMock = {
      request: {
        query: LIST_MY_PROFILES,
        variables: {},
      },
      result: {
        errors: [new GraphQLError('Token expired')],
      },
    };

    const client = new ApolloClient({
      link: new MockLink([errorDiscoveryMock, errorDiscoveryMock, errorDiscoveryMock]),
      cache: new InMemoryCache(),
      defaultOptions: apolloClient.defaultOptions,
    });

    render(
      <ApolloProvider client={client}>
        <DeleteAccountSection userEmail="proderror@example.com" />
      </ApolloProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));

    await waitFor(() => {
      expect(screen.getByText(/Failed to load seller profiles: Token expired/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/No seller profiles found\./i)).not.toBeInTheDocument();
  });
});
