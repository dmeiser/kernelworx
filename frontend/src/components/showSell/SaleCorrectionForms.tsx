/**
 * The correction and void forms for one sale (§4.5.1, on §4.3.1 / §4.3.2).
 *
 * Both are whole-sale acts that need the sale's own rows read against the event's
 * current version: a correction replaces every line and archives the whole prior
 * revision, and a void takes the whole sale down, releasing the stock it consumed
 * and closing every obligation it created. Neither is a delta, so neither is
 * entered line by line — the admin edits the whole row set and saves it once.
 *
 * A correction may also omit a line. Omitting is the way to void one line: its
 * We Owe obligation closes as cancelled and any reservation it held is released,
 * all in one transaction. The panel refuses the batch outright when any one line
 * cannot be sent, and says which lines will be voided before the admin commits.
 */

import React, { useMemo, useRef, useState } from 'react';
import { useMutation } from '@apollo/client/react';
import {
  Alert,
  Button,
  Card,
  CardContent,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
  IconButton,
} from '@mui/material';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import { CORRECT_SHOW_AND_SELL_SALE, VOID_SHOW_AND_SELL_SALE } from '../../lib/graphql';
import {
  BUYER_NAME_MAX_CHARS,
  BUYER_PHONE_MAX_CHARS,
  BUYER_EMAIL_MAX_CHARS,
  OTHER_DETAILS_MAX_CHARS,
  SPLIT_PAYMENT_TOOLTIP,
  correctionPlan,
  formatCents,
  isOtherMethodOption,
  noticesOf,
  weOweLineError,
  type CorrectionLineDraft,
  type CorrectionPlan,
  type ExistingLine,
  type PaymentMethodOption,
} from '../../lib/saleDesk';
import { describeShowAndSellFailure, formatInstant } from '../../lib/showSell';
import { createWriteIntent, isStaleVersionError, refreshQuery, type WriteIntent } from '../../lib/units';
import { ErrorNote } from '../ErrorAlert';
import { SaleLineTable } from './SaleLineEditor';
import { emptyLineRow, linesOf, type CatalogProduct, type LineRowDraft } from './saleLines';
import type {
  GqlCorrectShowAndSellSaleMutation,
  GqlVoidShowAndSellSaleMutation,
  GqlWeOweObligationFieldsFragment,
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSaleFieldsFragment,
} from '../../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Sale = GqlShowAndSellSaleFieldsFragment;
type MutationPayload = NonNullable<GqlCorrectShowAndSellSaleMutation['correctShowAndSellSale']>;
type ArchivedRevision = MutationPayload['priorRevision'];

const REASON_MAX_CHARS = 500;

/** The stored lines as the plan reads them, keyed by stable id. */
function existingOf(sale: Sale): ExistingLine[] {
  return sale.lineItems.map((line) => ({
    lineItemId: line.lineItemId,
    productId: line.productId,
    productNameSnapshot: line.productNameSnapshot,
    immediateQty: line.immediateQty,
    weOweQty: line.weOweQty,
  }));
}

/** The rows as the plan reads them; supplemental rows carry no id. */
function draftsOf(rows: readonly LineRowDraft[]): CorrectionLineDraft[] {
  return rows.map((row) => ({
    lineItemId: row.lineItemId ?? undefined,
    productId: row.productId,
    immediateQty: row.immediateQty,
    weOweQty: row.weOweQty,
  }));
}

/** The lines a correction omits: the originals the admin removed, with their owed quantity. */
function omittedOf(existing: readonly ExistingLine[], rows: readonly LineRowDraft[]): ExistingLine[] {
  const keptIds = new Set(rows.filter((row) => row.lineItemId != null).map((row) => row.lineItemId));
  return existing.filter((line) => !keptIds.has(line.lineItemId));
}

/** The method choices, plus the sale's own method when the Unit no longer offers it. */
function methodOptionsOf(options: readonly PaymentMethodOption[], stored: PaymentMethodSnapshot): PaymentMethodOption[] {
  const list = [...options];
  if (list.some((option) => option.value === stored.methodCode)) return list;
  list.push({
    value: stored.methodCode,
    label: `${stored.displayName} (retired)`,
    isBuiltIn: false,
    isOther: stored.methodCode === 'OTHER',
  });
  return list;
}

