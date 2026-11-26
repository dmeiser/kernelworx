/**
 * The sale desk: one event's sales, entered and corrected (§4.5.1, on §4.2-§4.3).
 *
 * A sale is a whole-sale fact — one instant, one method, one set of lines, one
 * buyer — so the surface is a list of records with actions rather than one long
 * form. The entry form sits under the list; each row opens its own correction or
 * void, because both are whole-sale acts that need the sale's own rows read against
 * the event's current version.
 *
 * Every write is aimed at the event's version read on this screen, and the screen
 * re-reads the event and the list after a write: the version chip in the header is
 * the number the write was aimed at, and a stale one is the one thing the server
 * refuses with a sentence this screen can show.
 */

import React, { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Divider,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  IconButton,
} from '@mui/material';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import {
  CREATE_SHOW_AND_SELL_SALE,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_SHOW_AND_SELL_SALES,
  LIST_UNIT_PAYMENT_METHODS,
  LIST_WE_OWE_OBLIGATIONS,
} from '../../lib/graphql';
import {
  acceptsSaleEntry,
  defaultSaleAt,
  formatCents,
  isDraftOnly,
  isOtherMethodOption,
  noticesOf,
  paymentMethodOptions,
  saleAtWindowError,
  salePlan,
  weOweLineError,
  BUYER_EMAIL_MAX_CHARS,
  BUYER_NAME_MAX_CHARS,
  BUYER_PHONE_MAX_CHARS,
  OTHER_DETAILS_MAX_CHARS,
  SPLIT_PAYMENT_TOOLTIP,
  type PaymentMethodOption,
  type SalePlan,
} from '../../lib/saleDesk';
import {
  SHOW_AND_SELL_PAGE_SIZE,
  describeShowAndSellFailure,
  formatInstant,
  utcToZonedWallClock,
  zonedWallClockToUtc,
} from '../../lib/showSell';
import { createWriteIntent, isStaleVersionError, refreshQuery, type WriteIntent } from '../../lib/units';
import { ConnectionRestNotice } from '../ConnectionRestNotice';
import { ErrorNote } from '../ErrorAlert';
import { LoadingState } from '../LoadingState';
import { useCompleteConnection } from '../../hooks/useCompleteConnection';
import { SaleLineTable } from './SaleLineEditor';
import { emptyLineRow, type CatalogProduct, type LineRowDraft } from './saleLines';
import { SaleCorrectionPanel, SaleVoidPanel } from './SaleCorrectionForms';
import type {
  GqlCreateShowAndSellSaleMutation,
  GqlGetUnitCampaignCatalogQuery,
  GqlListShowAndSellSalesQuery,
  GqlListUnitPaymentMethodsQuery,
  GqlListWeOweObligationsQuery,
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSaleFieldsFragment,
  GqlWeOweObligationFieldsFragment,
} from '../../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Sale = GqlShowAndSellSaleFieldsFragment;

const SALES_VARIABLES = (showAndSellId: string) => ({
  showAndSellId,
  status: undefined,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
});

interface FormState {
  rows: LineRowDraft[];
  paymentMethod: string;
  saleAt: string;
  buyerName: string;
  buyerPhone: string;
  buyerEmail: string;
  otherDetails: string;
}

/** A trimmed buyer/details field, or undefined when it is blank. */
function trimmedOrUndefined(value: string): string | undefined {
  return value.trim() || undefined;
}

/** The note the method allows: only Other carries one, so switching away drops it. */
function otherDetailsAfterMethod(options: readonly PaymentMethodOption[], value: string, current: string): string {
  return isOtherMethodOption(options, value) ? current : '';
}

/** The method sentence: a sale names a method the Unit offers, and the picker only ever offers one. */
function methodError(option: PaymentMethodOption | undefined): string | null {
  return option === undefined ? 'Choose a payment method the Unit still offers.' : null;
}

/** The Other note: the server’s 250-character ceiling, then the fact that Other requires one. */
function otherDetailsError(option: PaymentMethodOption | undefined, otherDetails: string): string | null {
  if (otherDetails.length > OTHER_DETAILS_MAX_CHARS) return `Other details may not exceed ${OTHER_DETAILS_MAX_CHARS} characters.`;
  if (option?.isOther === true && otherDetails === '') return 'Say what makes this payment an Other one.';
  return null;
}

