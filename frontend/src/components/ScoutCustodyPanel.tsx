/**
 * Scout custody: issue stock to a Scout and take a batch back (Show & Sell §2.6.2).
 *
 * Three rules decide what this screen may offer.
 *
 * **Eligibility is the roster, not the button.** Only an ACTIVE member of this Unit
 * Campaign can be issued to, and that is what the roster row answers. It is not an
 * authorization check — the server decides that — but it is the difference between
 * offering a write that can land and offering one that can only be refused. A Scout
 * who was removed still holds whatever they were issued, so the return side is driven
 * by the custody rows, not by the roster: their stock has to come back.
 *
 * **The campaign-wide total is the server's.** `totalWithScoutQty` is computed over
 * the whole filtered set. The per-Scout lines below are added up for presentation
 * only — a locally summed campaign total would change with the page size, which is
 * exactly how a custody number stops matching the audit trail.
 *
 * **A return is one write for the whole batch.** The admin clicks once and every
 * product that Scout holds for this campaign comes back together. The server refuses
 * the whole request when any one line would return more than is held, so nothing
 * moves on a refusal; the dialog says so in those words, because an admin who believes
 * a partial return landed starts counting the same stock twice.
 */

import React, { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
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
  GET_INVENTORY_POSITIONS,
  GET_SCOUT_CUSTODY_BALANCES,
  GET_UNIT_CAMPAIGN_CATALOG,
  ISSUE_STOCK_TO_SCOUT,
  LIST_UNIT_CAMPAIGN_ROSTER,
  RETURN_STOCK_FROM_SCOUT,
} from '../lib/graphql';
import {
  campaignLabel,
  describeInventoryFailure,
  page,
  parseQuantity,
  productLabel,
  scoutLabel,
} from '../lib/inventory';
import { UNIT_PAGE_SIZE, createWriteIntent } from '../lib/units';
import { ConnectionRestNotice } from './ConnectionRestNotice';
import { ErrorAlert } from './ErrorAlert';
import { FormDialog } from './FormDialog';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import type {
  GqlGetInventoryPositionsQuery,
  GqlGetScoutCustodyBalancesQuery,
  GqlGetUnitCampaignCatalogQuery,
  GqlInventoryPositionFieldsFragment,
  GqlListUnitCampaignRosterQuery,
  GqlScoutCustodyBalanceFieldsFragment,
  GqlUnitCampaignMembershipFieldsFragment,
} from '../types/graphql-generated';

type CatalogProduct = NonNullable<GqlGetUnitCampaignCatalogQuery['unitCampaignCatalog']>['products'][number];
type Balance = GqlScoutCustodyBalanceFieldsFragment;
type ProductNames = ReadonlyMap<string, string>;

/** A Scout who can be issued to: an ACTIVE roster row names both ids the write needs. */
interface EligibleScout {
  profileId: string;
  campaignId: string;
  scoutName: string;
  campaignName: string;
}

/** Anything a custody row names a Scout by, so one labelling rule serves both tables. */
type ScoutKey = { profileId: string; campaignId: string };

/** A custody row's place in the roster: the pair the stock was issued under, not the Scout alone. */
function rosterKey(key: ScoutKey): string {
  return `${key.profileId}#${key.campaignId}`;
}

/**
 * One return batch: one Scout's held stock under one Scout Campaign.
 *
 * The pair is the write's identity, not the Scout alone. Each custody row answers only
 * for the campaign it was written under (`unit_operations.py` refuses a return whose
 * `campaignId` is not the row's own), and every return item has to be at least one
 * Kernel, so a batch is exactly the rows that still hold something, under the campaign
 * they hold it under.
 */
interface CustodyGroup {
  profileId: string;
  campaignId: string;
  lines: Balance[];
  held: number;
}

/** The test id of one group, unique even when one Scout holds under two campaigns. */
function groupKey(group: CustodyGroup): string {
  return `${group.profileId}:${group.campaignId}`;
}

/** What the admin asked for: an issue, or one Scout's whole batch back. */
type PendingAction = { kind: 'issue' } | { kind: 'return'; group: CustodyGroup } | null;

