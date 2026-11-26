/**
 * The sale desk: one event's sales, entered and corrected (§4.5.1, on §4.2-§4.3).
 *
 * What each assertion pins, and why it matters:
 *
 * - The entry form is refused in the browser for the things the server would
 *   refuse identically: no lines, an out-of-window sale instant, an Other method
 *   without details, an owing line with no buyer name. A refusal means no write
 *   exists at all, so the idempotency key the screen would have sent is never
 *   spent.
 * - The create write is aimed at the event's current version, carries one
 *   idempotency key for the whole body, and reads the UTC instant back as the
 *   Unit's wall clock — the box shows the local reading, the write carries UTC.
 * - The sale list shows the server's own arithmetic (total, expected cash,
 *   revision) read back from the row, never a re-computation (SEC-05).
 * - A correction is a whole-sale act: removing a line voids it, the panel says
 *   so before the admin commits, and the write carries the sale's revision as
 *   its version condition.
 * - A void takes the whole sale down and carries its reason.
 * - A reopened event marks entry draft-only; a FINALIZED event refuses it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';
import { MockedProvider } from '@apollo/client/testing/react';
import {
  CREATE_SHOW_AND_SELL_SALE,
  CORRECT_SHOW_AND_SELL_SALE,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_SHOW_AND_SELL_SALES,
  LIST_UNIT_PAYMENT_METHODS,
  LIST_WE_OWE_OBLIGATIONS,
  VOID_SHOW_AND_SELL_SALE,
} from '../src/lib/graphql';
import { SalesDesk } from '../src/components/showSell/SalesDesk';
import { SHOW_AND_SELL_PAGE_SIZE } from '../src/lib/showSell';
import { clearAndType, chooseOption, typeInto } from './helpers/unitUi';
import type {
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSaleFieldsFragment,
  GqlWeOweObligationFieldsFragment,
} from '../src/types/graphql-generated';

const UC = 'UNITCAMP#pack-3149-fall';
const SSE = 'SSE#library';
const UNIT = 'UNIT#pack-3149';
const ZONE = 'America/Denver';
const CARAMEL = 'PROD#caramel';
const BUTTER = 'PROD#butter';

const EVENT_START = '2026-03-28T15:00:00.000Z';
const EVENT_END = '2026-03-28T18:30:00.000Z';

const SALES_VARIABLES = { showAndSellId: SSE, status: undefined, page: { limit: SHOW_AND_SELL_PAGE_SIZE } };
const OBLIGATIONS_VARIABLES = {
  unitCampaignId: UC,
  showAndSellId: SSE,
  status: undefined,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
};
const CATALOG_VARIABLES = { unitCampaignId: UC };
const METHODS_VARIABLES = { unitId: UNIT, includeInactive: true };

let keySequence = 0;
let sent: Record<string, Record<string, unknown>[]>;

beforeEach(() => {
  keySequence = 0;
  sent = { create: [], correct: [], void: [] };
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

type SaleLine = GqlShowAndSellSaleFieldsFragment['lineItems'][number];

function saleLineFixture(overrides: Partial<SaleLine> = {}): SaleLine {
  return {
    __typename: 'ShowAndSellSaleLine' as const,
    lineItemId: 'LINE#1',
    productId: CARAMEL,
    productNameSnapshot: 'Caramel',
    unitPriceCentsSnapshot: 1000,
    immediateQty: 2,
    weOweQty: 3,
    subtotalCents: 500,
    ...overrides,
  } as SaleLine;
}

function saleFixture(overrides: Partial<GqlShowAndSellSaleFieldsFragment> = {}): GqlShowAndSellSaleFieldsFragment {
  return {
    __typename: 'ShowAndSellSale',
    saleId: 'SALE#1',
    showAndSellId: SSE,
    unitId: UNIT,
    unitCampaignId: UC,
    saleAt: '2026-03-28T15:30:00.000Z',
    enteredByAccountId: 'ACCOUNT#casey',
    buyerName: 'Avery',
    buyerPhone: null,
    buyerEmail: null,
    totalCents: 500,
    revision: 2,
    status: 'ACTIVE',
    voidedByAccountId: null,
    voidedAt: null,
    createdAt: '2026-03-28T15:30:00.000Z',
    updatedAt: '2026-03-28T15:30:00.000Z',
    expectedCashCents: 200,
    lineItems: [saleLineFixture()],
    paymentMethodSnapshot: {
      __typename: 'SalePaymentSnapshot',
      methodCode: 'CASH',
      displayName: 'Cash',
      otherDetails: null,
    },
    ...overrides,
  };
}

function obligationFixture(overrides: Partial<GqlWeOweObligationFieldsFragment> = {}): GqlWeOweObligationFieldsFragment {
  return {
    __typename: 'WeOweObligation',
    weOweId: 'WEOWE#1',
    unitCampaignId: UC,
    showAndSellId: SSE,
    saleId: 'SALE#1',
    lineItemId: 'LINE#1',
    buyerName: 'Avery',
    productId: CARAMEL,
    productNameSnapshot: 'Caramel',
    originalQty: 3,
    fulfilledQty: 0,
    cancelledQty: 0,
    reservedQty: 0,
    remainingQty: 3,
    uncoveredQty: 3,
    valueCentsSnapshot: 300,
    status: 'OPEN',
    closeReason: null,
    version: 1,
    createdAt: '2026-03-28T15:30:00.000Z',
    closedAt: null,
    ...overrides,
  };
}

function eventFixture(overrides: Partial<GqlShowAndSellAdminFieldsFragment> = {}): GqlShowAndSellAdminFieldsFragment {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: SSE,
    unitId: UNIT,
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: null,
    startAt: EVENT_START,
    endAt: EVENT_END,
    status: 'ACTIVE',
    splitMethod: 'TIME_WORKED',
    weOweEnabled: true,
    productIds: [CARAMEL, BUTTER],
    allocations: [],
    slots: [],
    version: 7,
    createdAt: '2026-03-21T15:00:00.000Z',
    updatedAt: '2026-03-21T15:00:00.000Z',
    createdByAccountId: 'ACCOUNT#casey',
    updatedByAccountId: 'ACCOUNT#casey',
    cancelledByAccountId: null,
    cancelledAt: null,
    cancellationReason: null,
    ...overrides,
  };
}

const CATALOG_RESULT = {
  data: {
    unitCampaignCatalog: {
      __typename: 'UnitCampaignCatalog',
      catalogId: 'CATALOG#1',
      catalogName: 'Fall',
      products: [
        { __typename: 'Product', productId: CARAMEL, productName: 'Caramel', description: null, price: 10, sortOrder: 1 },
        { __typename: 'Product', productId: BUTTER, productName: 'Butter', description: null, price: 12.5, sortOrder: 2 },
      ],
    },
  },
};

const METHODS_RESULT = {
  data: {
    unitPaymentMethods: [
      { __typename: 'UnitPaymentMethod', paymentMethodId: 'CASH', unitId: UNIT, displayName: 'Cash', isActive: true, qrCodeS3Key: null, createdAt: null, version: 0 },
      { __typename: 'UnitPaymentMethod', paymentMethodId: 'CHECK', unitId: UNIT, displayName: 'Check', isActive: true, qrCodeS3Key: null, createdAt: null, version: 0 },
      { __typename: 'UnitPaymentMethod', paymentMethodId: 'OTHER', unitId: UNIT, displayName: 'Other', isActive: true, qrCodeS3Key: null, createdAt: null, version: 0 },
      { __typename: 'UnitPaymentMethod', paymentMethodId: 'CUSTOM#1', unitId: UNIT, displayName: 'Venmo', isActive: true, qrCodeS3Key: null, createdAt: '2026-01-01T00:00:00.000Z', version: 1 },
      { __typename: 'UnitPaymentMethod', paymentMethodId: 'CUSTOM#2', unitId: UNIT, displayName: 'Retired Pay', isActive: false, qrCodeS3Key: null, createdAt: '2026-01-01T00:00:00.000Z', version: 1 },
    ],
  },
};

function salesMock(items: GqlShowAndSellSaleFieldsFragment[]) {
  return {
    request: { query: LIST_SHOW_AND_SELL_SALES, variables: SALES_VARIABLES },
    result: {
      data: {
        showAndSellSales: {
          __typename: 'ShowAndSellSaleConnection',
          items,
          pageInfo: { endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function obligationsMock(items: GqlWeOweObligationFieldsFragment[] = []) {
  return {
    request: { query: LIST_WE_OWE_OBLIGATIONS, variables: OBLIGATIONS_VARIABLES },
    result: {
      data: {
        weOweObligations: {
          __typename: 'WeOweObligationConnection',
          items,
          pageInfo: { endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

interface DeskFixtures {
  event?: GqlShowAndSellAdminFieldsFragment;
  sales?: GqlShowAndSellSaleFieldsFragment[];
  obligations?: GqlWeOweObligationFieldsFragment[];
  mutationMocks?: object[];
}

/** The mocks every desk render needs: the catalog and methods the desk reads, the rows it lists, and the writes it is watching. */
function deskMocks(fixture: DeskFixtures) {
  return [
    { request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: CATALOG_VARIABLES }, result: CATALOG_RESULT },
    { request: { query: LIST_UNIT_PAYMENT_METHODS, variables: METHODS_VARIABLES }, result: METHODS_RESULT },
    salesMock(fixture.sales ?? []),
    obligationsMock(fixture.obligations ?? []),
    ...(fixture.mutationMocks ?? []),
  ] as never;
}

