/**
 * Individual Order custody consumption and fulfillment (Show & Sell §2.6.3, spec §10).
 *
 * A door-to-door sale is an ordinary individual Order that says it drew on the Scout's
 * held stock first (`fulfillmentMode: CONSUME_SCOUT_CUSTODY`). Two things follow, and
 * both are visible here:
 *
 * **The sale is never refused for wanting stock.** A Scout who sold more than they
 * were issued has still sold it. The write lands, the shortfall stays unfulfilled on
 * the line, and the admin fills that gap afterwards from Kernel stock or straight from
 * the Council. So each line shows what it owes next to what it already has.
 *
 * **A fulfillment names the line, not its position.** Lines carry a stable
 * `lineItemId` (§5.19), so fulfilling or reversing one survives a later edit that
 * re-orders the list. Each write carries the Order's `fulfillmentVersion`; a stale one
 * conflicts instead of double-fulfilling a line. A reversal is offered once per
 * fulfillment — the server allows at most one, and reading that state off the history
 * means the second button never appears.
 *
 * **Two projections, deliberately.** The admin audit names the actor account and the
 * inventory movement behind each record. The participant projection carries neither,
 * and this screen asks for the participant one when it shows what the Scout sees, so a
 * privacy rule lives in the document as well as the server.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
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
  FULFILL_INDIVIDUAL_ORDER_LINE,
  GET_ORDER_FULFILLMENTS,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_UNIT_CAMPAIGN_ROSTER,
  RECORD_CUSTODY_SALE,
  REVERSE_INDIVIDUAL_ORDER_FULFILLMENT,
} from '../lib/graphql';
import {
  canReverse,
  describeInventoryFailure,
  fetchAllCampaignOrders,
  fetchParticipantFulfillments,
  fulfillmentSourceLabel,
  fulfillmentStockNote,
  fulfillmentVersionOf,
  isCustodySale,
  page,
  parseQuantity,
  productLabel,
  reversedFulfillmentIds,
  unfulfilledQuantity,
} from '../lib/inventory';
import { UNIT_PAGE_SIZE, createWriteIntent } from '../lib/units';
import { ConfirmDialog } from './ConfirmDialog';
import { ErrorAlert, ErrorNote } from './ErrorAlert';
import { FormDialog } from './FormDialog';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import type {
  GqlGetOrderFulfillmentsQuery,
  GqlGetUnitCampaignCatalogQuery,
  GqlListUnitCampaignRosterQuery,
  GqlOrderFulfillmentFieldsFragment,
  GqlOrderFulfillmentSource,
  GqlParticipantOrderFulfillmentFieldsFragment,
  GqlUnitCampaignMembershipFieldsFragment,
  GqlUnitOrderFieldsFragment,
} from '../types/graphql-generated';

type CatalogProduct = NonNullable<GqlGetUnitCampaignCatalogQuery['unitCampaignCatalog']>['products'][number];
type OrderLine = GqlUnitOrderFieldsFragment['lineItems'][number];
type ProductNames = ReadonlyMap<string, string>;

/** A joined Scout Campaign: the roster row names both ids an Order write needs. */
interface ScoutCampaign {
  campaignId: string;
  profileId: string;
}

const ORDER_NOTE =
  'A door-to-door sale consumes the stock this Scout is holding first. What it cannot consume is not an error: it stays unfulfilled on the line until Kernel stock or a direct Council supply covers it.';

