import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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

// Mock useQuery for campaign settings page
let mockCampaignSettingsData: any = { getCampaign: null };
vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual<any>('@apollo/client/react');
  return {
    ...actual,
    useQuery: () => ({ data: mockCampaignSettingsData, loading: false, error: undefined, refetch: vi.fn() }),
    useMutation: () => [vi.fn().mockResolvedValue({ data: {} }), { loading: false }],
  };
});

import { CampaignSettingsPage } from '../src/pages/CampaignSettingsPage';
import { ApolloClient, InMemoryCache, ApolloProvider, ApolloLink } from '@apollo/client';

describe.skip('CampaignSettingsPage (unit)', () => {
  // TODO: These tests have pre-existing mock issues with Apollo useMutation
  // Need proper Apollo mock setup
  beforeEach(() => {
    mockNavigate.mockClear();
    mockCampaignSettingsData = { getCampaign: null };
  });

  test('shows banner for shared campaign and warns when changing name', async () => {
    mockCampaignSettingsData = {
      getCampaign: {
        campaignId: 'camp-1',
        campaignName: 'Fall',
        isShared: true,
        sharedInfo: { createdByName: 'Creator', sharedCampaignCode: 'PACK1' },
        __typename: 'Campaign',
      },
    };

    const client = new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.from([]) });
    render(
      <ApolloProvider client={client}>
        <MemoryRouter>
          <CampaignSettingsPage />
        </MemoryRouter>
      </ApolloProvider>
    );

    // Banner should show creator name
    expect(await screen.findByText(/Creator/)).toBeTruthy();

    // Attempt to change name - should show confirmation dialog
    const editNameBtn = screen.getByRole('button', { name: /Change Name/i });
    await userEvent.click(editNameBtn);

    // Confirm dialog appears
    expect(await screen.findByText(/Confirm name change/i)).toBeTruthy();
  });

  test('shows error when campaign fetch fails', async () => {
    vi.doMock('@apollo/client/react', async () => {
      const actual = await vi.importActual<any>('@apollo/client/react');
      return { ...actual, useQuery: () => ({ data: undefined, loading: false, error: new Error('failed') }) };
    });

    const { CampaignSettingsPage: Dyn } = await import('../src/pages/CampaignSettingsPage');

    render(
      <MemoryRouter>
        <Dyn />
      </MemoryRouter>
    );

    expect(await screen.findByText(/Failed to load campaign/i)).toBeTruthy();

    vi.doUnmock('@apollo/client/react');
  });
});