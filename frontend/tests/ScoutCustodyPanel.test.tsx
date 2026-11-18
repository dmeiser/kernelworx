/**
 * Scout custody: who holds what, issuing stock, and the one-click return
 * (Show & Sell §2.6.2, the `SS-SM-03` issue/sale/return sequence).
 *
 * The three numbers on this screen have three different owners, and the tests keep
 * them apart:
 *
 * - `withScoutQty` per line is the server's custody row, shown verbatim. After a
 *   partial sale the held figure has already fallen by what sold; a screen that
 *   subtracted sales itself would count the same Kernels gone twice.
 * - the per-Scout total is the only sum this screen makes, and only to present the
 *   lines it is already showing;
 * - the campaign-wide total is `totalWithScoutQty`, the server's aggregate over the
 *   whole filtered set. It is deliberately not the sum of the visible rows, so the
 *   fixture sets the two apart and the test proves which one is rendered.
 *
 * A return is one write for the whole batch, so the rollback rule is part of the
 * contract being tested: a refused line moves nothing, and the screen says so.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { ScoutCustodyPanel } from '../src/components/ScoutCustodyPanel';
import {
  GET_INVENTORY_POSITIONS,
  GET_SCOUT_CUSTODY_BALANCES,
  GET_UNIT_CAMPAIGN_CATALOG,
  ISSUE_STOCK_TO_SCOUT,
  LIST_UNIT_CAMPAIGN_ROSTER,
  RETURN_STOCK_FROM_SCOUT,
} from '../src/lib/graphql';
import { page } from '../src/lib/inventory';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { chooseOption, clearAndType, findOption, typeInto } from './helpers/unitUi';

const UC = 'UNITCAMP#pack-3149-fall';
const CARAMEL = 'PROD#caramel';
const BUTTER = 'PROD#butter';
const AVERY = 'PROFILE#avery';
const BETH = 'PROFILE#beth';
const CAMP = 'CAMP#fall-2026';

// A return batch is one Scout under one Scout Campaign, so the row's identity is the pair.
function held(profileId: string, campaignId: string = CAMP): string {
  return `${profileId}:${campaignId}`;
}

// The roster option names the Scout and their Campaign, which are the two things the
// write needs and the two a person can read.
const SCOUT_AVERY = /Avery Scout/;

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

/**
 * Caramel as SS-SM-03 leaves it: 14 received, 4 issued to Avery, 3 of those sold,
 * so 1 Kernel is still With Scout and 10 are unassigned.
 */
function positionFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'InventoryPosition',
    unitCampaignId: UC,
    productId: CARAMEL,
    kernelPhysicalQty: 14,
    soldInPossessionQty: 3,
    councilOnOrderQty: 0,
    version: 6,
    createdAt: '2026-02-01T15:00:00Z',
    updatedAt: '2026-02-06T15:00:00Z',
    sellableKernelQty: 10,
    assignedOpenQty: 0,
    unassignedKernelQty: 10,
    assignmentOverageQty: 0,
    withScoutQty: 1,
    totalUnitOwnedUndeliveredQty: 11,
    ...overrides,
  };
}

function custodyLine(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ScoutCustodyBalance',
    unitCampaignId: UC,
    productId: CARAMEL,
    profileId: AVERY,
    campaignId: CAMP,
    withScoutQty: 1,
    version: 4,
    createdAt: '2026-02-05T15:00:00Z',
    updatedAt: '2026-02-06T15:00:00Z',
    ...overrides,
  };
}

function rosterRow(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'UnitCampaignMembership',
    unitCampaignId: UC,
    unitId: 'UNIT#pack-3149',
    campaignId: CAMP,
    profileId: AVERY,
    scoutName: 'Avery Scout',
    campaignName: 'Fall 2026 Campaign',
    scoutCampaignCatalogId: 'CATALOG#fall',
    status: 'ACTIVE',
    joinedByAccountId: 'ACCOUNT#avery',
    joinedAt: '2026-01-20T15:00:00Z',
    removedByAccountId: null,
    removedAt: null,
    version: 1,
    guardVersion: 2,
    ...overrides,
  };
}