/**
 * The entry’s first sentence, in the one order the screen and the write read it:
 * lines, instant, method, the Other note, then the buyer an owing line requires.
 * Both halves call this same function, so the sentence that disables the button is
 * always the sentence a click would show — a refusal never sits on one side of the
 * pair while the other side waits for a write that cannot be sent.
 */
function entryError(
  plan: SalePlan,
  windowError: string | null,
  option: PaymentMethodOption | undefined,
  otherDetails: string,
  buyerError: string | null,
): string | null {
  return plan.error ?? windowError ?? methodError(option) ?? otherDetailsError(option, otherDetails) ?? buyerError;
}

/**
 * The create body: one instant, one method, one line per typed product, the
 * event's version — and the idempotency key derived from that whole body, so
 * every field the write sends is part of what the key stands for. A body that
 * differs in any one field is a different write; a retry of the same body is
 * the same write, and must replay rather than double-create.
 */
function createBody(
  plan: SalePlan,
  event: Event,
  form: FormState,
  method: PaymentMethodOption,
  saleAt: Date,
  otherDetails: string,
  intent: WriteIntent,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    showAndSellId: event.showAndSellId,
    saleAt: saleAt.toISOString(),
    lineItems: plan.lines.map((line) => ({
      productId: line.productId,
      immediateQty: line.immediateQty,
      weOweQty: line.weOweQty,
    })),
    paymentMethodCode: method.value,
    buyerName: trimmedOrUndefined(form.buyerName),
    buyerPhone: trimmedOrUndefined(form.buyerPhone),
    buyerEmail: trimmedOrUndefined(form.buyerEmail),
    otherDetails: method.isOther ? otherDetails : undefined,
    version: { expectedVersion: event.version },
  };
  return { ...payload, idempotency: { idempotencyKey: intent.keyFor(payload) } };
}

function emptyForm(event: Event, timezone: string): FormState {
  return {
    rows: [emptyLineRow()],
    paymentMethod: '',
    saleAt: utcToZonedWallClock(defaultSaleAt(event), timezone),
    buyerName: '',
    buyerPhone: '',
    buyerEmail: '',
    otherDetails: '',
  };
}

