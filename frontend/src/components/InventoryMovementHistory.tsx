/**
 * The inventory movement audit trail, with the filters the server answers
 * (Show & Sell §2.6.1, spec §5.8, `INV-Q-02`, `PAGE-01`).
 *
 * A movement is append-only: nothing here edits or deletes a row, and a
 * correction is a new movement linked to the one it fixes. So the screen's job is
 * to make the trail readable — which quantity moved, by whom, at what business
 * moment, and why — and to let an admin narrow it to one product, one movement
 * type, one Scout, or one window of time.
 *
 * The filters are applied on request rather than on every keystroke. A cursor is
 * bound to the filter set that issued it (the server refuses a cursor from a
 * different request), so a filter that changed mid-drain would strand the walk
 * halfway through a list, and a list the screen knows is short must not be
 * presented as complete.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useQuery } from '@apollo/client/react';
import {
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
import { GET_INVENTORY_MOVEMENTS } from '../lib/graphql';
import {
  MOVEMENT_TYPE_LABELS,
  describeInventoryFailure,
  movementDeltas,
  movementTypeLabel,
  page,
  parseDateRange,
  productLabel,
} from '../lib/inventory';
import { ConnectionRestNotice } from './ConnectionRestNotice';
import { ErrorNote } from './ErrorAlert';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import type {
  GqlGetInventoryMovementsQuery,
  GqlInventoryMovementFieldsFragment,
  GqlInventoryMovementType,
} from '../types/graphql-generated';

type CatalogProduct = { productId: string; productName: string };

/** The filter form and the filter set the current request actually carries. */
interface MovementFilters {
  productId: string;
  movementType: string;
  profileId: string;
  from: string;
  to: string;
}

const EMPTY_FILTERS: MovementFilters = { productId: '', movementType: '', profileId: '', from: '', to: '' };

const MOVEMENT_TYPES = Object.keys(MOVEMENT_TYPE_LABELS) as GqlInventoryMovementType[];

/** The query variables the applied filters name — absent, not null, when unset. */
function filterVariables(unitCampaignId: string, filters: MovementFilters) {
  const dateRange = parseDateRange(filters.from, filters.to).dateRange;
  return {
    unitCampaignId,
    productId: filters.productId || undefined,
    movementType: (filters.movementType || undefined) as GqlInventoryMovementType | undefined,
    profileId: filters.profileId || undefined,
    dateRange,
    page: page(),
  };
}

export const InventoryMovementHistory: React.FC<{
  unitCampaignId: string;
  products: readonly CatalogProduct[];
  /** Bumped by the screen whenever it records a movement, so the trail re-reads. */
  refreshToken: number;
}> = ({ unitCampaignId, products, refreshToken }) => {
  const [draft, setDraft] = useState<MovementFilters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<MovementFilters>(EMPTY_FILTERS);
  const [filterError, setFilterError] = useState<string | null>(null);

  const variables = filterVariables(unitCampaignId, applied);
  const movements = useQuery<GqlGetInventoryMovementsQuery>(GET_INVENTORY_MOVEMENTS, { variables });
  useTrailRefresh(movements, refreshToken);
  const complete = useCompleteConnection<GqlInventoryMovementFieldsFragment>(movements.data?.inventoryMovements, {
    query: GET_INVENTORY_MOVEMENTS,
    field: 'inventoryMovements',
    limit: page().limit as number,
    variables,
  });
  const rows = complete.items;
  const names = new Map(products.map((product) => [product.productId, product.productName]));

  const apply = () => {
    const range = parseDateRange(draft.from, draft.to);
    if (range.error) {
      setFilterError(range.error);
      return;
    }
    setFilterError(null);
    setApplied(draft);
  };

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Movement history
        </Typography>
        <FilterRow draft={draft} products={products} error={filterError} onChange={setDraft} onApply={apply} />
        <QueryGate
          query={movements}
          loading={<LoadingState minHeight="200px" />}
          failure={
            <ErrorNote message={describeInventoryFailure(movements.error, 'Could not load the movement history.')} />
          }
        >
          <MovementTable rows={rows} names={names} />
          <ConnectionRestNotice loading={complete.loadingRest} failed={complete.failedRest} />
        </QueryGate>
      </CardContent>
    </Card>
  );
};

/**
 * Re-read the trail when the screen records a movement.
 *
 * The trail's own query answers from the cache, so a receipt written on the stock board
 * above would leave this list at its mount-time answer: the admin would see the same
 * `N movements` with no trace of the one they just made, until changing a filter forced a
 * new request. The token is that force, and nothing else — it re-runs the request the
 * screen already made, with the filters the admin applied still applied, because a cursor
 * belongs to the filter set that issued it. Token 0 is the mount, which the query itself
 * already answers.
 */
