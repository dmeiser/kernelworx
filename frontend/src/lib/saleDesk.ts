/**
 * Shared rules for the Unit Admin sale entry/correction and We Owe screens
 * (checklist §4.5.1, built on §4.2, §4.3, §4.4 and the §8.1 / §10 contracts).
 *
 * The sale write is one atomic batch with the We Owe obligations it creates, so
 * every decision this file makes is a decision that is made once and sent: the
 * browser refuses a line it cannot honestly send, rather than letting the write
 * refuse it halfway through. Money is never recomputed here — a sale's
 * `totalCents`, `expectedCashCents`, `subtotalCents` and `valueCentsSnapshot`
 * are the server's own arithmetic, read back from the row after the write (§7.1).
 * What this file does compute is the *draft* arithmetic the admin is looking at:
 * the subtotal of the lines they typed, so the box can say what the sale would
 * total before it exists.
 */

import type {
  GqlShowAndSellStatus,
  GqlUnitPaymentMethod,
  GqlWeOweFulfillmentSource,
  GqlWeOweObligationFieldsFragment,
} from '../types/graphql-generated';

/** A catalog row the screens price a sale line from. */
export interface CatalogEntry {
  productId: string;
  productName: string;
  price: number;
}

/** The built-in Other method's code; the only method that may carry a note (§8.2). */
export const OTHER_METHOD_CODE = 'OTHER';

/** Built-in codes the server accepts, in the order the picker shows them. */
export const BUILTIN_METHOD_CODES = ['CASH', 'CHECK', 'OTHER'] as const;

/** Field lengths the server applies to the same strings (API contract §4.1.3). */
export const OTHER_DETAILS_MAX_CHARS = 250;
export const BUYER_NAME_MAX_CHARS = 100;
export const BUYER_PHONE_MAX_CHARS = 50;
export const BUYER_EMAIL_MAX_CHARS = 254;
export const SALE_REASON_MAX_CHARS = 500;

/** `en-US` with cents: `$1,234.56`, and `-$5.00` for a negative discrepancy. */
export function formatCents(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100);
  const remainder = abs % 100;
  return `${sign}$${dollars.toLocaleString('en-US')}.${String(remainder).padStart(2, '0')}`;
}

/** A catalog price (a Dollar float the server converts to cents) in the same spelling. */
export function formatCatalogPrice(price: number): string {
  const value = Number(price);
  if (!Number.isFinite(value)) return '$0.00';
  return `$${value.toFixed(2)}`;
}

// --- payment methods ──────────────────────────────────────────────────────────

export interface PaymentMethodOption {
  /** The code the sale names: CASH, CHECK, OTHER, or CUSTOM:<paymentMethodId>. */
  value: string;
  /** The display name the picker shows and the snapshot records (PAY-06). */
  label: string;
  isBuiltIn: boolean;
  isOther: boolean;
}

/** Built-ins answer `createdAt: null`; a custom method always carries who made it. */
export function isBuiltInMethod(method: GqlUnitPaymentMethod): boolean {
  return method.createdAt == null;
}

/** The methodCode a sale sends for one row in the method list. */
export function paymentMethodCodeOf(method: GqlUnitPaymentMethod): string {
  if (isBuiltInMethod(method)) return method.paymentMethodId;
  return `CUSTOM:${method.paymentMethodId}`;
}

/**
 * The methods a sale may name: every built-in plus every custom method that is
 * still active. A retired custom method is history, not an option — a sale that
 * names it is refused by the server, and the picker must not offer it.
 */
export function paymentMethodOptions(methods: readonly GqlUnitPaymentMethod[]): PaymentMethodOption[] {
  return methods
    .filter((method) => isBuiltInMethod(method) || method.isActive)
    .map((method) => {
      const code = paymentMethodCodeOf(method);
      return {
        value: code,
        label: method.displayName,
        isBuiltIn: isBuiltInMethod(method),
        isOther: code === OTHER_METHOD_CODE,
      };
    });
}

/** The code a method option names, or null when the option is missing. */
export function paymentMethodCode(options: readonly PaymentMethodOption[], value: string | undefined): string | null {
  if (value == null) return null;
  return options.some((option) => option.value === value) ? value : null;
}