export const SalesDesk: React.FC<{
  event: Event;
  timezone: string;
  onChanged: () => Promise<unknown>;
}> = ({ event, timezone, onChanged }) => {
  const catalog = useQuery<GqlGetUnitCampaignCatalogQuery>(GET_UNIT_CAMPAIGN_CATALOG, {
    variables: { unitCampaignId: event.unitCampaignId },
  });
  const methods = useQuery<GqlListUnitPaymentMethodsQuery>(LIST_UNIT_PAYMENT_METHODS, {
    variables: { unitId: event.unitId, includeInactive: true },
  });
  const sales = useQuery<GqlListShowAndSellSalesQuery>(LIST_SHOW_AND_SELL_SALES, {
    variables: SALES_VARIABLES(event.showAndSellId),
  });
  const allSales = useCompleteConnection<Sale>(sales.data?.showAndSellSales, {
    query: LIST_SHOW_AND_SELL_SALES,
    field: 'showAndSellSales',
    limit: SHOW_AND_SELL_PAGE_SIZE,
    variables: SALES_VARIABLES(event.showAndSellId),
  });
  const obligations = useQuery<GqlListWeOweObligationsQuery>(LIST_WE_OWE_OBLIGATIONS, {
    variables: {
      unitCampaignId: event.unitCampaignId,
      showAndSellId: event.showAndSellId,
      page: { limit: SHOW_AND_SELL_PAGE_SIZE },
    },
  });
  const allObligations = useCompleteConnection<GqlWeOweObligationFieldsFragment>(obligations.data?.weOweObligations, {
    query: LIST_WE_OWE_OBLIGATIONS,
    field: 'weOweObligations',
    limit: SHOW_AND_SELL_PAGE_SIZE,
    variables: {
      unitCampaignId: event.unitCampaignId,
      showAndSellId: event.showAndSellId,
      page: { limit: SHOW_AND_SELL_PAGE_SIZE },
    },
  });

  const products = useMemo(() => productsOf(catalog.data), [catalog.data]);
  const options = useMemo(() => paymentMethodOptions(methods.data?.unitPaymentMethods ?? []), [methods.data]);
  const [form, setForm] = useState<FormState>(() => emptyForm(event, timezone));
  const [correctionSale, setCorrectionSale] = useState<Sale | null>(null);
  const [voidSale, setVoidSale] = useState<Sale | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const intent = useRef(createWriteIntent());
  const [createSale, { loading: creating }] = useMutation<GqlCreateShowAndSellSaleMutation>(CREATE_SHOW_AND_SELL_SALE);

  const editable = acceptsSaleEntry(event.status);
  const draftOnly = isDraftOnly(event.status);

  const openCreate = () => {
    setCorrectionSale(null);
    setVoidSale(null);
    setForm(emptyForm(event, timezone));
    setError(null);
    setNotices([]);
    intent.current = createWriteIntent();
  };

  const reset = () => {
    setCorrectionSale(null);
    setVoidSale(null);
    setForm(emptyForm(event, timezone));
    setError(null);
    setNotices([]);
    intent.current = createWriteIntent();
  };

  const refetchDesk = async () => {
    await sales.refetch();
    await obligations.refetch();
  };

  const submitSale = async (body: Record<string, unknown>) => {
    try {
      const result = await createSale({ variables: { input: body } });
      setNotices(noticesOf(result.data?.createShowAndSellSale?.warnings));
      setForm(emptyForm(event, timezone));
      setError(null);
      // The intent is spent: a later, deliberately identical create is a new write.
      intent.current = createWriteIntent();
      await refreshQuery(onChanged);
      await refetchDesk();
    } catch (mutationError) {
      setError(describeShowAndSellFailure(mutationError, 'Could not save the sale.'));
      if (isStaleVersionError(mutationError)) await refreshQuery(onChanged);
    }
  };

  const submitCreate = async () => {
    const saleInstant = zonedWallClockToUtc(form.saleAt, timezone);
    const plan = salePlan(form.rows.map(rowToDraft), products);
    const windowError = saleAtWindowError(saleInstant, event);
    const method = options.find((option) => option.value === form.paymentMethod);
    const otherDetails = form.otherDetails.trim();
    const buyerError = weOweLineError(plan.lines, form.buyerName, event.weOweEnabled);
    const validationError = entryError(plan, windowError, method, otherDetails, buyerError);
    /* v8 ignore start -- the button is disabled by this same sentence; the write-side check is what
       keeps a body the screen never approved from being sent if the click ever reaches here */
    if (validationError !== null) {
      setError(validationError);
      return;
    }
    /* v8 ignore stop */
    const body = createBody(plan, event, form, method as PaymentMethodOption, saleInstant as Date, otherDetails, intent.current);
    await submitSale(body);
  };

  return (
    <Box sx={{ pt: 2 }}>
      <Alert severity="info" sx={{ mb: 2 }} data-testid="sale-desk-note">
        Enter a sale at the table: one instant, one payment method, and one line per product with what the buyer takes now and
        what the Unit owes them later. Every sale of this event is listed here.
      </Alert>
      <SalesNotices event={event} editable={editable} draftOnly={draftOnly} />
      <SaleList
        sales={allSales.items}
        timezone={timezone}
        loading={sales.loading && !sales.data}
        editable={editable}
        onCorrect={(sale) => {
          openCreate();
          setCorrectionSale(sale);
        }}
        onVoid={(sale) => {
          openCreate();
          setVoidSale(sale);
        }}
      />
      <ConnectionRestNotice loading={allSales.loadingRest} failed={allSales.failedRest} />
      {error !== null ? <ErrorNote message={error} data-testid="sale-desk-error" /> : null}
      <OverageNotices notices={notices} />
      <Divider sx={{ my: 2 }} />
      <DeskPanel
        correctionSale={correctionSale}
        voidSale={voidSale}
        event={event}
        timezone={timezone}
        products={products}
        options={options}
        form={form}
        setForm={setForm}
        loading={creating}
        editable={editable}
        obligations={allObligations.items}
        onChanged={onChanged}
        onRefetch={refetchDesk}
        onClose={reset}
        onSubmit={() => void submitCreate()}
      />
    </Box>
  );
};