const BALANCE_VARIABLES = (unitCampaignId: string) => ({ unitCampaignId, page: page() });

export const ScoutCustodyPanel: React.FC<{ unitCampaignId: string }> = ({ unitCampaignId }) => {
  const catalog = useQuery<GqlGetUnitCampaignCatalogQuery>(GET_UNIT_CAMPAIGN_CATALOG, {
    variables: { unitCampaignId },
  });
  const balances = useQuery<GqlGetScoutCustodyBalancesQuery>(GET_SCOUT_CUSTODY_BALANCES, {
    variables: BALANCE_VARIABLES(unitCampaignId),
  });
  const roster = useQuery<GqlListUnitCampaignRosterQuery>(LIST_UNIT_CAMPAIGN_ROSTER, {
    variables: { unitCampaignId, page: { limit: UNIT_PAGE_SIZE } },
  });
  const positions = useQuery<GqlGetInventoryPositionsQuery>(GET_INVENTORY_POSITIONS, {
    variables: BALANCE_VARIABLES(unitCampaignId),
  });

  // Custody lists are drained to the end: an admin who is shown one page of held
  // stock can conclude the rest was already returned.
  const completeBalances = useCompleteConnection<Balance>(balances.data?.scoutCustodyBalances, {
    query: GET_SCOUT_CUSTODY_BALANCES,
    field: 'scoutCustodyBalances',
    limit: page().limit as number,
    variables: BALANCE_VARIABLES(unitCampaignId),
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
  const completePositions = useCompleteConnection<GqlInventoryPositionFieldsFragment>(
    positions.data?.inventoryPositions,
    {
      query: GET_INVENTORY_POSITIONS,
      field: 'inventoryPositions',
      limit: page().limit as number,
      variables: BALANCE_VARIABLES(unitCampaignId),
    },
  );

  const products = useMemo(() => productsOf(catalog.data), [catalog.data]);
  const names = useMemo<ProductNames>(
    () => new Map(products.map((product) => [product.productId, product.productName])),
    [products],
  );
  const unassigned = useMemo<Map<string, number>>(
    () => new Map(completePositions.items.map((position) => [position.productId, position.unassignedKernelQty])),
    [completePositions.items],
  );
  const eligible = useMemo<EligibleScout[]>(
    () =>
      completeRoster.items
        .filter((member) => member.status === 'ACTIVE')
        .map((member) => ({
          profileId: member.profileId,
          campaignId: member.campaignId,
          scoutName: member.scoutName,
          campaignName: member.campaignName,
        })),
    [completeRoster.items],
  );
  // The custody rows carry ids; the roster is what knows who they belong to. Keyed by
  // the pair the stock was issued under, so a Scout holding under two Scout Campaigns is
  // named by the right one, and one map serves both tables and the return dialog.
  const scouts = useMemo<Map<string, GqlUnitCampaignMembershipFieldsFragment>>(
    () => new Map(completeRoster.items.map((member) => [rosterKey(member), member])),
    [completeRoster.items],
  );
  const lines = completeBalances.items;
  const groups = useMemo(() => groupByScout(lines), [lines]);
  const totalWithScout = totalHeld(balances.data);

  const writes = useCustodyWrites(unitCampaignId, balances.refetch, positions.refetch);
  const [pending, setPending] = useState<PendingAction>(null);

  return (
    <Box sx={{ pt: 2 }}>
      <Alert severity="info" sx={{ mb: 2 }} data-testid="custody-note">
        Stock issued to a Scout still belongs to the Unit. It is recorded as held by that Scout until they sell it or
        bring it back, and a Scout who left the campaign still owes whatever they hold.
      </Alert>
      <IssueButton eligible={eligible.length} products={products.length} onAsk={() => setPending({ kind: 'issue' })} />
      <QueryGate
        query={balances}
        loading={<LoadingState minHeight="200px" />}
        failure={<ErrorAlert message="Could not load the stock held by Scouts." />}
      >
        <CustodyTotal total={totalWithScout} groups={groups.length} />
        <ScoutSummary
          scouts={scouts}
          groups={groups}
          names={names}
          onAsk={(group) => setPending({ kind: 'return', group })}
        />
        <CustodyLines scouts={scouts} lines={lines} names={names} />
        <ConnectionRestNotice loading={completeBalances.loadingRest} failed={completeBalances.failedRest} />
      </QueryGate>
      <CustodyDialogs
        pending={pending}
        eligible={eligible}
        scouts={scouts}
        products={products}
        names={names}
        unassigned={unassigned}
        writes={writes}
        onClose={() => setPending(null)}
      />
    </Box>
  );
};

/**
 * The write can only be offered to someone eligible.
 *
 * Eligibility is the roster row, and the note says which half is missing: no catalog
 * product, or no active member who could hold stock. A removed Scout is not eligible
 * for more stock but is still owed theirs, so the return side does not ask this
 * question at all.
 */
const IssueButton: React.FC<{ eligible: number; products: number; onAsk: () => void }> = ({
  eligible,
  products,
  onAsk,
}) => (
  <Box sx={{ mb: 2 }}>
    <Button variant="contained" onClick={onAsk} disabled={eligible === 0 || products === 0} data-testid="issue-stock">
      Issue stock to a Scout
    </Button>
    {eligible === 0 ? (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="no-eligible-note">
        Nobody on this campaign roster can be issued stock. A Scout joins the roster first, and a removed Scout cannot
        be issued more.
      </Typography>
    ) : null}
  </Box>
);

const CustodyDialogs: React.FC<{
  pending: PendingAction;
  eligible: readonly EligibleScout[];
  scouts: ReadonlyMap<string, GqlUnitCampaignMembershipFieldsFragment>;
  products: readonly CatalogProduct[];
  names: ProductNames;
  unassigned: ReadonlyMap<string, number>;
  writes: ReturnType<typeof useCustodyWrites>;
  onClose: () => void;
}> = ({ pending, eligible, scouts, products, names, unassigned, writes, onClose }) => {
  if (pending?.kind === 'issue') {
    return (
      <IssueDialog
        eligible={eligible}
        products={products}
        names={names}
        unassigned={unassigned}
        writes={writes}
        onClose={onClose}
      />
    );
  }
  if (pending?.kind === 'return') {
    return <ReturnDialog group={pending.group} scouts={scouts} names={names} writes={writes} onClose={onClose} />;
  }
  return null;
};

/** The server's campaign-wide custody total, next to the rows this screen is showing. */
const CustodyTotal: React.FC<{ total: number; groups: number }> = ({ total, groups }) => (
  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }} data-testid="custody-total">
    {`${total} ${total === 1 ? 'Kernel is' : 'Kernels are'} held by ${groups} ${groups === 1 ? 'Scout' : 'Scouts'} in this campaign.`}
  </Typography>
);

