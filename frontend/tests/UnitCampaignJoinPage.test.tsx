/**
 * The Scout-side join screen (§1.6.3) — Avery–Devon join and Emery-independent.
 *
 * Avery hands Devon a join code; Devon enrols his own Scout profile against it. What
 * the code buys is exactly the projection the server answers: Unit name, campaign
 * name and year, catalog name, open or closed. The roster, the inventory, and every
 * other Scout stay unanswerable — so a join writes one Scout's campaign and cannot
 * be walked to discover anyone else's.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { UnitCampaignJoinPage } from '../src/pages/UnitCampaignJoinPage';
import { GET_UNIT_CAMPAIGN_JOIN_INFO, JOIN_UNIT_CAMPAIGN, LIST_MY_PROFILES, LIST_MY_SHARES } from '../src/lib/graphql';
import { joinPreviewFixture, membershipFixture, scoutProfileFixture } from './helpers/unitFixtures';
import { chooseOption, typeInto } from './helpers/unitUi';

const JOIN_CODE = 'JOIN1234CODE5678';
const PROFILES_PAGE = { limit: 100, nextToken: undefined };

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

const devon = scoutProfileFixture();
const emery = scoutProfileFixture({
  profileId: 'PROFILE#emery',
  ownerAccountId: 'ACCOUNT#emery',
  sellerName: 'Emery Scout',
  isOwner: false,
  latestCampaign: {
    __typename: 'Campaign',
    campaignId: 'CAMPAIGN#emery',
    campaignName: 'Emery 2026',
    campaignYear: 2026,
    isActive: true,
  },
});

function profilesQuery(profiles: unknown[]) {
  return {
    request: { query: LIST_MY_PROFILES, variables: PROFILES_PAGE },
    result: { data: { listMyProfiles: { __typename: 'ProfileConnection', profiles, nextToken: null } } },
  };
}

const joinInfoQuery = {
  request: { query: GET_UNIT_CAMPAIGN_JOIN_INFO, variables: { joinCode: JOIN_CODE } },
  result: { data: { unitCampaignJoinInfo: joinPreviewFixture() } },
};

async function enterCode(user: ReturnType<typeof userEvent.setup>) {
  await typeInto('join-code-input', JOIN_CODE, user);
  await user.click(await screen.findByTestId('lookup-join-code'));
}

function sharesQuery(shares: unknown[]) {
  return { request: { query: LIST_MY_SHARES, variables: {} }, result: { data: { listMyShares: shares } } };
}

function sharedProfileFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'SharedProfile',
    profileId: 'PROFILE#shared-write',
    ownerAccountId: 'ACCOUNT#another',
    sellerName: 'Shared Scout',
    unitType: 'Pack',
    unitNumber: 3149,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    isOwner: false,
    permissions: ['WRITE'],
    latestCampaign: {
      __typename: 'Campaign',
      campaignId: 'CAMPAIGN#shared-write',
      campaignName: 'Shared 2026',
      campaignYear: 2026,
      isActive: true,
    },
    ...overrides,
  };
}

function renderPage(mocks: unknown[]) {
  // The page reads shares alongside owned profiles; a test that does not care about
  // them still has to answer the read, or the picker's list is only half a list.
  const withShares = [...mocks, sharesQuery([])] as never[];
  render(
    <MockedProvider mocks={withShares}>
      <UnitCampaignJoinPage />
    </MockedProvider>,
  );
}

describe('UnitCampaignJoinPage', () => {
  it('answers a join code with only the preview the server projects', async () => {
    renderPage([profilesQuery([devon, emery]), joinInfoQuery]);
    const user = userEvent.setup();

    await enterCode(user);

    const preview = await screen.findByTestId('join-preview');
    expect(within(preview).getByText('Pack 3149 (Springfield, IL) · 2026 · Popcorn 2026')).toBeInTheDocument();
    // Nothing about the campaign's people is reachable from a code.
    expect(preview.textContent).not.toContain('PROFILE#');
    expect(preview.textContent).not.toContain('ACCOUNT#');
  });

  it('Devon joins Avery’s Unit Campaign with his own Scout profile', async () => {
    const joined = membershipFixture({ status: 'ACTIVE' });
    const mocks = [
      profilesQuery([devon, emery]),
      joinInfoQuery,
      {
        request: {
          query: JOIN_UNIT_CAMPAIGN,
          variables: {
            input: { joinCode: JOIN_CODE, campaignId: 'CAMPAIGN#devon', idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { joinUnitCampaign: joined } },
      },
      profilesQuery([devon, emery]),
    ];
    renderPage(mocks);
    const user = userEvent.setup();

    await enterCode(user);
    await chooseOption('join-profile', 'Devon Scout · Devon 2026', user);
    await user.click(await screen.findByTestId('submit-join'));

    expect(await screen.findByTestId('join-success')).toHaveTextContent(
      'Joined Fall Popcorn. Your Unit admin can now add you to events.',
    );
  });

  it('enrols one Scout campaign and makes no claim about any other Scout', async () => {
    // Emery's profile is listed because Devon's account holds write access on it.
    // Devon joins with his own, and the only campaign this screen can name is the one
    // behind the profile he chose — Emery's membership is not part of this write.
    const joined = membershipFixture({ status: 'ACTIVE' });
    const mocks = [
      profilesQuery([devon, emery]),
      joinInfoQuery,
      {
        request: {
          query: JOIN_UNIT_CAMPAIGN,
          variables: {
            input: { joinCode: JOIN_CODE, campaignId: 'CAMPAIGN#devon', idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { joinUnitCampaign: joined } },
      },
      profilesQuery([devon, emery]),
    ];
    renderPage(mocks);
    const user = userEvent.setup();

    await enterCode(user);
    // Menu items exist only while the picker is open: Emery's profile is offered
    // (Devon's account holds access to it) and Devon's is the one chosen.
    const picker = await screen.findByTestId('join-profile');
    await user.click(picker.querySelector('.MuiSelect-select') as HTMLElement);
    expect(await screen.findByTestId('join-profile-option-PROFILE#emery')).toBeEnabled();
    await user.click(await screen.findByRole('option', { name: 'Devon Scout · Devon 2026' }));
    await user.click(await screen.findByTestId('submit-join'));

    // The write matched, so the success below is only reachable if exactly Devon's
    // campaign was named.
    expect(await screen.findByTestId('join-success')).toBeInTheDocument();
    expect(screen.queryByTestId('roster-row-PROFILE#emery')).not.toBeInTheDocument();
    expect(screen.queryByText(/Emery/)).not.toBeInTheDocument();
  });

  it('a code that is unknown, expired, or points at a closed campaign says the same thing', async () => {
    const mocks = [
      profilesQuery([devon]),
      {
        request: { query: GET_UNIT_CAMPAIGN_JOIN_INFO, variables: { joinCode: 'GONE1234CODE5678' } },
        error: new GraphQLError('That code does not match an open campaign.', { extensions: { code: 'NOT_FOUND' } }),
      },
    ];
    renderPage(mocks);
    const user = userEvent.setup();

    await typeInto('join-code-input', 'GONE1234CODE5678', user);
    await user.click(await screen.findByTestId('lookup-join-code'));

    expect(await screen.findByText('That code does not match an open campaign.')).toBeInTheDocument();
    expect(screen.queryByTestId('join-preview')).not.toBeInTheDocument();
  });


  it('asks for a code before anything is sent', async () => {
    renderPage([profilesQuery([devon])]);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('lookup-join-code'));

    expect(await screen.findByText('Enter the join code your Unit admin gave you.')).toBeInTheDocument();
    expect(screen.queryByTestId('join-preview')).not.toBeInTheDocument();
  });

  it('lists a profile with no campaign of its own, named as such and not selectable', async () => {
    const noCampaign = scoutProfileFixture({
      profileId: 'PROFILE#no-campaign',
      sellerName: 'No Campaign Scout',
      latestCampaign: null,
    });
    renderPage([profilesQuery([devon, noCampaign]), joinInfoQuery]);
    const user = userEvent.setup();

    await enterCode(user);
    const picker = await screen.findByTestId('join-profile');
    await user.click(picker.querySelector('.MuiSelect-select') as HTMLElement);

    const listed = await screen.findByTestId('join-profile-option-PROFILE#no-campaign');
    expect(listed).toHaveTextContent('No Campaign Scout · no campaign yet');
    expect(listed).toHaveClass('Mui-disabled');
    expect(await screen.findByTestId('join-profile-option-PROFILE#devon')).toBeEnabled();
  });

  it('a join the server refuses says why, and no membership is claimed', async () => {
    const mocks = [
      profilesQuery([devon]),
      joinInfoQuery,
      {
        request: {
          query: JOIN_UNIT_CAMPAIGN,
          variables: {
            input: { joinCode: JOIN_CODE, campaignId: 'CAMPAIGN#devon', idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        error: new GraphQLError('That campaign is closed to new joins.', { extensions: { code: 'CONFLICT' } }),
      },
    ];
    renderPage(mocks);
    const user = userEvent.setup();

    await enterCode(user);
    await chooseOption('join-profile', 'Devon Scout · Devon 2026', user);
    await user.click(await screen.findByTestId('submit-join'));

    expect(await screen.findByText('That campaign is closed to new joins.')).toBeInTheDocument();
    expect(screen.queryByTestId('join-success')).not.toBeInTheDocument();
  });

  it('a membership that lands in any other state is named as that state', async () => {
    const mocks = [
      profilesQuery([devon]),
      joinInfoQuery,
      {
        request: {
          query: JOIN_UNIT_CAMPAIGN,
          variables: {
            input: { joinCode: JOIN_CODE, campaignId: 'CAMPAIGN#devon', idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { joinUnitCampaign: membershipFixture({ status: 'REMOVED' }) } },
      },
      profilesQuery([devon]),
    ];
    renderPage(mocks);
    const user = userEvent.setup();

    await enterCode(user);
    await chooseOption('join-profile', 'Devon Scout · Devon 2026', user);
    await user.click(await screen.findByTestId('submit-join'));

    expect(await screen.findByTestId('join-success')).toHaveTextContent('Your membership in Fall Popcorn is REMOVED.');
  });


  it('says so when the account has no Scout profile to enrol', async () => {
    renderPage([profilesQuery([]), joinInfoQuery]);
    const user = userEvent.setup();

    await enterCode(user);
    const picker = await screen.findByTestId('join-profile');
    await user.click(picker.querySelector('.MuiSelect-select') as HTMLElement);

    expect(await screen.findByTestId('join-profile-empty')).toBeInTheDocument();
  });

  it('a join that answers without a status is still reported as a membership', async () => {
    const joined = membershipFixture({ status: undefined });
    const mocks = [
      profilesQuery([devon]),
      joinInfoQuery,
      {
        request: {
          query: JOIN_UNIT_CAMPAIGN,
          variables: {
            input: { joinCode: JOIN_CODE, campaignId: 'CAMPAIGN#devon', idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { joinUnitCampaign: joined } },
      },
      profilesQuery([devon]),
    ];
    renderPage(mocks);
    const user = userEvent.setup();

    await enterCode(user);
    await chooseOption('join-profile', 'Devon Scout · Devon 2026', user);
    await user.click(await screen.findByTestId('submit-join'));

    expect(await screen.findByTestId('join-success')).toHaveTextContent('Joined Fall Popcorn.');
  });


  it('a lookup that fails without a reason still says what the caller can do', async () => {
    renderPage([
      profilesQuery([devon]),
      { request: { query: GET_UNIT_CAMPAIGN_JOIN_INFO, variables: { joinCode: JOIN_CODE } }, error: new Error('') },
    ]);
    const user = userEvent.setup();

    await enterCode(user);

    expect(await screen.findByText('That code does not match an open campaign.')).toBeInTheDocument();
  });

  it('offers a profile shared with WRITE, and joins through it', async () => {
    const shared = sharedProfileFixture();
    const readOnly = sharedProfileFixture({
      profileId: 'PROFILE#shared-read',
      permissions: ['READ'],
      latestCampaign: { ...sharedProfileFixture().latestCampaign, campaignId: 'CAMPAIGN#shared-read' },
    });
    const mocks = [
      profilesQuery([devon]),
      sharesQuery([shared, readOnly]),
      joinInfoQuery,
      {
        request: {
          query: JOIN_UNIT_CAMPAIGN,
          variables: {
            input: { joinCode: JOIN_CODE, campaignId: 'CAMPAIGN#shared-write', idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { joinUnitCampaign: membershipFixture() } },
      },
      profilesQuery([devon]),
      sharesQuery([shared, readOnly]),
    ];
    renderPage(mocks);
    const user = userEvent.setup();

    await enterCode(user);
    const picker = await screen.findByTestId('join-profile');
    await user.click(picker.querySelector('.MuiSelect-select') as HTMLElement);

    expect(await screen.findByTestId('join-profile-option-PROFILE#shared-write')).toBeInTheDocument();
    expect(screen.queryByTestId('join-profile-option-PROFILE#shared-read')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('join-profile-option-PROFILE#shared-write'));
    await user.click(await screen.findByTestId('submit-join'));

    expect(await screen.findByTestId('join-success')).toBeInTheDocument();
  });
});
