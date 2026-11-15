/**
 * Unit Campaign list and creation (Show & Sell §1.6.3).
 *
 * Two facts this screen is responsible for making visible:
 *
 * 1. **The join code is the credential a Scout uses.** The server generates it, it is
 *    revealed on the admin's own screen, and — unlike a Unit admin invite — it is
 *    reusable, so a campaign's whole roster shares one code for the season.
 * 2. **The catalog is fixed at creation.** Inventory, Order origin, and event product
 *    identity all key on it, so nothing here points an existing campaign at a
 *    different catalog; wanting another catalog means another campaign.
 *
 * Opening and closing a campaign writes only that state: closing stops new joins and
 * new participation, and touches no balance, obligation, or history.
 */

import React, {useCallback, useState} from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Card,
  Chip,
  IconButton,
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
import AddIcon from '@mui/icons-material/Add';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { CampaignYearField } from './CampaignYearField';
import { CatalogSelect } from './CatalogSelect';
import { ConfirmDialog } from './ConfirmDialog';
import { FormDialog } from './FormDialog';
import { ErrorNote } from './ErrorAlert';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { ConnectionRestNotice } from './ConnectionRestNotice';
import { useCompleteConnection } from '../hooks/useCompleteConnection';
import { useCatalogsData } from '../hooks/useCatalogsData';
import { CREATE_UNIT_CAMPAIGN, LIST_UNIT_CAMPAIGNS, UPDATE_UNIT_CAMPAIGN } from '../lib/graphql';
import { SHOW_SELL_BASE, UNIT_PAGE_SIZE, newIdempotencyKey, refreshQuery, unitCampaignStatusLabel } from '../lib/units';
import type { GqlListUnitCampaignsQuery, GqlUnit, GqlUnitCampaignAdmin } from '../types/graphql-generated';

type ActiveFilter = 'all' | 'active' | 'closed';

interface PendingToggle {
  campaign: GqlUnitCampaignAdmin;
  idempotencyKey: string;
}

function toIsActiveFilter(filter: ActiveFilter): boolean | undefined {
  if (filter === 'all') return undefined;
  return filter === 'active';
}


function readCreatedCampaign(result: unknown): GqlUnitCampaignAdmin | null {
  const created = (result as { data?: { createUnitCampaign?: GqlUnitCampaignAdmin } } | undefined)?.data
    ?.createUnitCampaign;
  return created ?? null;
}

interface UnitCampaignsPanelProps {
  unit: GqlUnit;
}

export const UnitCampaignsPanel: React.FC<UnitCampaignsPanelProps> = ({ unit }) => {
  const [filter, setFilter] = useState<ActiveFilter>('all');
  const [createOpen, setCreateOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [createdCampaign, setCreatedCampaign] = useState<GqlUnitCampaignAdmin | null>(null);
  const [pendingToggle, setPendingToggle] = useState<PendingToggle | null>(null);

  const campaignFilter = { unitId: unit.unitId, isActive: toIsActiveFilter(filter) };
  const campaigns = useQuery<GqlListUnitCampaignsQuery>(LIST_UNIT_CAMPAIGNS, {
    variables: { ...campaignFilter, page: { limit: UNIT_PAGE_SIZE } },
  });
  // A Unit admin choosing which campaign to open has to see all of them; page one is
  // not the answer to "which campaigns does this Unit have".
  const completeCampaigns = useCompleteConnection<GqlUnitCampaignAdmin>(campaigns.data?.unitCampaigns, {
    query: LIST_UNIT_CAMPAIGNS,
    field: 'unitCampaigns',
    limit: UNIT_PAGE_SIZE,
    variables: campaignFilter,
  });
  const applyToggle = useCampaignToggle();
  const rows = completeCampaigns.items;
  const refetchCampaigns = campaigns.refetch;

  // A campaign that exists must be in the list that says which campaigns exist;
  // the note only adds the join code, which is shown once at creation.
  const handleCreated = useCallback(
    (campaign: GqlUnitCampaignAdmin) => {
      setCreatedCampaign(campaign);
      void refreshQuery(refetchCampaigns);
    },
    [refetchCampaigns],
  );

  return (
    <QueryGate
      query={campaigns}
      loading={<LoadingState minHeight="200px" />}
      failure={<ErrorNote message="Could not load this Unit's campaigns." sx={{ mt: 2 }} />}
    >
      <Box sx={{ pt: 2 }}>
        <ErrorNote message={actionError} />
        <CreatedCampaignNote campaign={createdCampaign} onDismiss={() => setCreatedCampaign(null)} />

        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)} data-testid="create-campaign">
            Create campaign
          </Button>
          <TextField
            select
            label="Show"
            value={filter}
            onChange={(event) => setFilter(event.target.value as ActiveFilter)}
            size="small"
            data-testid="campaign-filter"
          >
            <MenuItem value="all">All</MenuItem>
            <MenuItem value="active">Active only</MenuItem>
            <MenuItem value="closed">Closed only</MenuItem>
          </TextField>
        </Stack>

        <CampaignTable rows={rows} onAskToggle={setPendingToggle} />
        <ConnectionRestNotice loading={completeCampaigns.loadingRest} failed={completeCampaigns.failedRest} />
        <CreateCampaignDialog unit={unit} open={createOpen} onClose={() => setCreateOpen(false)} onCreated={handleCreated} />
        <ToggleConfirm
          pending={pendingToggle}
          onCancel={() => setPendingToggle(null)}
          onConfirm={async (pending) => {
            setPendingToggle(null);
            setActionError(await applyToggle(pending));
            await refreshQuery(campaigns.refetch);
          }}
        />
      </Box>
    </QueryGate>
  );
};

