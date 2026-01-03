import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

// Mock Apollo useQuery to return campaigns data for this test
vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual('@apollo/client/react')
  return {
    ...actual,
    useQuery: () => {
      // Return campaigns data for LIST_CAMPAIGNS_BY_PROFILE
      return {
        data: {
          listCampaignsByProfile: [
            {
              campaignId: 'campaign-1',
              campaignName: 'Alpha Campaign',
              campaignYear: 2025,
              totalOrders: 10,
              totalRevenue: 200.5,
              startDate: '2025-09-01T00:00:00.000Z',
              __typename: 'Campaign',
            },
            {
              campaignId: 'campaign-2',
              campaignName: 'Beta Campaign',
              campaignYear: 2024,
              totalOrders: 5,
              totalRevenue: 50.0,
              startDate: '2024-05-01T00:00:00.000Z',
              __typename: 'Campaign',
            },
          ],
        },
        loading: false,
      }
    },
  }
})

import { ProfileCard } from '../src/components/ProfileCard'

describe('ProfileCard latest campaign', () => {
  it('shows latest campaign stats when campaigns exist', async () => {
    render(
      <BrowserRouter>
        <ProfileCard
          profileId="profile-123"
          sellerName="Scout Alpha"
          isOwner={true}
          permissions={[]}
        />
      </BrowserRouter>
    )

    expect(await screen.findByText(/Alpha Campaign/)).toBeInTheDocument()
    expect(screen.getByText(/\$200.50/)).toBeInTheDocument()
  })
})