export const OrderFulfillmentPanel: React.FC<{ unitCampaignId: string }> = ({ unitCampaignId }) => {
  const roster = useQuery<GqlListUnitCampaignRosterQuery>(LIST_UNIT_CAMPAIGN_ROSTER, {
    variables: { unitCampaignId, page: { limit: UNIT_PAGE_SIZE } },
  });
  const catalog = useQuery<GqlGetUnitCampaignCatalogQuery>(GET_UNIT_CAMPAIGN_CATALOG, {
    variables: { unitCampaignId },
  });
  const completeRoster = useCompleteConnection<GqlUnitCampaignMembershipFieldsFragment>(
    roster.data?.unitCampaignRoster,
    {
      query: LIST_UNIT_CAMPAIGN_ROSTER,
      field: 'unitCampaignRoster',
      limit: UNIT_PAGE_SIZE,
      variables: { unitCampaignId },
    },
  );
  const campaigns = useMemo<ScoutCampaign[]>(
    () => completeRoster.items.map((member) => ({ campaignId: member.campaignId, profileId: member.profileId })),
    [completeRoster.items],
  );

  const [campaignId, setCampaignId] = useState('');
  const orders = useScoutOrders(campaignId);
  const products = useMemo(() => catalog.data?.unitCampaignCatalog?.products ?? [], [catalog.data]);
  const names = useMemo<ProductNames>(
    () => new Map(products.map((product) => [product.productId, product.productName])),
    [products],
  );
  const writes = useFulfillmentWrites(orders.reload);
  const [pending, setPending] = useState<PendingAction | null>(null);

  return (
    <Box sx={{ pt: 2 }}>
      <Alert severity="info" sx={{ mb: 2 }} data-testid="fulfillment-note">
        {ORDER_NOTE}
      </Alert>
      <CampaignPicker
        campaigns={campaigns}
        campaignId={campaignId}
        onChange={setCampaignId}
        onAskSale={() => setPending({ kind: 'sale' })}
      />
      <OrdersArea campaignId={campaignId} state={orders} names={names} onAsk={setPending} />
      <PendingDialog
        pending={pending}
        campaign={campaignOf(campaigns, campaignId)}
        products={products}
        names={names}
        writes={writes}
        onClose={() => setPending(null)}
      />
    </Box>
  );
};

const CampaignPicker: React.FC<{
  campaigns: readonly ScoutCampaign[];
  campaignId: string;
  onChange: (campaignId: string) => void;
  onAskSale: () => void;
}> = ({ campaigns, campaignId, onChange, onAskSale }) => (
  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }} alignItems="flex-end">
    <TextField
      select
      label="Scout"
      value={campaignId}
      onChange={(event) => onChange(event.target.value)}
      helperText="A Scout Campaign joined to this Unit Campaign."
      data-testid="fulfillment-campaign"
    >
      {campaigns.map((campaign) => (
        <MenuItem key={campaign.campaignId} value={campaign.campaignId}>
          {`${campaign.profileId} · ${campaign.campaignId}`}
        </MenuItem>
      ))}
    </TextField>
    <Button variant="contained" onClick={onAskSale} disabled={!campaignId} data-testid="record-custody-sale">
      Record a door-to-door sale
    </Button>
    {campaigns.length === 0 ? (
      <Typography variant="body2" color="text.secondary" data-testid="no-campaign-note">
        No Scout Campaign is joined to this Unit Campaign, so there are no individual Orders to fulfill.
      </Typography>
    ) : null}
  </Stack>
);

/** The read state of the Order list, stated as the fact it is: loading, failed, or empty. */
const OrdersArea: React.FC<{
  campaignId: string;
  state: { orders: readonly GqlUnitOrderFieldsFragment[]; loading: boolean; failed: boolean };
  names: ProductNames;
  onAsk: (action: PendingAction) => void;
}> = ({ campaignId, state, names, onAsk }) => {
  if (state.loading) return <LoadingState minHeight="200px" />;
  if (state.failed) return <ErrorAlert message="Could not load this Scout's individual Orders." />;
  if (!campaignId) {
    return (
      <Typography variant="body2" color="text.secondary" data-testid="no-order-selected-note">
        Choose a Scout to see the individual Orders and what each line still owes.
      </Typography>
    );
  }
  return <OrderTable orders={state.orders} names={names} onAsk={onAsk} />;
};

const PendingDialog: React.FC<{
  pending: PendingAction | null;
  campaign: ScoutCampaign;
  products: readonly CatalogProduct[];
  names: ProductNames;
  writes: ReturnType<typeof useFulfillmentWrites>;
  onClose: () => void;
}> = ({ pending, campaign, products, names, writes, onClose }) => {
  if (pending === null) return null;
  if (pending.kind === 'sale')
    return <SaleDialog campaign={campaign} products={products} names={names} writes={writes} onClose={onClose} />;
  if (pending.kind === 'fulfill') {
    return (
      <FulfillDialog
        order={pending.order}
        line={pending.line}
        version={pending.version}
        names={names}
        writes={writes}
        onClose={onClose}
      />
    );
  }
  return <HistoryDialog order={pending.order} names={names} writes={writes} onClose={onClose} />;
};

function campaignOf(campaigns: readonly ScoutCampaign[], campaignId: string): ScoutCampaign {
  return campaigns.find((campaign) => campaign.campaignId === campaignId) as ScoutCampaign;
}

