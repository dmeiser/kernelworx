/**
 * SeasonCard component tests
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { SeasonCard } from '../src/components/SeasonCard';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe('SeasonCard', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  test('renders season information correctly', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123-456"
          profileId="profile-789"
          seasonName="Fall 2025 Popcorn Sale"
          startDate="2025-09-01T00:00:00Z"
          endDate="2025-11-30T00:00:00Z"
          totalOrders={25}
          totalRevenue={1250.50}
        />
      </BrowserRouter>
    );

    expect(screen.getByText('Fall 2025 Popcorn Sale')).toBeInTheDocument();
  });

  test('displays formatted date range', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Fall Sale"
          startDate="2025-09-01T00:00:00Z"
          endDate="2025-11-30T00:00:00Z"
        />
      </BrowserRouter>
    );

    // Dates may be off by one day due to timezone conversion
    expect(screen.getByText(/Aug 31, 2025|Sep 1, 2025/i)).toBeInTheDocument();
  });

  test('displays start date only when no end date provided', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Ongoing Sale"
          startDate="2025-09-01T00:00:00Z"
        />
      </BrowserRouter>
    );

    // Should show start date without end date dash
    const dateText = screen.getByText(/Aug 31, 2025|Sep 1, 2025/i);
    expect(dateText).toBeInTheDocument();
  });

  test('shows Active badge for ongoing season', () => {
    // Future end date
    const futureDate = new Date();
    futureDate.setFullYear(futureDate.getFullYear() + 1);

    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Active Sale"
          startDate="2025-01-01T00:00:00Z"
          endDate={futureDate.toISOString()}
        />
      </BrowserRouter>
    );

    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  test('shows Active badge when no end date provided', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Ongoing Sale"
          startDate="2025-01-01T00:00:00Z"
        />
      </BrowserRouter>
    );

    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  test('does not show Active badge for past season', () => {
    const pastDate = new Date('2020-01-01T00:00:00Z');

    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Past Sale"
          startDate="2019-09-01T00:00:00Z"
          endDate={pastDate.toISOString()}
        />
      </BrowserRouter>
    );

    expect(screen.queryByText('Active')).not.toBeInTheDocument();
  });

  test('displays order count with singular form', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Sale"
          startDate="2025-01-01T00:00:00Z"
          totalOrders={1}
        />
      </BrowserRouter>
    );

    expect(screen.getByText('1 order')).toBeInTheDocument();
  });

  test('displays order count with plural form', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Sale"
          startDate="2025-01-01T00:00:00Z"
          totalOrders={42}
        />
      </BrowserRouter>
    );

    expect(screen.getByText('42 orders')).toBeInTheDocument();
  });

  test('displays zero orders when totalOrders not provided', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Sale"
          startDate="2025-01-01T00:00:00Z"
        />
      </BrowserRouter>
    );

    expect(screen.getByText('0 orders')).toBeInTheDocument();
  });

  test('displays total revenue with 2 decimal places', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Sale"
          startDate="2025-01-01T00:00:00Z"
          totalRevenue={1234.567}
        />
      </BrowserRouter>
    );

    expect(screen.getByText('$1234.57 in sales')).toBeInTheDocument();
  });

  test('displays zero revenue when totalRevenue not provided', () => {
    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Sale"
          startDate="2025-01-01T00:00:00Z"
        />
      </BrowserRouter>
    );

    expect(screen.getByText('$0.00 in sales')).toBeInTheDocument();
  });

  test('navigates to season detail when View Orders clicked', async () => {
    const user = userEvent.setup();

    render(
      <BrowserRouter>
        <SeasonCard
          seasonId="season-123"
          profileId="profile-789"
          seasonName="Sale"
          startDate="2025-01-01T00:00:00Z"
        />
      </BrowserRouter>
    );

    const viewButton = screen.getByRole('button', { name: /view orders/i });
    await user.click(viewButton);

    expect(mockNavigate).toHaveBeenCalledWith('/profiles/profile-789/seasons/season-123');
  });
});