/** The one panel under the list: the correction or void in flight, or the entry form. */
const DeskPanel: React.FC<{
  correctionSale: Sale | null;
  voidSale: Sale | null;
  event: Event;
  timezone: string;
  products: readonly CatalogProduct[];
  options: ReturnType<typeof paymentMethodOptions>;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  loading: boolean;
  editable: boolean;
  obligations: readonly GqlWeOweObligationFieldsFragment[];
  onChanged: () => Promise<unknown>;
  onRefetch: () => Promise<void>;
  onClose: () => void;
  onSubmit: () => void;
}> = ({ correctionSale, voidSale, event, timezone, products, options, form, setForm, loading, editable, obligations, onChanged, onRefetch, onClose, onSubmit }) => {
  if (correctionSale !== null) {
    return (
      <SaleCorrectionPanel
        sale={correctionSale}
        event={event}
        timezone={timezone}
        products={products}
        options={options}
        obligations={obligations}
        onChanged={onChanged}
        onRefetch={onRefetch}
        onClose={onClose}
      />
    );
  }
  if (voidSale !== null) {
    return (
      <SaleVoidPanel
        sale={voidSale}
        event={event}
        timezone={timezone}
        onChanged={onChanged}
        onRefetch={onRefetch}
        onClose={onClose}
      />
    );
  }
  return (
    <SaleEntryForm
      event={event}
      timezone={timezone}
      products={products}
      options={options}
      form={form}
      setForm={setForm}
      loading={loading}
      editable={editable}
      onSubmit={onSubmit}
    />
  );
};

function productsOf(data?: GqlGetUnitCampaignCatalogQuery): CatalogProduct[] {
  return data?.unitCampaignCatalog?.products ?? [];
}

function rowToDraft(row: LineRowDraft) {
  return { productId: row.productId, immediateQty: row.immediateQty, weOweQty: row.weOweQty };
}

/** What the desk refuses to do right now, and why. */
const SalesNotices: React.FC<{ event: Event; editable: boolean; draftOnly: boolean }> = ({ event, editable, draftOnly }) => (
  <>
    {draftOnly ? (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="sale-draft-note">
        This event is reopened: what you save here is a draft. The campaign’s stock answer belongs to re-finalization, which
        is what decides the real balances.
      </Alert>
    ) : null}
    {!editable ? (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="sale-locked-note">
        Pooled sales are entered while an event is ACTIVE, ENDED or REOPENED; this event is {event.status}. Its sales stand
        as the history they were entered with.
      </Alert>
    ) : null}
    {!event.weOweEnabled ? (
      <Alert severity="info" sx={{ mb: 2 }} data-testid="sale-we-owe-off-note">
        This event does not offer We Owe. Sell every line immediately, or reopen the event with We Owe enabled.
      </Alert>
    ) : null}
  </>
);