/** What the admin asked to do. */
type PendingAction =
  | { kind: 'sale' }
  | { kind: 'fulfill'; order: GqlUnitOrderFieldsFragment; line: OrderLine; version: number }
  | { kind: 'history'; order: GqlUnitOrderFieldsFragment };

/**
 * The Orders of one Scout Campaign, every page of them.
 *
 * This is the legacy `nextToken` shape rather than the Show & Sell cursor shape, so it
 * is walked by its own token. A panel that stopped at the first page would hide Orders
 * whose lines still owe stock.
 */
function useScoutOrders(campaignId: string) {
  const client = useApolloClient();
  const [state, setState] = useState<{ orders: GqlUnitOrderFieldsFragment[]; loading: boolean; failed: boolean }>({
    orders: [],
    loading: false,
    failed: false,
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!campaignId) {
      setState({ orders: [], loading: false, failed: false });
      return undefined;
    }
    let active = true;
    setState((previous) => ({ orders: previous.orders, loading: true, failed: false }));
    void fetchAllCampaignOrders(client, campaignId)
      .then((orders) => {
        if (active) setState({ orders, loading: false, failed: false });
      })
      .catch(() => {
        if (active) setState({ orders: [], loading: false, failed: true });
      });
    return () => {
      active = false;
    };
  }, [client, campaignId, attempt]);

  return { ...state, reload: () => setAttempt((previous) => previous + 1) };
}

const OrderTable: React.FC<{
  orders: readonly GqlUnitOrderFieldsFragment[];
  names: ProductNames;
  onAsk: (action: PendingAction) => void;
}> = ({ orders, names, onAsk }) => (
  <Card variant="outlined">
    <CardContent>
      <Typography variant="h6" gutterBottom>
        Individual Orders
      </Typography>
      {orders.map((order) => (
        <OrderBlock key={order.orderId} order={order} names={names} onAsk={onAsk} />
      ))}
      {orders.length === 0 ? (
        <Typography color="text.secondary" data-testid="no-orders-note">
          This Scout has no individual Orders in this campaign.
        </Typography>
      ) : null}
    </CardContent>
  </Card>
);

const OrderBlock: React.FC<{
  order: GqlUnitOrderFieldsFragment;
  names: ProductNames;
  onAsk: (action: PendingAction) => void;
}> = ({ order, names, onAsk }) => (
  <Box sx={{ mb: 3 }} data-testid={`order-block-${order.orderId}`}>
    <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
      <Typography variant="subtitle2" data-testid={`order-customer-${order.orderId}`}>
        {`${order.customerName} · ${formatOrderDate(order.orderDate)}`}
      </Typography>
      <Typography variant="body2" color="text.secondary" data-testid={`order-version-${order.orderId}`}>
        {orderVersionLabel(order)}
      </Typography>
      <Button
        size="small"
        variant="text"
        onClick={() => onAsk({ kind: 'history', order })}
        data-testid={`order-history-${order.orderId}`}
      >
        Fulfillment history
      </Button>
    </Stack>
    <Box sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Product</TableCell>
            <TableCell align="right">Ordered</TableCell>
            <TableCell align="right">Fulfilled</TableCell>
            <TableCell align="right">Still owed</TableCell>
            <TableCell align="right">Fulfill</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {order.lineItems.map((line) => (
            <LineRow key={lineIdentity(order, line)} order={order} line={line} names={names} onAsk={onAsk} />
          ))}
        </TableBody>
      </Table>
    </Box>
  </Box>
);

/**
 * A line's React key, and why a pre-Wave-3 line cannot be acted on.
 *
 * Rows written before Wave 3 carry no `lineItemId`, so nothing can name them stably
 * across an edit — the server refuses to fulfill one, and the screen does not offer to.
 */
function lineIdentity(order: GqlUnitOrderFieldsFragment, line: OrderLine): string {
  return line.lineItemId ?? `${order.orderId}#${line.productId}`;
}