/**
 * The write that opens or closes a campaign — nothing else is touched.
 *
 * The version sent is the one this row was rendered with, which is what makes a
 * concurrent change by another admin a refusal rather than a silent overwrite.
 */
function useCampaignToggle() {
  const [updateCampaign] = useMutation(UPDATE_UNIT_CAMPAIGN);
  return useCallback(async (pending: PendingToggle): Promise<string | null> => {
    const { campaign, idempotencyKey } = pending;
    try {
      await updateCampaign({
        variables: {
          input: {
            unitCampaignId: campaign.unitCampaignId,
            isActive: !campaign.isActive,
            version: { expectedVersion: campaign.version },
            idempotency: { idempotencyKey },
          },
        },
      });
      return null;
    } catch (mutationError) {
      return (mutationError as Error).message || 'Could not change this campaign.';
    }
  }, [updateCampaign]);
}

const ToggleConfirm: React.FC<{
  pending: PendingToggle | null;
  onCancel: () => void;
  onConfirm: (pending: PendingToggle) => Promise<void>;
}> = ({ pending, onCancel, onConfirm }) => {
  const wording = toggleWordings(pending);
  return (
    <ConfirmDialog
      open={wording.open}
      title={wording.title}
      confirmLabel={wording.label}
      confirmColor={wording.color}
      onClose={onCancel}
      onConfirm={async () => {
        if (pending) await onConfirm(pending);
      }}
    >
      <Typography>{wording.body}</Typography>
    </ConfirmDialog>
  );
};

/**
 * Opening and closing are opposite actions with the same shape, and both sentences
 * say the same thing about what is *not* touched — history, orders, obligations.
 * Stating the pair once keeps the reassurance identical in both directions.
 */
interface ToggleWording {
  open: boolean;
  title: string;
  label: string;
  color: 'warning' | 'primary';
  body: string;
}

function toggleWordings(pending: PendingToggle | null): ToggleWording {
  const closing = pending !== null && pending.campaign.isActive;
  if (pending === null) {
    return { open: false, title: '', label: '', color: 'primary', body: '' };
  }
  if (closing) {
    return {
      open: true,
      title: 'Close this campaign?',
      label: 'Close campaign',
      color: 'warning',
      body: 'Closing stops new joins and new participation. Roster history, orders, and obligations stay exactly as they are.',
    };
  }
  return {
    open: true,
    title: 'Open this campaign?',
    label: 'Open campaign',
    color: 'primary',
    body: 'Opening lets Scouts with the join code participate again. Nothing else changes.',
  };
}