/**
 * What a custody row's Scout is called: the roster's own words, ids when it has none.
 *
 * The custody read answers ids and the roster read answers people, and the two arrive
 * independently. A Scout whose roster entry cannot be read keeps their ids here, which
 * is what still matches the audit trail, rather than disappearing from a table whose
 * whole job is showing stock that has to come back.
 */
function scoutNames(
  scouts: ReadonlyMap<string, GqlUnitCampaignMembershipFieldsFragment>,
  key: ScoutKey,
): { scoutName: string; campaignName: string } {
  const member = scouts.get(rosterKey(key));
  return {
    scoutName: scoutLabel(member ?? { profileId: key.profileId, scoutName: '' }),
    campaignName: campaignLabel(member ?? { campaignId: key.campaignId, campaignName: '' }),
  };
}

const ScoutSummary: React.FC<{
  scouts: ReadonlyMap<string, GqlUnitCampaignMembershipFieldsFragment>;
  groups: readonly CustodyGroup[];
  names: ProductNames;
  onAsk: (group: CustodyGroup) => void;
}> = ({ scouts, groups, names, onAsk }) => (
  <Card variant="outlined" sx={{ mb: 3 }}>
    <CardContent>
      <Typography variant="h6" gutterBottom>
        Held by Scout
      </Typography>
      <Box sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Scout</TableCell>
              <TableCell>Scout Campaign</TableCell>
              <TableCell>Products held</TableCell>
              <TableCell align="right">Kernels held</TableCell>
              <TableCell align="right">Return</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {groups.map((group) => (
              <ScoutRow key={groupKey(group)} scouts={scouts} group={group} names={names} onAsk={onAsk} />
            ))}
            {groups.length === 0 ? <NoCustodyRow /> : null}
          </TableBody>
        </Table>
      </Box>
    </CardContent>
  </Card>
);

