/**
 * ProfileCard component tests
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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

  test('renders profile information correctly', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-123"
            sellerName="Scout Alpha"
            isOwner={true}
            permissions={[]}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByText('Scout Alpha')).toBeInTheDocument();
  });

  test('displays Owner badge for owned profiles', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-456"
            sellerName="Scout Beta"
            isOwner={true}
            permissions={[]}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByText('Owner')).toBeInTheDocument();
  });

  test('displays Editor badge for shared profiles with WRITE permission', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-789"
            sellerName="Scout Gamma"
            isOwner={false}
            permissions={['WRITE']}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByText('Editor')).toBeInTheDocument();
  });

  test('displays Read-only badge for shared profiles with READ-only permission', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-999"
            sellerName="Scout Delta"
            isOwner={false}
            permissions={['READ']}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByText('Read-only')).toBeInTheDocument();
  });

  test('shows loading or empty state when no seasons loaded', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-empty"
            sellerName="Scout Epsilon"
            isOwner={true}
            permissions={[]}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    // Either loading spinner or "No seasons yet" should appear eventually
    // For now, just verify the card renders without crashing
    expect(screen.getByText('Scout Epsilon')).toBeInTheDocument();
  });

  test('renders View All Seasons button', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-123"
            sellerName="Scout Alpha"
            isOwner={true}
            permissions={[]}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.getByText('View All Seasons')).toBeInTheDocument();
  });

  test('navigates to all seasons page when View All Seasons clicked', async () => {
    const user = userEvent.setup();

    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-123"
            sellerName="Scout Alpha"
            isOwner={true}
            permissions={[]}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    const button = screen.getByText('View All Seasons');
    await user.click(button);

    expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-123/campaigns');
  });

  test('navigates to scout management when Manage Scout clicked for owners', async () => {
    const user = userEvent.setup();

    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-123"
            sellerName="Scout Alpha"
            isOwner={true}
            permissions={[]}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    const button = screen.getByText('Manage Scout');
    await user.click(button);

    expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-123/manage');
  });

  test('does not show Manage Scout button for non-owners', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-789"
            sellerName="Scout Gamma"
            isOwner={false}
            permissions={['WRITE']}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    expect(screen.queryByText('Manage Scout')).not.toBeInTheDocument();
  });

  test('does not show View Latest Season button when no seasons', () => {
    render(
      <MockedProvider mocks={[]}>
        <BrowserRouter>
          <ProfileCard
            profileId="profile-empty"
            sellerName="Scout Zeta"
            isOwner={true}
            permissions={[]}
          />
        </BrowserRouter>
      </MockedProvider>
    );

    // View Latest Season button should not exist when there are no seasons
    expect(screen.queryByText('View Latest Season')).not.toBeInTheDocument();
  });
});
