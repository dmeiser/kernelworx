/**
 * Inventory positions, receipt, stock-only adjustment, and Council on-order
 * (Show & Sell §2.6.1).
 *
 * Two rules shape this screen.
 *
 * **The balances are read, never added up here.** Sellable, assigned,
 * unassigned, overage, With Scout, and total unit-owned stock are derived
 * server-side from the balance row plus the open event allocations and the
 * custody rows (spec §7). Every column below is a field the server computed; the
 * screen has no arithmetic that could disagree with the audit trail it is
 * showing. The read names every catalog product, because a product with no
 * balance row yet answers as zeros at version 0 only when it is named: the
 * catalog, not the balance table, decides which rows exist.
 *
 * **A stock change is stock only.** `INV-03` and checklist §2.2.2: a receipt or
 * an adjustment creates no Order, sale, payment, trade record, fulfillment, or
 * Scout credit. The screen says so where the write is offered, because an admin
 * who treats a stock adjustment as a way to record money gets a number that can
 * never be reconciled against the cash. The reason field is required for the
 * same reason: an unexplained movement cannot be audited.
 *
 * **One intent, one idempotency key** (`createWriteIntent`, lib/units.ts): a
 * refused write leaves the dialog open with the same body, so pressing Confirm
 * again is the same intent and replays the original result rather than counting
 * the stock twice.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
import type { ApolloClient } from '@apollo/client';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import {
  ADJUST_COUNCIL_ON_ORDER,
  ADJUST_INVENTORY,
  GET_UNIT_CAMPAIGN_CATALOG,
  RECORD_INVENTORY_RECEIPT,
} from '../lib/graphql';
import {
  MAX_QUANTITY,
  STOCK_ONLY_NOTE,
  describeInventoryFailure,
  fetchInventoryPositions,
  parseQuantity,
  parseReason,
  productLabel,
} from '../lib/inventory';
import type { InventoryPositionRow } from '../lib/inventory';
import { ErrorAlert } from './ErrorAlert';
import { FormDialog } from './FormDialog';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { createWriteIntent } from '../lib/units';
import type { GqlGetUnitCampaignCatalogQuery } from '../types/graphql-generated';
import { InventoryMovementHistory } from './InventoryMovementHistory';

type CatalogProduct = NonNullable<GqlGetUnitCampaignCatalogQuery['unitCampaignCatalog']>['products'][number];
type ProductNames = ReadonlyMap<string, string>;

/** Which stock write the admin has asked to make. */
export type StockAction = 'receipt' | 'adjust' | 'on-order';

interface StockActionState {
  action: StockAction;
  productId: string;
  quantity: string;
  reason: string;
  fieldError: string | null;
}

interface InventoryPanelProps {
  unitCampaignId: string;
}

export const InventoryPanel: React.FC<InventoryPanelProps> = ({ unitCampaignId }) => {
  const client = useApolloClient();
  const catalog = useQuery<GqlGetUnitCampaignCatalogQuery>(GET_UNIT_CAMPAIGN_CATALOG, {
    variables: { unitCampaignId },
  });
  const products = useMemo(() => catalog.data?.unitCampaignCatalog?.products ?? [], [catalog.data]);
  const names = useMemo<ProductNames>(
    () => new Map(products.map((product) => [product.productId, product.productName])),
    [products],
  );
  // The catalog decides which rows exist, so its product ids go into the read: the
  // server answers a catalog product with no balance row yet at zeros only when the
  // read names it, and a board that listed only the balance rows would hide the product
  // nothing has been received for.
  const productIds = useMemo(() => products.map((product) => product.productId), [products]);
  const board = usePositionBoard(client, unitCampaignId, productIds, catalog.data !== undefined);
  const rows = board.rows ?? [];

  const writes = useStockWrites(unitCampaignId, board.reload);
  const [pending, setPending] = useState<StockActionState | null>(null);

  return (
    <Box sx={{ pt: 2 }}>
      <StockOnlyNote />
      <ActionRow
        products={products.length > 0}
        onAsk={(action) => setPending({ action, productId: '', quantity: '', reason: '', fieldError: null })}
      />
      <QueryGate
        query={{ loading: catalog.loading || board.loading, data: board.rows ?? undefined }}
        loading={<LoadingState minHeight="200px" />}
        failure={<ErrorAlert message="Could not load this campaign's stock." />}
      >
        <PositionTable rows={rows} names={names} />
      </QueryGate>
      <InventoryMovementHistory unitCampaignId={unitCampaignId} products={products} />
      {pending ? (
        <StockActionDialog
          state={pending}
          products={products}
          names={names}
          unitCampaignId={unitCampaignId}
          writes={writes}
          onStateChange={setPending}
          onClose={() => setPending(null)}
        />
      ) : null}
    </Box>
  );
};

