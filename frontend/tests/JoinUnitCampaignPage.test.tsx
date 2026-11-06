import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { vi, beforeEach } from 'vitest';
import { LIST_MY_PROFILES, LIST_CAMPAIGNS_BY_PROFILE, JOIN_UNIT_CAMPAIGN } from '../src/lib/graphql';
import JoinUnitCampaignPage from '../src/pages/JoinUnitCampaignPage';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    account: { accountId: 'devon', email: 'devon@fixtures.kernelworx.test', givenName: 'Devon' },
    loading: false,
    isAuthenticated: true,
    isAdmin: false,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const match = () => true;
// The fixtures use the REAL canonical id shape (PROFILE#<id> / CAMPAIGN#<id>), so the
// post-join route's prefix strip is genuinely exercised (unprefixed fixtures masked it).
const profile = (profileId: string, sellerName: string) => ({
  __typename: 'SellerProfile',
  profileId: `PROFILE#${profileId}`,
  sellerName,
  latestCampaign: null,
});
const campaign = (campaignId: string, campaignName: string, campaignYear: number) => ({
  __typename: 'Campaign',
  campaignId: `CAMPAIGN#${campaignId}`,
  campaignName,
  campaignYear,
});

function renderPage(mocks: unknown[]) {
  return render(
    <MockedProvider mocks={mocks as never} defaultOptions={{ watchQuery: { fetchPolicy: 'no-cache' } }}>
      <JoinUnitCampaignPage />
    </MockedProvider>,
  );
}

async function selectCampaign(user: ReturnType<typeof userEvent.setup>, name: string) {
  fireEvent.mouseDown(screen.getByLabelText(/Your campaign to join/i));
  await user.click(await screen.findByRole('option', { name: new RegExp(name, 'i') }));
}

beforeEach(() => {
  mockNavigate.mockClear();
});

it('shows an empty state when the account has no profiles', async () => {
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: { data: { listMyProfiles: { profiles: [], nextToken: null } } },
    },
  ]);

  expect(await screen.findByText(/No profiles/i)).toBeInTheDocument();
});

it('joins a unit campaign by code and routes to the profile campaigns', async () => {
  const user = userEvent.setup();
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: { data: { listMyProfiles: { profiles: [profile('prof-1', 'Aurora Pack 3149')], nextToken: null } } },
    },
    {
      request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: match },
      result: {
        data: { listCampaignsByProfile: { campaigns: [campaign('camp-1', '2026-27 Summer', 2026)], nextToken: null } },
      },
    },
    {
      request: { query: JOIN_UNIT_CAMPAIGN, variables: match },
      result: {
        data: {
          joinUnitCampaign: {
            __typename: 'UnitCampaignMembership',
            campaignId: 'camp-1',
            profileId: 'prof-1',
            status: 'JOINED',
            unitCampaignId: 'uc-1',
            unitId: 'unit-1',
            version: 1,
          },
        },
      },
    },
  ]);

  await screen.findByLabelText(/Your campaign to join/i);
  await selectCampaign(user, '2026-27 Summer');
  fireEvent.change(screen.getByLabelText(/Join code/i), { target: { value: 'JOIN-ABC' } });
  await user.click(screen.getByRole('button', { name: /Join/ }));

  // The profileId is the canonical PROFILE#prof-1; the post-join route strips the prefix
  // to /scouts/prof-1/campaigns (regression: navigating with the raw PROFILE# id parsed
  // the # as a URL fragment and bounced to the catch-all route).
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/scouts/prof-1/campaigns'));
});

it('requires a campaign and join code before submitting', async () => {
  const user = userEvent.setup();
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: { data: { listMyProfiles: { profiles: [profile('prof-1', 'Aurora Pack 3149')], nextToken: null } } },
    },
    {
      request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: match },
      result: {
        data: { listCampaignsByProfile: { campaigns: [campaign('camp-1', '2026-27 Summer', 2026)], nextToken: null } },
      },
    },
  ]);

  await screen.findByLabelText(/Your campaign to join/i);
  await selectCampaign(user, '2026-27 Summer');
  await user.click(screen.getByRole('button', { name: /Join/ }));

  expect(await screen.findByText(/Select a campaign and enter the join code/i)).toBeInTheDocument();
});

