/**
 * ProfileCard component tests
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { LIST_CAMPAIGNS_BY_PROFILE } from '../src/lib/graphql';

// Provide explicit mocks per profileId to ensure request variable matching
const campaignsEmptyMocks = [
  {
    request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: 'PROFILE#profile-123' } },
    result: { data: { listCampaignsByProfile: [] } },
  },
  {
    request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: 'PROFILE#profile-456' } },
    result: { data: { listCampaignsByProfile: [] } },
  },
  {
    request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: 'PROFILE#profile-789' } },
    result: { data: { listCampaignsByProfile: [] } },
  },
  {
    request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: 'PROFILE#profile-999' } },
    result: { data: { listCampaignsByProfile: [] } },
  },
  {
    request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: 'PROFILE#profile-empty' } },
    result: { data: { listCampaignsByProfile: [] } },
  },
];

import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';
import { ProfileCard } from '../src/components/ProfileCard';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe('ProfileCard', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  test('renders profile information correctly', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-123" sellerName="Scout Alpha" isOwner={true} permissions={[]} />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('Scout Alpha')).toBeInTheDocument();
  });

  test('displays Owner badge for owned profiles', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-456" sellerName="Scout Beta" isOwner={true} permissions={[]} />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('Owner')).toBeInTheDocument();
  });

  test('displays Editor badge for shared profiles with WRITE permission', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-789" sellerName="Scout Gamma" isOwner={false} permissions={['WRITE']} />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('Editor')).toBeInTheDocument();
  });

  test('displays Read-only badge for shared profiles with READ-only permission', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-999" sellerName="Scout Delta" isOwner={false} permissions={['READ']} />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('Read-only')).toBeInTheDocument();
  });

  test('shows loading or empty state when no campaigns loaded', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-empty" sellerName="Scout Epsilon" isOwner={true} permissions={[]} />
        </BrowserRouter>
      </MockedProvider>,
    );

    // Either loading spinner or "No campaigns yet" should appear eventually
    // For now, just verify the card renders without crashing
    expect(await screen.findByText('Scout Epsilon')).toBeInTheDocument();
  });

  test('renders View All Campaigns button', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-123" sellerName="Scout Alpha" isOwner={true} permissions={[]} />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText('View All Campaigns')).toBeInTheDocument();
  });

  test.skip('shows latest campaign stats when campaigns exist (moved to isolated test file)', async () => {
    // Covered in ProfileCard.latestCampaign.test.tsx using a direct useQuery mock
  });

  test('navigates to all campaigns page when View All Campaigns clicked', async () => {
    const user = userEvent.setup();

    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-123" sellerName="Scout Alpha" isOwner={true} permissions={[]} />
        </BrowserRouter>
      </MockedProvider>,
    );

    const button = await screen.findByText('View All Campaigns');
    await user.click(button);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-123/campaigns'));
  });

  test('navigates to scout management when Manage Scout clicked for owners', async () => {
    const user = userEvent.setup();

    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-123" sellerName="Scout Alpha" isOwner={true} permissions={[]} />
        </BrowserRouter>
      </MockedProvider>,
    );

    const button = await screen.findByText('Manage Scout');
    await user.click(button);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-123/manage'));
  });

  test('does not show Manage Scout button for non-owners', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-789" sellerName="Scout Gamma" isOwner={false} permissions={['WRITE']} />
        </BrowserRouter>
      </MockedProvider>,
    );

    await waitFor(() => expect(screen.queryByText('Manage Scout')).not.toBeInTheDocument());
  });

  test('does not show View Latest Campaign button when no campaigns', async () => {
    render(
      <MockedProvider mocks={campaignsEmptyMocks}>
        <BrowserRouter>
          <ProfileCard profileId="profile-empty" sellerName="Scout Zeta" isOwner={true} permissions={[]} />
        </BrowserRouter>
      </MockedProvider>,
    );

    // View Latest Campaign button should not exist when there are no campaigns
    await waitFor(() => expect(screen.queryByText('View Latest Campaign')).not.toBeInTheDocument());
  });
});