type PaymentMethodSnapshot = Sale['paymentMethodSnapshot'];

/** The sentence for a missing or over-long reason, in the act's own words. */
function reasonErrorOf(reasonTrimmed: string, act: string): string | null {
  if (reasonTrimmed === '') return `Say why the sale is being ${act}.`;
  if (reasonTrimmed.length > REASON_MAX_CHARS) return `The reason may not exceed ${REASON_MAX_CHARS} characters.`;
  return null;
}

/** The We Owe sentence for the corrected lines: an owing line needs the buyer named. */
function buyerErrorOf(plan: CorrectionPlan, buyerName: string, weOweEnabled: boolean): string | null {
  return weOweLineError(
    plan.lines.map((line) => ({
      productId: line.productId,
      immediateQty: line.immediateQty,
      weOweQty: line.weOweQty,
      subtotalCents: 0,
    })),
    buyerName,
    weOweEnabled,
  );
}

/** The note the method choice allows: only Other carries one, and when it does it is required. */
function otherDetailsErrorOf(otherSelected: boolean, otherDetails: string): string | null {
  // Switching away from Other drops the note, so a non-empty note here can only
  // come from a race between the draft and the write; the field is not offered.
  if (!otherSelected) return null;
  if (otherDetails === '') return 'Say what makes this payment an Other one.';
  if (otherDetails.length > OTHER_DETAILS_MAX_CHARS) return `Other details may not exceed ${OTHER_DETAILS_MAX_CHARS} characters.`;
  return null;
}

/** The first sentence for a correction that cannot be sent, in the order the panel reads it. */
function correctionFormError(plan: CorrectionPlan, reasonError: string | null, buyerError: string | null, otherDetailsError: string | null): string | null {
  return plan.error ?? reasonError ?? buyerError ?? otherDetailsError;
}

/** What the saved correction archived: the revision the server kept, and why it was kept. */
function priorRevisionNoteOf(archived: ArchivedRevision): string {
  if (!archived) return 'Correction saved.';
  return `Revision ${archived.revision} archived${archived.reason ? ` — ${archived.reason}` : ''}.`;
}

interface CorrectionFields {
  sale: Sale;
  event: Event;
  plan: CorrectionPlan;
  rows: readonly LineRowDraft[];
  method: string;
  changedMethod: boolean;
  otherSelected: boolean;
  otherDetails: string;
  storedOtherDetails: string;
  buyerName: string;
  storedBuyerName: string;
  buyerPhone: string;
  storedBuyerPhone: string;
  buyerEmail: string;
  storedBuyerEmail: string;
  reason: string;
  intent: WriteIntent;
}

/** The buyer and payment fields the sale holds, so the body can say only what actually moved. */
function storedBuyerOf(sale: Sale) {
  return {
    name: sale.buyerName ?? '',
    phone: sale.buyerPhone ?? '',
    email: sale.buyerEmail ?? '',
    otherDetails: sale.paymentMethodSnapshot.otherDetails ?? '',
  };
}

/** One line of the replacement set: the stable id when the line kept it, then the product and quantities. */
function lineItemsOf(plan: CorrectionPlan): Record<string, unknown>[] {
  return plan.lines.map((line) => ({
    ...(line.lineItemId != null ? { lineItemId: line.lineItemId } : {}),
    productId: line.productId,
    immediateQty: line.immediateQty,
    weOweQty: line.weOweQty,
  }));
}

/** The buyer fields that actually moved — an unchanged one is not a change the server has to re-snapshot. */
function changedBuyerFields(fields: CorrectionFields): Record<string, unknown> {
  const changed: Record<string, unknown> = {};
  if (fields.buyerName !== fields.storedBuyerName) changed.buyerName = fields.buyerName;
  if (fields.buyerPhone !== fields.storedBuyerPhone) changed.buyerPhone = fields.buyerPhone;
  if (fields.buyerEmail !== fields.storedBuyerEmail) changed.buyerEmail = fields.buyerEmail;
  return changed;
}