const ScoutRow: React.FC<{
  scouts: ReadonlyMap<string, GqlUnitCampaignMembershipFieldsFragment>;
  group: CustodyGroup;
  names: ProductNames;
  onAsk: (group: CustodyGroup) => void;
}> = ({ scouts, group, names, onAsk }) => {
  const key = groupKey(group);
  const shown = scoutNames(scouts, group);
  return (
    <TableRow data-testid={`custody-scout-row-${key}`}>
      <TableCell data-testid={`custody-scout-name-${key}`}>{shown.scoutName}</TableCell>
      <TableCell data-testid={`custody-scout-campaign-${key}`}>{shown.campaignName}</TableCell>
      <TableCell>{group.lines.map((line) => productLabel(names, line.productId)).join(', ')}</TableCell>
      <TableCell align="right" data-testid={`custody-scout-held-${key}`}>
        {group.held}
      </TableCell>
      <TableCell align="right">
        <Button variant="outlined" size="small" onClick={() => onAsk(group)} data-testid={`return-stock-${key}`}>
          Return all stock
        </Button>
      </TableCell>
    </TableRow>
  );
};

const CustodyLines: React.FC<{
  scouts: ReadonlyMap<string, GqlUnitCampaignMembershipFieldsFragment>;
  lines: readonly Balance[];
  names: ProductNames;
}> = ({ scouts, lines, names }) => (
  <Card variant="outlined">
    <CardContent>
      <Typography variant="h6" gutterBottom>
        Custody by product
      </Typography>
      <Box sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Scout</TableCell>
              <TableCell>Product</TableCell>
              <TableCell align="right">Held</TableCell>
              <TableCell align="right">Issued under</TableCell>
              <TableCell align="right">Version</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {lines.map((line) => (
              <CustodyLineRow key={`${line.profileId}#${line.productId}`} scouts={scouts} line={line} names={names} />
            ))}
          </TableBody>
        </Table>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="custody-line-count">
        {`${lines.length} ${lines.length === 1 ? 'custody line' : 'custody lines'} shown`}
      </Typography>
    </CardContent>
  </Card>
);

/** One custody line: the held quantity, and the Scout and Campaign it belongs to. */
const CustodyLineRow: React.FC<{
  scouts: ReadonlyMap<string, GqlUnitCampaignMembershipFieldsFragment>;
  line: Balance;
  names: ProductNames;
}> = ({ scouts, line, names }) => {
  const shown = scoutNames(scouts, line);
  return (
    <TableRow data-testid={`custody-line-${line.profileId}-${line.productId}`}>
      <TableCell data-testid={`custody-line-scout-${line.profileId}-${line.productId}`}>{shown.scoutName}</TableCell>
      <TableCell>{productLabel(names, line.productId)}</TableCell>
      <TableCell align="right" data-testid={`custody-line-qty-${line.profileId}-${line.productId}`}>
        {line.withScoutQty}
      </TableCell>
      <TableCell align="right">{shown.campaignName}</TableCell>
      <TableCell align="right">{`v${line.version}`}</TableCell>
    </TableRow>
  );
};

const NoCustodyRow: React.FC = () => (
  <TableRow>
    <TableCell colSpan={4}>
      <Box sx={{ p: 2 }}>
        <Typography color="text.secondary">No Scout holds stock for this campaign yet.</Typography>
      </Box>
    </TableCell>
  </TableRow>
);

