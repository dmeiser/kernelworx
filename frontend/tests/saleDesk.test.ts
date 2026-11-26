/**
 * The shared rules the sale and We Owe screens read (§4.5.1, on §4.2/§4.3/§4.4).
 *
 * These tests pin the browser-side half of the contract: what a line is allowed
 * to carry, what a correction is allowed to say about an existing line, and what
 * a reservation or a fulfillment is allowed to be. The server is the one that
 * refuses; this file pins that the screen refuses the same things with the same
 * sentences before the write exists.
 */

import { describe, expect, it } from 'vitest';
import {
  BUYER_EMAIL_MAX_CHARS,
  BUYER_NAME_MAX_CHARS,
  BUYER_PHONE_MAX_CHARS,
  OTHER_DETAILS_MAX_CHARS,
  SPLIT_PAYMENT_TOOLTIP,
  acceptsSaleEntry,
  closeReasonLabel,
  correctionPlan,
  defaultSaleAt,
  emptySalePlan,
  formatCents,
  fulfillmentPlan,
  fulfillmentSources,
  isBuiltInMethod,
  isDraftOnly,
  isOtherMethodOption,
  noticesOf,
  paymentMethodCode,
  paymentMethodCodeOf,
  paymentMethodOptions,
  reservationPlan,
  reservationTargetOf,
  saleAtWindowError,
  salePlan,
  validateSaleLine,
  weOweLineError,
  weOweStatusLabel,
  type ExistingLine,
} from '../src/lib/saleDesk';
import type { GqlUnitPaymentMethod, GqlWeOweObligationFieldsFragment } from '../src/types/graphql-generated';

const CATALOG = [
  { productId: 'PROD#caramel', productName: 'Caramel', price: 10 },
  { productId: 'PROD#butter', productName: 'Butter', price: 12.5 },
];

function obligation(overrides: Partial<GqlWeOweObligationFieldsFragment> = {}): GqlWeOweObligationFieldsFragment {
  return {
    __typename: 'WeOweObligation',
    weOweId: 'WEOWE#1',
    unitCampaignId: 'UNITCAMP#pack-3149-fall',
    showAndSellId: 'SSE#library',
    saleId: 'SALE#1',
    lineItemId: 'LINE#1',
    buyerName: 'Avery',
    productId: 'PROD#caramel',
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
    createdAt: '2026-03-28T15:00:00.000Z',
    closedAt: null,
    ...overrides,
  };
}

function method(overrides: Partial<GqlUnitPaymentMethod> = {}): GqlUnitPaymentMethod {
  return {
    __typename: 'UnitPaymentMethod',
    paymentMethodId: 'CASH',
    unitId: 'UNIT#pack-3149',
    displayName: 'Cash',
    createdAt: null,
    updatedAt: null,
    createdByAccountId: null,
    isActive: true,
    ...overrides,
  } as GqlUnitPaymentMethod;
}