it('surfaces a server error when the join code is rejected', async () => {
  const user = userEvent.setup();
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: { data: { listMyProfiles: { profiles: [profile('prof-1', 'Aurora Pack 3149')], nextToken: null } } },
    },
    {
      request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: match },
      result: {
        data: { listCampaignsByProfile: { campaigns: [campaign('camp-1', '2026-27 Summer', 2026)], nextToken: null } },
      },
    },
    {
      request: { query: JOIN_UNIT_CAMPAIGN, variables: match },
      result: { errors: [new GraphQLError('The join code is not valid', { extensions: { errorCode: 'FORBIDDEN' } })] },
    },
  ]);

  await screen.findByLabelText(/Your campaign to join/i);
  await selectCampaign(user, '2026-27 Summer');
  fireEvent.change(screen.getByLabelText(/Join code/i), { target: { value: 'JOIN-ABC' } });
  await user.click(screen.getByRole('button', { name: /Join/ }));

  expect(await screen.findByRole('alert')).toBeInTheDocument();
});

it('surfaces a campaign-load failure with a Retry and never shows the empty state', async () => {
  const user = userEvent.setup();
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: { data: { listMyProfiles: { profiles: [profile('prof-1', 'Aurora Pack 3149')], nextToken: null } } },
    },
    {
      request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: match },
      result: {
        errors: [new GraphQLError('The campaigns are unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })],
      },
    },
  ]);

  // The campaign load failure surfaces with a Retry, not the "no campaigns" empty state.
  expect(await screen.findByRole('button', { name: /Retry/i })).toBeInTheDocument();
  expect(await screen.findByText(/The campaigns are unavailable\./i)).toBeInTheDocument();
  expect(screen.queryByText(/This profile has no campaigns yet/i)).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Retry/i }));
});

it('shows the empty state when the selected profile has no campaigns', async () => {
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: { data: { listMyProfiles: { profiles: [profile('prof-1', 'Aurora Pack 3149')], nextToken: null } } },
    },
    {
      request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: match },
      result: { data: { listCampaignsByProfile: { campaigns: [], nextToken: null } } },
    },
  ]);

  expect(await screen.findByText(/This profile has no campaigns yet/i)).toBeInTheDocument();
});

it('switches the profile and resets the selected campaign', async () => {
  const user = userEvent.setup();
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: {
        data: {
          listMyProfiles: {
            profiles: [profile('prof-1', 'Aurora Pack 3149'), profile('prof-2', 'Denver Crew 7')],
            nextToken: null,
          },
        },
      },
    },
    {
      request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: match },
      result: {
        data: { listCampaignsByProfile: { campaigns: [campaign('camp-1', '2026-27 Summer', 2026)], nextToken: null } },
      },
    },
  ]);

  await screen.findByLabelText(/Your campaign to join/i);
  await selectCampaign(user, '2026-27 Summer');
  // Selecting a campaign enables the join-code field.
  expect(screen.getByLabelText(/Join code/i)).toBeEnabled();

  // Switch the profile — handleProfileChange resets the selected campaign.
  fireEvent.mouseDown(screen.getByLabelText(/Your profile/i));
  await user.click(await screen.findByRole('option', { name: /Denver Crew 7/i }));

  // The selected campaign was reset, so the join-code field is disabled again.
  await waitFor(() => expect(screen.getByLabelText(/Join code/i)).toBeDisabled());
});

it('surfaces a profile-load failure', async () => {
  renderPage([
    {
      request: { query: LIST_MY_PROFILES, variables: match },
      result: { errors: [new GraphQLError('Profiles are unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })] },
    },
  ]);

  expect(await screen.findByText(/Profiles are unavailable\./i)).toBeInTheDocument();
});
