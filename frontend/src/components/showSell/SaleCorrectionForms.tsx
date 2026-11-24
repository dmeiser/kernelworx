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
  correctionPlan,
  formatCents,
  weOweLineError,
  type CorrectionLineDraft,
  type ExistingLine,
  type PaymentMethodOption,
} from '../../lib/saleDesk';
import { describeShowAndSellFailure, formatInstant } from '../../lib/showSell';
import { createWriteIntent, isStaleVersionError, refreshQuery } from '../../lib/units';
import { ErrorNote } from '../ErrorAlert';
import { SaleLineTable, emptyLineRow, linesOf, type CatalogProduct, type LineRowDraft } from './SaleLineEditor';
import type {
  GqlCorrectShowAndSellSaleMutation,
  GqlVoidShowAndSellSaleMutation,
  GqlWeOweObligationFieldsFragment,
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellSaleFieldsFragment,
} from '../../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Sale = GqlShowAndSellSaleFieldsFragment;

const REASON_MAX_CHARS = 500;
const OTHER_DETAILS_MAX_CHARS = 250;

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
  const [rows, setRows] = useState<LineRowDraft[]>(() => linesOf(sale));
  const [method, setMethod] = useState<string>(sale.paymentMethodSnapshot.methodCode);
  const [otherDetails, setOtherDetails] = useState<string>(sale.paymentMethodSnapshot.otherDetails ?? '');
  const [buyerName, setBuyerName] = useState<string>(sale.buyerName ?? '');
  const [buyerPhone, setBuyerPhone] = useState<string>(sale.buyerPhone ?? '');
  const [buyerEmail, setBuyerEmail] = useState<string>(sale.buyerEmail ?? '');
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
  const methodOptions = useMemo(() => {
    const stored = sale.paymentMethodSnapshot.methodCode;
    const list = [...options];
    if (!list.some((option) => option.value === stored)) {
      list.push({
        value: stored,
        label: `${sale.paymentMethodSnapshot.displayName} (retired)`,
        isBuiltIn: false,
        isOther: stored === 'OTHER',
      });
    }
    return list;
  }, [options, sale.paymentMethodSnapshot.methodCode, sale.paymentMethodSnapshot.displayName]);

  const storedCode = sale.paymentMethodSnapshot.methodCode;
  const changedMethod = method !== storedCode;
  const selectedOption = methodOptions.find((option) => option.value === method);
  const otherSelected = selectedOption?.isOther === true;

  const plan = correctionPlan(existing, draftsOf(rows), products, obligationsForSale);
  const draftKernels = plan.lines.reduce((sum, line) => sum + line.immediateQty + line.weOweQty, 0);
  const reasonTrimmed = reason.trim();
  const reasonError =
    reasonTrimmed === ''
      ? 'Say why the sale is being corrected.'
      : reasonTrimmed.length > REASON_MAX_CHARS
        ? `The reason may not exceed ${REASON_MAX_CHARS} characters.`
        : null;
  const buyerError = weOweLineError(
    plan.lines.map((line) => ({ productId: line.productId, immediateQty: line.immediateQty, weOweQty: line.weOweQty, subtotalCents: 0 })),
    buyerName,
    event.weOweEnabled,
  );
  const otherDetailsError = otherSelected
    ? otherDetails.trim() === ''
      ? 'Say what makes this payment an Other one.'
      : otherDetails.trim().length > OTHER_DETAILS_MAX_CHARS
        ? `Other details may not exceed ${OTHER_DETAILS_MAX_CHARS} characters.`
        : null
    : otherDetails.trim() === ''
      ? null
      : 'Only an Other payment carries a note; remove it or choose the Other method.';

  const formError = plan.error ?? reasonError ?? buyerError ?? otherDetailsError;
  const error = formError ?? serverError;
  const canSubmit = !loading && formError === null;

  const submit = async () => {
    if (formError !== null) {
      setServerError(formError);
      return;
    }
    const storedDetails = sale.paymentMethodSnapshot.otherDetails;
    const detailsChanged = otherDetails.trim() !== (storedDetails ?? '');
    const body: Record<string, unknown> = {
      showAndSellId: event.showAndSellId,
      saleId: sale.saleId,
      saleVersion: { expectedVersion: sale.revision },
      version: { expectedVersion: event.version },
      lineItems: plan.lines.map((line) => ({
        ...(line.lineItemId != null ? { lineItemId: line.lineItemId } : {}),
        productId: line.productId,
        immediateQty: line.immediateQty,
        weOweQty: line.weOweQty,
      })),
      reason: reasonTrimmed,
      idempotency: {
        idempotencyKey: intent.current.keyFor({
          rows: rows.map((row) => ({ ...row })),
          method,
          otherDetails: otherDetails.trim(),
          buyerName: buyerName.trim(),
          buyerPhone: buyerPhone.trim(),
          buyerEmail: buyerEmail.trim(),
          reason: reasonTrimmed,
        }),
      },
    };
    if (buyerName.trim() !== (sale.buyerName ?? '')) body.buyerName = buyerName.trim();
    if (buyerPhone.trim() !== (sale.buyerPhone ?? '')) body.buyerPhone = buyerPhone.trim();
    if (buyerEmail.trim() !== (sale.buyerEmail ?? '')) body.buyerEmail = buyerEmail.trim();
    if (changedMethod) {
      body.paymentMethodCode = method;
      if (otherSelected) body.otherDetails = otherDetails.trim();
    } else if (otherSelected && detailsChanged) {
      body.otherDetails = otherDetails.trim();
    }
    try {
      const result = await correctSale({ variables: { input: body } });
      const archived = result.data?.correctShowAndSellSale?.priorRevision;
      setNotices(result.data?.correctShowAndSellSale?.warnings?.map((warning) => `${warning.productId}: ${warning.message}`) ?? []);
      setPriorRevisionNote(
        archived
          ? `Revision ${archived.revision} archived${archived.reason ? ` — ${archived.reason}` : ''}.`
          : 'Correction saved.',
      );
      setServerError(null);
      await refreshQuery(onChanged);
      await refreshQuery(onRefetch);
    } catch (mutationError) {
      setServerError(describeShowAndSellFailure(mutationError, 'Could not save the correction.'));
      if (isStaleVersionError(mutationError)) await refreshQuery(onChanged);
    }
  };

  return (
    <Card variant="outlined" data-testid="sale-correction-form">
      <CardContent>
        <Typography variant="subtitle1" gutterBottom data-testid="sale-correction-heading">
          Correct the sale
        </Typography>
        <Typography color="text.secondary" data-testid="sale-correction-summary" sx={{ mb: 2 }}>
          {formatInstant(sale.saleAt, timezone)} · {formatCents(sale.totalCents)} · {sale.paymentMethodSnapshot.displayName} · revision{' '}
          {sale.revision}
        </Typography>
        <Alert severity="info" sx={{ mb: 2 }} data-testid="sale-correction-note">
          A correction replaces every line. The whole previous revision is archived, and the event’s version is what this
          write is aimed at.
        </Alert>
        {omitted.length > 0 ? (
          <Alert severity="warning" sx={{ mb: 2 }} data-testid="correction-omission-warning">
            Leaving out {omitted.map((line) => `${line.productNameSnapshot} (${line.immediateQty + line.weOweQty} Kernels)`).join(', ')}{' '}
            voids {omitted.length === 1 ? 'that line' : 'those lines'} — their We Owe obligations close as cancelled and any
            reservation is released.
          </Alert>
        ) : null}
        <SaleLineTable
          rows={rows}
          products={products}
          idPrefix="correction-line"
          weOweAllowed={event.weOweEnabled}
          disabled={loading}
          onRow={(index, patch) => {
            setServerError(null);
            setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
          }}
          onRemove={(index) => {
            setServerError(null);
            setRows((current) => current.filter((_row, i) => i !== index));
          }}
          onAdd={() => {
            setServerError(null);
            setRows((current) => [...current, emptyLineRow()]);
          }}
        />
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
          <Select
            size="small"
            label="Payment method"
            value={method}
            displayEmpty
            onChange={(change) => setMethod(change.target.value)}
            disabled={loading}
            data-testid="correction-payment-method"
            inputProps={{ 'aria-label': 'Payment method' }}
            sx={{ minWidth: 220 }}
          >
            <MenuItem value="">Choose a payment method</MenuItem>
            {methodOptions.map((option) => (
              <MenuItem key={option.value} value={option.value} data-testid={`correction-payment-method-${option.value}`}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
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
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
          <TextField
            label="Buyer name"
            value={buyerName}
            onChange={(change) => setBuyerName(change.target.value)}
            disabled={loading}
            inputProps={{ 'aria-label': 'Buyer name', 'data-testid': 'correction-buyer-name', maxLength: 100 }}
            sx={{ minWidth: 200 }}
          />
          <TextField
            label="Buyer phone"
            value={buyerPhone}
            onChange={(change) => setBuyerPhone(change.target.value)}
            disabled={loading}
            inputProps={{ 'aria-label': 'Buyer phone', 'data-testid': 'correction-buyer-phone', maxLength: 50 }}
            sx={{ minWidth: 160 }}
          />
          <TextField
            label="Buyer email"
            value={buyerEmail}
            onChange={(change) => setBuyerEmail(change.target.value)}
            disabled={loading}
            inputProps={{ 'aria-label': 'Buyer email', 'data-testid': 'correction-buyer-email', maxLength: 254 }}
            sx={{ minWidth: 200 }}
          />
        </Stack>
        <TextField
          label="Why the correction"
          value={reason}
          onChange={(change) => setReason(change.target.value)}
          disabled={loading}
          inputProps={{ 'aria-label': 'Why the correction', 'data-testid': 'correction-reason', maxLength: REASON_MAX_CHARS }}
          sx={{ mt: 2, width: '100%' }}
        />
        <Typography variant="body2" color="text.secondary" data-testid="correction-draft-total" sx={{ mt: 2 }}>
          Draft: {draftKernels} Kernels across {plan.lines.length} {plan.lines.length === 1 ? 'line' : 'lines'}
          {omitted.length > 0 ? ` · ${omitted.length} line${omitted.length === 1 ? '' : 's'} omitted` : ''}
        </Typography>
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
        <Stack direction="row" spacing={2} sx={{ mt: 2 }} alignItems="center">
          <Button variant="contained" onClick={() => void submit()} disabled={!canSubmit || priorRevisionNote !== null} data-testid="save-correction">
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
};

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
  const reasonError =
    reasonTrimmed === ''
      ? 'Say why the sale is being voided.'
      : reasonTrimmed.length > REASON_MAX_CHARS
        ? `The reason may not exceed ${REASON_MAX_CHARS} characters.`
        : null;
  const canSubmit = !loading && reasonError === null;

  const submit = async () => {
    if (reasonError !== null) {
      setError(reasonError);
      return;
    }
    const body: Record<string, unknown> = {
      showAndSellId: event.showAndSellId,
      saleId: sale.saleId,
      saleVersion: { expectedVersion: sale.revision },
      version: { expectedVersion: event.version },
      reason: reasonTrimmed,
      idempotency: { idempotencyKey: intent.current.keyFor({ saleId: sale.saleId, reason: reasonTrimmed }) },
    };
    try {
      await voidSale({ variables: { input: body } });
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