function useTrailRefresh(movements: { refetch: () => unknown }, refreshToken: number): void {
  const seen = useRef(0);
  useEffect(() => {
    if (refreshToken === seen.current) return;
    seen.current = refreshToken;
    void movements.refetch();
  }, [movements, refreshToken]);
}

const FilterRow: React.FC<{
  draft: MovementFilters;
  products: readonly CatalogProduct[];
  error: string | null;
  onChange: (filters: MovementFilters) => void;
  onApply: () => void;
}> = ({ draft, products, error, onChange, onApply }) => (
  <Box sx={{ mb: 2 }}>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 1 }} alignItems="flex-end">
      <TextField
        select
        label="Product"
        value={draft.productId}
        onChange={(event) => onChange({ ...draft, productId: event.target.value })}
        size="small"
        data-testid="movement-filter-product"
      >
        <MenuItem value="">Every product</MenuItem>
        {products.map((product) => (
          <MenuItem key={product.productId} value={product.productId}>
            {product.productName}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        select
        label="Movement type"
        value={draft.movementType}
        onChange={(event) => onChange({ ...draft, movementType: event.target.value })}
        size="small"
        data-testid="movement-filter-type"
      >
        <MenuItem value="">Every type</MenuItem>
        {MOVEMENT_TYPES.map((type) => (
          <MenuItem key={type} value={type}>
            {MOVEMENT_TYPE_LABELS[type]}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="Scout"
        value={draft.profileId}
        onChange={(event) => onChange({ ...draft, profileId: event.target.value })}
        size="small"
        helperText="Profile id, for one Scout's custody and sales."
        data-testid="movement-filter-scout"
      />
      <TextField
        label="From"
        value={draft.from}
        onChange={(event) => onChange({ ...draft, from: event.target.value })}
        size="small"
        placeholder="YYYY-MM-DD"
        data-testid="movement-filter-from"
      />
      <TextField
        label="To"
        value={draft.to}
        onChange={(event) => onChange({ ...draft, to: event.target.value })}
        size="small"
        placeholder="YYYY-MM-DD"
        data-testid="movement-filter-to"
      />
      <Button variant="outlined" onClick={onApply} data-testid="movement-filter-apply">
        Apply filters
      </Button>
    </Stack>
    <ErrorNote message={error} />
  </Box>
);

const MovementTable: React.FC<{ rows: GqlInventoryMovementFieldsFragment[]; names: ReadonlyMap<string, string> }> = ({
  rows,
  names,
}) => (
  <Box sx={{ overflowX: 'auto' }}>
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>When</TableCell>
          <TableCell>Product</TableCell>
          <TableCell>Type</TableCell>
          <TableCell>What moved</TableCell>
          <TableCell>Reason</TableCell>
          <TableCell>Scout</TableCell>
          <TableCell>Recorded by</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((movement) => (
          <MovementRow key={movement.movementId} movement={movement} names={names} />
        ))}
        {rows.length === 0 ? <NoMovementsRow /> : null}
      </TableBody>
    </Table>
    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="movement-count">
      {`${rows.length} ${rows.length === 1 ? 'movement' : 'movements'}`}
    </Typography>
  </Box>
);

const MovementRow: React.FC<{ movement: GqlInventoryMovementFieldsFragment; names: ReadonlyMap<string, string> }> = ({
  movement,
  names,
}) => (
  <TableRow data-testid={`movement-row-${movement.movementId}`}>
    <TableCell data-testid={`movement-when-${movement.movementId}`}>{formatMoment(movement.occurredAt)}</TableCell>
    <TableCell>{productLabel(names, movement.productId)}</TableCell>
    <TableCell data-testid={`movement-type-${movement.movementId}`}>
      {movementTypeLabel(movement.movementType)}
    </TableCell>
    <TableCell data-testid={`movement-delta-${movement.movementId}`}>{movementDeltas(movement)}</TableCell>
    <TableCell data-testid={`movement-reason-${movement.movementId}`}>{movement.reason ?? '—'}</TableCell>
    <TableCell>{movement.profileId ?? '—'}</TableCell>
    <TableCell data-testid={`movement-actor-${movement.movementId}`}>{movement.actorAccountId}</TableCell>
  </TableRow>
);

/** The business moment, to the minute: the audit answers to the minute, not the day. */
function formatMoment(occurredAt: string): string {
  const parsed = new Date(occurredAt);
  if (Number.isNaN(parsed.getTime())) return occurredAt;
  return `${parsed.toLocaleDateString()} ${parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

const NoMovementsRow: React.FC = () => (
  <TableRow>
    <TableCell colSpan={7}>
      <Box sx={{ p: 2 }}>
        <Typography color="text.secondary">No movements match these filters.</Typography>
      </Box>
    </TableCell>
  </TableRow>
);
