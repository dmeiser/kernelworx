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
 * - One obligation is walked from the desk that writes it to the We Owe board that
 *   reserves and delivers it and back to the desk that corrects and voids the sale
 *   it came from, and both screens are driven on a phone and by keyboard alone.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';
import { MockedProvider } from '@apollo/client/testing/react';
import {
  CREATE_SHOW_AND_SELL_SALE,
  CORRECT_SHOW_AND_SELL_SALE,
  FULFILL_WE_OWE,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_SHOW_AND_SELL_SALES,
  LIST_UNIT_PAYMENT_METHODS,
  LIST_WE_OWE_OBLIGATIONS,
  SET_WE_OWE_RESERVATION,
  VOID_SHOW_AND_SELL_SALE,
} from '../src/lib/graphql';
import { SalesDesk } from '../src/components/showSell/SalesDesk';
import { WeOwePanel } from '../src/components/showSell/WeOwePanel';
import { SHOW_AND_SELL_PAGE_SIZE } from '../src/lib/showSell';
import { OTHER_DETAILS_MAX_CHARS, SALE_REASON_MAX_CHARS } from '../src/lib/saleDesk';
import { clearAndType, chooseOption, findOption, focusByTab, scrollContainerOf, typeInto, withViewport } from './helpers/unitUi';
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
  sent = { create: [], correct: [], void: [], reserve: [], fulfil: [] };
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

/** The revision the server archives when a correction lands. */
const PRIOR_REVISION = {
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
};

/**
 * A correction the server accepts, wired to the exact body the panel must send.
 * The payload is overridable so a test can answer with its own warnings, archived
 * revision, or sale.
 */