interface PositionBoardState {
  /** null until the read has answered, so a failed read is never an empty board. */
  rows: InventoryPositionRow[] | null;
  failed: boolean;
}

/**
 * The whole position board: every catalog product, every page of the read.
 *
 * The read is capped at 15 named products per call — the server's own bound, because it
 * answers one balance read per name — so a wider catalog is read chunk by chunk, each
 * chunk walked to its end. A chunk that fails fails the board: half a stock board with no
 * warning is how stock goes missing.
 */
function usePositionBoard(
  client: ApolloClient,
  unitCampaignId: string,
  productIds: readonly string[],
  catalogAnswered: boolean,
) {
  const [state, setState] = useState<PositionBoardState>({ rows: null, failed: false });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!catalogAnswered) return undefined;
    if (productIds.length === 0) {
      setState({ rows: [], failed: false });
      return undefined;
    }
    let active = true;
    void fetchInventoryPositions(client, unitCampaignId, productIds)
      .then((rows) => {
        if (active) setState({ rows, failed: false });
      })
      .catch(() => {
        if (active) setState({ rows: null, failed: true });
      });
    return () => {
      active = false;
    };
  }, [client, unitCampaignId, productIds, catalogAnswered, attempt]);

  // Asked for and not answered yet: the moment between the catalog landing and the read
  // starting belongs here too, or the board would flash a failure it never got.
  const loading = catalogAnswered && productIds.length > 0 && state.rows === null && !state.failed;
  return { rows: state.rows, loading, reload: () => setAttempt((previous) => previous + 1) };
}

/** The three stock writes, each with the read it must refresh afterwards. */
function useStockWrites(unitCampaignId: string, refresh: () => unknown) {
  const [recordReceipt] = useMutation(RECORD_INVENTORY_RECEIPT);
  const [adjustStock] = useMutation(ADJUST_INVENTORY);
  const [adjustOnOrder] = useMutation(ADJUST_COUNCIL_ON_ORDER);
  // One key per write intent, derived from the body: the same body pressed twice
  // is one write, and a body the admin changed is a different one.
  const intent = useRef(createWriteIntent()).current;

  const send = async (mutation: typeof recordReceipt, body: Record<string, unknown>, fallback: string) => {
    try {
      await mutation({ variables: { input: { ...body, idempotency: { idempotencyKey: intent.keyFor(body) } } } });
    } catch (failure) {
      throw new Error(describeInventoryFailure(failure, fallback), { cause: failure });
    }
    await refreshWith(refresh);
  };

  return {
    receipt: (productId: string, quantity: number) =>
      send(recordReceipt, { unitCampaignId, productId, quantity }, 'The receipt could not be recorded.'),
    adjust: (productId: string, quantityDelta: number, reason: string) =>
      send(
        adjustStock,
        { unitCampaignId, productId, quantityDelta, reason },
        'The stock adjustment could not be recorded.',
      ),
    onOrder: (productId: string, quantityDelta: number, reason: string) =>
      send(
        adjustOnOrder,
        { unitCampaignId, productId, quantityDelta, reason },
        'The Council on-order change could not be recorded.',
      ),
  };
}

/** A refresh that fails after a write has landed surfaces through the query itself. */
async function refreshWith(refresh: () => unknown): Promise<void> {
  try {
    await refresh();
  } catch {
    // The query's own error state is where this belongs; the write already happened.
  }
}

const StockOnlyNote: React.FC = () => (
  <Alert severity="info" sx={{ mb: 2 }} data-testid="stock-only-note">
    {STOCK_ONLY_NOTE}
  </Alert>
);

const ActionRow: React.FC<{ products: boolean; onAsk: (action: StockAction) => void }> = ({ products, onAsk }) => (
  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
    <Button variant="contained" onClick={() => onAsk('receipt')} data-testid="record-receipt" disabled={!products}>
      Record receipt
    </Button>
    <Button variant="outlined" onClick={() => onAsk('adjust')} data-testid="adjust-stock" disabled={!products}>
      Adjust stock
    </Button>
    <Button variant="outlined" onClick={() => onAsk('on-order')} data-testid="adjust-on-order" disabled={!products}>
      Adjust Council on order
    </Button>
    {!products ? (
      <Typography variant="body2" color="text.secondary" data-testid="no-catalog-note">
        This campaign has no catalog products to receive or adjust.
      </Typography>
    ) : null}
  </Stack>
);

