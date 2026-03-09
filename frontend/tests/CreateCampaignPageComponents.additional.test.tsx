/**
 * Tests for CreateCampaignPageComponents
 */

import { describe, test, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  LoadingState,
  CampaignNotFoundError,
  SharedCampaignBanner,
} from '../src/pages/CreateCampaignPageComponents';

describe('CreateCampaignPageComponents', () => {
  describe('LoadingState', () => {
    test('renders a loading spinner', () => {
      render(<LoadingState />);
      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });
  });

  describe('CampaignNotFoundError', () => {
    test('renders error message', () => {
      const onReturnClick = vi.fn();
      render(<CampaignNotFoundError message="Not found" onReturnClick={onReturnClick} />);
      expect(screen.getByText('Campaign Not Found')).toBeInTheDocument();
    });

    test('clicking Go to Profiles calls onReturnClick', async () => {
      const user = userEvent.setup();
      const onReturnClick = vi.fn();
      render(<CampaignNotFoundError message="Not found" onReturnClick={onReturnClick} />);
      await user.click(screen.getByText('Go to Profiles'));
      expect(onReturnClick).toHaveBeenCalled();
    });
  });

  describe('SharedCampaignBanner', () => {
    const sharedCampaign = {
      sharedCampaignCode: 'SC-123',
      campaignName: 'Fall Fundraiser',
      campaignYear: 2025,
      catalogId: 'CAT~1',
      unitType: 'Pack',
      unitNumber: 42,
      city: 'Portland',
      state: 'OR',
      isActive: true,
      createdByAccountId: 'ACCOUNT#user1',
      createdByName: 'John Smith',
      creatorMessage: 'Welcome to our campaign!',
    };

    test('renders creator name', () => {
      render(<SharedCampaignBanner sharedCampaign={sharedCampaign} />);
      expect(screen.getByText(/Campaign by John Smith/i)).toBeInTheDocument();
    });

    test('renders creator message', () => {
      render(<SharedCampaignBanner sharedCampaign={sharedCampaign} />);
      expect(screen.getByText(/"Welcome to our campaign!"/i)).toBeInTheDocument();
    });

    test('renders unit info', () => {
      render(<SharedCampaignBanner sharedCampaign={sharedCampaign} />);
      expect(screen.getByText(/Pack 42/)).toBeInTheDocument();
      expect(screen.getByText(/Portland, OR/)).toBeInTheDocument();
    });

    test('does not render creator message if absent', () => {
      const { creatorMessage: _, ...noMsg } = sharedCampaign;
      render(<SharedCampaignBanner sharedCampaign={noMsg as typeof sharedCampaign} />);
      expect(screen.queryByText(/Welcome/)).not.toBeInTheDocument();
    });
  });
});