// --- sale state ───────────────────────────────────────────────────────────────

/**
 * Whether this event may take a sale: active or ended (live), or reopened
 * (draft-only, §4.2.2 / §4.3.1 / §4.3.2). FINALIZED and CANCELLED are history.
 */
export function acceptsSaleEntry(status: GqlShowAndSellStatus): boolean {
  return status === 'ACTIVE' || status === 'ENDED' || status === 'REOPENED';
}

/** While the event is reopened, a sale is a draft; the stock effect belongs to re-finalization. */
export function isDraftOnly(status: GqlShowAndSellStatus): boolean {
  return status === 'REOPENED';
}

// --- sale instant ─────────────────────────────────────────────────────────────

/**
 * Where the sale-at box starts: now, pulled inside the event's interval.
 *
 * A sale is stamped when it happened, and the server refuses an instant outside the
 * interval the event was created with (§4.2.1) — so the box starts at the moment the
 * admin is standing in, clamped to the only window the write can be accepted in.
 * The value is an instant, and the screen shows it in the Unit's zone.
 */
export function defaultSaleAt(event: { startAt: string; endAt: string }, now: Date = new Date()): string {
  const start = Date.parse(event.startAt);
  const end = Date.parse(event.endAt);
  const instant = Number.isFinite(start) ? Math.max(start, now.getTime()) : now.getTime();
  const clamped = Number.isFinite(end) ? Math.min(instant, end) : instant;
  return new Date(clamped).toISOString();
}

/** The sentence for an instant outside the interval, or null when it is inside it. */
function saleAtWindowErrorOf(instant: number, start: number, end: number): string | null {
  if (Number.isFinite(start) && instant < start) {
    return 'The sale happened before this Show & Sell started. A sale belongs inside the event’s own hours.';
  }
  if (Number.isFinite(end) && instant > end) {
    return 'The sale happened after this Show & Sell ended. A sale belongs inside the event’s own hours.';
  }
  return null;
}

/** Why a typed sale instant cannot be written, or null when the interval holds it. */
export function saleAtWindowError(
  saleAt: Date | null,
  event: { startAt: string; endAt: string },
): string | null {
  if (saleAt === null) return 'Enter when the sale happened, as a date and time.';
  const start = Date.parse(event.startAt);
  const end = Date.parse(event.endAt);
  return saleAtWindowErrorOf(saleAt.getTime(), start, end);
}

// --- sale lines ───────────────────────────────────────────────────────────────

export interface SaleLineDraft {
  productId: string;
  immediateQty: string;
  weOweQty: string;
}

export interface ValidatedSaleLine {
  productId: string;
  immediateQty: number;
  weOweQty: number;
  /** The whole quantity priced at the catalog's snapshot price, in cents. */
  subtotalCents: number;
}

export interface SalePlan {
  lines: ValidatedSaleLine[];
  /** The sentence for the first line that cannot be sent, or null when the plan is sound. */
  error: string | null;
  /** The whole-sale total, in cents, from the lines that were validated. */
  totalCents: number;
}

const WHOLE_NUMBER = /^\d+$/;

/** One typed quantity as a whole number: empty means zero, anything else must be digits. */
function wholeQuantity(raw: string): number | null {
  const text = raw.trim();
  if (text === '') return 0;
  return WHOLE_NUMBER.test(text) ? Number(text) : null;
}

type QuantityResult = { immediateQty: number; weOweQty: number } | { badField: 'immediate' | 'weOwe' | 'empty' };

/** A typed pair of quantities, or the one that cannot be sent. */
function lineQuantities(immediateRaw: string, weOweRaw: string): QuantityResult {
  const immediateQty = wholeQuantity(immediateRaw);
  if (immediateQty === null) return { badField: 'immediate' };
  const weOweQty = wholeQuantity(weOweRaw);
  if (weOweQty === null) return { badField: 'weOwe' };
  if (immediateQty + weOweQty < 1) return { badField: 'empty' };
  return { immediateQty, weOweQty };
}