const PositionTable: React.FC<{ rows: InventoryPositionRow[]; names: ProductNames }> = ({ rows, names }) => (
  <Card variant="outlined" sx={{ mb: 3 }}>
    <CardContent>
      <Typography variant="h6" gutterBottom>
        Stock by product
      </Typography>
      <Box sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Product</TableCell>
              <TableCell align="right">Kernel on hand</TableCell>
              <TableCell align="right">We Owe held</TableCell>
              <TableCell align="right">Sellable</TableCell>
              <TableCell align="right">Assigned to events</TableCell>
              <TableCell align="right">Unassigned</TableCell>
              <TableCell align="right">Assignment overage</TableCell>
              <TableCell align="right">With Scout</TableCell>
              <TableCell align="right">Total unit-owned</TableCell>
              <TableCell align="right">Council on order</TableCell>
              <TableCell align="right">Version</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((position) => (
              <PositionRow key={position.productId} position={position} names={names} />
            ))}
            {rows.length === 0 ? <NoPositionsRow /> : null}
          </TableBody>
        </Table>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="position-count">
        {`${rows.length} ${rows.length === 1 ? 'product' : 'products'} in this campaign`}
      </Typography>
    </CardContent>
  </Card>
);

const PositionRow: React.FC<{ position: InventoryPositionRow; names: ProductNames }> = ({ position, names }) => {
  const id = position.productId;
  return (
    <TableRow data-testid={`position-row-${id}`}>
      <TableCell>{productLabel(names, id)}</TableCell>
      <QuantityCell testId={`position-kernel-${id}`} value={position.kernelPhysicalQty} />
      <QuantityCell testId={`position-sold-${id}`} value={position.soldInPossessionQty} />
      <QuantityCell testId={`position-sellable-${id}`} value={position.sellableKernelQty} />
      <QuantityCell testId={`position-assigned-${id}`} value={position.assignedOpenQty} />
      <QuantityCell testId={`position-unassigned-${id}`} value={position.unassignedKernelQty} />
      <QuantityCell
        testId={`position-overage-${id}`}
        value={position.assignmentOverageQty}
        emphasize={position.assignmentOverageQty > 0}
      />
      <QuantityCell testId={`position-with-scout-${id}`} value={position.withScoutQty} />
      <QuantityCell testId={`position-owned-${id}`} value={position.totalUnitOwnedUndeliveredQty} />
      <QuantityCell testId={`position-on-order-${id}`} value={position.councilOnOrderQty} />
      <TableCell align="right" data-testid={`position-version-${id}`}>{`v${position.version}`}</TableCell>
    </TableRow>
  );
};

const QuantityCell: React.FC<{ testId: string; value: number; emphasize?: boolean }> = ({
  testId,
  value,
  emphasize,
}) => (
  <TableCell align="right" data-testid={testId} sx={emphasize ? { color: 'error.text', fontWeight: 600 } : undefined}>
    {value}
  </TableCell>
);

const NoPositionsRow: React.FC = () => (
  <TableRow>
    <TableCell colSpan={11}>
      <Box sx={{ p: 2 }}>
        <Typography color="text.secondary">
          No stock recorded yet. Every product starts at zero until a receipt is recorded.
        </Typography>
      </Box>
    </TableCell>
  </TableRow>
);

/** The copy each write offers, so the three dialogs differ only in what they ask for. */
interface ActionWordings {
  title: string;
  confirm: string;
  quantityLabel: string;
  helper: string;
  signed: boolean;
  zeroAllowed: boolean;
  reasonRequired: boolean;
}

function actionWordings(action: StockAction): ActionWordings {
  if (action === 'receipt') {
    return {
      title: 'Record a receipt',
      confirm: 'Record receipt',
      quantityLabel: 'Quantity received',
      helper: 'How many of this product arrived. One inventory unit is one sale unit — there is no case size.',
      signed: false,
      zeroAllowed: false,
      reasonRequired: false,
    };
  }
  if (action === 'adjust') {
    return {
      title: 'Adjust Kernel stock',
      confirm: 'Adjust stock',
      quantityLabel: 'Change (use a minus to reduce)',
      helper: `A whole number between -${MAX_QUANTITY} and ${MAX_QUANTITY}, never zero. The result cannot take stock below zero or below what We Owe already holds.`,
      signed: true,
      zeroAllowed: false,
      reasonRequired: true,
    };
  }
  return {
    title: 'Adjust Council on order',
    confirm: 'Save on-order change',
    quantityLabel: 'Change (use a minus to reduce)',
    helper:
      'Council on order is shown beside stock and is never subtracted from what is needed. It cannot go below zero, ' +
      'and the change itself cannot be zero: a zero would write a movement that moves nothing.',
    signed: true,
    zeroAllowed: false,
    reasonRequired: false,
  };
}

