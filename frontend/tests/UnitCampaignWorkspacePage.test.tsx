/**
 * One Unit Campaign's workspace (§1.6.3): settings, roster, catalog, and the join
 * code the roster shares.
 *
 * Two things this screen must make impossible to miss: the catalog is fixed (the
 * note says so where the choice would otherwise be offered), and a rename answers
 * to the version the screen was rendered with.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { UnitCampaignWorkspacePage } from '../src/pages/UnitCampaignWorkspacePage';
import {
  GET_UNIT_CAMPAIGN,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_UNIT_CAMPAIGN_ROSTER,
  UPDATE_UNIT_CAMPAIGN,
} from '../src/lib/graphql';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { campaignFixture, catalogViewFixture, membershipFixture } from './helpers/unitFixtures';

const CAMPAIGN_ID = 'UNITCAMP#pack-3149-fall';

let keySequence = 0;
beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

const campaignMock = (campaign = campaignFixture()) => ({
  request: { query: GET_UNIT_CAMPAIGN, variables: { unitCampaignId: CAMPAIGN_ID } },
  result: { data: { unitCampaign: campaign } },
});

const rosterMock = (items: unknown[]) => ({
  request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { unitCampaignId: CAMPAIGN_ID, status: undefined, page: { limit: UNIT_PAGE_SIZE } } },
  result: {
    data: {
      unitCampaignRoster: {
        __typename: 'UnitCampaignMembershipConnection',
        items,
        pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
      },
    },
  },
});

function renderWorkspace(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      {/* The campaign id carries a '#'; a URL reads that as a fragment, so the
          route parameter is encoded the way a real link to it is. */}
      <MemoryRouter initialEntries={[`/campaigns/${encodeURIComponent(CAMPAIGN_ID)}`]}>
        <Routes>
          <Route path="/campaigns/:unitCampaignId" element={<UnitCampaignWorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('UnitCampaignWorkspacePage', () => {
  it('shows the campaign, its status, and that its catalog cannot change', async () => {
      renderWorkspace([campaignMock(), rosterMock([membershipFixture()])]);

      expect(await screen.findByText('Fall Popcorn')).toBeInTheDocument();
      expect(screen.getByTestId('campaign-status')).toHaveTextContent('Active');
      expect(screen.getByTestId('catalog-id')).toHaveTextContent('CATALOG#popcorn-2026');
      expect(screen.getByTestId('catalog-immutable-note')).toHaveTextContent('cannot change after creation');
    });

  it('the join code is shown to its own admin, and can be hidden and copied', async () => {
    renderWorkspace([campaignMock(), rosterMock([])]);
    const user = userEvent.setup();

    // The admin's own campaign screen shows the code; hiding it is what the control
    // is for, since this screen is not a secret from its own admin.
    expect(await screen.findByTestId('join-code')).toHaveTextContent('JOIN1234CODE5678');
    await user.click(screen.getByTestId('reveal-join-code'));
    expect(screen.getByTestId('join-code')).toHaveTextContent('••••••••••••••••');

    // The copy control sits beside the code it copies. jsdom hands out a fresh
    // clipboard per read, so the click is exercised without asserting on it.
    await user.click(screen.getByTestId('copy-join-code'));
    expect(screen.getByTestId('join-code')).toHaveTextContent('••••••••••••••••');
  });

  it('a rename writes the version this screen was rendered with', async () => {
      const renamed = { ...campaignFixture(), campaignName: 'Winter Popcorn', version: 2 };
      const mocks = [
        campaignMock(),
        rosterMock([]),
        {
          request: {
            query: UPDATE_UNIT_CAMPAIGN,
            variables: {
              input: {
                unitCampaignId: CAMPAIGN_ID,
                campaignName: 'Winter Popcorn',
                campaignYear: 2026,
                version: { expectedVersion: 1 },
                idempotency: { idempotencyKey: 'test-idem-1' },
              },
            },
          },
          result: { data: { updateUnitCampaign: renamed } },
        },
        campaignMock(renamed),
      ];
      renderWorkspace(mocks);
      const user = userEvent.setup();

      const name = (await screen.findByTestId('campaign-name')).querySelector('input') as HTMLInputElement;
      await user.clear(name);
      await user.type(name, 'Winter Popcorn');
      await user.click(screen.getByTestId('save-campaign'));

      await waitFor(() => expect(screen.getByTestId('catalog-id')).toHaveTextContent('CATALOG#popcorn-2026'));
      expect(await screen.findByText('Winter Popcorn')).toBeInTheDocument();
    });

  it('the catalog tab lists the products the campaign sells from', async () => {
      const mocks = [
        campaignMock(),
        rosterMock([]),
        {
          request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: CAMPAIGN_ID } },
          result: { data: { unitCampaignCatalog: catalogViewFixture() } },
        },
      ];
      renderWorkspace(mocks);
      const user = userEvent.setup();

      await user.click(await screen.findByTestId('tab-catalog'));

      expect(await screen.findByTestId('catalog-product-PROD#cheese')).toBeInTheDocument();
      expect(screen.getByTestId('catalog-product-PROD#caramel')).toBeInTheDocument();
    });

  it('closing the campaign writes only that state, and the header follows', async () => {
      const closed = { ...campaignFixture(), isActive: false, version: 2 };
      const mocks = [
        campaignMock(),
        rosterMock([]),
        {
          request: {
            query: UPDATE_UNIT_CAMPAIGN,
            variables: {
              input: {
                unitCampaignId: CAMPAIGN_ID,
                isActive: false,
                version: { expectedVersion: 1 },
                idempotency: { idempotencyKey: 'test-idem-1' },
              },
            },
          },
          result: { data: { updateUnitCampaign: closed } },
        },
        campaignMock(closed),
      ];
      renderWorkspace(mocks);
      const user = userEvent.setup();

      await user.click(await screen.findByTestId('toggle-campaign'));
      await waitFor(() => expect(screen.getAllByRole('dialog').length).toBeGreaterThan(0));
      const dialog = screen.getAllByRole('dialog').at(-1) as HTMLElement;
      await user.click(within(dialog).getByRole('button', { name: 'Close campaign' }));

      await waitFor(() => expect(screen.getByTestId('campaign-status')).toHaveTextContent('Closed'));
    });

  it('a campaign the caller cannot see answers without confirming it exists', async () => {
      renderWorkspace([{ request: { query: GET_UNIT_CAMPAIGN, variables: { unitCampaignId: CAMPAIGN_ID } }, result: { data: { unitCampaign: null } } }]);

      expect(await screen.findByText('This campaign is not yours, or it no longer exists.')).toBeInTheDocument();
    });


  it('the catalog tab says what is missing when the catalog is not there to read', async () => {
    const mocks = [
      campaignMock(),
      rosterMock([]),
      {
        request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: CAMPAIGN_ID } },
        result: { data: { unitCampaignCatalog: catalogViewFixture({ products: [] }) } },
      },
    ];
    renderWorkspace(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('tab-catalog'));

    expect(await screen.findByText('This catalog has no products yet.')).toBeInTheDocument();
  });

  it('a campaign whose catalog cannot be read says so on the catalog tab', async () => {
    const mocks = [
      campaignMock(),
      rosterMock([]),
      {
        request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: CAMPAIGN_ID } },
        result: { data: { unitCampaignCatalog: null } },
      },
    ];
    renderWorkspace(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('tab-catalog'));

    expect(await screen.findByText('This campaign has no catalog.')).toBeInTheDocument();
  });

  it('opening a closed campaign is offered as the opposite write', async () => {
    const closed = { ...campaignFixture(), isActive: false, version: 2 };
    const opened = { ...closed, isActive: true, version: 3 };
    const mocks = [
      campaignMock(closed),
      rosterMock([]),
      {
        request: {
          query: UPDATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              isActive: true,
              version: { expectedVersion: 2 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { updateUnitCampaign: opened } },
      },
      campaignMock(opened),
    ];
    renderWorkspace(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('toggle-campaign'));
    await waitFor(() => expect(screen.getAllByRole('dialog').length).toBeGreaterThan(0));
    const dialog = screen.getAllByRole('dialog').at(-1) as HTMLElement;
    await user.click(within(dialog).getByRole('button', { name: 'Open campaign' }));

    await waitFor(() => expect(screen.getByTestId('campaign-status')).toHaveTextContent('Active'));
  });


  it('a settings save that fails without a reason still says what it could not do', async () => {
    const mocks = [
      campaignMock(),
      rosterMock([]),
      {
        request: {
          query: UPDATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              campaignName: 'Winter Popcorn',
              campaignYear: 2026,
              version: { expectedVersion: 1 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new Error(''),
      },
      // Delayed on purpose: a refused save still refreshes the campaign, and that
      // refresh is in flight when the screen tears down.
      { ...campaignMock(), delay: 250 },
    ];
    renderWorkspace(mocks);
    const user = userEvent.setup();

    const name = (await screen.findByTestId('campaign-name')).querySelector('input') as HTMLInputElement;
    await user.clear(name);
    await user.type(name, 'Winter Popcorn');
    await user.click(screen.getByTestId('save-campaign'));

    expect(await screen.findByText('Could not save the campaign settings.')).toBeInTheDocument();
  });


  it('saves two edits made in one mounted screen as two separate writes', async () => {
    const renamed = campaignFixture({ campaignName: 'Winter Popcorn', version: 2 });
    const yearEdited = campaignFixture({ campaignName: 'Winter Popcorn', campaignYear: 2027, version: 3 });
    const saveName = {
      request: {
        query: UPDATE_UNIT_CAMPAIGN,
        variables: {
          input: {
            unitCampaignId: CAMPAIGN_ID,
            campaignName: 'Winter Popcorn',
            campaignYear: 2026,
            version: { expectedVersion: 1 },
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
        },
      },
      result: { data: { updateUnitCampaign: renamed } },
    };
    const saveYear = {
      request: {
        query: UPDATE_UNIT_CAMPAIGN,
        variables: {
          input: {
            unitCampaignId: CAMPAIGN_ID,
            campaignName: 'Winter Popcorn',
            campaignYear: 2027,
            version: { expectedVersion: 2 },
            idempotency: { idempotencyKey: 'test-idem-2' },
          },
        },
      },
      result: { data: { updateUnitCampaign: yearEdited } },
    };
    renderWorkspace([campaignMock(), rosterMock([]), saveName, campaignMock(renamed), saveYear, campaignMock(yearEdited)]);
    const user = userEvent.setup();

    const name = (await screen.findByTestId('campaign-name')).querySelector('input') as HTMLInputElement;
    await user.clear(name);
    await user.type(name, 'Winter Popcorn');
    await user.click(screen.getByTestId('save-campaign'));
    expect(await screen.findByText('Winter Popcorn')).toBeInTheDocument();

    const year = (screen.getByTestId('campaign-year')).querySelector('input') as HTMLInputElement;
    await user.clear(year);
    await user.type(year, '2027');
    await user.click(screen.getByTestId('save-campaign'));

    // The refreshed campaign alone does not prove the second write happened: the
    // card refreshes after a failed save too. An unanswered request surfaces as an
    // alert, so a clean screen is what says both writes were the ones described.
    await waitFor(() => expect(screen.getByText('2027 · Active')).toBeInTheDocument());
        // The settings card always carries its fixed-catalog note as an alert; any other
    // alert on this screen is a write that did not land.
    const failedWrites = screen.getAllByRole('alert').filter((node) => !node.textContent?.includes('cannot change'));
    expect(failedWrites).toEqual([]);
  });

  it('retries a save whose answer never arrived as the same write', async () => {
    const renamed = campaignFixture({ campaignName: 'Winter Popcorn', version: 2 });
    const input = {
      unitCampaignId: CAMPAIGN_ID,
      campaignName: 'Winter Popcorn',
      campaignYear: 2026,
      version: { expectedVersion: 1 },
    };
    const dropped = {
      request: { query: UPDATE_UNIT_CAMPAIGN, variables: { input: { ...input, idempotency: { idempotencyKey: 'test-idem-1' } } } },
      error: new Error(''),
    };
    const replay = {
      request: { query: UPDATE_UNIT_CAMPAIGN, variables: { input: { ...input, idempotency: { idempotencyKey: 'test-idem-1' } } } },
      result: { data: { updateUnitCampaign: renamed } },
    };
    renderWorkspace([campaignMock(), rosterMock([]), dropped, campaignMock(), replay, campaignMock(renamed)]);
    const user = userEvent.setup();

    const name = (await screen.findByTestId('campaign-name')).querySelector('input') as HTMLInputElement;
    await user.clear(name);
    await user.type(name, 'Winter Popcorn');
    await user.click(screen.getByTestId('save-campaign'));
    expect(await screen.findByText('Could not save the campaign settings.')).toBeInTheDocument();

    await user.click(screen.getByTestId('save-campaign'));

    await waitFor(() => expect(screen.getByText('Winter Popcorn')).toBeInTheDocument());
    expect(screen.queryByText('Could not save the campaign settings.')).not.toBeInTheDocument();
  });
});
