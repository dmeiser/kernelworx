/**
 * CampaignCard component tests
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { CampaignCard } from '../src/components/CampaignCard';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe('CampaignCard', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  test('renders campaign information correctly', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123-456"
          profileId="profile-789"
          campaignName="Fall 2025 Popcorn Sale"
          campaignYear={2025}
          totalOrders={25}
          totalRevenue={1250.5}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('Fall 2025 Popcorn Sale 2025')).toBeInTheDocument();
  });

  test('displays campaign name with year', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Fall Sale"
          campaignYear={2025}
        />
      </BrowserRouter>,
    );

    // CampaignCard displays "campaignName campaignYear" format
    expect(screen.getByText('Fall Sale 2025')).toBeInTheDocument();
  });

  test('shows Active badge by default, driven by isActive rather than the end date', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Active Sale"
          campaignYear={2025}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('Active Sale 2025')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  test('shows Active badge when isActive is explicitly true', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Ongoing Sale"
          campaignYear={2025}
          isActive
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('Ongoing Sale 2025')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  test('does not show Active badge for a deactivated campaign, even without a past end date', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Past Sale"
          campaignYear={2025}
          isActive={false}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('Past Sale 2025')).toBeInTheDocument();
    expect(screen.queryByText('Active')).not.toBeInTheDocument();
  });

  test('displays order count with singular form', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Sale"
          campaignYear={2025}
          totalOrders={1}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('1 order')).toBeInTheDocument();
  });

  test('displays order count with plural form', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Sale"
          campaignYear={2025}
          totalOrders={42}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('42 orders')).toBeInTheDocument();
  });

  test('displays zero orders when totalOrders not provided', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Sale"
          campaignYear={2025}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('0 orders')).toBeInTheDocument();
  });

  test('displays total revenue with 2 decimal places', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Sale"
          campaignYear={2025}
          totalRevenue={1234.567}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('$1234.57 in sales')).toBeInTheDocument();
  });

  test('displays zero revenue when totalRevenue not provided', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Sale"
          campaignYear={2025}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('$0.00 in sales')).toBeInTheDocument();
  });

  test('navigates to campaign detail when View Orders clicked', async () => {
    const user = userEvent.setup();

    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Sale"
          campaignYear={2025}
        />
      </BrowserRouter>,
    );

    const viewButton = screen.getByRole('button', { name: /view orders/i });
    await user.click(viewButton);

    expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-789/campaigns/campaign-123');
  });
});