const CampaignTable: React.FC<{
  rows: GqlUnitCampaignAdmin[];
  onAskToggle: (pending: PendingToggle) => void;
}> = ({ rows, onAskToggle }) => (
  <Card variant="outlined">
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Campaign</TableCell>
          <TableCell>Status</TableCell>
          <TableCell>Join code</TableCell>
          <TableCell>Catalog</TableCell>
          <TableCell align="right">Actions</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((campaign) => (
          <CampaignRow key={campaign.unitCampaignId} campaign={campaign} onAskToggle={onAskToggle} />
        ))}
        {rows.length === 0 && (
          <TableRow>
            <TableCell colSpan={5}>
              <Box sx={{ p: 2 }}>
                <Typography color="text.secondary">
                  No campaigns here yet. A campaign is a season: it owns a catalog, a join code, and a roster.
                </Typography>
              </Box>
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  </Card>
);

const CampaignRow: React.FC<{ campaign: GqlUnitCampaignAdmin; onAskToggle: (pending: PendingToggle) => void }> = ({
  campaign,
  onAskToggle,
}) => {
  const navigate = useNavigate();
  const [revealed, setRevealed] = useState(false);

  return (
    <TableRow data-testid={`campaign-row-${campaign.unitCampaignId}`}>
      <TableCell>
        {campaign.campaignName} · {campaign.campaignYear}
      </TableCell>
      <TableCell data-testid={`campaign-status-${campaign.unitCampaignId}`}>
        <Chip
          size="small"
          label={unitCampaignStatusLabel(campaign.isActive)}
          color={campaign.isActive ? 'success' : 'default'}
        />
      </TableCell>
      <TableCell>
        <JoinCodeCell campaign={campaign} revealed={revealed} onToggle={() => setRevealed((value) => !value)} />
      </TableCell>
      <TableCell data-testid={`catalog-${campaign.unitCampaignId}`}>{campaign.catalogId}</TableCell>
      <TableCell align="right">
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button
            size="small"
            onClick={() => void navigate(`${SHOW_SELL_BASE}/units/${campaign.unitId}/campaigns/${campaign.unitCampaignId}`)}
            data-testid={`roster-${campaign.unitCampaignId}`}
          >
            Roster
          </Button>
          <Button
            size="small"
            color={campaign.isActive ? 'error' : 'primary'}
            onClick={() => onAskToggle({ campaign, idempotencyKey: newIdempotencyKey() })}
            data-testid={`toggle-${campaign.unitCampaignId}`}
          >
            {campaign.isActive ? 'Close' : 'Open'}
          </Button>
        </Stack>
      </TableCell>
    </TableRow>
  );
};

const JoinCodeCell: React.FC<{ campaign: GqlUnitCampaignAdmin; revealed: boolean; onToggle: () => void }> = ({
  campaign,
  revealed,
  onToggle,
}) => (
  <Stack direction="row" spacing={1} alignItems="center">
    <span data-testid={`join-code-${campaign.unitCampaignId}`}>{revealed ? campaign.joinCode : '••••••••••••••••'}</span>
    <IconButton
      size="small"
      aria-label={revealed ? 'Hide join code' : 'Show join code'}
      data-testid={`reveal-${campaign.unitCampaignId}`}
      onClick={onToggle}
    >
      <VisibilityIcon fontSize="small" />
    </IconButton>
  </Stack>
);

/** The join code a new campaign was issued, offered once where it was created. */
const CreatedCampaignNote: React.FC<{ campaign: GqlUnitCampaignAdmin | null; onDismiss: () => void }> = ({
  campaign,
  onDismiss,
}) => {
  if (!campaign) return null;
  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }} data-testid="created-campaign-note">
      <Typography>
        {campaign.campaignName} is open. Join code: <strong data-testid="created-join-code">{campaign.joinCode}</strong>
      </Typography>
      <IconButton
        size="small"
        aria-label="Copy join code"
        data-testid="copy-join-code"
        onClick={() => void navigator.clipboard?.writeText(campaign.joinCode)}
      >
        <ContentCopyIcon fontSize="small" />
      </IconButton>
      <Button size="small" onClick={onDismiss}>
        Dismiss
      </Button>
    </Stack>
  );
};

/**
 * The create form. The catalog is chosen here and nowhere afterwards, which is why
 * the immutability note sits under the selector rather than in a tooltip.
 */
const CreateCampaignDialog: React.FC<{
  unit: GqlUnit;
  open: boolean;
  onClose: () => void;
  onCreated: (campaign: GqlUnitCampaignAdmin) => void;
}> = ({ unit, open, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [year, setYear] = useState(new Date().getFullYear());
  const [catalogId, setCatalogId] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const { filteredMyCatalogs, filteredPublicCatalogs, catalogsLoading } = useCatalogsData(false);
  const [createCampaign] = useMutation(CREATE_UNIT_CAMPAIGN);

  const submit = async () => {
    const invalid = missingCreateField(name, catalogId);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    try {
      const result = await createCampaign({
        variables: {
          input: {
            unitId: unit.unitId,
            campaignName: name.trim(),
            campaignYear: year,
            catalogId,
            idempotency: { idempotencyKey: newIdempotencyKey() },
          },
        },
      });
      const created = readCreatedCampaign(result);
      if (created) onCreated(created);
      onClose();
    } catch (mutationError) {
      setFormError((mutationError as Error).message || 'Could not create the campaign.');
    }
  };

  if (!open) return null;
  return (
    <FormDialog
      title="Create a campaign"
      confirmLabel="Create campaign"
      onCancel={onClose}
      onConfirm={submit}
      error={formError}
      onDismissError={() => setFormError(null)}
    >
      <Stack spacing={2}>
        <TextField
          label="Campaign name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          data-testid="campaign-name"
        />
        <CampaignYearField label="Campaign year" value={year} onChange={setYear} />
        <CatalogSelect
          value={catalogId}
          onChange={setCatalogId}
          myCatalogs={filteredMyCatalogs}
          publicCatalogs={filteredPublicCatalogs}
          loading={catalogsLoading}
          required
          label="Catalog"
        />
        <Typography variant="body2" color="text.secondary" data-testid="catalog-immutability-note">
          The catalog is fixed once the campaign exists. Selling from a different catalog means creating a new campaign —
          inventory, orders, and event products all point at the one chosen here.
        </Typography>
      </Stack>
    </FormDialog>
  );
};

function missingCreateField(name: string, catalogId: string): string | null {
  if (!name.trim()) return 'Give the campaign a name.';
  if (!catalogId) return 'Choose the catalog this campaign sells from.';
  return null;
}