function renderDesk(fixture: DeskFixtures = {}) {
  const onChanged = vi.fn(async () => undefined);
  render(
    <MockedProvider mocks={deskMocks(fixture)}>
      <SalesDesk event={fixture.event ?? eventFixture()} timezone={ZONE} onChanged={onChanged} />
    </MockedProvider>,
  );
  return onChanged;
}

/** Fill the first line of the entry form: product, immediate quantity, sale instant. */
async function fillFirstLine(user: ReturnType<typeof userEvent.setup>) {
  await chooseOption('sale-line-product-0', 'Caramel', user);
  await typeInto('sale-line-immediate-0', '2', user);
}

describe('the entry form', () => {

  it('is refused in the browser when the sale instant falls outside the interval', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);
    await clearAndType('sale-at', '2026-03-27T12:00', user);

    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent('before this Show & Sell started');
    expect(screen.getByTestId('save-sale')).toBeDisabled();
    expect(sent.create).toHaveLength(0);
  });

  it('refuses an owing line without a buyer name', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);
    await typeInto('sale-line-weowe-0', '1', user);

    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent('buyer name');
    expect(screen.getByTestId('save-sale')).toBeDisabled();
  });

  it('refuses an Other method without details', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);
    await chooseOption('sale-payment-method', 'Other', user);

    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent('Say what makes this payment an Other one');
    expect(screen.getByTestId('save-sale')).toBeDisabled();
  });

  it('is refused in the browser with no write when the batch is empty', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');

    await user.click(screen.getByTestId('sale-line-remove-line-0'));

    expect(screen.getByTestId('save-sale')).toBeDisabled();
    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent('Add at least one line');
    expect(sent.create).toHaveLength(0);
  });

  it('writes the sale against the event version, carrying the UTC instant and one idempotency key', async () => {
    const user = userEvent.setup();
    const mutation = {
      request: {
        query: CREATE_SHOW_AND_SELL_SALE,
        variables: {
          input: {
            showAndSellId: SSE,
            saleAt: '2026-03-28T15:30:00.000Z',
            lineItems: [{ productId: CARAMEL, immediateQty: 2, weOweQty: 0 }],
            paymentMethodCode: 'CASH',
            version: { expectedVersion: 7 },
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
        },
      },
      result: (variables: Record<string, unknown>) => {
        sent.create.push(variables);
        return {
          data: {
            createShowAndSellSale: {
              __typename: 'ShowAndSellSalePayload',
              eventVersion: 8,
              draftOnly: false,
              sale: saleFixture({ saleAt: '2026-03-28T15:30:00.000Z' }),
              warnings: [],
              obligations: [],
            },
          },
        };
      },
    };
    renderDesk({ mutationMocks: [mutation] });
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);
    await chooseOption('sale-payment-method', 'Cash', user);
    await clearAndType('sale-at', '2026-03-28T09:30', user);

    await user.click(screen.getByTestId('save-sale'));

    await waitFor(() => expect(sent.create).toHaveLength(1));
    const input = sent.create[0].input as Record<string, unknown>;
    expect(input.saleAt).toBe('2026-03-28T15:30:00.000Z');
    expect(input.lineItems).toEqual([{ productId: CARAMEL, immediateQty: 2, weOweQty: 0 }]);
    expect(input.paymentMethodCode).toBe('CASH');
    expect(input.version).toEqual({ expectedVersion: 7 });
    expect(input.idempotency).toEqual({ idempotencyKey: 'test-idem-1' });
  });

  it('re-reads the event and the list after a successful write', async () => {
    const user = userEvent.setup();
    const mutation = {
      request: {
        query: CREATE_SHOW_AND_SELL_SALE,
        variables: {
          input: {
            showAndSellId: SSE,
            saleAt: '2026-03-28T15:30:00.000Z',
            lineItems: [{ productId: CARAMEL, immediateQty: 2, weOweQty: 0 }],
            paymentMethodCode: 'CASH',
            version: { expectedVersion: 7 },
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
        },
      },
      result: () => ({
        data: {
          createShowAndSellSale: {
            __typename: 'ShowAndSellSalePayload',
            eventVersion: 8,
            draftOnly: false,
            sale: saleFixture(),
            warnings: [{ __typename: 'AllocationWarning', productId: CARAMEL, currentStockQty: 2, assignedQty: 5, overageQty: 3, message: 'Over-assigned.' }],
            obligations: [],
          },
        },
      }),
    };
    const onChanged = renderDesk({ mutationMocks: [mutation] });
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);
    await chooseOption('sale-payment-method', 'Cash', user);
    await clearAndType('sale-at', '2026-03-28T09:30', user);

    await user.click(screen.getByTestId('save-sale'));

    expect(await screen.findByTestId('sale-warnings')).toHaveTextContent('Over-assigned.');
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it('marks the form draft-only for a reopened event', async () => {
    renderDesk({ event: eventFixture({ status: 'REOPENED' }) });
    expect(await screen.findByTestId('sale-draft-note')).toHaveTextContent('draft');
  });

  it('refuses entry for a FINALIZED event', async () => {
    renderDesk({ event: eventFixture({ status: 'FINALIZED' }) });
    expect(await screen.findByTestId('sale-locked-note')).toHaveTextContent('FINALIZED');
    expect(screen.getByTestId('save-sale')).toBeDisabled();
  });
});

