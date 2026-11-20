/**
 * The allocation editor: how many Kernels this event holds, per product
 * (Show & Sell §3.5.2, built on §3.2.1-§3.2.3).
 *
 * The field is a **target**, never a delta: the admin says how many the event
 * should hold and the resolver works out what that changes. Three consequences
 * of that contract decide this screen:
 *
 * - A product left blank is left alone. The batch omits it, so an event that
 *   already holds six of something keeps six.
 * - A target of zero is a real answer: it releases the remainder this event still
 *   holds. It is sent as zero, not omitted, because omitting would keep it.
 * - What the event already sold is never taken back, so the row shows sold and
 *   remaining next to the target rather than pretending the target is stock.
 *
 * Over-assignment across events that never overlap is a **warning**, not a
 * refusal, and it is never clamped here: a campaign may legitimately hold a
 * morning and an afternoon event against the same four Kernels (ALLOC-03). The
 * server's sentence is what the help text shows, and the help is a real focusable
 * control, because a tooltip that only appears on hover is unreadable by keyboard
 * and by touch.
 */

import React, { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import {
  ASSIGN_SHOW_AND_SELL_INVENTORY,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_EVENT_INVENTORY_ALLOCATIONS,
} from '../../lib/graphql';
import {
  SHOW_AND_SELL_PAGE_SIZE,
  acceptsAllocationEdits,
  allocationTargets,
  describeShowAndSellFailure,
  hasAllocationChanges,
  openAllocationsByProduct,
  overageWarnings,
  productQuantityOf,
  warningSentence,
} from '../../lib/showSell';
import { createWriteIntent, refreshQuery } from '../../lib/units';
import { ConnectionRestNotice } from '../ConnectionRestNotice';
import { ErrorAlert, ErrorNote } from '../ErrorAlert';
import { LoadingState } from '../LoadingState';
import { QueryGate } from '../QueryGate';
import { useCompleteConnection } from '../../hooks/useCompleteConnection';
import type {
  GqlAllocationWarning,
  GqlAssignShowAndSellInventoryMutation,
  GqlGetUnitCampaignCatalogQuery,
  GqlListEventInventoryAllocationsQuery,
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellAllocationFieldsFragment,
  GqlShowAndSellStatus,
} from '../../types/graphql-generated';

type Event = GqlShowAndSellAdminFieldsFragment;
type Allocation = GqlShowAndSellAllocationFieldsFragment;
type CatalogProduct = NonNullable<GqlGetUnitCampaignCatalogQuery['unitCampaignCatalog']>['products'][number];

const ALLOCATION_VARIABLES = (unitCampaignId: string) => ({
  unitCampaignId,
  productId: undefined,
  showAndSellId: undefined,
  status: undefined,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
});

export const AllocationEditor: React.FC<{
  event: Event;
  onChanged: () => Promise<unknown>;
}> = ({ event, onChanged }) => {
  const catalog = useQuery<GqlGetUnitCampaignCatalogQuery>(GET_UNIT_CAMPAIGN_CATALOG, {
    variables: { unitCampaignId: event.unitCampaignId },
  });
  const allocations = useQuery<GqlListEventInventoryAllocationsQuery>(LIST_EVENT_INVENTORY_ALLOCATIONS, {
    variables: ALLOCATION_VARIABLES(event.unitCampaignId),
  });
  const campaignAllocations = useCompleteConnection<Allocation>(allocations.data?.eventInventoryAllocations, {
    query: LIST_EVENT_INVENTORY_ALLOCATIONS,
    field: 'eventInventoryAllocations',
    limit: SHOW_AND_SELL_PAGE_SIZE,
    variables: ALLOCATION_VARIABLES(event.unitCampaignId),
  });

  const products = useMemo(() => productsOf(catalog.data), [catalog.data]);
  // Every product the event has ever held is shown even if the catalog no longer
  // lists it: an allocation row that the editor cannot see is a reservation the
  // admin cannot release.
  const rows = useMemo(
    () => [
      ...products.map((product) => ({ productId: product.productId, name: product.productName })),
      ...event.productIds
        .filter((productId) => !products.some((product) => product.productId === productId))
        .map((productId) => ({ productId, name: productId })),
    ],
    [products, event.productIds],
  );
  const held = useMemo(() => openAllocationsByProduct(event.allocations), [event.allocations]);
  const assignedEverywhere = useMemo(
    () => productQuantityOf(campaignAllocations.items),
    [campaignAllocations.items],
  );

  const [drafts, setDrafts] = useState<Map<string, string>>(new Map());
  const [warnings, setWarnings] = useState<GqlAllocationWarning[]>([]);
  const [error, setError] = useState<string | null>(null);
  const intent = React.useRef(createWriteIntent());
  const [assignInventory, { loading }] = useMutation<GqlAssignShowAndSellInventoryMutation>(
    ASSIGN_SHOW_AND_SELL_INVENTORY,
  );

  const editable = acceptsAllocationEdits(event.status);
  const valueOf = (productId: string): string =>
    drafts.get(productId) ?? String(held.get(productId)?.allocatedQty ?? '');

  const save = async () => {
    const merged = mergeDrafts(rows, held, drafts);
    const items = allocationTargets(held, merged);
    try {
      const result = await assignInventory({
        variables: {
          input: {
            showAndSellId: event.showAndSellId,
            items,
            version: { expectedVersion: event.version },
            idempotency: { idempotencyKey: intent.current.keyFor(items) },
          },
        },
      });
      setWarnings(overageWarnings(result.data?.assignShowAndSellInventory?.warnings));
      setDrafts(new Map());
    } catch (mutationError) {
      setError(describeShowAndSellFailure(mutationError, 'Could not save the stock assigned to this event.'));
    }
    await refreshQuery(onChanged);
  };

  const dirty = hasAllocationChanges(held, mergeDrafts(rows, held, drafts));
  const lines = useMemo(() => rows.map((row) => allocationLine(row, held, assignedEverywhere)), [rows, held, assignedEverywhere]);

  return (
    <Box sx={{ pt: 2 }}>
      <Alert severity="info" sx={{ mb: 2 }} data-testid="allocation-note">
        Enter how many Kernels this event should hold for each product. A product you leave alone keeps what it holds, a
        target of zero releases what it still holds, and what the event has already sold is never taken back. Assigning
        more than the campaign holds at the same moment is refused and writes nothing.
      </Alert>
      <AllocationNotices status={event.status} editable={editable} />
      <OverageWarnings warnings={warnings} />
      <QueryGate
        query={allocations}
        loading={<LoadingState minHeight="200px" />}
        failure={<ErrorAlert message="Could not load this campaign’s allocations." />}
      >
        <Table size="small" aria-label="Stock assigned to this event">
          <TableHead>
            <TableRow>
              <TableCell>Product</TableCell>
              <TableCell>This event holds</TableCell>
              <TableCell>Sold at this event</TableCell>
              <TableCell>Still unsold here</TableCell>
              <TableCell>Assigned across all events</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {lines.map((line) => (
              <AllocationRow
                key={line.productId}
                line={line}
                value={valueOf(line.productId)}
                editable={editable}
                loading={loading}
                onDraft={(productId, value) => setDrafts((current) => new Map(current).set(productId, value))}
              />
            ))}
          </TableBody>
        </Table>
        <ConnectionRestNotice loading={campaignAllocations.loadingRest} failed={campaignAllocations.failedRest} />
      </QueryGate>
      <ErrorNote message={error} />
      <Stack direction="row" spacing={2} sx={{ pt: 2 }} alignItems="center">
        <AllocationSaveButton editable={editable} loading={loading} dirty={dirty} onSave={() => void save()} />
        <Typography variant="body2" color="text.secondary" data-testid="allocation-event-version">
          Saved against event version {event.version}. Physical stock does not move: this reserves stock for the event.
        </Typography>
      </Stack>
    </Box>
  );
};

/** The campaign's catalog products, or nothing while the catalog is still loading. */
function productsOf(data?: GqlGetUnitCampaignCatalogQuery): CatalogProduct[] {
  return data?.unitCampaignCatalog?.products ?? [];
}

/** What the editor cannot do right now, and why. */
const AllocationNotices: React.FC<{ status: GqlShowAndSellStatus; editable: boolean }> = ({ status, editable }) => (
  <>
    {status === 'REOPENED' ? (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="allocation-reopened-note">
        This event is reopened: what you save here is a draft. The campaign’s stock answer belongs to re-finalization,
        which is what decides the real balances.
      </Alert>
    ) : null}
    {editable ? null : (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="allocation-locked-note">
        A finalized or cancelled event cannot change its allocations. Its rows stand as the history they were finalized
        with.
      </Alert>
    )}
  </>
);

const AllocationSaveButton: React.FC<{
  editable: boolean;
  loading: boolean;
  dirty: boolean;
  onSave: () => void;
}> = ({ editable, loading, dirty, onSave }) => (
  <Button
    variant="contained"
    onClick={onSave}
    disabled={!editable || loading || !dirty}
    data-testid="save-allocations"
  >
    {loading ? 'Saving…' : 'Save stock targets'}
  </Button>
);

/**
 * One product's row: what the event holds, what it sold, and the target box.
 *
 * The box starts empty rather than at the held quantity: an empty box means "I am
 * not changing this product", and pre-filling it would turn every save into a
 * rewrite of every row on the screen.
 */
/** One row's numbers, read once so the row itself has nothing to work out. */
interface AllocationLine {
  productId: string;
  name: string;
  sold: number;
  remaining: number;
  assigned: number;
}

function allocationLine(
  row: { productId: string; name: string },
  held: ReadonlyMap<string, Allocation>,
  assignedEverywhere: ReadonlyMap<string, number>,
): AllocationLine {
  const allocation = held.get(row.productId);
  const counts = allocationCounts(allocation);
  return {
    productId: row.productId,
    name: row.name,
    sold: counts.sold,
    remaining: counts.remaining,
    assigned: assignedEverywhere.get(row.productId) ?? 0,
  };
}

/** What one event has sold of a product and what it still holds; zero for a product the event never took. */
function allocationCounts(allocation?: Allocation): { sold: number; remaining: number } {
  return { sold: allocation?.soldQty ?? 0, remaining: allocation?.remainingQty ?? 0 };
}

const AllocationRow: React.FC<{
  line: AllocationLine;
  value: string;
  editable: boolean;
  loading: boolean;
  onDraft: (productId: string, value: string) => void;
}> = ({ line, value, editable, loading, onDraft }) => (
  <TableRow data-testid={`allocation-row-${line.productId}`}>
    <TableCell data-testid={`allocation-name-${line.productId}`}>{line.name}</TableCell>
    <TableCell>
      <TextField
        size="small"
        inputMode="numeric"
        value={value}
        onChange={(input) => onDraft(line.productId, input.target.value)}
        disabled={!editable || loading}
        inputProps={{
          'data-testid': `allocation-target-${line.productId}`,
          'aria-label': `Kernels this event should hold for ${line.name}`,
        }}
        sx={{ width: 110 }}
      />
    </TableCell>
    <TableCell data-testid={`allocation-sold-${line.productId}`}>{line.sold}</TableCell>
    <TableCell data-testid={`allocation-remaining-${line.productId}`}>{line.remaining}</TableCell>
    <TableCell data-testid={`allocation-assigned-${line.productId}`}>{line.assigned}</TableCell>
  </TableRow>
);

/**
 * The drafts the editor holds, filled in with what the event already holds.
 *
 * A blank field is not an instruction to release — it is the admin not touching
 * that product — so the unedited value is what goes into the comparison, and
 * `allocationTargets` then omits the unchanged rows.
 */
function mergeDrafts(
  rows: readonly { productId: string }[],
  held: ReadonlyMap<string, Allocation>,
  drafts: ReadonlyMap<string, string>,
): Map<string, string> {
  const merged = new Map<string, string>();
  for (const row of rows) {
    merged.set(row.productId, drafts.get(row.productId) ?? String(held.get(row.productId)?.allocatedQty ?? ''));
  }
  return merged;
}

/**
 * The over-assignment warnings from the last save.
 *
 * Each one names the product, the stock, the assigned total, and the overage — the
 * four numbers an admin needs to decide which event gives stock back. The sentence
 * is reachable two ways: as a focusable help button for keyboard and screen-reader
 * users, and as the same text in an alert for a user who never hovers anything.
 */
const OverageWarnings: React.FC<{ warnings: GqlAllocationWarning[] }> = ({ warnings }) => {
  if (warnings.length === 0) return null;
  return (
    <Card variant="outlined" sx={{ mb: 2 }} data-testid="overage-warnings">
      <CardContent>
        <Typography variant="subtitle1" gutterBottom>
          Saved, with a warning
        </Typography>
        <Typography color="text.secondary" gutterBottom>
          This campaign’s open allocations promise more than it holds for {warnings.length}{' '}
          {warnings.length === 1 ? 'product' : 'products'}. Nothing was clamped, and the write stands: a campaign may hold
          events at different times against the same stock.
        </Typography>
        <Stack spacing={1}>
          {warnings.map((warning) => (
            <Stack
              key={warning.productId}
              direction="row"
              spacing={1}
              alignItems="center"
              data-testid={`overage-warning-${warning.productId}`}
            >
              <Typography data-testid={`overage-sentence-${warning.productId}`}>{warningSentence(warning)}</Typography>
              <Tooltip title={warningSentence(warning)} describeChild>
                <IconButton
                  size="small"
                  aria-label={`Why this product is over-assigned: ${warning.productId}`}
                  data-testid={`overage-help-${warning.productId}`}
                >
                  <HelpOutlineIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
};
