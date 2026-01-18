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
          startDate="2025-09-01T00:00:00Z"
          endDate="2025-11-30T00:00:00Z"
          totalOrders={25}
          totalRevenue={1250.5}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('Fall 2025 Popcorn Sale')).toBeInTheDocument();
  });

  test('displays campaign name with year', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Fall Sale"
          campaignYear={2025}
          startDate="2025-09-01T00:00:00Z"
          endDate="2025-11-30T00:00:00Z"
        />
      </BrowserRouter>,
    );

    // CampaignCard displays "campaignName campaignYear" format
    expect(screen.getByText('Fall Sale 2025')).toBeInTheDocument();
  });

  test('renders with startDate prop even though dates are not displayed', () => {
    // CampaignCard accepts startDate but doesn't display it (simplified card view)
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Ongoing Sale"
          campaignYear={2025}
          startDate="2025-09-01T00:00:00Z"
        />
      </BrowserRouter>,
    );

    // Component should render without error
    expect(screen.getByText('Ongoing Sale 2025')).toBeInTheDocument();
  });

  test('shows Active badge for ongoing campaign', () => {
    // Future end date
    const futureDate = new Date();
    futureDate.setFullYear(futureDate.getFullYear() + 1);

    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Active Sale"
          startDate="2025-01-01T00:00:00Z"
          endDate={futureDate.toISOString()}
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  test('shows Active badge when no end date provided', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Ongoing Sale"
          startDate="2025-01-01T00:00:00Z"
        />
      </BrowserRouter>,
    );

    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  test('does not show Active badge for past campaign', () => {
    const pastDate = new Date('2020-01-01T00:00:00Z');

    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Past Sale"
          startDate="2019-09-01T00:00:00Z"
          endDate={pastDate.toISOString()}
        />
      </BrowserRouter>,
    );

    expect(screen.queryByText('Active')).not.toBeInTheDocument();
  });

  test('displays order count with singular form', () => {
    render(
      <BrowserRouter>
        <CampaignCard
          campaignId="campaign-123"
          profileId="profile-789"
          campaignName="Sale"
          startDate="2025-01-01T00:00:00Z"
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
          startDate="2025-01-01T00:00:00Z"
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
          startDate="2025-01-01T00:00:00Z"
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
          startDate="2025-01-01T00:00:00Z"
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
          startDate="2025-01-01T00:00:00Z"
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
          startDate="2025-01-01T00:00:00Z"
        />
      </BrowserRouter>,
    );

    const viewButton = screen.getByRole('button', { name: /view orders/i });
    await user.click(viewButton);

    expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-789/campaigns/campaign-123');
  });
});