const catalogQuery = {
  request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: UC } },
  result: {
    data: {
      unitCampaignCatalog: {
        __typename: 'UnitCampaignCatalog',
        catalogId: 'CATALOG#fall',
        catalogName: 'Fall catalog',
        products: [
          { __typename: 'CatalogProduct', productId: CARAMEL, productName: 'Caramel Corn', description: null, price: 6, sortOrder: 1 },
          { __typename: 'CatalogProduct', productId: BUTTER, productName: 'Butter Popcorn', description: null, price: 6, sortOrder: 2 },
        ],
      },
    },
  },
};

const ROSTER_VARIABLES = { unitCampaignId: UC, page: { limit: UNIT_PAGE_SIZE } };

function rosterQuery(items: unknown[]) {
  return {
    request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: ROSTER_VARIABLES },
    result: {
      data: {
        unitCampaignRoster: {
          __typename: 'UnitCampaignMembershipConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function positionsQuery(items: unknown[]) {
  return {
    request: { query: GET_INVENTORY_POSITIONS, variables: { unitCampaignId: UC, page: page() } },
    result: {
      data: {
        inventoryPositions: {
          __typename: 'InventoryPositionConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function balancesQuery(items: unknown[], totalWithScoutQty: number) {
  return {
    request: { query: GET_SCOUT_CUSTODY_BALANCES, variables: { unitCampaignId: UC, page: page() } },
    result: {
      data: {
        scoutCustodyBalances: {
          __typename: 'ScoutCustodyBalanceConnection',
          items,
          totalWithScoutQty,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

/** What one Scout holds, and what the campaign holds in total, in the fixture's default shape. */
interface ReadFixture {
  balances: unknown[];
  total: number;
  positions: unknown[];
  roster: unknown[];
}

const DEFAULT_READS: ReadFixture = {
  balances: [custodyLine()],
  total: 1,
  positions: [positionFixture()],
  roster: [rosterRow()],
};

/** The four reads every render of this screen makes, in the order the mocks are consumed. */
function reads(overrides: Partial<ReadFixture> = {}) {
  const fixture = { ...DEFAULT_READS, ...overrides };
  return [
    catalogQuery,
    balancesQuery(fixture.balances, fixture.total),
    rosterQuery(fixture.roster),
    positionsQuery(fixture.positions),
  ];
}

function renderPanel(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      <ScoutCustodyPanel unitCampaignId={UC} />
    </MockedProvider>,
  );
}

/** Opens the issue dialog once the roster and catalog have made the write possible. */
async function openIssue(user: ReturnType<typeof userEvent.setup>) {
  const button = await screen.findByTestId('issue-stock');
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
}

/** Fills the issue form: Scout, product, quantity. */
async function fillIssue(scoutName: RegExp, product: string, quantity: string, user: ReturnType<typeof userEvent.setup>) {
  await chooseOption('custody-scout', scoutName, user);
  await chooseOption('custody-product', product, user);
  await clearAndType('custody-quantity', quantity, user);
}

/** Opens the Scout select so its options can be read as well as chosen. */
async function openScoutSelect(user: ReturnType<typeof userEvent.setup>) {
  const field = await screen.findByTestId('custody-scout');
  await user.click(field.querySelector('.MuiSelect-select') as HTMLElement);
}

describe('ScoutCustodyPanel', () => {
  it('shows what each Scout holds, and the campaign total the server computed rather than the rows it can see', async () => {
    renderPanel(
      reads({
        balances: [
          custodyLine({ productId: CARAMEL, profileId: AVERY, withScoutQty: 4, version: 2 }),
          custodyLine({ productId: BUTTER, profileId: BETH, withScoutQty: 1, version: 1 }),
        ],
        // The server's aggregate is over every custody row in the campaign, not the
        // two lines this page happens to show, so the fixture keeps them apart.
        total: 9,
      }),
    );

    expect(await screen.findByTestId('custody-total')).toHaveTextContent('9 Kernels are held by 2 Scouts in this campaign.');

    const avery = screen.getByTestId(`custody-scout-row-${held(AVERY)}`);
    expect(within(avery).getByTestId(`custody-scout-held-${held(AVERY)}`)).toHaveTextContent('4');
    expect(within(avery).getByText('Caramel Corn')).toBeInTheDocument();
    const beth = screen.getByTestId(`custody-scout-row-${held(BETH)}`);
    expect(within(beth).getByTestId(`custody-scout-held-${held(BETH)}`)).toHaveTextContent('1');

    // A Scout is chosen by name, so both tables say who holds the stock.
    expect(within(avery).getByTestId(`custody-scout-name-${held(AVERY)}`)).toHaveTextContent('Avery Scout');
    expect(within(avery).getByTestId(`custody-scout-campaign-${held(AVERY)}`)).toHaveTextContent('Fall 2026 Campaign');
    expect(screen.getByTestId(`custody-line-scout-${AVERY}-${CARAMEL}`)).toHaveTextContent('Avery Scout');
    // Beth has no roster row in this fixture, so the id is what is left to name her by -
    // and her line still shows, because that stock has to come back either way.
    expect(within(beth).getByTestId(`custody-scout-name-${held(BETH)}`)).toHaveTextContent(BETH);

    expect(screen.getByTestId(`custody-line-${AVERY}-${CARAMEL}`)).toBeInTheDocument();
    expect(screen.getByTestId(`custody-line-qty-${AVERY}-${CARAMEL}`)).toHaveTextContent('4');
    expect(screen.getByTestId(`custody-line-${BETH}-${BUTTER}`)).toBeInTheDocument();
    expect(screen.getByTestId('custody-line-count')).toHaveTextContent('2 custody lines shown');
  });

  it('names the Scout in the issue picker, because an id is not a choice', async () => {
    const user = userEvent.setup();
    renderPanel(reads({ balances: [], total: 0 }));

    await openIssue(user);
    const option = await findOption('custody-scout', /Avery Scout/, user);
    expect(option).toHaveTextContent('Fall 2026 Campaign');
    expect(option.textContent).not.toContain(AVERY);
  });

  it('names the Scout in the return dialog, the one batch that has to come back', async () => {
    const user = userEvent.setup();
    renderPanel(reads({ balances: [custodyLine({ withScoutQty: 4, version: 2 })], total: 4 }));

    await user.click(await screen.findByTestId(`return-stock-${held(AVERY)}`));
    expect(await screen.findByText(/Return Avery Scout's stock/)).toBeInTheDocument();
  });

  it('issue-4: issues four Caramel to an eligible Scout and shows the custody the write created', async () => {
    const user = userEvent.setup();
    renderPanel([
      ...reads({ balances: [], total: 0, positions: [positionFixture({ withScoutQty: 0, unassignedKernelQty: 14, soldInPossessionQty: 0 })] }),
      {
        request: {
          query: ISSUE_STOCK_TO_SCOUT,
          variables: {
            input: {
              unitCampaignId: UC,
              campaignId: CAMP,
              profileId: AVERY,
              productId: CARAMEL,
              quantity: 4,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            issueStockToScout: {
              __typename: 'IssueStockToScoutPayload',
              inventoryPosition: positionFixture({ withScoutQty: 4 }),
              custodyBalance: custodyLine({ withScoutQty: 4, version: 1 }),
            },
          },
        },
      },
      balancesQuery([custodyLine({ withScoutQty: 4, version: 1 })], 4),
      positionsQuery([positionFixture({ withScoutQty: 4, unassignedKernelQty: 10, soldInPossessionQty: 0 })]),
    ]);

    await openIssue(user);
    // The guidance beside the product is the server's unassigned figure, not a
    // number this screen worked out from the positions it can see.
    await chooseOption('custody-scout', SCOUT_AVERY, user);
    await chooseOption('custody-product', 'Caramel Corn', user);
    expect(await screen.findByText('14 unassigned Kernels of this product.')).toBeInTheDocument();
    await typeInto('custody-quantity', '4', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByTestId(`custody-line-qty-${AVERY}-${CARAMEL}`)).toHaveTextContent('4');
    expect(screen.getByTestId('custody-total')).toHaveTextContent('4 Kernels are held by 1 Scout in this campaign.');
    await waitFor(() => expect(screen.queryByTestId('form-dialog-confirm')).not.toBeInTheDocument());
  });

  it("partial-sale: the held figure is the server's own, already fallen by what sold", async () => {
    renderPanel(
      reads({
        // Four were issued and three sold. The custody row says 1; the screen has no
        // sales arithmetic of its own that could take it to 1 minus 3.
        balances: [custodyLine({ withScoutQty: 1, version: 4 })],
        total: 1,
        positions: [positionFixture({ kernelPhysicalQty: 14, soldInPossessionQty: 3, withScoutQty: 1, totalUnitOwnedUndeliveredQty: 11 })],
      }),
    );

    expect(await screen.findByTestId(`custody-line-qty-${AVERY}-${CARAMEL}`)).toHaveTextContent('1');
    expect(screen.getByTestId(`custody-scout-held-${held(AVERY)}`)).toHaveTextContent('1');
    expect(screen.getByTestId('custody-total')).toHaveTextContent('1 Kernel is held by 1 Scout in this campaign.');
    expect(screen.getByTestId('custody-note')).toHaveTextContent('still owes whatever they hold');
  });

  it('issue-2: a second issue to the Scout who already holds stock is its own write, not a rewrite of the first line', async () => {
    const user = userEvent.setup();
    renderPanel([
      ...reads({ balances: [custodyLine({ withScoutQty: 1 })], total: 1 }),
      {
        request: {
          query: ISSUE_STOCK_TO_SCOUT,
          variables: {
            input: {
              unitCampaignId: UC,
              campaignId: CAMP,
              profileId: AVERY,
              productId: BUTTER,
              quantity: 2,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            issueStockToScout: {
              __typename: 'IssueStockToScoutPayload',
              inventoryPosition: positionFixture({ productId: BUTTER }),
              custodyBalance: custodyLine({ productId: BUTTER, withScoutQty: 2, version: 1 }),
            },
          },
        },
      },
      balancesQuery(
        [custodyLine({ withScoutQty: 1 }), custodyLine({ productId: BUTTER, withScoutQty: 2, version: 1 })],
        3,
      ),
      positionsQuery([positionFixture(), positionFixture({ productId: BUTTER, withScoutQty: 2, unassignedKernelQty: 8 })]),
    ]);

    await openIssue(user);
    await fillIssue(SCOUT_AVERY, 'Butter Popcorn', '2', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByTestId(`custody-line-qty-${AVERY}-${BUTTER}`)).toHaveTextContent('2');
    expect(screen.getByTestId(`custody-line-qty-${AVERY}-${CARAMEL}`)).toHaveTextContent('1');
    expect(screen.getByTestId(`custody-scout-held-${held(AVERY)}`)).toHaveTextContent('3');
    expect(screen.getByTestId('custody-total')).toHaveTextContent('3 Kernels are held by 1 Scout in this campaign.');
  });

  it('return-1: one click brings the whole batch back in one write', async () => {
    const user = userEvent.setup();
    renderPanel([
      ...reads({ balances: [custodyLine({ withScoutQty: 1 })], total: 1 }),
      {
        request: {
          query: RETURN_STOCK_FROM_SCOUT,
          variables: {
            input: {
              unitCampaignId: UC,
              campaignId: CAMP,
              profileId: AVERY,
              // The batch is the custody lines on screen, quantities and all: the
              // admin confirmed exactly this.
              items: [{ productId: CARAMEL, quantity: 1 }],
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            returnStockFromScout: {
              __typename: 'ReturnStockFromScoutPayload',
              inventoryPositions: [positionFixture({ withScoutQty: 0 })],
              custodyBalances: [custodyLine({ withScoutQty: 0, version: 5 })],
            },
          },
        },
      },
      balancesQuery([], 0),
      positionsQuery([positionFixture({ withScoutQty: 0 })]),
    ]);

    await user.click(await screen.findByTestId(`return-stock-${held(AVERY)}`));
    expect(await screen.findByTestId(`return-batch-line-${CARAMEL}`)).toHaveTextContent('Caramel Corn: 1');
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByText('No Scout holds stock for this campaign yet.')).toBeInTheDocument();
    expect(screen.getByTestId('custody-total')).toHaveTextContent('0 Kernels are held by 0 Scouts in this campaign.');
    expect(screen.getByTestId('custody-line-count')).toHaveTextContent('0 custody lines shown');
  });

  it('a batch is named line by line before it is returned, and one click is enough to return it', async () => {
    const user = userEvent.setup();
    renderPanel(
      reads({
        balances: [custodyLine({ withScoutQty: 4 }), custodyLine({ productId: BUTTER, withScoutQty: 10, version: 2 })],
        total: 14,
      }),
    );

    await user.click(await screen.findByTestId(`return-stock-${held(AVERY)}`));
    const dialog = await screen.findByRole('dialog');
    expect(screen.getByTestId('return-batch-note')).toHaveTextContent('the whole batch is refused and no stock moves');
    expect(within(dialog).getByTestId(`return-batch-line-${CARAMEL}`)).toHaveTextContent('Caramel Corn: 4');
    expect(within(dialog).getByTestId(`return-batch-line-${BUTTER}`)).toHaveTextContent('Butter Popcorn: 10');
    // The dialog offers one confirmation, not one per line: the batch is the unit
    // of the write, which is what makes the all-or-nothing refusal meaningful.
    expect(within(dialog).getAllByRole('button').map((button) => button.textContent)).toEqual(['Cancel', 'Return all stock']);
  });

  it('a product the Scout has already sold out of is left out of the return batch', async () => {
    const user = userEvent.setup();
    renderPanel([
      ...reads({
        balances: [
          custodyLine({ withScoutQty: 4 }),
          // The row a sale or an earlier return leaves behind: a return drives it to
          // zero and keeps it, which is what lets a replayed return answer the same list.
          custodyLine({ productId: BUTTER, withScoutQty: 0, version: 7 }),
        ],
        total: 4,
      }),
      {
        request: {
          query: RETURN_STOCK_FROM_SCOUT,
          variables: {
            input: {
              unitCampaignId: UC,
              campaignId: CAMP,
              profileId: AVERY,
              // The empty line is not in the batch. The server requires every return item
              // to be at least one Kernel, so one zero row would refuse the whole write.
              items: [{ productId: CARAMEL, quantity: 4 }],
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            returnStockFromScout: {
              __typename: 'ReturnStockFromScoutPayload',
              inventoryPositions: [positionFixture({ withScoutQty: 0 })],
              custodyBalances: [custodyLine({ withScoutQty: 0, version: 8 })],
            },
          },
        },
      },
      balancesQuery([custodyLine({ productId: BUTTER, withScoutQty: 0, version: 7 })], 0),
      positionsQuery([positionFixture({ withScoutQty: 0 })]),
    ]);

    await user.click(await screen.findByTestId(`return-stock-${held(AVERY)}`));
    // The batch names only what is still held, and the Scout's total counts only it too.
    expect(await screen.findByTestId(`return-batch-line-${CARAMEL}`)).toHaveTextContent('Caramel Corn: 4');
    expect(screen.queryByTestId(`return-batch-line-${BUTTER}`)).not.toBeInTheDocument();
    expect(screen.getByTestId(`custody-scout-held-${held(AVERY)}`)).toHaveTextContent('4');

    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('0 Kernels are held by 0 Scouts in this campaign.')).toBeInTheDocument();
  });

  it('one Scout holding under two Scout Campaigns gets one return batch per campaign', async () => {
    const SPRING = 'CAMP#spring-2027';
    const user = userEvent.setup();
    renderPanel([
      ...reads({
        balances: [
          custodyLine({ withScoutQty: 2 }),
          custodyLine({ productId: BUTTER, campaignId: SPRING, withScoutQty: 3, version: 5 }),
        ],
        total: 5,
        roster: [rosterRow(), rosterRow({ campaignId: SPRING, campaignName: 'Spring 2027 Campaign' })],
      }),
      {
        request: {
          query: RETURN_STOCK_FROM_SCOUT,
          variables: {
            input: {
              unitCampaignId: UC,
              // Each custody row answers for the Scout Campaign it was written under, and
              // the server refuses a return whose campaignId is not the row's own.
              campaignId: SPRING,
              profileId: AVERY,
              items: [{ productId: BUTTER, quantity: 3 }],
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            returnStockFromScout: {
              __typename: 'ReturnStockFromScoutPayload',
              inventoryPositions: [positionFixture({ productId: BUTTER, withScoutQty: 0 })],
              custodyBalances: [custodyLine({ productId: BUTTER, campaignId: SPRING, withScoutQty: 0, version: 6 })],
            },
          },
        },
      },
      balancesQuery([custodyLine({ withScoutQty: 2 })], 2),
      positionsQuery([positionFixture({ withScoutQty: 2 })]),
    ]);

    // Two batches, not one row that cannot say which campaign it returns: the Campaign is
    // named on the row so the admin can tell them apart, and the name is what they read.
    expect(await screen.findByTestId(`custody-scout-campaign-${held(AVERY, CAMP)}`)).toHaveTextContent(
      'Fall 2026 Campaign',
    );
    const springRow = await screen.findByTestId(`custody-scout-row-${held(AVERY, SPRING)}`);
    expect(within(springRow).getByTestId(`custody-scout-campaign-${held(AVERY, SPRING)}`)).toHaveTextContent(
      'Spring 2027 Campaign',
    );
    expect(within(springRow).getByTestId(`custody-scout-held-${held(AVERY, SPRING)}`)).toHaveTextContent('3');

    await user.click(within(springRow).getByTestId(`return-stock-${held(AVERY, SPRING)}`));
    expect(await screen.findByTestId(`return-batch-line-${BUTTER}`)).toHaveTextContent('Butter Popcorn: 3');
    expect(screen.queryByTestId(`return-batch-line-${CARAMEL}`)).not.toBeInTheDocument();

    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('2 Kernels are held by 1 Scout in this campaign.')).toBeInTheDocument();
  });

  it('over-return rollback: a refused line refuses the whole batch, and the stock on screen has not moved', async () => {
    const user = userEvent.setup();
    const balances = [custodyLine({ withScoutQty: 4 }), custodyLine({ productId: BUTTER, withScoutQty: 10, version: 2 })];
    renderPanel([
      ...reads({ balances, total: 14 }),
      {
        request: {
          query: RETURN_STOCK_FROM_SCOUT,
          variables: {
            input: {
              unitCampaignId: UC,
              campaignId: CAMP,
              profileId: AVERY,
              items: [
                { productId: CARAMEL, quantity: 4 },
                { productId: BUTTER, quantity: 10 },
              ],
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('Butter custody would return more than the Scout holds.', {
          extensions: { code: 'CONFLICT' },
        }),
      },
      // The refusal re-reads custody: the batch body comes from these lines, so a
      // stale line has to be replaced before the button is worth pressing again.
      balancesQuery(balances, 14),
      positionsQuery([positionFixture(), positionFixture({ productId: BUTTER })]),
    ]);

    await user.click(await screen.findByTestId(`return-stock-${held(AVERY)}`));
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByText(/stock or a version has already moved/)).toBeInTheDocument();
    expect(screen.getByTestId('form-dialog-confirm')).toBeInTheDocument();
    expect(screen.getByTestId(`custody-line-qty-${AVERY}-${CARAMEL}`)).toHaveTextContent('4');
    expect(screen.getByTestId(`custody-line-qty-${AVERY}-${BUTTER}`)).toHaveTextContent('10');
    expect(screen.getByTestId('custody-total')).toHaveTextContent('14 Kernels are held by 1 Scout in this campaign.');
  });

  it('replays one intent when a refused return is confirmed again', async () => {
    const user = userEvent.setup();
    const balances = [custodyLine({ withScoutQty: 4 })];
    const body = {
      unitCampaignId: UC,
      campaignId: CAMP,
      profileId: AVERY,
      items: [{ productId: CARAMEL, quantity: 4 }],
      idempotency: { idempotencyKey: 'test-idem-1' },
    };
    renderPanel([
      ...reads({ balances, total: 4 }),
      {
        request: { query: RETURN_STOCK_FROM_SCOUT, variables: { input: body } },
        error: new GraphQLError('The server was busy.', { extensions: { code: 'RESOURCE_BUSY' } }),
      },
      balancesQuery(balances, 4),
      positionsQuery([positionFixture()]),
      {
        request: { query: RETURN_STOCK_FROM_SCOUT, variables: { input: body } },
        result: {
          data: {
            returnStockFromScout: {
              __typename: 'ReturnStockFromScoutPayload',
              inventoryPositions: [positionFixture({ withScoutQty: 0 })],
              custodyBalances: [custodyLine({ withScoutQty: 0, version: 5 })],
            },
          },
        },
      },
      balancesQuery([], 0),
      positionsQuery([positionFixture({ withScoutQty: 0 })]),
    ]);

    await user.click(await screen.findByTestId(`return-stock-${held(AVERY)}`));
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('The server was busy and nothing was changed. Try again.')).toBeInTheDocument();

    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('No Scout holds stock for this campaign yet.')).toBeInTheDocument();
  });

  it('offers only an active roster member to issue to, and still asks a removed Scout to bring their stock back', async () => {
    const user = userEvent.setup();
    renderPanel(
      reads({
        roster: [rosterRow(), rosterRow({ profileId: BETH, status: 'REMOVED', removedAt: '2026-02-08T15:00:00Z' })],
        balances: [custodyLine({ profileId: BETH, withScoutQty: 2, version: 3 })],
        total: 2,
      }),
    );

    await openIssue(user);
    await openScoutSelect(user);
    const options = await screen.findAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual(['Avery Scout · Fall 2026 Campaign']);
    // The open menu is a modal of its own: it hides the rest of the page from the
    // accessibility tree, so it closes before anything else is reached.
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    // Removed from the roster, still holding stock: the return side is driven by the
    // custody rows, because that stock has to come back either way.
    expect(await screen.findByTestId(`return-stock-${held(BETH)}`)).toBeEnabled();
    expect(screen.getByTestId('custody-total')).toHaveTextContent('2 Kernels are held by 1 Scout in this campaign.');
  });

  it('will not offer an issue when nobody on the roster can hold stock', async () => {
    renderPanel(reads({ roster: [rosterRow({ status: 'REMOVED' })], balances: [], total: 0 }));

    const button = await screen.findByTestId('issue-stock');
    expect(button).toBeDisabled();
    expect(screen.getByTestId('no-eligible-note')).toHaveTextContent('A Scout joins the roster first, and a removed Scout cannot be issued more.');
  });

  it('refuses an issue the server could only turn down, before sending it', async () => {
    const user = userEvent.setup();
    // No write mock in this test at all: nothing here may reach the server.
    renderPanel(reads({ balances: [], total: 0 }));

    await openIssue(user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Choose the Scout being issued to.')).toBeInTheDocument();

    await chooseOption('custody-scout', SCOUT_AVERY, user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Choose a product.')).toBeInTheDocument();

    await chooseOption('custody-product', 'Caramel Corn', user);
    await clearAndType('custody-quantity', '2.5', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a whole number.')).toBeInTheDocument();

    await clearAndType('custody-quantity', '0', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a quantity above zero.')).toBeInTheDocument();
  });

  it('is operable from the keyboard alone, including the write itself', async () => {
    const user = userEvent.setup();
    renderPanel([
      ...reads({ balances: [custodyLine({ withScoutQty: 1 })], total: 1 }),
      {
        request: {
          query: RETURN_STOCK_FROM_SCOUT,
          variables: {
            input: {
              unitCampaignId: UC,
              campaignId: CAMP,
              profileId: AVERY,
              items: [{ productId: CARAMEL, quantity: 1 }],
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            returnStockFromScout: {
              __typename: 'ReturnStockFromScoutPayload',
              inventoryPositions: [positionFixture({ withScoutQty: 0 })],
              custodyBalances: [custodyLine({ withScoutQty: 0, version: 5 })],
            },
          },
        },
      },
      balancesQuery([], 0),
      positionsQuery([positionFixture({ withScoutQty: 0 })]),
    ]);

    const returnButton = await screen.findByTestId(`return-stock-${held(AVERY)}`);
    returnButton.focus();
    await user.keyboard('{Enter}');

    // The dialog takes the focus, so the admin is never left tabbing through the
    // screen behind it, and its two controls are all that stands in the way.
    const confirm = await screen.findByTestId('form-dialog-confirm');
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement);

    // Tab is enough to reach the write — wherever the dialog chose to start, it is
    // inside the dialog, and the confirm is a short tab away.
    for (let tabs = 0; tabs < 3 && document.activeElement !== confirm; tabs += 1) {
      await user.tab();
    }
    expect(confirm).toHaveFocus();
    await user.keyboard('{Enter}');

    expect(await screen.findByText('No Scout holds stock for this campaign yet.')).toBeInTheDocument();
  });

  it('scrolls its tables inside their own container, so a phone-width screen can reach every column', async () => {
    renderPanel(reads());

    await screen.findByTestId('custody-total');
    const tables = screen.getAllByRole('table');
    expect(tables).toHaveLength(2);
    for (const table of tables) {
      const container = table.parentElement as HTMLElement;
      expect(getComputedStyle(container).overflowX).toBe('auto');
    }
    // Every row keeps its own return control: nothing on this screen is revealed by
    // hovering, which a touch screen never does.
    expect(await screen.findByTestId(`return-stock-${held(AVERY)}`)).toBeVisible();
  });

  it('a custody read that failed is not shown as an empty one', async () => {
    renderPanel([
      catalogQuery,
      {
        request: { query: GET_SCOUT_CUSTODY_BALANCES, variables: { unitCampaignId: UC, page: page() } },
        error: new GraphQLError('Service unavailable.'),
      },
      rosterQuery([rosterRow()]),
      positionsQuery([positionFixture()]),
    ]);

    expect(await screen.findByText('Could not load the stock held by Scouts.')).toBeInTheDocument();
    expect(screen.queryByText('No Scout holds stock for this campaign yet.')).not.toBeInTheDocument();
  });
});