describe('the correction form', () => {
  it('opens on Correct and refuses a kept line below the fulfilled quantity', async () => {
    const user = userEvent.setup();
    const obligations = [obligationFixture({ fulfilledQty: 2 })];
    renderDesk({ sales: [saleFixture()], obligations });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));

    await clearAndType('correction-line-weowe-0', '1', user);
    await waitFor(() => expect(screen.getByTestId('correction-line-weowe-0')).toHaveValue('1'));
    expect(screen.getByTestId('sale-correction-error')).toHaveTextContent('already fulfilled');
    expect(screen.getByTestId('save-correction')).toBeDisabled();
  });

  it('names the lines it will void before the admin commits', async () => {
    const user = userEvent.setup();
    const sale = saleFixture({
      lineItems: [
        saleLineFixture(),
        saleLineFixture({ lineItemId: 'LINE#2', productId: BUTTER, productNameSnapshot: 'Butter', subtotalCents: 1250, immediateQty: 1, weOweQty: 0 }),
      ],
    });
    renderDesk({ sales: [sale] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-line-immediate-0');
    expect(screen.queryByTestId('correction-omission-warning')).toBeNull();

    await user.click(screen.getByTestId('correction-line-remove-line-1'));

    expect(await screen.findByTestId('correction-omission-warning')).toHaveTextContent('Butter');
    expect(screen.getByTestId('correction-omission-warning')).toHaveTextContent('voids');
  });

  it('writes the correction with the sale’s revision and the event version', async () => {
    const user = userEvent.setup();
    const mutation = {
      request: {
        query: CORRECT_SHOW_AND_SELL_SALE,
        variables: {
          input: {
            showAndSellId: SSE,
            saleId: 'SALE#1',
            saleVersion: { expectedVersion: 2 },
            version: { expectedVersion: 7 },
            lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 2 }],
            reason: 'Fix the split',
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
        },
      },
      result: (variables: Record<string, unknown>) => {
        sent.correct.push(variables);
        return {
          data: {
            correctShowAndSellSale: {
              __typename: 'ShowAndSellSalePayload',
              eventVersion: 8,
              draftOnly: false,
              sale: saleFixture({ revision: 3, lineItems: [saleLineFixture({ weOweQty: 2, subtotalCents: 400 })] }),
            priorRevision: {
              __typename: 'ShowAndSellSaleRevision',
              saleId: 'SALE#1',
              showAndSellId: SSE,
              revision: 2,
              saleAt: '2026-03-28T15:30:00.000Z',
              enteredByAccountId: 'ACCOUNT#casey',
              buyerName: 'Avery',
              buyerPhone: null,
              buyerEmail: null,
              totalCents: 500,
              status: 'ACTIVE',
              correctedByAccountId: 'ACCOUNT#casey',
              correctedAt: '2026-03-28T16:00:00.000Z',
              reason: 'Fix the split',
              lineItems: [saleLineFixture()],
              paymentMethodSnapshot: { __typename: 'SalePaymentSnapshot', methodCode: 'CASH', displayName: 'Cash', otherDetails: null },
            },
            warnings: [],
            obligations: [],
          },
        },
      };
      },
    };
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-reason');
    await clearAndType('correction-line-weowe-0', '2', user);
    await typeInto('correction-reason', 'Fix the split', user);
    await user.click(screen.getByTestId('save-correction'));

    await waitFor(() => expect(sent.correct).toHaveLength(1));
    const input = sent.correct[0].input as Record<string, unknown>;
    expect(input.saleVersion).toEqual({ expectedVersion: 2 });
    expect(input.version).toEqual({ expectedVersion: 7 });
    expect(input.reason).toBe('Fix the split');
    expect(input.lineItems).toEqual([{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 2 }]);
  });

  it('shows the prior revision note after a saved correction', async () => {
    const user = userEvent.setup();
    const mutation = {
      request: {
        query: CORRECT_SHOW_AND_SELL_SALE,
        variables: {
          input: {
            showAndSellId: SSE,
            saleId: 'SALE#1',
            saleVersion: { expectedVersion: 2 },
            version: { expectedVersion: 7 },
            lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 2 }],
            reason: 'Fix the split',
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
        },
      },
      result: () => ({
        data: {
          correctShowAndSellSale: {
            __typename: 'ShowAndSellSalePayload',
            eventVersion: 8,
            draftOnly: false,
            sale: saleFixture({ revision: 3 }),
            priorRevision: {
              __typename: 'ShowAndSellSaleRevision',
              saleId: 'SALE#1',
              showAndSellId: SSE,
              revision: 2,
              saleAt: '2026-03-28T15:30:00.000Z',
              enteredByAccountId: 'ACCOUNT#casey',
              buyerName: 'Avery',
              buyerPhone: null,
              buyerEmail: null,
              totalCents: 500,
              status: 'ACTIVE',
              correctedByAccountId: 'ACCOUNT#casey',
              correctedAt: '2026-03-28T16:00:00.000Z',
              reason: 'Fix the split',
              lineItems: [saleLineFixture()],
              paymentMethodSnapshot: { __typename: 'SalePaymentSnapshot', methodCode: 'CASH', displayName: 'Cash', otherDetails: null },
            },
            warnings: [],
            obligations: [],
          },
        },
      }),
    };
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-reason');
    await clearAndType('correction-line-weowe-0', '2', user);
    await typeInto('correction-reason', 'Fix the split', user);
    await user.click(screen.getByTestId('save-correction'));

    expect(await screen.findByTestId('correction-saved')).toHaveTextContent('Revision 2 archived');
  });
});