/** The sentence for a bad pair of quantities, in the words the server uses. */
function quantityErrorMessage(badField: 'immediate' | 'weOwe' | 'empty', productName: string): string {
  if (badField === 'immediate') return `Enter a whole number of Kernels handed over at the table for ${productName}.`;
  if (badField === 'weOwe') return `Enter a whole number of Kernels owed later for ${productName}.`;
  return `${productName} needs at least one item, handed over or owed later.`;
}

/** The whole quantity priced at the catalog's snapshot price, in cents. */
function subtotalCents(immediateQty: number, weOweQty: number, price: number): number {
  return Math.round((immediateQty + weOweQty) * price * 100);
}

/**
 * One typed line's quantities, validated against the server's rules.
 *
 * A line is the atomic unit of a sale (§7.1): whole numbers, at least one item
 * across the two quantities, and nothing else. The immediate/We Owe split is the
 * admin's call and is sent as-is — the server is what refuses an immediate
 * handoff the event cannot hold, not the browser.
 */
export function validateSaleLine(
  draft: SaleLineDraft,
  catalog: readonly CatalogEntry[],
): { line: ValidatedSaleLine } | { error: string } {
  const product = catalog.find((entry) => entry.productId === draft.productId);
  if (product == null) {
    return { error: 'Choose a product for every line.' };
  }
  const quantities = lineQuantities(draft.immediateQty, draft.weOweQty);
  if ('badField' in quantities) {
    return { error: quantityErrorMessage(quantities.badField, product.productName) };
  }
  return {
    line: {
      productId: product.productId,
      immediateQty: quantities.immediateQty,
      weOweQty: quantities.weOweQty,
      subtotalCents: subtotalCents(quantities.immediateQty, quantities.weOweQty, product.price),
    },
  };
}

/** The whole sale, from the typed lines, or the first line that cannot be sent. */
export function salePlan(
  drafts: readonly SaleLineDraft[],
  catalog: readonly CatalogEntry[],
): SalePlan {
  if (drafts.length === 0) return emptySalePlan();
  const lines: ValidatedSaleLine[] = [];
  for (const draft of drafts) {
    const result = validateSaleLine(draft, catalog);
    if ('error' in result) return { lines: [], error: result.error, totalCents: 0 };
    lines.push(result.line);
  }
  return {
    lines,
    error: null,
    totalCents: lines.reduce((sum, line) => sum + line.subtotalCents, 0),
  };
}

/** A sale with no typed lines has no plan, and says so rather than looking like a zero-line sale. */
export function emptySalePlan(): SalePlan {
  return { lines: [], error: 'Add at least one line — a sale with nothing on it is not a sale.', totalCents: 0 };
}

// --- correction ───────────────────────────────────────────────────────────────

export interface ExistingLine {
  lineItemId: string;
  productId: string;
  productNameSnapshot: string;
  immediateQty: number;
  weOweQty: number;
}

export interface CorrectionLineDraft {
  /** Omitted for a supplemental line, which the server mints its own stable id for. */
  lineItemId?: string;
  productId: string;
  immediateQty: string;
  weOweQty: string;
}

export interface CorrectionPlan {
  /** The lines the server asked for, in the order typed. */
  lines: { lineItemId?: string; productId: string; immediateQty: number; weOweQty: number }[];
  /** The original lines the correction leaves out — each will be voided. */
  omitted: ExistingLine[];
  /** The sentence for the first line that cannot be sent, or null when sound. */
  error: string | null;
}

/** The product name a correction can name, or null when it cannot be named. */
function productNameOf(
  original: ExistingLine | undefined,
  draft: CorrectionLineDraft,
  catalog: readonly CatalogEntry[],
): string | null {
  if (original != null) return original.productNameSnapshot;
  return catalog.find((entry) => entry.productId === draft.productId)?.productName ?? null;
}

/** The first identity refusal a draft line can carry, or null when it may be read. */
function correctionIdentityError(
  original: ExistingLine | undefined,
  draft: CorrectionLineDraft,
  catalog: readonly CatalogEntry[],
): string | null {
  if (draft.lineItemId != null && original == null) {
    return 'One of the lines being corrected is not on this sale.';
  }
  if (original == null && productNameOf(original, draft, catalog) == null) {
    return 'Choose a product for every line.';
  }
  return null;
}