/** The payment fields that actually moved: a new method, or the note only Other may carry. */
function changedPaymentFields(fields: CorrectionFields): Record<string, unknown> {
  const { method, changedMethod, otherSelected, otherDetails, storedOtherDetails } = fields;
  if (changedMethod) {
    const changed: Record<string, unknown> = { paymentMethodCode: method };
    if (otherSelected) changed.otherDetails = otherDetails;
    return changed;
  }
  if (otherSelected && otherDetails !== storedOtherDetails) return { otherDetails };
  return {};
}

/**
 * The correction body: the whole replacement line set, the sale's own revision and
 * the event's version as its conditions, and only the buyer and payment fields that
 * actually moved — an unchanged field is not a change the server has to re-snapshot.
 */
function correctionBodyOf(fields: CorrectionFields): Record<string, unknown> {
  const { sale, event, reason, plan } = fields;
  const payload: Record<string, unknown> = {
    showAndSellId: event.showAndSellId,
    saleId: sale.saleId,
    saleVersion: { expectedVersion: sale.revision },
    version: { expectedVersion: event.version },
    lineItems: lineItemsOf(plan),
    reason,
    ...changedBuyerFields(fields),
    ...changedPaymentFields(fields),
  };
  return { ...payload, idempotency: { idempotencyKey: fields.intent.keyFor(payload) } };
}

/** The draft read-out: what the typed rows add up to, and what the correction leaves out. */
function draftSummaryOf(draftKernels: number, lineCount: number, omittedCount: number): string {
  const lines = lineCount === 1 ? 'line' : 'lines';
  if (omittedCount === 0) return `Draft: ${draftKernels} Kernels across ${lineCount} ${lines}`;
  return `Draft: ${draftKernels} Kernels across ${lineCount} ${lines} · ${omittedCount} line${omittedCount === 1 ? '' : 's'} omitted`;
}

interface CorrectionFormState {
  rows: LineRowDraft[];
  method: string;
  otherDetails: string;
  buyerName: string;
  buyerPhone: string;
  buyerEmail: string;
}

/** The panel opens with the sale as it stands, so the admin corrects what they are shown. */
function formStateOf(sale: Sale): CorrectionFormState {
  return {
    rows: linesOf(sale),
    method: sale.paymentMethodSnapshot.methodCode,
    otherDetails: sale.paymentMethodSnapshot.otherDetails ?? '',
    buyerName: sale.buyerName ?? '',
    buyerPhone: sale.buyerPhone ?? '',
    buyerEmail: sale.buyerEmail ?? '',
  };
}