describe('the void form', () => {
  it('refuses a void without a reason', async () => {
    const user = userEvent.setup();
    renderDesk({ sales: [saleFixture()] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('void-sale-SALE#1'));

    expect(await screen.findByTestId('sale-void-form')).toBeVisible();
    expect(screen.getByTestId('save-void')).toBeDisabled();
    expect(sent.void).toHaveLength(0);
  });

  it('writes the void with the sale’s revision and the event version', async () => {
    const user = userEvent.setup();
    const mutation = {
      request: {
        query: VOID_SHOW_AND_SELL_SALE,
        variables: {
          input: {
            showAndSellId: SSE,
            saleId: 'SALE#1',
            saleVersion: { expectedVersion: 2 },
            version: { expectedVersion: 7 },
            reason: 'Duplicate entry',
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
        },
      },
      result: (variables: Record<string, unknown>) => {
        sent.void.push(variables);
        return {
          data: {
            voidShowAndSellSale: {
              __typename: 'ShowAndSellSalePayload',
              eventVersion: 8,
              draftOnly: false,
              sale: saleFixture({ status: 'VOIDED' }),
              priorRevision: null,
              warnings: [],
              obligations: [],
            },
          },
        };
      },
    };
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('void-sale-SALE#1'));
    await typeInto('void-reason', 'Duplicate entry', user);
    await user.click(screen.getByTestId('save-void'));

    await waitFor(() => expect(sent.void).toHaveLength(1));
    const input = sent.void[0].input as Record<string, unknown>;
    expect(input.saleId).toBe('SALE#1');
    expect(input.saleVersion).toEqual({ expectedVersion: 2 });
    expect(input.version).toEqual({ expectedVersion: 7 });
    expect(input.reason).toBe('Duplicate entry');
  });
});

const STALE_SENTENCE =
  'That was refused because the event, a slot, or a signup has already moved. Reload this screen and try again with what it now shows.';

/** A create mock pinned to one intent key, so a replayed key cannot satisfy a later write. */
function createMutation(key: string, error?: GraphQLError) {
  return {
    request: {
      query: CREATE_SHOW_AND_SELL_SALE,
      variables: {
        input: {
          showAndSellId: SSE,
          saleAt: '2026-03-28T15:30:00.000Z',
          lineItems: [{ productId: CARAMEL, immediateQty: 2, weOweQty: 0 }],
          paymentMethodCode: 'CASH',
          version: { expectedVersion: 7 },
          idempotency: { idempotencyKey: key },
        },
      },
    },
    ...(error
      ? { error }
      : {
          result: (variables: Record<string, unknown>) => {
            sent.create.push(variables);
            return {
              data: {
                createShowAndSellSale: {
                  __typename: 'ShowAndSellSalePayload',
                  eventVersion: 8,
                  draftOnly: false,
                  sale: saleFixture(),
                  warnings: [],
                  obligations: [],
                },
              },
            };
          },
        }),
  };
}

async function fillCashSale(user: ReturnType<typeof userEvent.setup>) {
  await fillFirstLine(user);
  await chooseOption('sale-payment-method', 'Cash', user);
  await clearAndType('sale-at', '2026-03-28T09:30', user);
}

describe('the entry form after review', () => {
  it('keeps the split-payment guidance and the server-side field ceilings on the fields', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');

    expect(screen.getByTestId('sale-payment-help')).toBeVisible();
    await user.hover(screen.getByTestId('sale-payment-help'));
    expect(await screen.findByText('For split payments, select Other and enter each payment method and amount.')).toBeVisible();
    expect(screen.getByTestId('sale-buyer-name')).toHaveAttribute('maxlength', '200');
    expect(screen.getByTestId('sale-buyer-phone')).toHaveAttribute('maxlength', '40');
    expect(screen.getByTestId('sale-buyer-email')).toHaveAttribute('maxlength', '254');

    await chooseOption('sale-payment-method', 'Other', user);
    expect(screen.getByTestId('sale-other-details')).toHaveAttribute('maxlength', '250');
  });

  it('drops an Other note when the method is switched away, instead of sending a note on Cash', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);

    await chooseOption('sale-payment-method', 'Other', user);
    await typeInto('sale-other-details', 'Apple Pay; cash portion reported separately', user);
    expect(screen.getByTestId('sale-other-details')).toHaveValue('Apple Pay; cash portion reported separately');

    await chooseOption('sale-payment-method', 'Cash', user);

    expect(screen.queryByTestId('sale-other-details')).toBeNull();
    expect(screen.queryByTestId('sale-entry-error')).toBeNull();
    expect(screen.getByTestId('save-sale')).toBeEnabled();
    expect(sent.create).toHaveLength(0);
  });

  it('spends the create intent: a deliberately identical second sale carries a fresh key', async () => {
    const user = userEvent.setup();
    renderDesk({ mutationMocks: [createMutation('test-idem-1'), createMutation('test-idem-2')] });
    await screen.findByTestId('sale-entry-form');

    await fillCashSale(user);
    await user.click(screen.getByTestId('save-sale'));
    await waitFor(() => expect(sent.create).toHaveLength(1));

    await fillCashSale(user);
    await user.click(screen.getByTestId('save-sale'));
    await waitFor(() => expect(sent.create).toHaveLength(2));

    const keys = sent.create.map((variables) => (variables.input as Record<string, unknown>).idempotency);
    expect(keys).toEqual([
      { idempotencyKey: 'test-idem-1' },
      { idempotencyKey: 'test-idem-2' },
    ]);
  });

  it('shows the stale sentence and re-reads the board when a create is refused with CONFLICT', async () => {
    const user = userEvent.setup();
    const onChanged = renderDesk({
      mutationMocks: [createMutation('test-idem-1', new GraphQLError('expectedVersion 7 does not match 9', { extensions: { code: 'CONFLICT' } }))],
    });
    await screen.findByTestId('sale-entry-form');
    await fillCashSale(user);

    await user.click(screen.getByTestId('save-sale'));

    expect(await screen.findByTestId('sale-desk-error')).toHaveTextContent(STALE_SENTENCE);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('removes a line with the keyboard alone', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');

    const remove = screen.getByTestId('sale-line-remove-line-0');
    remove.focus();
    await user.keyboard('{Enter}');

    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent('Add at least one line');
    expect(screen.getByTestId('save-sale')).toBeDisabled();
  });
});