/** The fulfilled quantity of one line, from the obligations the sale created. */
function fulfilledQtyOf(lineItemId: string | undefined, obligations: readonly GqlWeOweObligationFieldsFragment[]): number {
  if (lineItemId == null) return 0;
  return obligations.find((entry) => entry.lineItemId === lineItemId)?.fulfilledQty ?? 0;
}

/** A supplemental line: new, and priced from the catalog. */
function supplementalLine(
  draft: CorrectionLineDraft,
  catalog: readonly CatalogEntry[],
  quantities: { immediateQty: number; weOweQty: number },
): { line: CorrectionPlan['lines'][number] } | { error: string } {
  if (!catalog.some((entry) => entry.productId === draft.productId)) {
    return { error: 'Choose a product for every line.' };
  }
  return {
    line: {
      productId: draft.productId,
      immediateQty: quantities.immediateQty,
      weOweQty: quantities.weOweQty,
    },
  };
}

/** An existing line kept as corrected: the product it sold, and the quantities it may carry. */
function keptLine(
  original: ExistingLine,
  draft: CorrectionLineDraft,
  quantities: { immediateQty: number; weOweQty: number },
  obligations: readonly GqlWeOweObligationFieldsFragment[],
): { line: CorrectionPlan['lines'][number] } | { error: string } {
  if (draft.productId !== original.productId) {
    return {
      error: `${original.productNameSnapshot}: a corrected line keeps the product it sold; move the quantity by omitting this line and adding a supplemental line for the other product.`,
    };
  }
  const fulfilled = fulfilledQtyOf(draft.lineItemId, obligations);
  if (quantities.weOweQty < fulfilled) {
    return {
      error: `${original.productNameSnapshot}: ${fulfilled} Kernels are already fulfilled; a correction cannot take back stock the buyer has (SALE-M-03-02).`,
    };
  }
  if (quantities.weOweQty > original.weOweQty) {
    return {
      error: `${original.productNameSnapshot}: an existing line's We Owe quantity cannot exceed the ${original.weOweQty} it was entered with; add a new line for the extra.`,
    };
  }
  return {
    line: {
      lineItemId: draft.lineItemId as string,
      productId: draft.productId,
      immediateQty: quantities.immediateQty,
      weOweQty: quantities.weOweQty,
    },
  };
}

/** One typed row, read against the sale's own lines and the obligations they created. */
function correctionLine(
  original: ExistingLine | undefined,
  draft: CorrectionLineDraft,
  catalog: readonly CatalogEntry[],
  obligations: readonly GqlWeOweObligationFieldsFragment[],
): { line: CorrectionPlan['lines'][number] } | { error: string } {
  const identity = correctionIdentityError(original, draft, catalog);
  if (identity !== null) return { error: identity };
  const quantities = lineQuantities(draft.immediateQty, draft.weOweQty);
  if ('badField' in quantities) {
    const productName = productNameOf(original, draft, catalog) ?? draft.productId;
    return { error: quantityErrorMessage(quantities.badField, productName) };
  }
  if (original == null) return supplementalLine(draft, catalog, quantities);
  return keptLine(original, draft, quantities, obligations);
}

/**
 * A correction is a whole replacement, not a delta: every line the admin keeps is
 * sent with its whole post-correction quantities, and every line omitted is
 * voided — its We Owe obligation closes as cancelled and any reservation above
 * the corrected remainder is released, all in one transaction (§4.3.1). The
 * browser decides which of the two is what the admin typed, and refuses the
 * batch outright when any one line cannot be sent.
 *
 * A kept line may never name another product (the server refuses it), may not
 * carry less We Owe than that line has already fulfilled (SALE-M-03-02), and may
 * not carry more We Owe than it was entered with — an increase is a new
 * supplemental line and a new obligation, not an edit to the original.
 */