export const SaleCorrectionPanel: React.FC<{
  sale: Sale;
  event: Event;
  timezone: string;
  products: readonly CatalogProduct[];
  options: readonly PaymentMethodOption[];
  obligations: readonly GqlWeOweObligationFieldsFragment[];
  onChanged: () => Promise<unknown>;
  onRefetch: () => Promise<unknown>;
  onClose: () => void;
}> = ({ sale, event, timezone, products, options, obligations, onChanged, onRefetch, onClose }) => {
  const intent = useRef(createWriteIntent());
  const [initial] = useState(() => formStateOf(sale));
  const [rows, setRows] = useState<LineRowDraft[]>(initial.rows);
  const [method, setMethod] = useState<string>(initial.method);
  const [otherDetails, setOtherDetails] = useState<string>(initial.otherDetails);
  const [buyerName, setBuyerName] = useState<string>(initial.buyerName);
  const [buyerPhone, setBuyerPhone] = useState<string>(initial.buyerPhone);
  const [buyerEmail, setBuyerEmail] = useState<string>(initial.buyerEmail);
  const [reason, setReason] = useState<string>('');
  const [serverError, setServerError] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [priorRevisionNote, setPriorRevisionNote] = useState<string | null>(null);
  const [correctSale, { loading }] = useMutation<GqlCorrectShowAndSellSaleMutation>(CORRECT_SHOW_AND_SELL_SALE);

  const existing = useMemo(() => existingOf(sale), [sale]);
  const omitted = useMemo(() => omittedOf(existing, rows), [existing, rows]);
  const obligationsForSale = useMemo(
    () => obligations.filter((obligation) => obligation.saleId === sale.saleId),
    [obligations, sale.saleId],
  );
  const methodOptions = useMemo(() => methodOptionsOf(options, sale.paymentMethodSnapshot), [options, sale.paymentMethodSnapshot]);

  const changedMethod = method !== sale.paymentMethodSnapshot.methodCode;
  const otherSelected = methodOptions.some((option) => option.value === method && option.isOther === true);

  const plan = correctionPlan(existing, draftsOf(rows), products, obligationsForSale);
  const draftKernels = plan.lines.reduce((sum, line) => sum + line.immediateQty + line.weOweQty, 0);
  const reasonTrimmed = reason.trim();
  const trimmedDetails = otherDetails.trim();
  const formError = correctionFormError(
    plan,
    reasonErrorOf(reasonTrimmed, 'corrected'),
    buyerErrorOf(plan, buyerName, event.weOweEnabled),
    otherDetailsErrorOf(otherSelected, trimmedDetails),
  );
  const error = formError ?? serverError;
  const canSubmit = !loading && formError === null;

  const editRow = (index: number, patch: Partial<LineRowDraft>) => {
    setServerError(null);
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const removeRow = (index: number) => {
    setServerError(null);
    setRows((current) => current.filter((_row, i) => i !== index));
  };

  const addRow = () => {
    setServerError(null);
    setRows((current) => [...current, emptyLineRow()]);
  };

  const applyPayload = (payload: MutationPayload | undefined) => {
    setNotices(noticesOf(payload?.warnings));
    setPriorRevisionNote(priorRevisionNoteOf(payload?.priorRevision));
    setServerError(null);
  };

  const stored = storedBuyerOf(sale);

  const submit = async () => {
    if (formError !== null) {
      setServerError(formError);
      return;
    }
    const body = correctionBodyOf({
      sale,
      event,
      plan,
      rows,
      method,
      changedMethod,
      otherSelected,
      otherDetails: trimmedDetails,
      storedOtherDetails: stored.otherDetails,
      buyerName: buyerName.trim(),
      storedBuyerName: stored.name,
      buyerPhone: buyerPhone.trim(),
      storedBuyerPhone: stored.phone,
      buyerEmail: buyerEmail.trim(),
      storedBuyerEmail: stored.email,
      reason: reasonTrimmed,
      intent: intent.current,
    });
    try {
      const result = await correctSale({ variables: { input: body } });
      applyPayload(result.data?.correctShowAndSellSale);
      // The intent is spent: a later, deliberately identical correction is a new write.
      intent.current = createWriteIntent();
      await refreshQuery(onChanged);
      await refreshQuery(onRefetch);
    } catch (mutationError) {
      setServerError(describeShowAndSellFailure(mutationError, 'Could not save the correction.'));
      if (isStaleVersionError(mutationError)) await refreshQuery(onChanged);
    }
  };

  return (
    <CorrectionFormView
      sale={sale}
      event={event}
      timezone={timezone}
      products={products}
      methodOptions={methodOptions}
      otherSelected={otherSelected}
      method={method}
      setMethod={setMethod}
      otherDetails={otherDetails}
      setOtherDetails={setOtherDetails}
      buyerName={buyerName}
      setBuyerName={setBuyerName}
      buyerPhone={buyerPhone}
      setBuyerPhone={setBuyerPhone}
      buyerEmail={buyerEmail}
      setBuyerEmail={setBuyerEmail}
      reason={reason}
      setReason={setReason}
      rows={rows}
      onEditRow={editRow}
      onRemoveRow={removeRow}
      onAddRow={addRow}
      loading={loading}
      omitted={omitted}
      draftSummary={draftSummaryOf(draftKernels, plan.lines.length, omitted.length)}
      error={error}
      notices={notices}
      priorRevisionNote={priorRevisionNote}
      canSubmit={canSubmit}
      onSubmit={() => void submit()}
      onClose={onClose}
    />
  );
};

/** The whole correction form: the sale as it stands, the rows being replaced, and the save. */
const CorrectionFormView: React.FC<{
  sale: Sale;
  event: Event;
  timezone: string;
  products: readonly CatalogProduct[];
  methodOptions: readonly PaymentMethodOption[];
  otherSelected: boolean;
  method: string;
  setMethod: (value: string) => void;
  otherDetails: string;
  setOtherDetails: (value: string) => void;
  buyerName: string;
  setBuyerName: (value: string) => void;
  buyerPhone: string;
  setBuyerPhone: (value: string) => void;
  buyerEmail: string;
  setBuyerEmail: (value: string) => void;
  reason: string;
  setReason: (value: string) => void;
  rows: LineRowDraft[];
  onEditRow: (index: number, patch: Partial<LineRowDraft>) => void;
  onRemoveRow: (index: number) => void;
  onAddRow: () => void;
  loading: boolean;
  omitted: readonly ExistingLine[];
  draftSummary: string;
  error: string | null;
  notices: string[];
  priorRevisionNote: string | null;
  canSubmit: boolean;
  onSubmit: () => void;
  onClose: () => void;
}> = ({
  sale,
  event,
  timezone,
  products,
  methodOptions,
  otherSelected,
  method,
  setMethod,
  otherDetails,
  setOtherDetails,
  buyerName,
  setBuyerName,
  buyerPhone,
  setBuyerPhone,
  buyerEmail,
  setBuyerEmail,
  reason,
  setReason,
  rows,
  onEditRow,
  onRemoveRow,
  onAddRow,
  loading,
  omitted,
  draftSummary,
  error,
  notices,
  priorRevisionNote,
  canSubmit,
  onSubmit,
  onClose,
}) => (
  <Card variant="outlined" data-testid="sale-correction-form">
    <CardContent>
      <Typography variant="subtitle1" gutterBottom data-testid="sale-correction-heading">
        Correct the sale
      </Typography>
      <CorrectionSaleSummary sale={sale} timezone={timezone} />
      <Alert severity="info" sx={{ mb: 2 }} data-testid="sale-correction-note">
        A correction replaces every line. The whole previous revision is archived, and the event’s version is what this
        write is aimed at.
      </Alert>
      {omitted.length > 0 ? <OmittedLinesNotice omitted={omitted} /> : null}
      <SaleLineTable
        rows={rows}
        products={products}
        idPrefix="correction-line"
        weOweAllowed={event.weOweEnabled}
        disabled={loading}
        onRow={onEditRow}
        onRemove={onRemoveRow}
        onAdd={onAddRow}
      />
      <CorrectionPaymentFields
        methodOptions={methodOptions}
        method={method}
        setMethod={setMethod}
        otherSelected={otherSelected}
        otherDetails={otherDetails}
        setOtherDetails={setOtherDetails}
        loading={loading}
      />
      <CorrectionBuyerFields
        buyerName={buyerName}
        setBuyerName={setBuyerName}
        buyerPhone={buyerPhone}
        setBuyerPhone={setBuyerPhone}
        buyerEmail={buyerEmail}
        setBuyerEmail={setBuyerEmail}
        loading={loading}
      />
      <TextField
        label="Why the correction"
        value={reason}
        onChange={(change) => setReason(change.target.value)}
        disabled={loading}
        inputProps={{ 'aria-label': 'Why the correction', 'data-testid': 'correction-reason', maxLength: REASON_MAX_CHARS }}
        sx={{ mt: 2, width: '100%' }}
      />
      <Typography variant="body2" color="text.secondary" data-testid="correction-draft-total" sx={{ mt: 2 }}>
        {draftSummary}
      </Typography>
      <CorrectionOutcomes error={error} notices={notices} priorRevisionNote={priorRevisionNote} />
      <Stack direction="row" spacing={2} sx={{ mt: 2 }} alignItems="center">
        <Button variant="contained" onClick={onSubmit} disabled={!canSubmit || priorRevisionNote !== null} data-testid="save-correction">
          {loading ? 'Saving…' : 'Save the correction'}
        </Button>
        <Button variant="text" onClick={onClose} data-testid="cancel-correction">
          {priorRevisionNote !== null ? 'Done' : 'Cancel'}
        </Button>
        <Tooltip title="The correction is written against this event’s current version and the sale’s current revision." describeChild>
          <IconButton size="small" aria-label="Why the correction is saved this way" data-testid="sale-correction-help">
            <HelpOutlineIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
    </CardContent>
  </Card>
);

/** The sale the correction is aimed at, as the panel reads it back. */
const CorrectionSaleSummary: React.FC<{ sale: Sale; timezone: string }> = ({ sale, timezone }) => (
  <Typography color="text.secondary" data-testid="sale-correction-summary" sx={{ mb: 2 }}>
    {formatInstant(sale.saleAt, timezone)} · {formatCents(sale.totalCents)} · {sale.paymentMethodSnapshot.displayName} · revision{' '}
    {sale.revision}
  </Typography>
);

/** What leaving these lines out will do, said before the admin commits. */
const OmittedLinesNotice: React.FC<{ omitted: readonly ExistingLine[] }> = ({ omitted }) => (
  <Alert severity="warning" sx={{ mb: 2 }} data-testid="correction-omission-warning">
    Leaving out {omitted.map((line) => `${line.productNameSnapshot} (${line.immediateQty + line.weOweQty} Kernels)`).join(', ')}{' '}
    voids {omitted.length === 1 ? 'that line' : 'those lines'} — their We Owe obligations close as cancelled and any
    reservation is released.
  </Alert>
);

/** The method the sale keeps, with the note only Other may carry. */
const CorrectionPaymentFields: React.FC<{
  methodOptions: readonly PaymentMethodOption[];
  method: string;
  setMethod: (value: string) => void;
  otherSelected: boolean;
  otherDetails: string;
  setOtherDetails: (value: string) => void;
  loading: boolean;
}> = ({ methodOptions, method, setMethod, otherSelected, otherDetails, setOtherDetails, loading }) => (
  <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
    <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 220 }}>
      <Select
        size="small"
        label="Payment method"
        value={method}
        displayEmpty
        onChange={(change) => {
          const value = change.target.value;
          setMethod(value);
          // The note only belongs to an Other payment: switching away drops it.
          if (!isOtherMethodOption(methodOptions, value)) setOtherDetails('');
        }}
        disabled={loading}
        data-testid="correction-payment-method"
        inputProps={{ 'aria-label': 'Payment method' }}
        sx={{ minWidth: 220, flex: 1 }}
      >
        <MenuItem value="">Choose a payment method</MenuItem>
        {methodOptions.map((option) => (
          <MenuItem key={option.value} value={option.value} data-testid={`correction-payment-method-${option.value}`}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
      <Tooltip title={SPLIT_PAYMENT_TOOLTIP} describeChild>
        <IconButton size="small" aria-label="How split payments are recorded" data-testid="correction-payment-help" disabled={loading}>
          <HelpOutlineIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
    {otherSelected ? (
      <TextField
        label="Other details"
        value={otherDetails}
        onChange={(change) => setOtherDetails(change.target.value)}
        disabled={loading}
        inputProps={{ 'aria-label': 'Other payment details', 'data-testid': 'correction-other-details', maxLength: OTHER_DETAILS_MAX_CHARS }}
        sx={{ minWidth: 220 }}
      />
    ) : null}
  </Stack>
);

const CorrectionBuyerFields: React.FC<{
  buyerName: string;
  setBuyerName: (value: string) => void;
  buyerPhone: string;
  setBuyerPhone: (value: string) => void;
  buyerEmail: string;
  setBuyerEmail: (value: string) => void;
  loading: boolean;
}> = ({ buyerName, setBuyerName, buyerPhone, setBuyerPhone, buyerEmail, setBuyerEmail, loading }) => (
  <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
    <TextField
      label="Buyer name"
      value={buyerName}
      onChange={(change) => setBuyerName(change.target.value)}
      disabled={loading}
      inputProps={{ 'aria-label': 'Buyer name', 'data-testid': 'correction-buyer-name', maxLength: BUYER_NAME_MAX_CHARS }}
      sx={{ minWidth: 200 }}
    />
    <TextField
      label="Buyer phone"
      value={buyerPhone}
      onChange={(change) => setBuyerPhone(change.target.value)}
      disabled={loading}
      inputProps={{ 'aria-label': 'Buyer phone', 'data-testid': 'correction-buyer-phone', maxLength: BUYER_PHONE_MAX_CHARS }}
      sx={{ minWidth: 160 }}
    />
    <TextField
      label="Buyer email"
      value={buyerEmail}
      onChange={(change) => setBuyerEmail(change.target.value)}
      disabled={loading}
      inputProps={{ 'aria-label': 'Buyer email', 'data-testid': 'correction-buyer-email', maxLength: BUYER_EMAIL_MAX_CHARS }}
      sx={{ minWidth: 200 }}
    />
  </Stack>
);

/** What the last save said: the sentence it refused with, the warnings it kept, the revision it archived. */
const CorrectionOutcomes: React.FC<{ error: string | null; notices: string[]; priorRevisionNote: string | null }> = ({
  error,
  notices,
  priorRevisionNote,
}) => (
  <>
    {error ? <ErrorNote message={error} data-testid="sale-correction-error" /> : null}
    {notices.length > 0 ? (
      <Alert severity="warning" sx={{ mt: 2 }} data-testid="correction-warnings">
        {notices.map((notice) => (
          <Typography key={notice} data-testid="correction-warning">
            {notice}
          </Typography>
        ))}
      </Alert>
    ) : null}
    {priorRevisionNote ? (
      <Alert severity="success" sx={{ mt: 2 }} data-testid="correction-saved">
        {priorRevisionNote}
      </Alert>
    ) : null}
  </>
);

export const SaleVoidPanel: React.FC<{
  sale: Sale;
  event: Event;
  timezone: string;
  onChanged: () => Promise<unknown>;
  onRefetch: () => Promise<unknown>;
  onClose: () => void;
}> = ({ sale, event, timezone, onChanged, onRefetch, onClose }) => {
  const intent = useRef(createWriteIntent());
  const [reason, setReason] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [voidSale, { loading }] = useMutation<GqlVoidShowAndSellSaleMutation>(VOID_SHOW_AND_SELL_SALE);

  const reasonTrimmed = reason.trim();
  const reasonError = reasonErrorOf(reasonTrimmed, 'voided');
  const canSubmit = !loading && reasonError === null;

  const submit = async () => {
    if (reasonError !== null) {
      setError(reasonError);
      return;
    }
    const payload: Record<string, unknown> = {
      showAndSellId: event.showAndSellId,
      saleId: sale.saleId,
      saleVersion: { expectedVersion: sale.revision },
      version: { expectedVersion: event.version },
      reason: reasonTrimmed,
    };
    const body: Record<string, unknown> = {
      ...payload,
      idempotency: { idempotencyKey: intent.current.keyFor(payload) },
    };
    try {
      await voidSale({ variables: { input: body } });
      // The intent is spent: a later, deliberately identical void is a new write.
      intent.current = createWriteIntent();
      await refreshQuery(onChanged);
      await refreshQuery(onRefetch);
      onClose();
    } catch (mutationError) {
      setError(describeShowAndSellFailure(mutationError, 'Could not void the sale.'));
      if (isStaleVersionError(mutationError)) await refreshQuery(onChanged);
    }
  };

  return (
    <Card variant="outlined" data-testid="sale-void-form">
      <CardContent>
        <Typography variant="subtitle1" gutterBottom data-testid="sale-void-heading">
          Void the sale
        </Typography>
        <Alert severity="warning" sx={{ mb: 2 }} data-testid="sale-void-note">
          A void takes the whole sale down: the stock it consumed is handed back through one movement per product, every
          We Owe obligation it created closes as cancelled and any reservation is released. A line whose quantity the buyer
          already holds makes the void impossible. This cannot be undone — a new sale replaces it.
        </Alert>
        <Typography color="text.secondary" data-testid="sale-void-summary" sx={{ mb: 2 }}>
          {formatInstant(sale.saleAt, timezone)} · {formatCents(sale.totalCents)} · {sale.lineItems.length}{' '}
          {sale.lineItems.length === 1 ? 'line' : 'lines'} · revision {sale.revision}
        </Typography>
        <TextField
          label="Why the void"
          value={reason}
          onChange={(change) => setReason(change.target.value)}
          disabled={loading}
          inputProps={{ 'aria-label': 'Why the void', 'data-testid': 'void-reason', maxLength: REASON_MAX_CHARS }}
          sx={{ mt: 1, width: '100%' }}
        />
        {error ? <ErrorNote message={error} data-testid="sale-void-error" /> : null}
        <Stack direction="row" spacing={2} sx={{ mt: 2 }} alignItems="center">
          <Button variant="contained" color="error" onClick={() => void submit()} disabled={!canSubmit} data-testid="save-void">
            {loading ? 'Voiding…' : 'Void the sale'}
          </Button>
          <Button variant="text" onClick={onClose} data-testid="cancel-void">
            Cancel
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
};