describe('the sale list after review', () => {
  it('names the buyer but keeps the buyer’s phone and email out of the shared list', async () => {
    renderDesk({
      sales: [saleFixture({ buyerName: 'Quinn WeOwe', buyerPhone: '555-0100', buyerEmail: 'quinn@example.test' })],
    });

    const row = await screen.findByTestId('sale-row-SALE#1');
    expect(row).toHaveTextContent('Quinn WeOwe');
    expect(row).not.toHaveTextContent('555-0100');
    expect(row).not.toHaveTextContent('quinn@example.test');
    expect(screen.queryByText('555-0100')).toBeNull();
    expect(screen.queryByText('quinn@example.test')).toBeNull();
  });

  it('says so when the event has no sales', async () => {
    renderDesk();
    expect(await screen.findByTestId('sale-list-empty')).toHaveTextContent('No sales');
  });

  it('disables Correct and Void for an ACTIVE sale on an event that is now FINALIZED', async () => {
    renderDesk({ event: eventFixture({ status: 'FINALIZED' }), sales: [saleFixture()] });

    expect(await screen.findByTestId('correct-sale-SALE#1')).toBeDisabled();
    expect(screen.getByTestId('void-sale-SALE#1')).toBeDisabled();
  });

  function pagedDesk(failedContinuation: boolean) {
    const pageOne = {
      request: { query: LIST_SHOW_AND_SELL_SALES, variables: SALES_VARIABLES },
      result: {
        data: {
          showAndSellSales: {
            __typename: 'ShowAndSellSaleConnection',
            items: [saleFixture()],
            pageInfo: { endCursor: 'cursor-1', hasNextPage: true },
          },
        },
      },
    };
    const pageTwo = {
      request: {
        query: LIST_SHOW_AND_SELL_SALES,
        variables: { showAndSellId: SSE, page: { limit: SHOW_AND_SELL_PAGE_SIZE, cursor: 'cursor-1' } },
      },
      ...(failedContinuation
        ? { error: new GraphQLError('the continuation could not be read') }
        : {
            result: {
              data: {
                showAndSellSales: {
                  __typename: 'ShowAndSellSaleConnection',
                  items: [saleFixture({ saleId: 'SALE#2', buyerName: 'Quinn' })],
                  pageInfo: { endCursor: null, hasNextPage: false },
                },
              },
            },
          }),
    };
    render(
      <MockedProvider
        mocks={[
          { request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: CATALOG_VARIABLES }, result: CATALOG_RESULT },
          { request: { query: LIST_UNIT_PAYMENT_METHODS, variables: METHODS_VARIABLES }, result: METHODS_RESULT },
          pageOne,
          obligationsMock(),
          pageTwo,
        ] as never}
      >
        <SalesDesk event={eventFixture()} timezone={ZONE} onChanged={vi.fn(async () => undefined)} />
      </MockedProvider>,
    );
  }

  it('reads the cursor through to the last page before calling the list complete', async () => {
    pagedDesk(false);

    expect(await screen.findByTestId('sale-row-SALE#1')).toBeVisible();
    expect(await screen.findByTestId('sale-row-SALE#2')).toHaveTextContent('Quinn');
    await waitFor(() => expect(screen.queryByTestId('connection-rest-loading')).toBeNull());
    expect(screen.queryByText('The rest of this list could not be loaded, so some rows are not shown.')).toBeNull();
  });

  it('says the list is short when a later page cannot be read', async () => {
    pagedDesk(true);

    expect(await screen.findByTestId('sale-row-SALE#1')).toBeVisible();
    expect(await screen.findByText('The rest of this list could not be loaded, so some rows are not shown.')).toBeVisible();
    expect(screen.queryByTestId('sale-row-SALE#2')).toBeNull();
  });
});