/** The catalog decides which products can be issued at all, not the balance table. */
function productsOf(data?: GqlGetUnitCampaignCatalogQuery): CatalogProduct[] {
  return data?.unitCampaignCatalog?.products ?? [];
}

/** The server's campaign-wide custody aggregate, or zero before it answers. */
function totalHeld(data?: GqlGetScoutCustodyBalancesQuery): number {
  return data?.scoutCustodyBalances?.totalWithScoutQty ?? 0;
}

/**
 * The two custody writes, each followed by the reads it changed.
 *
 * A failure refreshes too. The return body is built from the custody lines on screen,
 * so a refusal that came from a stale line has to be re-read before the admin can
 * press the button again with a body the server will accept.
 */
function useCustodyWrites(unitCampaignId: string, refreshBalances: () => unknown, refreshPositions: () => unknown) {
  const [issueStock] = useMutation(ISSUE_STOCK_TO_SCOUT);
  const [returnStock] = useMutation(RETURN_STOCK_FROM_SCOUT);
  const intent = useRef(createWriteIntent()).current;

  const send = async (mutation: typeof issueStock, body: Record<string, unknown>, fallback: string) => {
    try {
      await mutation({ variables: { input: { ...body, idempotency: { idempotencyKey: intent.keyFor(body) } } } });
    } catch (failure) {
      await refreshAfter(refreshBalances, refreshPositions);
      throw new Error(describeInventoryFailure(failure, fallback), { cause: failure });
    }
    await refreshAfter(refreshBalances, refreshPositions);
  };

  return {
    issue: (scout: EligibleScout, productId: string, quantity: number) =>
      send(
        issueStock,
        { unitCampaignId, campaignId: scout.campaignId, profileId: scout.profileId, productId, quantity },
        'The stock could not be issued.',
      ),
    returnBatch: (group: CustodyGroup) =>
      send(
        returnStock,
        {
          unitCampaignId,
          campaignId: group.campaignId,
          profileId: group.profileId,
          items: group.lines.map((line) => ({ productId: line.productId, quantity: line.withScoutQty })),
        },
        'The stock could not be returned.',
      ),
  };
}

async function refreshAfter(refreshBalances: () => unknown, refreshPositions: () => unknown): Promise<void> {
  try {
    await Promise.all([refreshBalances(), refreshPositions()]);
  } catch {
    // A refresh that failed after the write landed is the query's own error state.
  }
}

/**
 * The return batches: one per Scout and Scout Campaign, holding only what is still held.
 *
 * A product a Scout has already sold out of or returned keeps its custody row — a return
 * drives it to zero and leaves it, which is what makes a replayable return answer the same
 * list — so the balance read hands back zero rows on purpose. They stay out of the batch,
 * because the server requires every return item to be at least one Kernel and would refuse
 * the whole batch for one of them. A Scout who holds nothing anywhere is not offered a
 * return: the write could only fail, and a button that cannot work is not an offer.
 */
function groupByScout(lines: readonly Balance[]): CustodyGroup[] {
  const groups = new Map<string, CustodyGroup>();
  for (const line of lines) {
    if (line.withScoutQty <= 0) continue;
    const key = `${line.campaignId}::${line.profileId}`;
    const group = groups.get(key) ?? {
      profileId: line.profileId,
      campaignId: line.campaignId,
      lines: [],
      held: 0,
    };
    group.lines.push(line);
    group.held += line.withScoutQty;
    groups.set(key, group);
  }
  return [...groups.values()];
}

interface IssueFormState {
  profileId: string;
  productId: string;
  quantity: string;
  fieldError: string | null;
}

/**
 * The issue dialog: Scout, product, quantity.
 *
 * The Scout list is the ACTIVE roster, so the option the admin picks already names
 * both ids the write needs (`profileId` and the roster's `campaignId`). The unassigned
 * figure beside the product is the server's own derived number, shown as guidance:
 * issuing more than that is the server's to refuse, and its refusal is what the
 * screen reports rather than a second local rule that could disagree.
 */
