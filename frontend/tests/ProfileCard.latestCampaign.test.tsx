import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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

import { ProfileCard } from '../src/components/ProfileCard';

const mockLatestCampaign = {
  campaignId: 'campaign-1',
  campaignName: 'Alpha Campaign',
  campaignYear: 2025,
  isActive: true,
};

describe('ProfileCard latest campaign', () => {
  it('shows latest campaign info when latestCampaign prop is provided', async () => {
    render(
      <BrowserRouter>
        <ProfileCard
          profileId="profile-123"
          sellerName="Scout Alpha"
          isOwner={true}
          permissions={[]}
          latestCampaign={mockLatestCampaign}
        />
      </BrowserRouter>,
    );

    expect(await screen.findByText(/Alpha Campaign/)).toBeInTheDocument();
    expect(screen.getByText(/2025/)).toBeInTheDocument();
  });

  it('navigates to latest campaign when View Latest Campaign clicked', async () => {
    const user = userEvent.setup();
    mockNavigate.mockClear();

    render(
      <BrowserRouter>
        <ProfileCard
          profileId="profile-123"
          sellerName="Scout Alpha"
          isOwner={true}
          permissions={[]}
          latestCampaign={mockLatestCampaign}
        />
      </BrowserRouter>,
    );

    const button = await screen.findByText('View Latest Campaign');
    await user.click(button);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-123/campaigns/campaign-1'));
  });
});