/** The one act a draft asks for: keep the line as corrected, or the sentence for why it cannot be sent. */
function correctionOutcome(
  existing: readonly ExistingLine[],
  draft: CorrectionLineDraft,
  catalog: readonly CatalogEntry[],
  obligations: readonly GqlWeOweObligationFieldsFragment[],
): { line: CorrectionPlan['lines'][number] } | { error: string } {
  const original = draft.lineItemId == null ? undefined : existing.find((line) => line.lineItemId === draft.lineItemId);
  return correctionLine(original, draft, catalog, obligations);
}

export function correctionPlan(
  existing: readonly ExistingLine[],
  drafts: readonly CorrectionLineDraft[],
  catalog: readonly CatalogEntry[],
  obligations: readonly GqlWeOweObligationFieldsFragment[] = [],
): CorrectionPlan {
  const lines: CorrectionPlan['lines'] = [];
  const kept = new Set<string>();
  for (const draft of drafts) {
    const outcome = correctionOutcome(existing, draft, catalog, obligations);
    if ('error' in outcome) return { lines: [], omitted: [], error: outcome.error };
    if (outcome.line.lineItemId != null) kept.add(outcome.line.lineItemId);
    lines.push(outcome.line);
  }
  const omitted = existing.filter((line) => !kept.has(line.lineItemId));
  return { lines, omitted, error: null };
}

// --- We Owe ───────────────────────────────────────────────────────────────────

/** The reservation the admin may set for one obligation, as a target quantity. */
export function reservationTargetOf(raw: string, obligation: GqlWeOweObligationFieldsFragment): number | null {
  const text = raw.trim();
  if (text === '') return obligation.reservedQty;
  if (!WHOLE_NUMBER.test(text)) return null;
  const target = Number(text);
  if (target < 0 || target > obligation.remainingQty) return null;
  return target;
}

export interface ReservationPlan {
  target: number | null;
  error: string | null;
  /** The reservation the target replaces, so the screen can say what moves. */
  current: number;
  /** True when the target is a release of the excess rather than a new hold. */
  isRelease: boolean;
}

/**
 * One reservation save's target, or the reason it cannot be sent.
 *
 * A target of zero is a complete release and is sent as zero — omitting the row
 * would keep it (§4.4.2). The target may never exceed the remaining owed
 * quantity or the campaign's unassigned stock: the server is what knows the
 * stock, so the screen bounds only the owed side and says so.
 */
/** The reservation sentence for a typed target, or null when the target is sound. */
function reservationErrorOf(raw: string, obligation: GqlWeOweObligationFieldsFragment): string | null {
  const text = raw.trim();
  if (text === '') return null;
  if (!WHOLE_NUMBER.test(text)) return 'Enter a whole number of Kernels.';
  if (Number(text) > obligation.remainingQty) {
    return `This obligation owes ${obligation.remainingQty} more; a reservation may not exceed that.`;
  }
  return null;
}

export function reservationPlan(
  raw: string,
  obligation: GqlWeOweObligationFieldsFragment,
): ReservationPlan {
  const current = obligation.reservedQty;
  const error = reservationErrorOf(raw, obligation);
  if (error !== null) {
    return { target: null, error, current, isRelease: false };
  }
  const target = reservationTargetOf(raw, obligation);
  if (target === null) {
    return { target: null, error: 'Enter a whole number of Kernels.', current, isRelease: false };
  }
  return { target, error: null, current, isRelease: target < current };
}

export interface FulfillmentPlan {
  quantity: number | null;
  error: string | null;
  /** The source the server will accept, already bounded by the obligation. */
  maxBySource: number;
  source: GqlWeOweFulfillmentSource;
  /** True when the source may not be used at all (no stock held, or nothing uncovered). */
  blocked: boolean;
}

/**
 * One fulfillment's quantity, bounded per source (§4.4.3, OWE-07):
 * KERNEL_STOCK may only reach what is reserved, EXTERNAL_COUNCIL only what is
 * not covered — so a covered portion has to be released first, and the screen
 * refuses a Council fulfillment of stock the Kernel already set aside.
 */
/** The quantity a source may reach, bounded by what that source holds. */
function sourceCapacityOf(source: GqlWeOweFulfillmentSource, obligation: GqlWeOweObligationFieldsFragment): number {
  return source === 'KERNEL_STOCK' ? obligation.reservedQty : obligation.uncoveredQty;
}