const IssueDialog: React.FC<{
  eligible: readonly EligibleScout[];
  products: readonly CatalogProduct[];
  names: ProductNames;
  unassigned: ReadonlyMap<string, number>;
  writes: ReturnType<typeof useCustodyWrites>;
  onClose: () => void;
}> = ({ eligible, products, names, unassigned, writes, onClose }) => {
  const [state, setState] = useState<IssueFormState>({ profileId: '', productId: '', quantity: '', fieldError: null });
  const scout = eligible.find((candidate) => candidate.profileId === state.profileId);

  const submit = async () => {
    if (!scout) {
      setState({ ...state, fieldError: 'Choose the Scout being issued to.' });
      throw new Error('Choose the Scout being issued to.');
    }
    if (!state.productId) {
      setState({ ...state, fieldError: 'Choose a product.' });
      throw new Error('Choose a product.');
    }
    const quantity = parseQuantity(state.quantity);
    if (quantity.error) {
      setState({ ...state, fieldError: quantity.error });
      throw new Error(quantity.error);
    }
    await writes.issue(scout, state.productId, quantity.value as number);
    onClose();
  };

  return (
    <FormDialog
      title="Issue stock to a Scout"
      confirmLabel="Issue stock"
      onCancel={onClose}
      onConfirm={submit}
      error={state.fieldError}
    >
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary">
          The Scout must be an active member of this campaign. Issued stock stays Unit property and is recorded as held
          by the Scout until it is sold or returned.
        </Typography>
        <TextField
          select
          label="Scout"
          value={state.profileId}
          onChange={(event) => setState({ ...state, profileId: event.target.value, fieldError: null })}
          data-testid="custody-scout"
        >
          {eligible.map((candidate) => (
            <MenuItem key={candidate.profileId} value={candidate.profileId}>
              {`${scoutLabel(candidate)} · ${campaignLabel(candidate)}`}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Product"
          value={state.productId}
          onChange={(event) => setState({ ...state, productId: event.target.value, fieldError: null })}
          helperText={
            state.productId && unassigned.has(state.productId)
              ? `${unassigned.get(state.productId)} unassigned Kernels of this product.`
              : 'Only unassigned Kernel stock can be issued.'
          }
          data-testid="custody-product"
        >
          {products.map((product) => (
            <MenuItem key={product.productId} value={product.productId}>
              {productLabel(names, product.productId)}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Quantity issued"
          value={state.quantity}
          onChange={(event) => setState({ ...state, quantity: event.target.value, fieldError: null })}
          inputMode="numeric"
          helperText="Whole Kernels only."
          data-testid="custody-quantity"
        />
      </Stack>
    </FormDialog>
  );
};

/**
 * One click returns the whole batch. The line list is read from the custody rows the
 * admin is looking at, so what they confirm is what the screen showed them, and the
 * rollback rule is stated where the confirmation is.
 */
const ReturnDialog: React.FC<{
  group: CustodyGroup;
  scouts: ReadonlyMap<string, GqlUnitCampaignMembershipFieldsFragment>;
  names: ProductNames;
  writes: ReturnType<typeof useCustodyWrites>;
  onClose: () => void;
}> = ({ group, scouts, names, writes, onClose }) => (
  <FormDialog
    title={`Return ${scoutNames(scouts, group).scoutName}'s stock`}
    confirmLabel="Return all stock"
    confirmColor="primary"
    onCancel={onClose}
    onConfirm={async () => {
      await writes.returnBatch(group);
      onClose();
    }}
  >
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary" data-testid="return-batch-note">
        Every product this Scout holds comes back in one write. If any one line cannot be returned, the whole batch is
        refused and no stock moves.
      </Typography>
      <Box>
        {group.lines.map((line) => (
          <Typography key={line.productId} variant="body2" data-testid={`return-batch-line-${line.productId}`}>
            {`${productLabel(names, line.productId)}: ${line.withScoutQty}`}
          </Typography>
        ))}
      </Box>
    </Stack>
  </FormDialog>
);