function correctionMock(input: Record<string, unknown>, payload: Record<string, unknown> = {}) {
  return {
    request: { query: CORRECT_SHOW_AND_SELL_SALE, variables: { input } },
    result: (variables: Record<string, unknown>) => {
      sent.correct.push(variables);
      return {
        data: {
          correctShowAndSellSale: {
            __typename: 'ShowAndSellSalePayload',
            eventVersion: 8,
            draftOnly: false,
            sale: saleFixture({ revision: 3 }),
            priorRevision: PRIOR_REVISION,
            warnings: [],
            obligations: [],
            ...payload,
          },
        },
      };
    },
  };
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
    await chooseOption('sale-payment-method', 'Cash', user);
    await typeInto('sale-line-weowe-0', '1', user);

    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent('buyer name');
    expect(screen.getByTestId('save-sale')).toBeDisabled();
  });

  // A half-picked method used to sit on only one half of the pair: the button was
  // enabled because the form read no error, and the click answered with the
  // sentence instead of writing. One validator means the disabled button and the
  // click always say the same thing.
  it('refuses to write until a payment method is chosen', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);

    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent('payment method the Unit still offers');
    expect(screen.getByTestId('save-sale')).toBeDisabled();
    expect(sent.create).toHaveLength(0);
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

  // The input carries maxLength, but the same ceiling is checked here as well: a
  // note that arrives by some other path (a filled-in form, a browser that does
  // not sanitize) still cannot become a body the server would refuse.
  it('refuses an Other-method note longer than the server’s ceiling', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');
    await fillFirstLine(user);
    await chooseOption('sale-payment-method', 'Other', user);
    fireEvent.change(screen.getByTestId('sale-other-details'), { target: { value: 'x'.repeat(OTHER_DETAILS_MAX_CHARS + 1) } });

    expect(screen.getByTestId('sale-entry-error')).toHaveTextContent(`Other details may not exceed ${OTHER_DETAILS_MAX_CHARS} characters`);
    expect(screen.getByTestId('save-sale')).toBeDisabled();
    expect(sent.create).toHaveLength(0);
  });

  it('adds a line to the batch', async () => {
    const user = userEvent.setup();
    renderDesk();
    await screen.findByTestId('sale-entry-form');
    await chooseOption('sale-line-product-0', 'Caramel', user);
    await user.click(screen.getByTestId('sale-line-add-line'));

    expect(screen.getByTestId('sale-line-product-1')).toBeInTheDocument();
    await typeInto('sale-line-immediate-0', '2', user);
    await chooseOption('sale-line-product-1', 'Butter', user);
    await typeInto('sale-line-immediate-1', '1', user);
    await chooseOption('sale-payment-method', 'Cash', user);

    expect(screen.getByTestId('sale-draft-total')).toHaveTextContent('$32.50');
    expect(screen.getByTestId('save-sale')).toBeEnabled();
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

  // The buyer fields are part of the write, and part of what the idempotency key
  // stands for: the same lines with a different buyer is a different body.
  it('carries the buyer contact the desk typed into the write', async () => {
    const user = userEvent.setup();
    const mutation = {
      request: {
        query: CREATE_SHOW_AND_SELL_SALE,
        variables: {
          input: {
            showAndSellId: SSE,
            saleAt: '2026-03-28T15:30:00.000Z',
            lineItems: [{ productId: CARAMEL, immediateQty: 1, weOweQty: 1 }],
            paymentMethodCode: 'CHECK',
            buyerName: 'Avery T',
            buyerPhone: '555-0100',
            buyerEmail: 'avery@example.test',
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
              sale: saleFixture(),
              warnings: [],
              obligations: [],
            },
          },
        };
      },
    };
    renderDesk({ mutationMocks: [mutation] });
    await screen.findByTestId('sale-entry-form');
    await chooseOption('sale-line-product-0', 'Caramel', user);
    await typeInto('sale-line-immediate-0', '1', user);
    await typeInto('sale-line-weowe-0', '1', user);
    await chooseOption('sale-payment-method', 'Check', user);
    await typeInto('sale-buyer-name', 'Avery T', user);
    await typeInto('sale-buyer-phone', '555-0100', user);
    await typeInto('sale-buyer-email', 'avery@example.test', user);
    await clearAndType('sale-at', '2026-03-28T09:30', user);

    await user.click(screen.getByTestId('save-sale'));

    await waitFor(() => expect(sent.create).toHaveLength(1));
    const input = sent.create[0].input as Record<string, unknown>;
    expect(input.buyerName).toBe('Avery T');
    expect(input.buyerPhone).toBe('555-0100');
    expect(input.buyerEmail).toBe('avery@example.test');
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

  // An event that closed We Owe before it ended cannot take an owing line, so the
  // desk says why the We Owe column is missing rather than leaving the admin to
  // discover it in a refused write.
  it('says the event does not offer We Owe', async () => {
    renderDesk({ event: eventFixture({ weOweEnabled: false }) });

    expect(await screen.findByTestId('sale-we-owe-off-note')).toHaveTextContent('does not offer We Owe');
    expect(screen.getByTestId('sale-line-weowe-0')).toBeDisabled();
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

  // A sale can name a method the Unit has since retired. The panel keeps that
  // method in front of the admin instead of pushing them to pick a different one,
  // and a correction that changes nothing about payment says nothing about it.
  it('keeps a retired method the sale was entered with', async () => {
    const user = userEvent.setup();
    const sale = saleFixture({
      paymentMethodSnapshot: { __typename: 'SalePaymentSnapshot', methodCode: 'CUSTOM#2', displayName: 'Retired Pay', otherDetails: null },
    });
    const mutation = correctionMock({
      showAndSellId: SSE,
      saleId: 'SALE#1',
      saleVersion: { expectedVersion: 2 },
      version: { expectedVersion: 7 },
      lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
      reason: 'Recount at the table',
      idempotency: { idempotencyKey: 'test-idem-1' },
    });
    renderDesk({ sales: [sale], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-reason');

    const retired = await findOption('correction-payment-method', /Retired Pay/, user);
    expect(retired).toHaveTextContent('Retired Pay (retired)');
    await user.click(retired);

    await typeInto('correction-reason', 'Recount at the table', user);
    await user.click(screen.getByTestId('save-correction'));

    await waitFor(() => expect(sent.correct).toHaveLength(1));
    const input = sent.correct[0].input as Record<string, unknown>;
    expect(input.paymentMethodCode).toBeUndefined();
    expect(input.otherDetails).toBeUndefined();
  });

  // A method the Unit does offer is a real choice, and switching to Other carries
  // the note the new method requires in the same write.
  it('carries a changed method and its Other note into the write', async () => {
    const user = userEvent.setup();
    const mutation = correctionMock({
      showAndSellId: SSE,
      saleId: 'SALE#1',
      saleVersion: { expectedVersion: 2 },
      version: { expectedVersion: 7 },
      lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
      reason: 'Paid by chit',
      paymentMethodCode: 'OTHER',
      otherDetails: 'Council chit #12',
      idempotency: { idempotencyKey: 'test-idem-1' },
    });
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-reason');
    await chooseOption('correction-payment-method', 'Other', user);
    await typeInto('correction-other-details', 'Council chit #12', user);
    await typeInto('correction-reason', 'Paid by chit', user);
    expect(screen.getByTestId('save-correction')).toBeEnabled();

    await user.click(screen.getByTestId('save-correction'));

    await waitFor(() => expect(sent.correct).toHaveLength(1));
    const input = sent.correct[0].input as Record<string, unknown>;
    expect(input.paymentMethodCode).toBe('OTHER');
    expect(input.otherDetails).toBe('Council chit #12');
  });

  // Only Other carries a note, and an Other with no note is not a payment anybody
  // can audit: the panel refuses it before a write exists.
  it('refuses an Other method with no note in a correction', async () => {
    const user = userEvent.setup();
    renderDesk({ sales: [saleFixture()] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await chooseOption('correction-payment-method', 'Other', user);
    await typeInto('correction-reason', 'Paid by chit', user);

    expect(screen.getByTestId('sale-correction-error')).toHaveTextContent('Say what makes this payment an Other one');
    expect(screen.getByTestId('save-correction')).toBeDisabled();
    expect(sent.correct).toHaveLength(0);
  });

  // The note the sale was entered with is editable on its own: the method stays
  // where it is and the body carries only the note.
  it('revises a stored Other note without touching the method', async () => {
    const user = userEvent.setup();
    const sale = saleFixture({
      paymentMethodSnapshot: { __typename: 'SalePaymentSnapshot', methodCode: 'OTHER', displayName: 'Other', otherDetails: 'Chit' },
    });
    const mutation = correctionMock({
      showAndSellId: SSE,
      saleId: 'SALE#1',
      saleVersion: { expectedVersion: 2 },
      version: { expectedVersion: 7 },
      lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
      reason: 'Chit number was wrong',
      otherDetails: 'Council chit #12',
      idempotency: { idempotencyKey: 'test-idem-1' },
    });
    renderDesk({ sales: [sale], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await clearAndType('correction-other-details', 'Council chit #12', user);
    await typeInto('correction-reason', 'Chit number was wrong', user);
    await user.click(screen.getByTestId('save-correction'));

    await waitFor(() => expect(sent.correct).toHaveLength(1));
    const input = sent.correct[0].input as Record<string, unknown>;
    expect(input.otherDetails).toBe('Council chit #12');
    expect(input.paymentMethodCode).toBeUndefined();
  });

  // Both free-text fields have the server's own ceiling on the input, so the only
  // way past it is a value that arrived by another path. The panel still refuses.
  it('refuses a correction reason or note longer than the server’s ceiling', async () => {
    const user = userEvent.setup();
    renderDesk({ sales: [saleFixture()] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    const reason = screen.getByTestId('correction-reason') as HTMLInputElement;
    const reasonCeiling = reason.maxLength;
    expect(reasonCeiling).toBe(SALE_REASON_MAX_CHARS);
    // A typed value stops at the ceiling, so the only way past it is a value the
    // field did not type. fireEvent hands the panel that value directly.
    fireEvent.change(reason, { target: { value: 'r'.repeat(reasonCeiling + 1) } });
    await waitFor(() =>
      expect(screen.getByTestId('sale-correction-error')).toHaveTextContent(`The reason may not exceed ${reasonCeiling} characters`),
    );
    expect(screen.getByTestId('save-correction')).toBeDisabled();

    // The reason is in order now; the note is the field that cannot be sent.
    await clearAndType('correction-reason', 'Paid by chit', user);
    await chooseOption('correction-payment-method', 'Other', user);
    const details = screen.getByTestId('correction-other-details') as HTMLInputElement;
    expect(details.maxLength).toBe(OTHER_DETAILS_MAX_CHARS);
    fireEvent.change(details, { target: { value: 'x'.repeat(OTHER_DETAILS_MAX_CHARS + 1) } });
    await waitFor(() =>
      expect(screen.getByTestId('sale-correction-error')).toHaveTextContent(
        `Other details may not exceed ${OTHER_DETAILS_MAX_CHARS} characters`,
      ),
    );
    expect(screen.getByTestId('save-correction')).toBeDisabled();
    expect(sent.correct).toHaveLength(0);
  });

  // A line the buyer never took is added as a supplemental row: it carries no
  // stable id, and the read-out counts it with the lines that did.
  it('adds a supplemental line beside the stored ones', async () => {
    const user = userEvent.setup();
    const mutation = correctionMock({
      showAndSellId: SSE,
      saleId: 'SALE#1',
      saleVersion: { expectedVersion: 2 },
      version: { expectedVersion: 7 },
      lineItems: [
        { lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 },
        { productId: BUTTER, immediateQty: 1, weOweQty: 0 },
      ],
      reason: 'Second box came back',
      idempotency: { idempotencyKey: 'test-idem-1' },
    });
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await user.click(screen.getByTestId('correction-line-add-line'));
    await chooseOption('correction-line-product-1', 'Butter', user);
    await typeInto('correction-line-immediate-1', '1', user);
    await typeInto('correction-reason', 'Second box came back', user);

    expect(screen.getByTestId('correction-line-correcting-0')).toHaveTextContent('Correcting this line');
    expect(screen.getByTestId('correction-draft-total')).toHaveTextContent('across 2 lines');

    await user.click(screen.getByTestId('save-correction'));

    await waitFor(() => expect(sent.correct).toHaveLength(1));
    const input = sent.correct[0].input as Record<string, unknown>;
    expect(input.lineItems).toEqual([
      { lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 },
      { productId: BUTTER, immediateQty: 1, weOweQty: 0 },
    ]);
  });

  // The buyer fields move one at a time: the body carries the ones that changed
  // and leaves the ones that did not for the snapshot the server already holds.
  // A correction of an owing sale has to keep a buyer name on the line, and the
  // body carries only the contact fields that actually moved.
  it('carries only the buyer fields that moved', async () => {
    const user = userEvent.setup();
    const mutation = correctionMock(
      {
        showAndSellId: SSE,
        saleId: 'SALE#1',
        saleVersion: { expectedVersion: 2 },
        version: { expectedVersion: 7 },
        lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
        reason: 'Wrong phone',
        buyerPhone: '555-010-0100',
        buyerEmail: 'avery@example.test',
        idempotency: { idempotencyKey: 'test-idem-1' },
      },
      { sale: saleFixture({ revision: 3, buyerPhone: '555-010-0100', buyerEmail: 'avery@example.test' }) },
    );
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await typeInto('correction-buyer-phone', '555-010-0100', user);
    await typeInto('correction-buyer-email', 'avery@example.test', user);
    await typeInto('correction-reason', 'Wrong phone', user);
    // The write carries what the fields hold, so the fields have to hold it first.
    await waitFor(() => {
      expect((screen.getByTestId('correction-buyer-phone') as HTMLInputElement).value).toBe('555-010-0100');
      expect((screen.getByTestId('correction-buyer-email') as HTMLInputElement).value).toBe('avery@example.test');
    });
    await user.click(screen.getByTestId('save-correction'));

    await waitFor(() => expect(sent.correct).toHaveLength(1));
    const input = sent.correct[0].input as Record<string, unknown>;
    expect(input.buyerPhone).toBe('555-010-0100');
    expect(input.buyerEmail).toBe('avery@example.test');
    expect(input.buyerName).toBeUndefined();
  });

  // What the saved correction archived, in the words the server has: a revision
  // with no reason of its own still says what happened.
  it('names the archived revision even when it carries no reason', async () => {
    const user = userEvent.setup();
    const mutation = correctionMock(
      {
        showAndSellId: SSE,
        saleId: 'SALE#1',
        saleVersion: { expectedVersion: 2 },
        version: { expectedVersion: 7 },
        lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
        reason: 'Recount at the table',
        idempotency: { idempotencyKey: 'test-idem-1' },
      },
      { priorRevision: { ...PRIOR_REVISION, reason: null } },
    );
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await typeInto('correction-reason', 'Recount at the table', user);
    await user.click(screen.getByTestId('save-correction'));

    expect(await screen.findByTestId('correction-saved')).toHaveTextContent('Revision 2 archived.');
    expect(screen.getByTestId('cancel-correction')).toHaveTextContent('Done');
  });

  // The server's warnings survive the write: an over-assigned product is still
  // over-assigned after a correction, and the panel has to say so.
  it('keeps the warnings the server answered with', async () => {
    const user = userEvent.setup();
    const mutation = correctionMock(
      {
        showAndSellId: SSE,
        saleId: 'SALE#1',
        saleVersion: { expectedVersion: 2 },
        version: { expectedVersion: 7 },
        lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 9, weOweQty: 0 }],
        reason: 'All taken at the table',
        idempotency: { idempotencyKey: 'test-idem-1' },
      },
      { warnings: [{ __typename: 'AllocationWarning', productId: CARAMEL, currentStockQty: 2, assignedQty: 9, overageQty: 7, message: 'Over-assigned by 7.' }] },
    );
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await clearAndType('correction-line-immediate-0', '9', user);
    await clearAndType('correction-line-weowe-0', '0', user);
    await typeInto('correction-reason', 'All taken at the table', user);
    await user.click(screen.getByTestId('save-correction'));

    expect(await screen.findByTestId('correction-warnings')).toHaveTextContent('Over-assigned by 7.');
    expect(screen.getAllByTestId('correction-warning')).toHaveLength(1);
  });

  // A correction that lands on a sale someone else already corrected has to stop
  // and re-read, not offer to write over a revision nobody has looked at.
  it('shows the stale sentence and re-reads the board when a correction is refused with CONFLICT', async () => {
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
            lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
            reason: 'Recount at the table',
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
        },
      },
      error: new GraphQLError('conflict', { extensions: { code: 'CONFLICT' } }),
    };
    const onChanged = renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await typeInto('correction-reason', 'Recount at the table', user);
    await user.click(screen.getByTestId('save-correction'));

    expect(await screen.findByTestId('sale-correction-error')).toBeInTheDocument();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  // Leaving one line out and leaving two out are different acts in the sentence
  // the admin has to read before committing, and the summary says how many lines
  // the sale has in the first place.
  it('says which lines are being voided, one at a time or together', async () => {
    const user = userEvent.setup();
    const twoLines = saleFixture({
      lineItems: [saleLineFixture(), saleLineFixture({ lineItemId: 'LINE#2', productId: BUTTER, productNameSnapshot: 'Butter' })],
    });
    renderDesk({ sales: [twoLines] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await waitFor(() => expect(screen.getByTestId('correction-draft-total')).toHaveTextContent('across 2 lines'));

    await user.click(screen.getByTestId('correction-line-remove-line-0'));
    await waitFor(() => expect(screen.getByTestId('correction-omission-warning')).toHaveTextContent('voids that line'));
    expect(screen.getByTestId('correction-draft-total')).toHaveTextContent('1 line omitted');

    await user.click(screen.getByTestId('correction-line-remove-line-0'));
    await waitFor(() => expect(screen.getByTestId('correction-omission-warning')).toHaveTextContent('voids those lines'));
    expect(screen.getByTestId('correction-draft-total')).toHaveTextContent('2 lines omitted');
  });

  // A product the catalog no longer lists can still sit on a stored sale. The picker
  // keeps offering it, so the admin can keep the line instead of being pushed into
  // dropping it — and dropping it would cancel an obligation nobody decided to cancel.
  it('keeps a product the catalog has dropped on a stored line', async () => {
    const user = userEvent.setup();
    const sale = saleFixture({
      lineItems: [saleLineFixture({ productId: 'PROD#retired', productNameSnapshot: 'Old Caramel' })],
    });
    renderDesk({ sales: [sale] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    const option = await findOption('correction-line-product-0', 'PROD#retired', user);
    expect(option).toBeInTheDocument();
    await user.click(option);
    expect(screen.getByTestId('save-correction')).toBeDisabled();

    await typeInto('correction-reason', 'Recount at the table', user);
    expect(screen.getByTestId('save-correction')).toBeEnabled();
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

  // A sale can be stored with no buyer at all, and an Other payment can be stored
  // with no note. The panel opens on what the sale holds — nothing in the buyer
  // cell, nothing in the note — and refuses to write until the admin fills in what
  // the event requires: the name behind an owing line, or a method that carries no
  // note. Only the fields that moved leave the browser.
  it('opens a sale stored without a buyer or a note and sends only what the admin filled in', async () => {
    const user = userEvent.setup();
    const mutation = correctionMock(
      {
        showAndSellId: SSE,
        saleId: 'SALE#1',
        saleVersion: { expectedVersion: 2 },
        version: { expectedVersion: 7 },
        lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
        reason: 'Named the buyer at the desk',
        buyerName: 'Avery',
        paymentMethodCode: 'CASH',
        idempotency: { idempotencyKey: 'test-idem-1' },
      },
      { sale: saleFixture({ revision: 3, buyerName: 'Avery' }) },
    );
    const stored = saleFixture({
      buyerName: null,
      paymentMethodSnapshot: { __typename: 'SalePaymentSnapshot', methodCode: 'OTHER', displayName: 'Other', otherDetails: null },
    });
    renderDesk({ sales: [stored], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-buyer-name');

    // The panel opens on the stored sale, not on a blank form: the buyer cell is
    // empty because the sale holds no buyer, and the first sentence is the missing
    // reason.
    expect((screen.getByTestId('correction-buyer-name') as HTMLInputElement).value).toBe('');
    expect(screen.getByTestId('sale-correction-error')).toHaveTextContent('Say why the sale is being corrected');
    expect(screen.getByTestId('save-correction')).toBeDisabled();

    await typeInto('correction-reason', 'Named the buyer at the desk', user);
    // Then the owing line: a We Owe the sale created needs the name behind it.
    await waitFor(() => expect(screen.getByTestId('sale-correction-error')).toHaveTextContent('buyer name'));

    await typeInto('correction-buyer-name', 'Avery', user);
    // Then the payment: Other without a note is a payment no report can read.
    await waitFor(() => expect(screen.getByTestId('sale-correction-error')).toHaveTextContent('Say what makes this payment an Other one'));

    await typeInto('correction-other-details', 'Paid at the door', user);

    // Switching the method away from Other drops the note the field was holding:
    // Cash carries no note, and a body that sent one would be a body the server
    // refuses.
    await chooseOption('correction-payment-method', 'Cash', user);
    expect(screen.queryByTestId('correction-other-details')).toBeNull();
    await waitFor(() => expect((screen.getByTestId('correction-payment-method') as HTMLElement).textContent).toContain('Cash'));
    expect(screen.getByTestId('save-correction')).toBeEnabled();

    await user.click(screen.getByTestId('save-correction'));
    await waitFor(() => expect(sent.correct).toHaveLength(1));
    const input = sent.correct[0].input as Record<string, unknown>;
    expect(input.buyerName).toBe('Avery');
    expect(input.paymentMethodCode).toBe('CASH');
    expect(input).not.toHaveProperty('buyerPhone');
    expect(input).not.toHaveProperty('buyerEmail');
    expect(input).not.toHaveProperty('otherDetails');
  });

  // Some deployments keep the revision the correction replaced, and some answer
  // with only the new one. Either way the admin is told the correction landed; the
  // panel never claims an archived revision the server did not name.
  it('says only that the correction was saved when the server keeps no archived revision', async () => {
    const user = userEvent.setup();
    const mutation = correctionMock(
      {
        showAndSellId: SSE,
        saleId: 'SALE#1',
        saleVersion: { expectedVersion: 2 },
        version: { expectedVersion: 7 },
        lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 2 }],
        reason: 'Fix the split',
        idempotency: { idempotencyKey: 'test-idem-1' },
      },
      { sale: saleFixture({ revision: 3, lineItems: [saleLineFixture({ weOweQty: 2, subtotalCents: 400 })] }), priorRevision: null },
    );
    renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-reason');
    await clearAndType('correction-line-weowe-0', '2', user);
    await typeInto('correction-reason', 'Fix the split', user);
    await user.click(screen.getByTestId('save-correction'));

    expect(await screen.findByTestId('correction-saved')).toHaveTextContent('Correction saved.');
    expect(screen.getByTestId('save-correction')).toBeDisabled();
    expect(screen.getByTestId('cancel-correction')).toHaveTextContent('Done');
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

  // A sale someone else already corrected or voided cannot be taken down over
  // their head: the panel stops, says why, and re-reads the list.
  it('shows the stale sentence and re-reads the board when a void is refused with CONFLICT', async () => {
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
      error: new GraphQLError('conflict', { extensions: { code: 'CONFLICT' } }),
    };
    const onChanged = renderDesk({ sales: [saleFixture()], mutationMocks: [mutation] });
    await screen.findByTestId('sale-row-SALE#1');

    await user.click(screen.getByTestId('void-sale-SALE#1'));
    await typeInto('void-reason', 'Duplicate entry', user);
    await user.click(screen.getByTestId('save-void'));

    expect(await screen.findByTestId('sale-void-error')).toHaveTextContent('already moved');
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  // A void takes the whole sale, so the panel says how many lines it is taking down.
  it('counts the lines a void takes down, one or many', async () => {
    const user = userEvent.setup();
    const twoLines = saleFixture({
      saleId: 'SALE#2',
      lineItems: [saleLineFixture(), saleLineFixture({ lineItemId: 'LINE#2', productId: BUTTER, productNameSnapshot: 'Butter' })],
    });
    renderDesk({ sales: [saleFixture(), twoLines] });
    await screen.findByTestId('sale-row-SALE#2');

    await user.click(screen.getByTestId('void-sale-SALE#1'));
    expect(screen.getByTestId('sale-void-summary')).toHaveTextContent('1 line');
    await user.click(screen.getByTestId('cancel-void'));

    await user.click(screen.getByTestId('void-sale-SALE#2'));
    expect(screen.getByTestId('sale-void-summary')).toHaveTextContent('2 lines');
  });

  // A sale the server already took down stays on the list as history, and the two
  // actions that act on a live sale stop working for it.
  it('keeps a voided sale on the list with its actions closed', async () => {
    renderDesk({
      sales: [saleFixture({ status: 'VOIDED', voidedByAccountId: 'ACCOUNT#averyn', voidedAt: '2026-03-28T16:00:00.000Z' })],
    });

    const row = await screen.findByTestId('sale-row-SALE#1');
    expect(row).toHaveTextContent('VOIDED');
    expect(screen.getByTestId('correct-sale-SALE#1')).toBeDisabled();
    expect(screen.getByTestId('void-sale-SALE#1')).toBeDisabled();
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

  // The note is part of the body, so it is part of what the key stands for: the
  // same lines paid another way is another write.
  it('writes an Other payment with the note that explains it', async () => {
    const user = userEvent.setup();
    const mutation = {
      request: {
        query: CREATE_SHOW_AND_SELL_SALE,
        variables: {
          input: {
            showAndSellId: SSE,
            saleAt: '2026-03-28T15:30:00.000Z',
            lineItems: [{ productId: CARAMEL, immediateQty: 2, weOweQty: 0 }],
            paymentMethodCode: 'OTHER',
            otherDetails: 'Apple Pay; cash portion reported separately',
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
    await chooseOption('sale-payment-method', 'Other', user);
    await typeInto('sale-other-details', 'Apple Pay; cash portion reported separately', user);
    await clearAndType('sale-at', '2026-03-28T09:30', user);

    await user.click(screen.getByTestId('save-sale'));
    await waitFor(() => expect(sent.create).toHaveLength(1));

    const input = sent.create[0].input as Record<string, unknown>;
    expect(input.paymentMethodCode).toBe('OTHER');
    expect(input.otherDetails).toBe('Apple Pay; cash portion reported separately');
    expect(input.idempotency).toEqual({ idempotencyKey: 'test-idem-1' });
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

  // A sale entered with no buyer is a normal Cash sale: the list still has to say
  // the buyer cell is empty rather than leave an unexplained gap.
  it('marks the buyer cell for a sale entered without a buyer', async () => {
    renderDesk({ sales: [saleFixture({ buyerName: null })] });

    expect(await screen.findByTestId('sale-row-SALE#1')).toHaveTextContent('—');
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

// ---------------------------------------------------------------------------------------------
// §4.5.1: one obligation, from the desk that writes it to the We Owe board that closes it
// ---------------------------------------------------------------------------------------------

describe('one obligation, from the desk that writes it to the board that closes it', () => {
  /*
   * Every screen above is tested where it stands; what is tested here is the chain
   * between them, which is what a Kernel actually walks on a sale Saturday. The sale
   * writes an obligation, the board holds Kernels against that obligation and later
   * delivers part of it, and the desk then corrects and voids the sale the obligation
   * came from. The stages hand the server's own rows to the screen after them, so each
   * write is aimed at the version the write before it returned, and the delivery the
   * board recorded comes back to the desk as the floor under what a correction may do
   * to that line. A screen that drops a version, a line id, or a fulfilled count loses
   * the sale in the middle of it.
   */

  /** One stage of the desk, with the handle that takes it down before the next stage mounts. */
  function mountDesk(fixture: DeskFixtures) {
    const onChanged = vi.fn(async () => undefined);
    const view = render(
      <MockedProvider
        mocks={
          [
            ...deskMocks(fixture),
            // A successful write makes the desk re-read its rows and MockedProvider
            // answers one read per mock, so this second copy is that re-read.
            salesMock(fixture.sales ?? []),
            obligationsMock(fixture.obligations ?? []),
          ] as never
        }
      >
        <SalesDesk event={fixture.event ?? eventFixture()} timezone={ZONE} onChanged={onChanged} />
      </MockedProvider>,
    );
    return { onChanged, view };
  }

  /** One stage of the We Owe board, reading the rows the stage before it produced. */
  function mountBoard(obligations: readonly GqlWeOweObligationFieldsFragment[], writes: object[]) {
    const onChanged = vi.fn(async () => undefined);
    const read = obligationsMock([...obligations]);
    const view = render(
      <MockedProvider mocks={[read, read, ...writes] as never}>
        <WeOwePanel event={eventFixture()} timezone={ZONE} onChanged={onChanged} />
      </MockedProvider>,
    );
    return { onChanged, view };
  }

  /** A reservation write, answering with the row as the server has it afterwards. */
  function reserveWrite(input: Record<string, unknown>, after: GqlWeOweObligationFieldsFragment) {
    return {
      request: { query: SET_WE_OWE_RESERVATION, variables: { input } },
      result: (variables: Record<string, unknown>) => {
        sent.reserve.push(variables);
        return {
          data: { setWeOweReservation: { __typename: 'SetWeOweReservationPayload', obligation: after } },
        };
      },
    };
  }

  /** A fulfillment write, answering with the row, the delivery, and the movement it drew on. */
  function fulfillWrite(input: Record<string, unknown>, after: GqlWeOweObligationFieldsFragment) {
    return {
      request: { query: FULFILL_WE_OWE, variables: { input } },
      result: (variables: Record<string, unknown>) => {
        sent.fulfil.push(variables);
        return {
          data: {
            fulfillWeOwe: {
              __typename: 'FulfillWeOwePayload',
              obligation: after,
              fulfillment: {
                __typename: 'WeOweFulfillment',
                fulfillmentId: 'FULFILL#1',
                weOweId: 'WEOWE#1',
                quantity: 2,
                source: 'KERNEL_STOCK',
                actorAccountId: 'ACCOUNT#casey',
                createdAt: '2026-03-28T16:00:00.000Z',
                inventoryMovementId: 'MOVE#1',
              },
            },
          },
        };
      },
    };
  }

  /** The body of a write, for reading its version condition back out. */
  function bodyOf(write: Record<string, unknown>[]): Record<string, unknown> {
    return write[0].input as Record<string, unknown>;
  }

  it('writes the sale, holds what it owes, delivers two, corrects it, and shows which void the server refuses', async () => {
    const user = userEvent.setup();

    // 1. The desk: two Kernels taken at the table, three owed later, and the buyer
    //    named because an owed quantity with no name on it is a promise nobody holds.
    const owed = obligationFixture();
    const desk = mountDesk({
      mutationMocks: [
        {
          request: {
            query: CREATE_SHOW_AND_SELL_SALE,
            variables: {
              input: {
                showAndSellId: SSE,
                saleAt: '2026-03-28T15:30:00.000Z',
                lineItems: [{ productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
                paymentMethodCode: 'CASH',
                buyerName: 'Avery',
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
                  sale: saleFixture(),
                  warnings: [],
                  obligations: [owed],
                },
              },
            };
          },
        },
      ],
    });

    await screen.findByTestId('sale-entry-form');
    await chooseOption('sale-line-product-0', 'Caramel', user);
    await typeInto('sale-line-immediate-0', '2', user);
    await typeInto('sale-line-weowe-0', '3', user);
    await typeInto('sale-buyer-name', 'Avery', user);
    await chooseOption('sale-payment-method', 'Cash', user);
    await clearAndType('sale-at', '2026-03-28T09:30', user);
    await user.click(screen.getByTestId('save-sale'));

    await waitFor(() => expect(sent.create).toHaveLength(1));
    expect(bodyOf(sent.create).lineItems).toEqual([{ productId: CARAMEL, immediateQty: 2, weOweQty: 3 }]);
    desk.view.unmount();

    // 2. The board: the Kernels for that promise are held against it. The card it shows
    //    is the row the create reported, and the write is aimed at that row's version 1.
    const reserved = { ...owed, reservedQty: 3, uncoveredQty: 0, version: 2 };
    const holding = mountBoard([owed], [
      reserveWrite(
        { weOweId: 'WEOWE#1', targetReservedQty: 3, version: { expectedVersion: 1 }, idempotency: { idempotencyKey: 'test-idem-2' } },
        reserved,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    expect(screen.getByTestId('we-owe-buyer-WEOWE#1')).toHaveTextContent('Avery');
    await clearAndType('we-owe-reserve-target-WEOWE#1', '3', user);
    await user.click(screen.getByTestId('we-owe-save-reservation-WEOWE#1'));

    await waitFor(() => expect(sent.reserve).toHaveLength(1));
    expect(bodyOf(sent.reserve).version).toEqual({ expectedVersion: 1 });
    holding.view.unmount();

    // 3. The board, a week later: two of the three are delivered out of reserved stock,
    //    aimed at version 2 — the version the reservation wrote.
    const delivered = { ...reserved, fulfilledQty: 2, reservedQty: 1, remainingQty: 1, version: 3 };
    const delivery = mountBoard([reserved], [
      fulfillWrite(
        { weOweId: 'WEOWE#1', quantity: 2, source: 'KERNEL_STOCK', version: { expectedVersion: 2 }, idempotency: { idempotencyKey: 'test-idem-3' } },
        delivered,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await clearAndType('we-owe-fulfill-qty-WEOWE#1', '2', user);
    await user.click(screen.getByTestId('we-owe-fulfill-WEOWE#1'));

    await waitFor(() => expect(sent.fulfil).toHaveLength(1));
    expect(bodyOf(sent.fulfil).version).toEqual({ expectedVersion: 2 });
    expect(bodyOf(sent.fulfil).source).toBe('KERNEL_STOCK');
    delivery.view.unmount();

    // 4. Back at the desk: the two Kernels the board delivered are now a floor the
    //    correction cannot go under, because the obligation the desk reads carries the
    //    fulfilled count the board wrote. Taking the line to one owed Kernel would
    //    cancel an obligation the Unit has already partly kept.
    const correction = correctionMock({
      showAndSellId: SSE,
      saleId: 'SALE#1',
      saleVersion: { expectedVersion: 2 },
      version: { expectedVersion: 7 },
      lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
      reason: 'Owed three all along',
      idempotency: { idempotencyKey: 'test-idem-4' },
    });
    const revised = mountDesk({ sales: [saleFixture()], obligations: [delivered], mutationMocks: [correction] });

    await screen.findByTestId('sale-row-SALE#1');
    await user.click(screen.getByTestId('correct-sale-SALE#1'));
    await screen.findByTestId('correction-reason');

    await clearAndType('correction-line-weowe-0', '1', user);
    expect(screen.getByTestId('sale-correction-error')).toHaveTextContent('already fulfilled');
    expect(screen.getByTestId('save-correction')).toBeDisabled();

    await clearAndType('correction-line-weowe-0', '3', user);
    await typeInto('correction-reason', 'Owed three all along', user);
    await user.click(screen.getByTestId('save-correction'));

    await waitFor(() => expect(sent.correct).toHaveLength(1));
    // The corrected line still carries the id of the line the obligation was written
    // from: that id is what makes "change this line" and "drop this line" different.
    expect(bodyOf(sent.correct).lineItems).toEqual([{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }]);
    revised.view.unmount();

    // 5. The void aimed at that sale is refused, in the server's own words: two Kernels
    //    are already in the buyer's hands, so the sale cannot be taken down as though
    //    nothing was delivered (SALE-M-03-02). The attempt is still pinned to revision 3
    //    — the one the correction left — because a void aimed at an old revision is a
    //    different body, and the screen that holds the old one has to be told, not
    //    silently re-aimed.
    const refused = mountDesk({
      sales: [saleFixture({ revision: 3 })],
      obligations: [delivered],
      mutationMocks: [
        {
          request: {
            query: VOID_SHOW_AND_SELL_SALE,
            variables: {
              input: {
                showAndSellId: SSE,
                saleId: 'SALE#1',
                saleVersion: { expectedVersion: 3 },
                version: { expectedVersion: 7 },
                reason: 'Entered twice at the table',
                idempotency: { idempotencyKey: 'test-idem-5' },
              },
            },
          },
          error: new GraphQLError(
            'This line already has 2 fulfilled; a correction or void cannot take back stock the buyer has (SALE-M-03-02).',
            { extensions: { code: 'FULFILLED_WE_OWE_PROTECTED' } },
          ),
        },
      ],
    });

    await screen.findByTestId('sale-row-SALE#1');
    await user.click(screen.getByTestId('void-sale-SALE#1'));
    await typeInto('void-reason', 'Entered twice at the table', user);
    await user.click(screen.getByTestId('save-void'));

    expect(await screen.findByTestId('sale-void-error')).toHaveTextContent('cannot take back stock the buyer has');
    expect(screen.getByTestId('sale-row-SALE#1')).toHaveTextContent('ACTIVE');
    refused.view.unmount();

    // 6. The void that does land belongs to the other sale at the table: it owed two and
    //    never received one, so the whole sale goes down and its obligation closes as
    //    cancelled rather than staying something to act on.
    const owedAgain = obligationFixture({
      weOweId: 'WEOWE#2',
      saleId: 'SALE#2',
      lineItemId: 'LINE#2',
      buyerName: 'Quinn',
      originalQty: 2,
      remainingQty: 2,
      uncoveredQty: 2,
      valueCentsSnapshot: 200,
    });
    // The other sale at the table: it owes two Kernels and never delivered one, which is
    // the shape a void can close.
    const repeat = saleFixture({
      saleId: 'SALE#2',
      revision: 1,
      buyerName: 'Quinn',
      totalCents: 200,
      expectedCashCents: 0,
      lineItems: [saleLineFixture({ lineItemId: 'LINE#2', immediateQty: 0, weOweQty: 2, subtotalCents: 200 })],
    });
    const cancelledAgain = {
      ...owedAgain,
      status: 'CLOSED' as const,
      closeReason: 'CANCELLED' as const,
      cancelledQty: 2,
      remainingQty: 0,
      version: 2,
    };
    const deskAfter = mountDesk({
      sales: [saleFixture({ revision: 3 }), repeat],
      obligations: [delivered, owedAgain],
      mutationMocks: [
        {
          request: {
            query: VOID_SHOW_AND_SELL_SALE,
            variables: {
              input: {
                showAndSellId: SSE,
                saleId: 'SALE#2',
                saleVersion: { expectedVersion: 1 },
                version: { expectedVersion: 7 },
                reason: 'Buyer never came back',
                idempotency: { idempotencyKey: 'test-idem-6' },
              },
            },
          },
          result: (variables: Record<string, unknown>) => {
            sent.void.push(variables);
            return {
              data: {
                voidShowAndSellSale: {
                  __typename: 'ShowAndSellSalePayload',
                  eventVersion: 9,
                  draftOnly: false,
                  sale: { ...repeat, revision: 2, status: 'VOIDED' as const, voidedByAccountId: 'ACCOUNT#casey', voidedAt: '2026-03-28T17:00:00.000Z' },
                  priorRevision: null,
                  warnings: [],
                  obligations: [cancelledAgain],
                },
              },
            };
          },
        },
      ],
    });

    await screen.findByTestId('sale-row-SALE#2');
    await user.click(screen.getByTestId('void-sale-SALE#2'));
    await typeInto('void-reason', 'Buyer never came back', user);
    await user.click(screen.getByTestId('save-void'));

    await waitFor(() => expect(sent.void).toHaveLength(1));
    expect(bodyOf(sent.void).saleVersion).toEqual({ expectedVersion: 1 });
    deskAfter.view.unmount();

    // 7. And the board the Kernel closes the tab on shows both results side by side: the
    //    obligation the refused void left alone is still open with its two delivered
    //    Kernels counted and its actions still offered, while the cancelled one is
    //    history with its reason.
    const closing = mountBoard([delivered, cancelledAgain], []);

    const stillOpen = await screen.findByTestId('we-owe-card-WEOWE#1');
    expect(screen.getByTestId('we-owe-status-WEOWE#1')).toHaveTextContent('Open');
    expect(stillOpen).toHaveTextContent('fulfilled 2');
    expect(screen.getByTestId('we-owe-fulfill-WEOWE#1')).toBeInTheDocument();

    const closed = screen.getByTestId('we-owe-card-WEOWE#2');
    expect(screen.getByTestId('we-owe-status-WEOWE#2')).toHaveTextContent('Closed · Cancelled');
    expect(closed).toHaveTextContent('history');
    expect(screen.queryByTestId('we-owe-save-reservation-WEOWE#2')).toBeNull();
    expect(screen.queryByTestId('we-owe-fulfill-WEOWE#2')).toBeNull();
    closing.view.unmount();
  });
});

// ---------------------------------------------------------------------------------------------
// §4.5.1: the desk and the board on a phone, and with the keyboard alone
// ---------------------------------------------------------------------------------------------

describe('§4.5.1: the desk and the board on a 390-pixel viewport', () => {
  /*
   * A Kernel works the table with a phone in one hand, and an admin who does not use a
   * pointer has to reach the same writes with Tab and Enter. Both claims are about the
   * markup: at a phone width every control is present and reachable, and a table that
   * is wider than the phone slides inside its own container instead of pushing its
   * last column — the Correct and Void buttons, the We Owe quantity — past the edge of
   * the screen, where nothing can bring it back.
   *
   * jsdom performs no layout, so `scrollWidth` reads 0 whatever the markup is and a
   * measured overflow cannot be asserted here. What these tests pin is the shape that
   * makes a wide column reachable at all: the table's nearest scrolling ancestor, and
   * the fact that a row's controls sit inside it.
   */

  /** The scrolling container the named table has to sit inside. */
  function scrollContainerFor(tableName: string): HTMLElement {
    const table = screen.getByRole('table', { name: tableName });
    const scroller = scrollContainerOf(table);
    expect(scroller, `the "${tableName}" table sits outside any scrolling container, so a phone cuts off its last column`).not.toBeNull();
    return scroller as HTMLElement;
  }

  it('keeps every control of a sale line present at phone width, and scrolls the rows rather than the page', async () => {
    await withViewport(390, async () => {
      renderDesk();
      await screen.findByTestId('sale-entry-form');

      const scroller = scrollContainerFor('Sale lines');
      // The whole row scrolls together: a control left outside the scroller would sit
      // past the edge of the phone with nothing to slide it back into view.
      expect(scroller).toContainElement(screen.getByTestId('sale-line-product-0'));
      expect(scroller).toContainElement(screen.getByTestId('sale-line-weowe-0'));
      expect(scroller).toContainElement(screen.getByTestId('sale-line-remove-line-0'));

      // Nothing is hidden at this width either — the rows slide, they do not drop
      // columns, and the write itself is on the page and not behind a wider screen.
      for (const id of ['sale-line-product-0', 'sale-line-immediate-0', 'sale-line-weowe-0', 'sale-payment-method', 'sale-at', 'save-sale']) {
        expect(screen.getByTestId(id), `${id} is not shown at 390 pixels`).toBeVisible();
      }
    });
  });

  it('keeps Correct and Void reachable inside the sales list at phone width', async () => {
    await withViewport(390, async () => {
      renderDesk({ sales: [saleFixture()] });
      await screen.findByTestId('sale-row-SALE#1');

      const scroller = scrollContainerFor('Sales at this event');
      expect(scroller).toContainElement(screen.getByTestId('correct-sale-SALE#1'));
      expect(scroller).toContainElement(screen.getByTestId('void-sale-SALE#1'));
      expect(screen.getByTestId('sale-expected-cash-SALE#1')).toBeVisible();
    });
  });

  it('enters a sale with Tab and Enter alone, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      renderDesk({ mutationMocks: [createMutation('test-idem-1')] });
      await screen.findByTestId('sale-entry-form');
      await fillCashSale(user);

      screen.getByTestId('sale-buyer-name').focus();
      await focusByTab(screen.getByTestId('save-sale'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(sent.create).toHaveLength(1));
    });
  });

  it('opens a correction, scrolls its lines, and saves it with Tab and Enter alone, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      renderDesk({
        sales: [saleFixture()],
        mutationMocks: [
          correctionMock({
            showAndSellId: SSE,
            saleId: 'SALE#1',
            saleVersion: { expectedVersion: 2 },
            version: { expectedVersion: 7 },
            lineItems: [{ lineItemId: 'LINE#1', productId: CARAMEL, immediateQty: 2, weOweQty: 3 }],
            reason: 'Recount at the table',
            idempotency: { idempotencyKey: 'test-idem-1' },
          }),
        ],
      });
      await screen.findByTestId('sale-row-SALE#1');

      // The row that needs correcting is reached from the list, and the form it opens
      // lays its lines out in a table that slides for a phone just like the entry one.
      const correct = screen.getByTestId('correct-sale-SALE#1');
      correct.focus();
      await user.keyboard('{Enter}');
      await screen.findByTestId('sale-correction-form');
      scrollContainerFor('Sale lines');

      await typeInto('correction-reason', 'Recount at the table', user);
      await focusByTab(screen.getByTestId('save-correction'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(sent.correct).toHaveLength(1));
    });
  });

  it('voids a sale with Tab and Enter alone, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      renderDesk({
        sales: [saleFixture()],
        mutationMocks: [
          {
            request: {
              query: VOID_SHOW_AND_SELL_SALE,
              variables: {
                input: {
                  showAndSellId: SSE,
                  saleId: 'SALE#1',
                  saleVersion: { expectedVersion: 2 },
                  version: { expectedVersion: 7 },
                  reason: 'Entered twice at the table',
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
          },
        ],
      });
      await screen.findByTestId('sale-row-SALE#1');

      const voidButton = screen.getByTestId('void-sale-SALE#1');
      voidButton.focus();
      await user.keyboard('{Enter}');
      await screen.findByTestId('sale-void-form');

      await typeInto('void-reason', 'Entered twice at the table', user);
      await focusByTab(screen.getByTestId('save-void'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(sent.void).toHaveLength(1));
    });
  });
});