describe('sale entry state and instant', () => {
  it('accepts entry only while live or reopened, and treats reopened as draft-only', () => {
    expect(acceptsSaleEntry('SCHEDULED')).toBe(false);
    expect(acceptsSaleEntry('ACTIVE')).toBe(true);
    expect(acceptsSaleEntry('ENDED')).toBe(true);
    expect(acceptsSaleEntry('FINALIZED')).toBe(false);
    expect(acceptsSaleEntry('REOPENED')).toBe(true);
    expect(acceptsSaleEntry('CANCELLED')).toBe(false);
    expect(isDraftOnly('REOPENED')).toBe(true);
    expect(isDraftOnly('ACTIVE')).toBe(false);
  });

  it('starts the sale-at box inside the event interval', () => {
    const event = { startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T18:30:00.000Z' };
    const now = new Date('2026-03-28T16:00:00.000Z');
    expect(defaultSaleAt(event, now)).toBe('2026-03-28T16:00:00.000Z');
    const early = new Date('2026-03-28T14:00:00.000Z');
    expect(defaultSaleAt(event, early)).toBe('2026-03-28T15:00:00.000Z');
    const late = new Date('2026-03-28T19:00:00.000Z');
    expect(defaultSaleAt(event, late)).toBe('2026-03-28T18:30:00.000Z');
  });

  it('refuses a sale instant outside the interval', () => {
    const event = { startAt: '2026-03-28T15:00:00.000Z', endAt: '2026-03-28T18:30:00.000Z' };
    expect(saleAtWindowError(new Date('2026-03-28T14:59:59.000Z'), event)).toContain('before this Show & Sell started');
    expect(saleAtWindowError(new Date('2026-03-28T18:30:01.000Z'), event)).toContain('after this Show & Sell ended');
    expect(saleAtWindowError(new Date('2026-03-28T16:00:00.000Z'), event)).toBeNull();
    expect(saleAtWindowError(null, event)).toContain('Enter when the sale happened');
  });
});

describe('payment method options', () => {
  it('offers built-ins and active customs, and never a retired custom', () => {
    const options = paymentMethodOptions([
      method({ paymentMethodId: 'CASH', displayName: 'Cash' }),
      method({ paymentMethodId: 'CHECK', displayName: 'Check' }),
      method({ paymentMethodId: 'CUSTOM#1', displayName: 'Venmo', createdAt: '2026-01-01T00:00:00.000Z', isActive: true }),
      method({ paymentMethodId: 'CUSTOM#2', displayName: 'Retired Pay', createdAt: '2026-01-01T00:00:00.000Z', isActive: false }),
    ]);
    expect(options.map((option) => option.value)).toEqual(['CASH', 'CHECK', 'CUSTOM:CUSTOM#1']);
    expect(options.map((option) => option.label)).toContain('Venmo');
    expect(options.find((option) => option.value === 'CASH')?.isBuiltIn).toBe(true);
    expect(options.find((option) => option.value === 'CUSTOM:CUSTOM#1')?.isBuiltIn).toBe(false);
  });

  it('flags the Other method only by code', () => {
    const options = paymentMethodOptions([
      method({ paymentMethodId: 'OTHER', displayName: 'Other' }),
      method({ paymentMethodId: 'CASH', displayName: 'Cash' }),
    ]);
    expect(options.find((option) => option.value === 'OTHER')?.isOther).toBe(true);
    expect(options.find((option) => option.value === 'CASH')?.isOther).toBe(false);
  });

  it('recognises the Other option only by its selected value (PAY-05)', () => {
    const options = paymentMethodOptions([
      method({ paymentMethodId: 'OTHER', displayName: 'Other' }),
      method({ paymentMethodId: 'CASH', displayName: 'Cash' }),
    ]);
    expect(isOtherMethodOption(options, 'OTHER')).toBe(true);
    expect(isOtherMethodOption(options, 'CASH')).toBe(false);
    expect(isOtherMethodOption(options, undefined)).toBe(false);
    expect(isOtherMethodOption([], 'OTHER')).toBe(false);
    expect(SPLIT_PAYMENT_TOOLTIP).toContain('split payments');
    expect(SPLIT_PAYMENT_TOOLTIP).toContain('Other');
  });

  it('uses the server-side ceilings verbatim, without a browser-only smaller one', () => {
    expect(OTHER_DETAILS_MAX_CHARS).toBe(250);
    expect(BUYER_NAME_MAX_CHARS).toBe(200);
    expect(BUYER_PHONE_MAX_CHARS).toBe(40);
    expect(BUYER_EMAIL_MAX_CHARS).toBe(254);
  });

  it('names the code a selection carries, or refuses an unknown one', () => {
    const options = paymentMethodOptions([method({ paymentMethodId: 'CASH', displayName: 'Cash' })]);
    expect(paymentMethodCode(options, 'CASH')).toBe('CASH');
    expect(paymentMethodCode(options, 'OTHER')).toBeNull();
    expect(paymentMethodCode(options, undefined)).toBeNull();
  });
});

describe('sale lines', () => {
  it('refuses a line with no product, and the whole batch for one bad line', () => {
    expect(salePlan([{ productId: '', immediateQty: '1', weOweQty: '' }], CATALOG).error).toContain('Choose a product');
    const result = salePlan(
      [
        { productId: 'PROD#caramel', immediateQty: '1', weOweQty: '2' },
        { productId: 'PROD#butter', immediateQty: '1.5', weOweQty: '' },
      ],
      CATALOG,
    );
    expect(result.error).toContain('whole number');
    expect(result.lines).toEqual([]);
  });

  it('refuses a line with nothing to hand over or owe', () => {
    expect(salePlan([{ productId: 'PROD#caramel', immediateQty: '', weOweQty: '' }], CATALOG).error).toContain('at least one item');
  });

  it('prices a line at the whole quantity, handed over plus owed', () => {
    const plan = salePlan([{ productId: 'PROD#butter', immediateQty: '1', weOweQty: '1' }], CATALOG);
    expect(plan.error).toBeNull();
    expect(plan.lines).toEqual([{ productId: 'PROD#butter', immediateQty: 1, weOweQty: 1, subtotalCents: 2500 }]);
    expect(plan.totalCents).toBe(2500);
  });

  it('refuses an empty batch rather than sending zero lines', () => {
    expect(salePlan([], CATALOG).error).toContain('at least one line');
  });

  it('requires the buyer name only for lines that owe', () => {
    const owing = salePlan([{ productId: 'PROD#caramel', immediateQty: '0', weOweQty: '2' }], CATALOG);
    expect(weOweLineError(owing.lines, '', true)).toContain('buyer name');
    expect(weOweLineError(owing.lines, 'Avery', true)).toBeNull();
    const immediate = salePlan([{ productId: 'PROD#caramel', immediateQty: '2', weOweQty: '' }], CATALOG);
    expect(weOweLineError(immediate.lines, '', false)).toBeNull();
  });

  it('refuses We Owe on an event that does not offer it', () => {
    const owing = salePlan([{ productId: 'PROD#caramel', immediateQty: '0', weOweQty: '2' }], CATALOG);
    expect(weOweLineError(owing.lines, 'Avery', false)).toContain('does not offer We Owe');
  });
});

describe('correction plan', () => {
  const existing: ExistingLine[] = [
    { lineItemId: 'LINE#1', productId: 'PROD#caramel', productNameSnapshot: 'Caramel', immediateQty: 2, weOweQty: 3 },
    { lineItemId: 'LINE#2', productId: 'PROD#butter', productNameSnapshot: 'Butter', immediateQty: 1, weOweQty: 0 },
  ];

  it('sends every kept line whole and reports the lines it omits', () => {
    const plan = correctionPlan(existing, [{ lineItemId: 'LINE#1', productId: 'PROD#caramel', immediateQty: '1', weOweQty: '2' }], CATALOG);
    expect(plan.error).toBeNull();
    expect(plan.lines).toEqual([{ lineItemId: 'LINE#1', productId: 'PROD#caramel', immediateQty: 1, weOweQty: 2 }]);
    expect(plan.omitted.map((line) => line.lineItemId)).toEqual(['LINE#2']);
  });

  it('refuses a line that names another product', () => {
    const plan = correctionPlan(existing, [{ lineItemId: 'LINE#1', productId: 'PROD#butter', immediateQty: '2', weOweQty: '1' }], CATALOG);
    expect(plan.error).toContain('keeps the product it sold');
  });

  it('refuses a kept line below its fulfilled quantity', () => {
    const obligations = [obligation({ lineItemId: 'LINE#1', fulfilledQty: 2, reservedQty: 0, remainingQty: 1 })];
    const plan = correctionPlan(existing, [{ lineItemId: 'LINE#1', productId: 'PROD#caramel', immediateQty: '1', weOweQty: '1' }], CATALOG, obligations);
    expect(plan.error).toContain('already fulfilled');
  });

  it('refuses a kept line above the quantity it was entered with', () => {
    const plan = correctionPlan(existing, [{ lineItemId: 'LINE#1', productId: 'PROD#caramel', immediateQty: '1', weOweQty: '4' }], CATALOG);
    expect(plan.error).toContain('cannot exceed the 3 it was entered with');
  });

  it('refuses a line that names an id the sale does not carry', () => {
    const plan = correctionPlan(existing, [{ lineItemId: 'LINE#nope', productId: 'PROD#caramel', immediateQty: '1', weOweQty: '0' }], CATALOG);
    expect(plan.error).toContain('not on this sale');
  });

  it('sends a supplemental line with no id and a catalog product', () => {
    const plan = correctionPlan(existing, [{ productId: 'PROD#butter', immediateQty: '1', weOweQty: '1' }], CATALOG);
    expect(plan.error).toBeNull();
    expect(plan.lines).toEqual([{ productId: 'PROD#butter', immediateQty: 1, weOweQty: 1 }]);
  });
});

describe('We Owe rules', () => {
  it('reads an empty target as the reservation already held', () => {
    expect(reservationTargetOf('', obligation({ reservedQty: 2 }))).toBe(2);
    expect(reservationTargetOf(' 3 ', obligation({ reservedQty: 2 }))).toBe(3);
    expect(reservationTargetOf('-1', obligation({ reservedQty: 2 }))).toBeNull();
    expect(reservationTargetOf('4', obligation({ reservedQty: 2, remainingQty: 3 }))).toBeNull();
  });

  it('plans a release, a new hold and the zero release', () => {
    const held = obligation({ reservedQty: 2, remainingQty: 3 });
    expect(reservationPlan('1', held).isRelease).toBe(true);
    expect(reservationPlan('0', held).isRelease).toBe(true);
    expect(reservationPlan('3', held).isRelease).toBe(false);
    const empty = obligation({ reservedQty: 0, remainingQty: 3 });
    expect(reservationPlan('0', empty).isRelease).toBe(false);
    expect(reservationPlan('abc', empty).error).toContain('whole number');
    expect(reservationPlan('4', empty).error).toContain('owes 3 more');
  });

  it('bounds fulfillment by the source and the remaining quantity', () => {
    const reserved = obligation({ reservedQty: 2, remainingQty: 3, uncoveredQty: 1 });
    expect(fulfillmentPlan('2', 'KERNEL_STOCK', reserved)).toMatchObject({ quantity: 2, maxBySource: 2, blocked: false });
    expect(fulfillmentPlan('3', 'KERNEL_STOCK', reserved).error).toContain('Only 2 Kernels are reserved');
    expect(fulfillmentPlan('1', 'EXTERNAL_COUNCIL', reserved).quantity).toBe(1);
    expect(fulfillmentPlan('2', 'EXTERNAL_COUNCIL', reserved).error).toContain('Only 1 is uncovered');
    expect(fulfillmentPlan('0', 'KERNEL_STOCK', reserved).error).toContain('at least one');
    expect(fulfillmentPlan('4', 'EXTERNAL_COUNCIL', reserved).error).toContain('owes 3 more');
    expect(fulfillmentPlan('x', 'KERNEL_STOCK', reserved).error).toContain('whole number');
  });

  it('offers the sources an obligation can draw on, in order', () => {
    expect(fulfillmentSources(obligation({ reservedQty: 2, uncoveredQty: 1 }))).toEqual(['KERNEL_STOCK', 'EXTERNAL_COUNCIL']);
    expect(fulfillmentSources(obligation({ reservedQty: 0, uncoveredQty: 1 }))).toEqual(['EXTERNAL_COUNCIL']);
    expect(fulfillmentSources(obligation({ reservedQty: 0, uncoveredQty: 0 }))).toEqual([]);
  });

  it('labels status and close reason in words', () => {
    expect(closeReasonLabel('FULFILLED')).toBe('Fulfilled');
    expect(closeReasonLabel('CANCELLED')).toBe('Cancelled');
    expect(closeReasonLabel(null)).toBe('');
    expect(weOweStatusLabel('OPEN')).toBe('Open');
    expect(weOweStatusLabel('CLOSED')).toBe('Closed');
  });

  it('shows the server’s over-assignment warnings as its own sentences', () => {
    expect(noticesOf([{ productId: 'PROD#caramel', message: '3 more Kernels sold than were allocated' }])).toEqual([
      'PROD#caramel: 3 more Kernels sold than were allocated',
    ]);
    // No warnings is an empty list, not a missing section the screen has to guess about.
    expect(noticesOf(undefined)).toEqual([]);
    expect(noticesOf([])).toEqual([]);
  });

  it('refuses a fulfillment a source cannot cover at all', () => {
    // Nothing reserved: KERNEL_STOCK has no reach, so even one Kernel is refused as blocked.
    const nothingHeld = obligation({ reservedQty: 0, uncoveredQty: 4, remainingQty: 4 });
    expect(fulfillmentPlan('1', 'KERNEL_STOCK', nothingHeld).error).toContain('release the reservation first');
    // Nothing uncovered: the Council has nothing to supply.
    const allCovered = obligation({ reservedQty: 4, uncoveredQty: 0, remainingQty: 4 });
    expect(fulfillmentPlan('1', 'EXTERNAL_COUNCIL', allCovered).error).toContain('release the reservation on the covered portion');
    // A zero quantity against a dead source is both errors at once: nothing to fulfill, nowhere to fulfill it from.
    expect(fulfillmentPlan('0', 'KERNEL_STOCK', nothingHeld)).toMatchObject({ quantity: null, blocked: true, maxBySource: 0 });
  });
});

describe('money and method codes', () => {
  it('writes money the way the desk reads it, including a negative discrepancy', () => {
    expect(formatCents(0)).toBe('$0.00');
    expect(formatCents(5)).toBe('$0.05');
    expect(formatCents(123_456)).toBe('$1,234.56');
    expect(formatCents(-500)).toBe('-$5.00');
  });

  it('codes a built-in by its own code and a custom method by its id', () => {
    expect(isBuiltInMethod(method({ paymentMethodId: 'CASH', createdAt: null }))).toBe(true);
    expect(paymentMethodCodeOf(method({ paymentMethodId: 'CASH', createdAt: null }))).toBe('CASH');
    const custom = method({ paymentMethodId: 'CUSTOM#1', displayName: 'Venmo', createdAt: '2026-01-01T00:00:00.000Z' });
    expect(isBuiltInMethod(custom)).toBe(false);
    expect(paymentMethodCodeOf(custom)).toBe('CUSTOM:CUSTOM#1');
  });
});

describe('an event with no interval to clamp to', () => {
  it('starts the sale-at box at now when the event carries no usable bounds', () => {
    const event = { startAt: '', endAt: '' };
    const now = new Date('2026-03-28T16:00:00.000Z');
    expect(defaultSaleAt(event, now)).toBe('2026-03-28T16:00:00.000Z');
    // The server owns the interval check; with nothing to compare against, the browser stays silent.
    expect(saleAtWindowError(now, event)).toBeNull();
  });

  it('bounds a sale on only one side when the event names only that side', () => {
    const openEnded = { startAt: '2026-03-28T15:00:00.000Z', endAt: '' };
    expect(saleAtWindowError(new Date('2026-04-28T15:00:00.000Z'), openEnded)).toBeNull();
    expect(saleAtWindowError(new Date('2026-03-28T14:59:59.000Z'), openEnded)).toContain('before this Show & Sell started');
    const openStarted = { startAt: '', endAt: '2026-03-28T18:30:00.000Z' };
    expect(saleAtWindowError(new Date('2026-03-28T18:30:01.000Z'), openStarted)).toContain('after this Show & Sell ended');
    expect(defaultSaleAt(openStarted, new Date('2026-03-28T19:00:00.000Z'))).toBe('2026-03-28T18:30:00.000Z');
  });
});

describe('one typed line, on its own', () => {
  it('refuses each thing a line can get wrong, naming the product', () => {
    expect(validateSaleLine({ productId: 'PROD#nope', immediateQty: '1', weOweQty: '' }, CATALOG)).toEqual({
      error: 'Choose a product for every line.',
    });
    expect(validateSaleLine({ productId: 'PROD#caramel', immediateQty: '2.5', weOweQty: '' }, CATALOG)).toEqual({
      error: 'Enter a whole number of Kernels handed over at the table for Caramel.',
    });
    expect(validateSaleLine({ productId: 'PROD#caramel', immediateQty: '2', weOweQty: 'x' }, CATALOG)).toEqual({
      error: 'Enter a whole number of Kernels owed later for Caramel.',
    });
    expect(validateSaleLine({ productId: 'PROD#caramel', immediateQty: '0', weOweQty: '0' }, CATALOG)).toEqual({
      error: 'Caramel needs at least one item, handed over or owed later.',
    });
    expect(validateSaleLine({ productId: 'PROD#caramel', immediateQty: ' 2 ', weOweQty: ' 1 ' }, CATALOG)).toEqual({
      line: { productId: 'PROD#caramel', immediateQty: 2, weOweQty: 1, subtotalCents: 3000 },
    });
  });

  it('has no plan for an empty batch, in words that say what to add', () => {
    expect(emptySalePlan()).toEqual({
      lines: [],
      error: 'Add at least one line — a sale with nothing on it is not a sale.',
      totalCents: 0,
    });
    expect(salePlan([], CATALOG).error).toBe(emptySalePlan().error);
  });
});

describe('a correction line, on its own', () => {
  const existing: ExistingLine[] = [
    { lineItemId: 'LINE#1', productId: 'PROD#caramel', productNameSnapshot: 'Caramel', immediateQty: 2, weOweQty: 3 },
  ];

  it('names the product of the line it is refusing, using the snapshot for a kept line', () => {
    expect(correctionPlan(existing, [{ lineItemId: 'LINE#1', productId: 'PROD#caramel', immediateQty: '1.5', weOweQty: '' }], CATALOG).error)
      .toContain('handed over at the table for Caramel');
    expect(correctionPlan(existing, [{ productId: 'PROD#butter', immediateQty: '1', weOweQty: 'x' }], CATALOG).error)
      .toContain('owed later for Butter');
    expect(correctionPlan(existing, [{ productId: 'PROD#butter', immediateQty: '', weOweQty: '' }], CATALOG).error)
      .toContain('Butter needs at least one item');
  });

  it('refuses a supplemental line that names no catalog product', () => {
    expect(correctionPlan(existing, [{ productId: 'PROD#gone', immediateQty: '1', weOweQty: '' }], CATALOG).error)
      .toContain('Choose a product for every line.');
  });

  it('counts a fulfilled quantity only from the obligation that line created', () => {
    // A line with no obligation of its own has nothing fulfilled, so any quantity is allowed down to zero.
    const obligations = [obligation({ lineItemId: 'LINE#other', fulfilledQty: 5 })];
    const plan = correctionPlan(existing, [{ lineItemId: 'LINE#1', productId: 'PROD#caramel', immediateQty: '2', weOweQty: '0' }], CATALOG, obligations);
    expect(plan.error).toBeNull();
    expect(plan.lines).toEqual([{ lineItemId: 'LINE#1', productId: 'PROD#caramel', immediateQty: 2, weOweQty: 0 }]);
  });
});