const LineRow: React.FC<{
  order: GqlUnitOrderFieldsFragment;
  line: OrderLine;
  names: ProductNames;
  onAsk: (action: PendingAction) => void;
}> = ({ order, line, names, onAsk }) => {
  const owed = unfulfilledQuantity(line.quantity, line.fulfilledQuantity);
  const version = fulfillmentVersionOf(order);
  const id = lineIdentity(order, line);
  return (
    <TableRow data-testid={`line-row-${id}`}>
      <TableCell>{productLabel(names, line.productId)}</TableCell>
      <TableCell align="right">{line.quantity}</TableCell>
      <TableCell align="right" data-testid={`line-fulfilled-${id}`}>
        {line.fulfilledQuantity ?? 0}
      </TableCell>
      <TableCell align="right" data-testid={`line-owed-${id}`}>
        {owed}
      </TableCell>
      <TableCell align="right">
        {line.lineItemId && owed > 0 && version !== null ? (
          <Button
            size="small"
            variant="outlined"
            onClick={() => onAsk({ kind: 'fulfill', order, line, version })}
            data-testid={`fulfill-${order.orderId}-${line.lineItemId}`}
          >
            Fulfill
          </Button>
        ) : (
          <Typography variant="body2" color="text.secondary" data-testid={`no-fulfill-${id}`}>
            {noFulfillLabel(line, version)}
          </Typography>
        )}
      </TableCell>
    </TableRow>
  );
};

/** Why a line has no Fulfill button, in the words an admin can act on. */
function noFulfillLabel(line: OrderLine, version: number | null): string {
  if (!line.lineItemId) return 'Written before stable line ids, so nothing can name it';
  if (version === null) return 'This Order carries no fulfillment version';
  return 'Nothing owed';
}

/**
 * The version a fulfillment write against this Order has to carry.
 *
 * A pre-Wave-3 row has none, and the admin needs to know that before wondering why
 * the lines have no Fulfill button — printing `v` with no number after it would say
 * nothing either way.
 */
function orderVersionLabel(order: GqlUnitOrderFieldsFragment): string {
  const version = fulfillmentVersionOf(order);
  return version === null ? 'no fulfillment version yet' : `fulfillment record v${version}`;
}

/** The Order's own date, as the Order recorded it. */
function formatOrderDate(orderDate: string): string {
  const parsed = new Date(orderDate);
  return Number.isNaN(parsed.getTime()) ? orderDate : parsed.toLocaleDateString();
}

/** The three Order writes, each followed by the Order read it changed. */
function useFulfillmentWrites(refreshOrders: () => unknown) {
  const [createSale] = useMutation(RECORD_CUSTODY_SALE);
  const [fulfillLine] = useMutation(FULFILL_INDIVIDUAL_ORDER_LINE);
  const [reverseFulfillment] = useMutation(REVERSE_INDIVIDUAL_ORDER_FULFILLMENT);
  const intent = useRef(createWriteIntent()).current;

  const send = async (mutation: typeof createSale, body: Record<string, unknown>, fallback: string) => {
    try {
      // `createOrder` carries its key flat on the input, not in an IdempotencyInput:
      // it is the existing Order API, and Wave 3 only requires the key when the write
      // moves stock.
      const isSale = body.fulfillmentMode !== undefined;
      const input = isSale
        ? { ...body, idempotencyKey: intent.keyFor(body) }
        : { ...body, idempotency: { idempotencyKey: intent.keyFor(body) } };
      await mutation({ variables: { input } });
    } catch (failure) {
      // A stale `expectedFulfillmentVersion` is fixed by reading the Order again, so a
      // refusal reloads rather than leaving the button armed with the same stale body.
      await refreshQuietly(refreshOrders);
      throw new Error(describeInventoryFailure(failure, fallback), { cause: failure });
    }
    await refreshQuietly(refreshOrders);
  };

  return {
    sale: (campaign: ScoutCampaign, orderDraft: SaleDraft) =>
      send(
        createSale,
        {
          profileId: campaign.profileId,
          campaignId: campaign.campaignId,
          customerName: orderDraft.customerName,
          orderDate: orderDraft.orderDate,
          paymentMethod: orderDraft.paymentMethod,
          lineItems: orderDraft.lineItems,
          fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
        },
        'The sale could not be recorded.',
      ),
    fulfill: (
      order: GqlUnitOrderFieldsFragment,
      line: OrderLine,
      version: number,
      quantity: number,
      source: GqlOrderFulfillmentSource,
    ) =>
      send(
        fulfillLine,
        {
          orderId: order.orderId,
          lineItemId: line.lineItemId as string,
          quantity,
          source,
          expectedFulfillmentVersion: version,
        },
        'The line could not be fulfilled.',
      ),
    reverse: (order: GqlUnitOrderFieldsFragment, fulfillmentId: string, version: number) =>
      send(
        reverseFulfillment,
        { orderId: order.orderId, fulfillmentId, expectedFulfillmentVersion: version },
        'The fulfillment could not be reversed.',
      ),
  };
}

