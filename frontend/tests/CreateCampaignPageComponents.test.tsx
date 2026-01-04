/**
 * CreateCampaignPageComponents unit tests
 */

import { describe, test, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DiscoveredCampaignAlert } from '../src/pages/CreateCampaignPageComponents';

describe('CreateCampaignPageComponents', () => {
  describe('DiscoveredCampaignAlert', () => {
    test('renders with correct campaign info and calls onUseCampaign when clicked', async () => {
      const user = userEvent.setup();
      const mockOnUseCampaign = vi.fn();

      render(
        <DiscoveredCampaignAlert
          campaignName="Fall Fundraiser"
          campaignYear={2025}
          unitType="Pack"
          unitNumber="123"
          city="Springfield"
          state="IL"
          createdByName="Jane Doe"
          onUseCampaign={mockOnUseCampaign}
        />,
      );

      // Check that the alert displays correct info
      expect(screen.getByText(/Existing Campaign Found!/i)).toBeInTheDocument();
      expect(screen.getByText(/Fall Fundraiser 2025/i)).toBeInTheDocument();
      expect(screen.getByText(/Pack 123/i)).toBeInTheDocument();
      expect(screen.getByText(/Springfield, IL/i)).toBeInTheDocument();
      expect(screen.getByText(/Jane Doe/i)).toBeInTheDocument();

      // Click "Use Campaign" button
      const useButton = screen.getByRole('button', { name: /Use Campaign/i });
      await user.click(useButton);

      expect(mockOnUseCampaign).toHaveBeenCalledTimes(1);
    });
  });
});
