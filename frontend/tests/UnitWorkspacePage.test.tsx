/**
 * One Unit's workspace (§1.6.1–§1.6.3 assembly) and the reachability answer.
 *
 * The screen is where the three panels meet, so the test asserts the assembly: the
 * Unit is named by its generated display name, the tabs move between panels, and a
 * Unit the caller cannot see answers the same way whether it is missing or someone
 * else's.
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { UnitWorkspacePage } from '../src/pages/UnitWorkspacePage';
import { GET_UNIT, LIST_UNIT_ADMINS, LIST_UNIT_CAMPAIGNS, LIST_UNIT_INVITES } from '../src/lib/graphql';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { campaignFixture, grantFixture, unitFixture } from './helpers/unitFixtures';

const UNIT_ID = 'UNIT#pack-3149';

// The account is optional on purpose: the access panel still lists admins when the
// session carries no account id to mark a row as the caller's own.
const mockUseAuth = vi.fn(() => ({ account: { accountId: 'ACCOUNT#avery' } }));
vi.mock('../src/contexts/AuthContext', () => ({ useAuth: () => mockUseAuth() }));

const connection = (key: string, items: unknown[]) => ({
  [key]: {
    __typename: `${key === 'unitAdmins' ? 'UnitAccessGrant' : key === 'unitInvites' ? 'UnitInvite' : 'UnitCampaign'}Connection`,
    items,
    pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
  },
});

const pageMocks = (extra: unknown[] = []) => [
  { request: { query: GET_UNIT, variables: { unitId: UNIT_ID } }, result: { data: { unit: unitFixture() } } },
  ...extra,
];

function renderWorkspace(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      {/* The Unit id carries a '#', which a URL reads as a fragment — the route
          parameter has to be encoded the way a real link to it is. */}
      <MemoryRouter initialEntries={[`/units/${encodeURIComponent(UNIT_ID)}`]}>
        <Routes>
          <Route path="/units/:unitId" element={<UnitWorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('UnitWorkspacePage', () => {
  it('names the Unit by its generated display name and opens on Settings', async () => {
    renderWorkspace(pageMocks());

    expect(await screen.findByText('Pack 3149 (Springfield, IL)')).toBeInTheDocument();
    expect(screen.getByTestId('save-unit')).toBeInTheDocument();
    expect(screen.getByTestId('unit-version')).toHaveTextContent('Version 3 · 2 admins');
  });

  it('the Access tab shows the admins, and Campaigns shows the Unit’s campaigns', async () => {
    const mocks = pageMocks([
      {
        request: { query: LIST_UNIT_ADMINS, variables: { unitId: UNIT_ID, page: { limit: UNIT_PAGE_SIZE } } },
        result: { data: connection('unitAdmins', [grantFixture({ accountId: 'ACCOUNT#avery', name: 'Avery Admin' })]) },
      },
      {
        request: { query: LIST_UNIT_INVITES, variables: { unitId: UNIT_ID, page: { limit: UNIT_PAGE_SIZE } } },
        result: { data: connection('unitInvites', []) },
      },
      {
        request: { query: LIST_UNIT_CAMPAIGNS, variables: { unitId: UNIT_ID, isActive: undefined, page: { limit: UNIT_PAGE_SIZE } } },
        result: { data: connection('unitCampaigns', [campaignFixture()]) },
      },
    ]);
    renderWorkspace(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('tab-access'));
    expect(await screen.findByTestId('admin-row-ACCOUNT#avery')).toBeInTheDocument();

    await user.click(await screen.findByTestId('tab-campaigns'));
    expect(await screen.findByTestId(`campaign-row-${campaignFixture().unitCampaignId}`)).toBeInTheDocument();
  });

  it('a Unit that is not the caller’s and a Unit that is gone answer identically', async () => {
    renderWorkspace([{ request: { query: GET_UNIT, variables: { unitId: UNIT_ID } }, result: { data: { unit: null } } }]);

    expect(
      await screen.findByText(
        'This Unit is not yours, or it no longer exists. Unit access is granted per Unit — there is no view of Units you do not administer.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('unit-tabs')).not.toBeInTheDocument();
  });


  it('still lists the admins when the session carries no account id to compare with', async () => {
    mockUseAuth.mockReturnValueOnce({ account: null } as never);
    const mocks = pageMocks([
      {
        request: { query: LIST_UNIT_ADMINS, variables: { unitId: UNIT_ID, page: { limit: UNIT_PAGE_SIZE } } },
        result: { data: connection('unitAdmins', [grantFixture()]) },
      },
      {
        request: { query: LIST_UNIT_INVITES, variables: { unitId: UNIT_ID, page: { limit: UNIT_PAGE_SIZE } } },
        result: { data: connection('unitInvites', []) },
      },
    ]);
    renderWorkspace(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('tab-access'));

    expect(await screen.findByTestId('admin-row-account-casey')).toBeInTheDocument();
    mockUseAuth.mockReturnValue({ account: { accountId: 'ACCOUNT#avery' } });
  });
});