/** The field errors a submission would send, or null when the body is sendable. */
function validate(state: StockActionState, wordings: ActionWordings): string | null {
  if (!state.productId) return 'Choose a product.';
  const quantity = parseQuantity(state.quantity, { signed: wordings.signed, zeroAllowed: wordings.zeroAllowed });
  if (quantity.error) return quantity.error;
  return parseReason(state.reason, wordings.reasonRequired);
}

const StockActionDialog: React.FC<{
  state: StockActionState;
  products: CatalogProduct[];
  names: ProductNames;
  unitCampaignId: string;
  writes: ReturnType<typeof useStockWrites>;
  onStateChange: (state: StockActionState) => void;
  onClose: () => void;
}> = ({ state, products, names, writes, onStateChange, onClose }) => {
  const wordings = actionWordings(state.action);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    const error = validate(state, wordings);
    if (error) {
      onStateChange({ ...state, fieldError: error });
      throw new Error(error);
    }
    const quantity = parseQuantity(state.quantity, { signed: wordings.signed, zeroAllowed: wordings.zeroAllowed });
    setSubmitting(true);
    try {
      await sendAction(writes, state.action, state.productId, quantity.value as number, state.reason.trim());
    } finally {
      setSubmitting(false);
    }
    onClose();
  };

  return (
    <FormDialog
      title={wordings.title}
      confirmLabel={wordings.confirm}
      onCancel={onClose}
      onConfirm={submit}
      error={state.fieldError}
      onDismissError={() => onStateChange({ ...state, fieldError: null })}
    >
      <StockActionFields
        state={state}
        products={products}
        names={names}
        wordings={wordings}
        submitting={submitting}
        onChange={onStateChange}
      />
    </FormDialog>
  );
};

function sendAction(
  writes: ReturnType<typeof useStockWrites>,
  action: StockAction,
  productId: string,
  quantity: number,
  reason: string,
): Promise<unknown> {
  if (action === 'receipt') return writes.receipt(productId, quantity);
  if (action === 'adjust') return writes.adjust(productId, quantity, reason);
  return writes.onOrder(productId, quantity, reason);
}

const StockActionFields: React.FC<{
  state: StockActionState;
  products: CatalogProduct[];
  names: ProductNames;
  wordings: ActionWordings;
  submitting: boolean;
  onChange: (state: StockActionState) => void;
}> = ({ state, products, names, wordings, submitting, onChange }) => (
  <Stack spacing={2}>
    <Typography variant="body2" color="text.secondary">
      {wordings.helper}
    </Typography>
    <TextField
      select
      label="Product"
      value={state.productId}
      onChange={(event) => onChange({ ...state, productId: event.target.value, fieldError: null })}
      disabled={submitting}
      data-testid="stock-product"
    >
      {products.map((product) => (
        <MenuItem key={product.productId} value={product.productId}>
          {productLabel(names, product.productId)}
        </MenuItem>
      ))}
    </TextField>
    <TextField
      label={wordings.quantityLabel}
      value={state.quantity}
      onChange={(event) => onChange({ ...state, quantity: event.target.value, fieldError: null })}
      disabled={submitting}
      inputMode={wordings.signed ? 'text' : 'numeric'}
      helperText="Whole Kernels only."
      data-testid="stock-quantity"
    />
    {wordings.reasonRequired || state.action === 'on-order' ? (
      <ReasonField wordings={wordings} state={state} submitting={submitting} onChange={onChange} />
    ) : null}
  </Stack>
);

/**
 * The reason line.
 *
 * Mandatory for a stock adjustment, optional for a Council on-order change: the
 * adjustment moves stock the audit trail must explain, while the on-order figure is an
 * expectation. Either way the field says which one it is asking for.
 */
const ReasonField: React.FC<{
  wordings: ActionWordings;
  state: StockActionState;
  submitting: boolean;
  onChange: (state: StockActionState) => void;
}> = ({ wordings, state, submitting, onChange }) => (
  <TextField
    label={wordings.reasonRequired ? 'Reason' : 'Reason (optional)'}
    value={state.reason}
    onChange={(event) => onChange({ ...state, reason: event.target.value, fieldError: null })}
    disabled={submitting}
    multiline
    minRows={2}
    helperText={
      wordings.reasonRequired
        ? 'Who it was for or why the count changed — this is what the audit trail answers with.'
        : 'Say why the expectation changed, if you want the history to explain itself.'
    }
    data-testid="stock-reason"
  />
);