/** The list: every sale of this event, with its revision and the two actions that act on it. */
const SaleList: React.FC<{
  sales: readonly Sale[];
  timezone: string;
  loading: boolean;
  editable: boolean;
  onCorrect: (sale: Sale) => void;
  onVoid: (sale: Sale) => void;
}> = ({ sales, timezone, loading, editable, onCorrect, onVoid }) => {
  if (loading && sales.length === 0) return <LoadingState minHeight="120px" />;
  if (sales.length === 0) {
    return (
      <Alert severity="info" data-testid="sale-list-empty" sx={{ mb: 2 }}>
        No sales yet. Enter one below — every sale of this event is listed here.
      </Alert>
    );
  }
  return (
    // Eight columns cannot fit a phone, and the page does not scroll sideways: the
    // list scrolls inside its own container so the Correct and Void controls of a
    // wide row are reached by sliding the rows, not by losing them past the edge.
    <Box sx={{ overflowX: 'auto' }}>
      <Table size="small" aria-label="Sales at this event">
        <TableHead>
          <TableRow>
            <TableCell>When</TableCell>
            <TableCell>Lines</TableCell>
            <TableCell>Total</TableCell>
            <TableCell>Method</TableCell>
            <TableCell>Expected cash</TableCell>
            <TableCell>Buyer</TableCell>
            <TableCell>Status</TableCell>
            <TableCell aria-label="Actions" />
          </TableRow>
        </TableHead>
        <TableBody>
          {sales.map((sale) => (
            <TableRow key={sale.saleId} data-testid={`sale-row-${sale.saleId}`}>
              <TableCell>{formatInstant(sale.saleAt, timezone)}</TableCell>
              <TableCell>{sale.lineItems.length}</TableCell>
              <TableCell>{formatCents(sale.totalCents)}</TableCell>
              <TableCell>{sale.paymentMethodSnapshot.displayName}</TableCell>
              <TableCell data-testid={`sale-expected-cash-${sale.saleId}`}>{formatCents(sale.expectedCashCents)}</TableCell>
              <TableCell>{sale.buyerName ?? '—'}</TableCell>
              <TableCell>{sale.status}</TableCell>
              <TableCell>
                <SaleActions sale={sale} editable={editable} onCorrect={onCorrect} onVoid={onVoid} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
};

const SaleActions: React.FC<{
  sale: Sale;
  editable: boolean;
  onCorrect: (sale: Sale) => void;
  onVoid: (sale: Sale) => void;
}> = ({ sale, editable, onCorrect, onVoid }) => {
  // The buttons act on the event's live history, not on FINALIZED/CANCELLED
  // events: an ACTIVE sale on a history event is history too.
  const active = editable && sale.status === 'ACTIVE';
  return (
    <Stack direction="row" spacing={1}>
      <Button
        size="small"
        variant="outlined"
        onClick={() => onCorrect(sale)}
        disabled={!active}
        data-testid={`correct-sale-${sale.saleId}`}
      >
        Correct
      </Button>
      <Button
        size="small"
        color="error"
        variant="outlined"
        onClick={() => onVoid(sale)}
        disabled={!active}
        data-testid={`void-sale-${sale.saleId}`}
      >
        Void
      </Button>
    </Stack>
  );
};

/** The over-assignment warnings the last create saved with. */
const OverageNotices: React.FC<{ notices: string[] }> = ({ notices }) => {
  if (notices.length === 0) return null;
  return (
    <Card variant="outlined" sx={{ mb: 2 }} data-testid="sale-warnings">
      <CardContent>
        <Typography variant="subtitle1" gutterBottom>
          Saved, with a warning
        </Typography>
        <Typography color="text.secondary">
          Stock assigned to this event may exceed what the campaign holds. Nothing was clamped; the write stands.
        </Typography>
        <Stack spacing={1}>
          {notices.map((notice) => (
            <Typography key={notice} data-testid="sale-warning">
              {notice}
            </Typography>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
};

/** The entry form: one create, with the whole sale read out before it is written. */
const SaleEntryForm: React.FC<{
  event: Event;
  timezone: string;
  products: readonly CatalogProduct[];
  options: ReturnType<typeof paymentMethodOptions>;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  loading: boolean;
  editable: boolean;
  onSubmit: () => void;
}> = ({ event, timezone, products, options, form, setForm, loading, editable, onSubmit }) => {
  const plan = salePlan(form.rows.map(rowToDraft), products);
  const windowError = saleAtWindowError(zonedWallClockToUtc(form.saleAt, timezone), event);
  const option = options.find((entry) => entry.value === form.paymentMethod);
  const otherDetails = form.otherDetails.trim();
  const buyerError = weOweLineError(plan.lines, form.buyerName, event.weOweEnabled);
  const error = entryError(plan, windowError, option, otherDetails, buyerError);
  const otherDetailsRequired = option?.isOther === true;
  const disabled = !editable || loading;
  const canSubmit = editable && !loading && error === null;

  return (
    <SaleEntryFormView
      event={event}
      products={products}
      options={options}
      form={form}
      setForm={setForm}
      loading={loading}
      disabled={disabled}
      canSubmit={canSubmit}
      error={error}
      otherDetailsRequired={otherDetailsRequired}
      totalCents={plan.totalCents}
      onSubmit={onSubmit}
    />
  );
};

const SaleEntryFormView: React.FC<{
  event: Event;
  products: readonly CatalogProduct[];
  options: ReturnType<typeof paymentMethodOptions>;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  loading: boolean;
  disabled: boolean;
  canSubmit: boolean;
  error: string | null;
  otherDetailsRequired: boolean;
  totalCents: number;
  onSubmit: () => void;
}> = ({ event, products, options, form, setForm, loading, disabled, canSubmit, error, otherDetailsRequired, totalCents, onSubmit }) => (
    <Card variant="outlined" data-testid="sale-entry-form">
      <CardContent>
        <Typography variant="subtitle1" gutterBottom>
          Enter a sale
        </Typography>
        <SaleLineTable
          rows={form.rows}
          products={products}
          idPrefix="sale-line"
          weOweAllowed={event.weOweEnabled}
          disabled={disabled}
          onRow={(index, patch) => setForm((current) => ({ ...current, rows: current.rows.map((row, i) => (i === index ? { ...row, ...patch } : row)) }))}
          onRemove={(index) => setForm((current) => ({ ...current, rows: current.rows.filter((_row, i) => i !== index) }))}
          onAdd={() => setForm((current) => ({ ...current, rows: [...current.rows, emptyLineRow()] }))}
        />
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
          <TextField
            label="When the sale happened"
            type="datetime-local"
            size="small"
            value={form.saleAt}
            onChange={(change) => setForm((current) => ({ ...current, saleAt: change.target.value }))}
            disabled={disabled}
            inputProps={{ 'aria-label': 'When the sale happened', 'data-testid': 'sale-at' }}
          />
          <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 220 }}>
            <Select
              size="small"
              label="Payment method"
              value={form.paymentMethod}
              displayEmpty
              onChange={(change) => setForm((current) => ({
                ...current,
                paymentMethod: change.target.value,
                otherDetails: otherDetailsAfterMethod(options, change.target.value, current.otherDetails),
              }))}
              disabled={disabled}
              data-testid="sale-payment-method"
              inputProps={{ 'aria-label': 'Payment method' }}
              sx={{ minWidth: 220, flex: 1 }}
            >
              <MenuItem value="">Choose a payment method</MenuItem>
              {options.map((entry) => (
                <MenuItem key={entry.value} value={entry.value} data-testid={`payment-method-${entry.value}`}>
                  {entry.label}
                </MenuItem>
              ))}
            </Select>
            <Tooltip title={SPLIT_PAYMENT_TOOLTIP} describeChild>
              <IconButton size="small" aria-label="How split payments are recorded" data-testid="sale-payment-help" disabled={disabled}>
                <HelpOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
          {otherDetailsRequired ? (
            <TextField
              label="Other details (required)"
              value={form.otherDetails}
              onChange={(change) => setForm((current) => ({ ...current, otherDetails: change.target.value }))}
              disabled={disabled}
              inputProps={{ 'aria-label': 'Other payment details', 'data-testid': 'sale-other-details', maxLength: OTHER_DETAILS_MAX_CHARS }}
              sx={{ minWidth: 220 }}
            />
          ) : null}
        </Stack>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
          <TextField
            label="Buyer name"
            value={form.buyerName}
            onChange={(change) => setForm((current) => ({ ...current, buyerName: change.target.value }))}
            disabled={disabled}
            inputProps={{ 'aria-label': 'Buyer name', 'data-testid': 'sale-buyer-name', maxLength: BUYER_NAME_MAX_CHARS }}
            sx={{ minWidth: 200 }}
          />
          <TextField
            label="Buyer phone"
            value={form.buyerPhone}
            onChange={(change) => setForm((current) => ({ ...current, buyerPhone: change.target.value }))}
            disabled={disabled}
            inputProps={{ 'aria-label': 'Buyer phone', 'data-testid': 'sale-buyer-phone', maxLength: BUYER_PHONE_MAX_CHARS }}
            sx={{ minWidth: 160 }}
          />
          <TextField
            label="Buyer email"
            value={form.buyerEmail}
            onChange={(change) => setForm((current) => ({ ...current, buyerEmail: change.target.value }))}
            disabled={disabled}
            inputProps={{ 'aria-label': 'Buyer email', 'data-testid': 'sale-buyer-email', maxLength: BUYER_EMAIL_MAX_CHARS }}
            sx={{ minWidth: 200 }}
          />
        </Stack>
        <Typography variant="body2" color="text.secondary" data-testid="sale-draft-total" sx={{ mt: 2 }}>
          Draft total: {formatCents(totalCents)} — the server prices the lines from the catalog; this is what the typed quantities add up to
        </Typography>
        {error !== null ? <ErrorNote message={error} data-testid="sale-entry-error" /> : null}
        <Stack direction="row" spacing={2} sx={{ mt: 2 }} alignItems="center">
          <Button variant="contained" onClick={onSubmit} disabled={!canSubmit} data-testid="save-sale">
            {loading ? 'Saving…' : 'Enter the sale'}
          </Button>
          <Tooltip title="A sale is written against this event’s current version, and the same body reuses one idempotency key." describeChild>
            <IconButton size="small" aria-label="Why the sale is saved this way" data-testid="sale-entry-help">
              <HelpOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </CardContent>
    </Card>
);