/** The sentence for a quantity past a source's own reach, in the words the screen uses. */
function overSourceError(source: GqlWeOweFulfillmentSource, obligation: GqlWeOweObligationFieldsFragment): string {
  if (source === 'KERNEL_STOCK') {
    return `Only ${obligation.reservedQty} Kernels are reserved for this obligation; release the reservation first or record the rest as EXTERNAL_COUNCIL.`;
  }
  return `Only ${obligation.uncoveredQty} is uncovered; release the reservation on the covered portion before a Council supplies it.`;
}

export function fulfillmentPlan(
  raw: string,
  source: GqlWeOweFulfillmentSource,
  obligation: GqlWeOweObligationFieldsFragment,
): FulfillmentPlan {
  const text = raw.trim();
  if (!WHOLE_NUMBER.test(text)) {
    return { quantity: null, error: 'Enter a whole number of Kernels to fulfill.', maxBySource: 0, source, blocked: false };
  }
  const quantity = Number(text);
  const maxBySource = sourceCapacityOf(source, obligation);
  if (quantity < 1) {
    return { quantity: null, error: 'Enter at least one Kernel to fulfill.', maxBySource, source, blocked: maxBySource < 1 };
  }
  if (quantity > obligation.remainingQty) {
    return { quantity: null, error: `This obligation owes ${obligation.remainingQty} more; ${quantity} cannot be fulfilled against it.`, maxBySource, source, blocked: false };
  }
  if (quantity > maxBySource) {
    return { quantity: null, error: overSourceError(source, obligation), maxBySource, source, blocked: maxBySource < 1 };
  }
  return { quantity, error: null, maxBySource, source, blocked: maxBySource < 1 };
}

/** The sources a fulfilled obligation may draw on, in the order the picker shows them. */
export function fulfillmentSources(obligation: GqlWeOweObligationFieldsFragment): GqlWeOweFulfillmentSource[] {
  const sources: GqlWeOweFulfillmentSource[] = [];
  if (obligation.reservedQty > 0) sources.push('KERNEL_STOCK');
  if (obligation.uncoveredQty > 0) sources.push('EXTERNAL_COUNCIL');
  return sources;
}

/** What the obligation is, in the words the screen shows. */
export function weOweStatusLabel(status: GqlWeOweObligationFieldsFragment['status']): string {
  return status === 'CLOSED' ? 'Closed' : 'Open';
}

/** The close reason in words, for a closed obligation. */
export function closeReasonLabel(reason?: string | null): string {
  if (reason === 'FULFILLED') return 'Fulfilled';
  if (reason === 'CANCELLED') return 'Cancelled';
  return '';
}

export const WE_OWE_STATUS_OPTIONS: { value: 'OPEN' | 'CLOSED'; label: string }[] = [
  { value: 'OPEN', label: 'Open' },
  { value: 'CLOSED', label: 'Closed' },
];

/** The server's over-assignment warnings, one line per product, for the screens to show. */
export function noticesOf(warnings: readonly { productId: string; message: string }[] | undefined): string[] {
  return (warnings ?? []).map((warning) => `${warning.productId}: ${warning.message}`);
}

/**
 * The We Owe side of one line batch, as the server reads it (§4.3.1, §7.1):
 * a line that creates We Owe requires the buyer name, and the event must offer
 * We Owe at all. Both are checked against the lines that were typed rather than
 * against the event alone, so the refusal sentence names the lines that caused it.
 */
export function weOweLineError(
  lines: readonly ValidatedSaleLine[],
  buyerName: string,
  weOweEnabled: boolean,
): string | null {
  const owing = lines.filter((line) => line.weOweQty > 0);
  if (owing.length === 0) return null;
  if (!weOweEnabled) {
    return 'This event does not offer We Owe. Sell the quantities immediately or reopen the event with We Owe enabled.';
  }
  if (buyerName.trim() === '') {
    return 'Enter the buyer name: a line that creates We Owe requires it.';
  }
  return null;
}