async function refreshQuietly(refresh: () => unknown): Promise<void> {
  try {
    await refresh();
  } catch {
    // The read's own error state carries this; the write already happened.
  }
}

interface SaleDraft {
  customerName: string;
  orderDate: string;
  paymentMethod: string;
  lineItems: { productId: string; quantity: number }[];
}

interface SaleFormState {
  customerName: string;
  orderDate: string;
  paymentMethod: string;
  productId: string;
  quantity: string;
  lineItems: { productId: string; quantity: number }[];
  fieldError: string | null;
}

/**
 * The door-to-door sale: an individual Order marked `CONSUME_SCOUT_CUSTODY`.
 *
 * The screen adds no custody sufficiency rule of its own — the sale is valid whatever
 * the Scout is holding, and the shortfall is what the fulfillment rows below then
 * cover. What it does insist on is a customer, a date, a payment method, and at least
 * one line with a whole positive quantity, because those are the parts of the Order
 * the server cannot invent.
 */
const SaleDialog: React.FC<{
  campaign: ScoutCampaign;
  products: readonly CatalogProduct[];
  names: ProductNames;
  writes: ReturnType<typeof useFulfillmentWrites>;
  onClose: () => void;
}> = ({ campaign, products, names, writes, onClose }) => {
  const [state, setState] = useState<SaleFormState>({
    customerName: '',
    orderDate: new Date().toISOString().slice(0, 10),
    paymentMethod: '',
    productId: '',
    quantity: '',
    lineItems: [],
    fieldError: null,
  });

  const addLine = () => {
    const quantity = parseQuantity(state.quantity);
    if (!state.productId || !quantity.value || quantity.error) {
      setState({ ...state, fieldError: quantity.error ?? 'Choose a product to add.' });
      return;
    }
    setState({
      ...state,
      productId: '',
      quantity: '',
      fieldError: null,
      lineItems: [...state.lineItems, { productId: state.productId, quantity: quantity.value }],
    });
  };

  const submit = async () => {
    const error = saleError(state);
    if (error) {
      setState({ ...state, fieldError: error });
      throw new Error(error);
    }
    await writes.sale(campaign, {
      customerName: state.customerName.trim(),
      orderDate: new Date(`${state.orderDate}T00:00:00Z`).toISOString(),
      paymentMethod: state.paymentMethod.trim(),
      lineItems: state.lineItems,
    });
    onClose();
  };

  return (
    <FormDialog
      title="Record a door-to-door sale"
      confirmLabel="Record sale"
      onCancel={onClose}
      onConfirm={submit}
      error={state.fieldError}
    >
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary" data-testid="sale-mode-note">
          {`${ORDER_NOTE} This sale is recorded as consuming ${campaign.profileId}'s held stock first.`}
        </Typography>
        <TextField
          label="Customer name"
          value={state.customerName}
          onChange={(event) => setState({ ...state, customerName: event.target.value, fieldError: null })}
          data-testid="sale-customer"
        />
        <TextField
          label="Order date"
          value={state.orderDate}
          onChange={(event) => setState({ ...state, orderDate: event.target.value, fieldError: null })}
          helperText="YYYY-MM-DD"
          data-testid="sale-date"
        />
        <TextField
          label="Payment method"
          value={state.paymentMethod}
          onChange={(event) => setState({ ...state, paymentMethod: event.target.value, fieldError: null })}
          data-testid="sale-payment"
        />
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems="flex-end">
          <TextField
            select
            label="Product"
            value={state.productId}
            onChange={(event) => setState({ ...state, productId: event.target.value, fieldError: null })}
            data-testid="sale-product"
          >
            {products.map((product) => (
              <MenuItem key={product.productId} value={product.productId}>
                {productLabel(names, product.productId)}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Quantity"
            value={state.quantity}
            onChange={(event) => setState({ ...state, quantity: event.target.value, fieldError: null })}
            inputMode="numeric"
            data-testid="sale-quantity"
          />
          <Button variant="outlined" onClick={addLine} data-testid="sale-add-line">
            Add line
          </Button>
        </Stack>
        <Box data-testid="sale-lines">
          {state.lineItems.map((line, index) => (
            <Typography key={`${line.productId}#${index}`} variant="body2" data-testid={`sale-line-${line.productId}`}>
              {`${productLabel(names, line.productId)}: ${line.quantity}`}
            </Typography>
          ))}
        </Box>
      </Stack>
    </FormDialog>
  );
};

/** Who the sale was to, and how it was paid for: the Order cannot be written without it. */
function saleHeaderError(state: SaleFormState): string | null {
  if (!state.customerName.trim()) return 'Enter the customer name.';
  if (!state.paymentMethod.trim()) return 'Enter how the customer paid.';
  return null;
}

/** The Order's own moment, and the lines it is made of. */
function saleDraftError(state: SaleFormState): string | null {
  if (!state.orderDate.trim()) return 'Enter the order date.';
  if (Number.isNaN(new Date(`${state.orderDate}T00:00:00Z`).getTime())) return 'Enter the order date as YYYY-MM-DD.';
  if (state.lineItems.length === 0) return 'Add at least one product line.';
  return null;
}

function saleError(state: SaleFormState): string | null {
  return saleHeaderError(state) ?? saleDraftError(state);
}

/**
 * Filling one line: Kernel stock or a direct Council supply.
 *
 * `SCOUT_CUSTODY` is not offered — that source is consumed by the sale itself, and the
 * server refuses it here. The quantity cannot exceed what the line owes, and the write
 * carries the `fulfillmentVersion` this screen read, so two admins looking at the same
 * Order cannot both fill the same last Kernel.
 */
const FulfillDialog: React.FC<{
  order: GqlUnitOrderFieldsFragment;
  line: OrderLine;
  version: number;
  names: ProductNames;
  writes: ReturnType<typeof useFulfillmentWrites>;
  onClose: () => void;
}> = ({ order, line, version, names, writes, onClose }) => {
  const owed = unfulfilledQuantity(line.quantity, line.fulfilledQuantity);
  const [state, setState] = useState({
    quantity: '',
    source: 'KERNEL_STOCK' as GqlOrderFulfillmentSource,
    fieldError: null as string | null,
  });

  const submit = async () => {
    const quantity = parseQuantity(state.quantity);
    if (quantity.error) {
      setState({ ...state, fieldError: quantity.error });
      throw new Error(quantity.error);
    }
    if ((quantity.value as number) > owed) {
      const message = `Only ${owed} ${owed === 1 ? 'Kernel is' : 'Kernels are'} left to fulfill on this line.`;
      setState({ ...state, fieldError: message });
      throw new Error(message);
    }
    await writes.fulfill(order, line, version, quantity.value as number, state.source);
    onClose();
  };

  return (
    <FormDialog
      title={`Fulfill ${productLabel(names, line.productId)}`}
      confirmLabel="Fulfill line"
      onCancel={onClose}
      onConfirm={submit}
      error={state.fieldError}
    >
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary" data-testid="fulfill-owed-note">
          {`${owed} of ${line.quantity} still owed on this line.`}
        </Typography>
        <TextField
          label="Quantity to fulfill"
          value={state.quantity}
          onChange={(event) => setState({ ...state, quantity: event.target.value, fieldError: null })}
          inputMode="numeric"
          helperText={`At most ${owed} whole Kernels.`}
          data-testid="fulfill-quantity"
        />
        <TextField
          select
          label="Stock source"
          value={state.source}
          onChange={(event) =>
            setState({ ...state, source: event.target.value as GqlOrderFulfillmentSource, fieldError: null })
          }
          data-testid="fulfill-source"
        >
          <MenuItem value="KERNEL_STOCK">{fulfillmentSourceLabel('KERNEL_STOCK')}</MenuItem>
          <MenuItem value="EXTERNAL_COUNCIL">{fulfillmentSourceLabel('EXTERNAL_COUNCIL')}</MenuItem>
        </TextField>
        <Typography variant="body2" color="text.secondary" data-testid="fulfill-source-note">
          {state.source === 'EXTERNAL_COUNCIL'
            ? 'A direct Council supply leaves Kernel stock where it is and records no balance movement.'
            : 'Kernel stock moves out of unassigned stock for this line.'}
        </Typography>
      </Stack>
    </FormDialog>
  );
};

/**
 * Who did it, which movement did it, and what the Scout is allowed to see.
 *
 * The admin rows name the actor account and the inventory movement id behind each
 * record. The participant rows come from a different document that asks for neither,
 * and the toggle is this screen's own proof of that split.
 */
const HistoryDialog: React.FC<{
  order: GqlUnitOrderFieldsFragment;
  names: ProductNames;
  writes: ReturnType<typeof useFulfillmentWrites>;
  onClose: () => void;
}> = ({ order, names, writes, onClose }) => {
  const admin = useQuery<GqlGetOrderFulfillmentsQuery>(GET_ORDER_FULFILLMENTS, {
    variables: { orderId: order.orderId, page: page() },
  });
  const completeAdmin = useCompleteConnection<GqlOrderFulfillmentFieldsFragment>(admin.data?.orderFulfillments, {
    query: GET_ORDER_FULFILLMENTS,
    field: 'orderFulfillments',
    limit: page().limit as number,
    variables: { orderId: order.orderId },
  });
  const [pendingReversal, setPendingReversal] = useState<string | null>(null);
  const records = completeAdmin.items;
  const reversed = useMemo(() => reversedFulfillmentIds(records), [records]);
  const reversing = records.find((record) => record.fulfillmentId === pendingReversal);
  const version = fulfillmentVersionOf(order);

  return (
    <FormDialog title="Fulfillment history" confirmLabel="Done" onCancel={onClose} onConfirm={onClose}>
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary" data-testid="audit-note">
          Every record names the admin account that wrote it and the inventory movement it belongs to. Nothing here is
          edited: a correction is a reversal, and a reversal restores only what its own record took.
        </Typography>
        <QueryGate
          query={admin}
          loading={<LoadingState minHeight="120px" />}
          failure={<ErrorAlert message="Could not load this Order's fulfillment history." />}
        >
          <AdminRecords
            records={records}
            names={names}
            reversed={reversed}
            version={version}
            onAskReverse={setPendingReversal}
          />
        </QueryGate>
        <ParticipantBlock order={order} names={names} />
        {reversing ? (
          <ConfirmDialog
            open
            title="Reverse this fulfillment"
            confirmLabel="Reverse"
            confirmColor="warning"
            onClose={() => setPendingReversal(null)}
            onConfirm={async () => {
              await writes.reverse(order, reversing.fulfillmentId, version as number);
              // The reversal is a new record in the same history the admin is
              // looking at, and the Orders reload below it does not touch this
              // query — without this the button would appear to have done nothing.
              await admin.refetch();
            }}
          >
            <Typography variant="body2" data-testid="reversal-copy">
              {`Reversing returns ${reversing.quantity} ${reversing.quantity === 1 ? 'Kernel' : 'Kernels'} to ${fulfillmentSourceLabel(reversing.source)}. The fulfillment stays in the history; the reversal is a new record linked to it.`}
            </Typography>
          </ConfirmDialog>
        ) : null}
      </Stack>
    </FormDialog>
  );
};

interface ParticipantState {
  rows: readonly GqlParticipantOrderFulfillmentFieldsFragment[];
  loading: boolean;
  failed: boolean;
  asked: boolean;
}

/**
 * The Scout's own view of the same history.
 *
 * This is the half of the privacy rule the screen can prove: it asks for the
 * participant document, which carries no actor account and no inventory movement id,
 * so the audit fields cannot reach this table even by accident.
 */
const ParticipantBlock: React.FC<{ order: GqlUnitOrderFieldsFragment; names: ProductNames }> = ({ order, names }) => {
  const client = useApolloClient();
  const [state, setState] = useState<ParticipantState>({ rows: [], loading: false, failed: false, asked: false });

  const show = async () => {
    setState({ rows: [], loading: true, failed: false, asked: true });
    try {
      setState({
        rows: await fetchParticipantFulfillments(client, order.orderId),
        loading: false,
        failed: false,
        asked: true,
      });
    } catch {
      setState({ rows: [], loading: false, failed: true, asked: true });
    }
  };

  if (!state.asked) {
    return (
      <Button variant="text" onClick={() => void show()} data-testid="participant-view-toggle">
        What the Scout sees
      </Button>
    );
  }
  if (state.loading) return <LoadingState minHeight="80px" />;
  if (state.failed) return <ErrorNote message="The Scout's own view of these records could not be loaded." />;
  return (
    <Box data-testid="participant-view">
      <Typography variant="body2" color="text.secondary" data-testid="participant-note">
        This is the participant projection: the same records without the admin account or the inventory movement behind
        them.
      </Typography>
      {state.rows.map((record) => (
        <Typography key={record.fulfillmentId} variant="body2" data-testid={`participant-row-${record.fulfillmentId}`}>
          {participantRowLabel(names, record)}
        </Typography>
      ))}
      {state.rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary" data-testid="no-participant-fulfillments-note">
          No records to show the Scout.
        </Typography>
      ) : null}
    </Box>
  );
};

/** One participant row: what moved, how much, and from which source. Nothing else. */
function participantRowLabel(names: ProductNames, record: GqlParticipantOrderFulfillmentFieldsFragment): string {
  const kind = record.recordType === 'REVERSAL' ? 'Reversal' : 'Fulfilled';
  return `${kind} · ${productLabel(names, record.productId)} · ${record.quantity} · ${fulfillmentSourceLabel(record.source)}`;
}

/**
 * Why a record has no Reverse button.
 *
 * At most one reversal may exist per fulfillment, so a FULFILL record whose reversal is
 * already in the history is spent; a REVERSAL record is never reversible; and an Order
 * with no `fulfillmentVersion` cannot be written against at all.
 */
function reversalLabel(record: Pick<GqlOrderFulfillmentFieldsFragment, 'recordType'>, version: number | null): string {
  if (record.recordType === 'REVERSAL') return 'Reversal record';
  if (version === null) return 'This Order carries no fulfillment version';
  return 'Already reversed';
}

/** The audit rows, or the words that say nothing has been fulfilled yet. */
const AdminRecords: React.FC<{
  records: readonly GqlOrderFulfillmentFieldsFragment[];
  names: ProductNames;
  reversed: ReadonlySet<string>;
  version: number | null;
  onAskReverse: (fulfillmentId: string) => void;
}> = ({ records, names, reversed, version, onAskReverse }) => (
  <Box>
    {isCustodySale(records) ? (
      <Typography variant="body2" color="text.secondary" data-testid="custody-sale-note">
        This Order drew on the Scout's held stock first.
      </Typography>
    ) : null}
    {records.map((record) => (
      <HistoryRow
        key={record.fulfillmentId}
        record={record}
        names={names}
        reversible={canReverse(record, reversed) && version !== null}
        stateLabel={reversalLabel(record, version)}
        onAskReverse={onAskReverse}
      />
    ))}
    {records.length === 0 ? (
      <Typography variant="body2" color="text.secondary" data-testid="no-fulfillments-note">
        Nothing has been fulfilled on this Order yet.
      </Typography>
    ) : null}
  </Box>
);

const HistoryRow: React.FC<{
  record: GqlOrderFulfillmentFieldsFragment;
  names: ProductNames;
  reversible: boolean;
  stateLabel: string;
  onAskReverse: (fulfillmentId: string) => void;
}> = ({ record, names, reversible, stateLabel, onAskReverse }) => (
  <Stack
    direction={{ xs: 'column', sm: 'row' }}
    spacing={2}
    alignItems={{ xs: 'flex-start', sm: 'center' }}
    data-testid={`fulfillment-row-${record.fulfillmentId}`}
  >
    <Typography variant="body2" data-testid={`fulfillment-type-${record.fulfillmentId}`}>
      {record.recordType === 'REVERSAL' ? 'Reversal' : 'Fulfilled'}
    </Typography>
    <Typography variant="body2">{`${productLabel(names, record.productId)} · ${record.quantity}`}</Typography>
    <Typography variant="body2" data-testid={`fulfillment-source-${record.fulfillmentId}`}>
      {`${fulfillmentSourceLabel(record.source)} · ${fulfillmentStockNote(record)}`}
    </Typography>
    <Typography variant="body2" color="text.secondary" data-testid={`fulfillment-actor-${record.fulfillmentId}`}>
      {`${record.actorAccountId}${record.inventoryMovementId ? ` · ${record.inventoryMovementId}` : ' · no movement'}`}
    </Typography>
    <Box>
      {reversible ? (
        <Button
          size="small"
          variant="outlined"
          color="warning"
          onClick={() => onAskReverse(record.fulfillmentId)}
          data-testid={`reverse-${record.fulfillmentId}`}
        >
          Reverse
        </Button>
      ) : (
        <Typography variant="body2" color="text.secondary" data-testid={`reversal-state-${record.fulfillmentId}`}>
          {stateLabel}
        </Typography>
      )}
    </Box>
  </Stack>
);
