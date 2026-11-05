/**
 * UnitCampaignsSection - administer a Unit's Show & Sell campaigns.
 *
 * Show & Sell Unit surface (batch C, leaf 1.6.3). Wires `unitCampaigns`,
 * `createUnitCampaign`, `updateUnitCampaign`, `unitCampaignCatalog`,
 * `unitCampaignRoster`, and `removeUnitCampaignMembership`.
 *
 * The catalog is chosen once at creation and is immutable afterwards: the
 * create form exposes a catalog selector, the edit form deliberately does not,
 * and `updateUnitCampaign` has no catalog field. The roster keeps removed
 * memberships as history (status REMOVED with removal provenance).
 */

import React, { useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import { EmptyState } from '../components/EmptyState';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { CatalogSelect } from '../components/CatalogSelect';
import { CampaignYearField } from '../components/CampaignYearField';
import {
  UNIT_CAMPAIGNS,
  CREATE_UNIT_CAMPAIGN,
  UPDATE_UNIT_CAMPAIGN,
  UNIT_CAMPAIGN_CATALOG,
  UNIT_CAMPAIGN_ROSTER,
  REMOVE_UNIT_CAMPAIGN_MEMBERSHIP,
  LIST_MY_CATALOGS,
  LIST_MANAGED_CATALOGS,
} from '../lib/graphql';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/errorCodes';
import { newUnitIdempotencyKey } from '../lib/unitForm';
import type {
  GqlCatalog,
  GqlUnitCampaignAdmin,
  GqlUnitCampaignCatalog,
  GqlUnitCampaignMembership,
} from '../types';

const statusLabel = (status: GqlUnitCampaignMembership['status']): string =>
  status === 'ACTIVE' ? 'Active' : 'Removed';

const selectMyCatalogs = (data: { listMyCatalogs: GqlCatalog[] } | undefined): GqlCatalog[] =>
  data ? data.listMyCatalogs : [];

const selectManagedCatalogs = (data: { listManagedCatalogs: GqlCatalog[] } | undefined): GqlCatalog[] =>
  data ? data.listManagedCatalogs : [];

const selectUnitCampaigns = (
  data: { unitCampaigns: { items: GqlUnitCampaignAdmin[] } } | undefined,
): GqlUnitCampaignAdmin[] => (data ? data.unitCampaigns.items : []);

const selectRoster = (
  data: { unitCampaignRoster: { items: GqlUnitCampaignMembership[] } } | undefined,
): GqlUnitCampaignMembership[] => (data ? data.unitCampaignRoster.items : []);

const CreateUnitCampaignDialog: React.FC<{
  open: boolean;
  unitId: string;
  onClose: () => void;
  onCreated?: (unitCampaignId: string) => void;
}> = ({ open, unitId, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [catalogId, setCatalogId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [createCampaign, { loading: submitting }] = useMutation<{
    createUnitCampaign: { unitCampaignId: string };
  }>(CREATE_UNIT_CAMPAIGN, {
    refetchQueries: [{ query: UNIT_CAMPAIGNS, variables: { unitId } }],
    onCompleted: (data) => {
      onCreated?.(data.createUnitCampaign.unitCampaignId);
      onClose();
    },
    onError: (e) => setError(mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e))),
  });

  const { data: myData, loading: myLoading } = useQuery<{ listMyCatalogs: GqlCatalog[] }>(LIST_MY_CATALOGS, {
    skip: !open,
  });
  const { data: managedData, loading: managedLoading } = useQuery<{ listManagedCatalogs: GqlCatalog[] }>(
    LIST_MANAGED_CATALOGS,
    { skip: !open },
  );

  const myCatalogs = selectMyCatalogs(myData);
  const managedCatalogs = selectManagedCatalogs(managedData);
  const filteredPublic = managedCatalogs.filter((c) => !myCatalogs.some((m) => m.catalogId === c.catalogId));
  const busy = [submitting, myLoading, managedLoading].some(Boolean);

  const handleClose = () => {
    if (submitting) return;
    setError(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !year || !catalogId) {
      setError('Enter a campaign name, year, and choose a catalog.');
      return;
    }
    setError(null);
    try {
      await createCampaign({
        variables: {
          input: {
            unitId,
            campaignName: name.trim(),
            campaignYear: year,
            catalogId,
            idempotency: { idempotencyKey: newUnitIdempotencyKey() },
          },
        },
      });
    } catch {
      // GraphQL errors are surfaced by the onError callback; swallow to avoid an unhandled rejection.
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create Show &amp; Sell campaign</DialogTitle>
      <Box component="form" noValidate onSubmit={(e) => void handleSubmit(e)}>
        <DialogContent>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField
            fullWidth
            required
            label="Campaign name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            sx={{ mb: 2 }}
            helperText='For example "Pack 3149 Fall Show & Sell"'
          />
          <CampaignYearField label="Year" value={year} onChange={setYear} sx={{ mb: 2 }} />
          <CatalogSelect
            value={catalogId}
            onChange={setCatalogId}
            myCatalogs={myCatalogs}
            publicCatalogs={filteredPublic}
            loading={myLoading || managedLoading}
            fullWidth
            required
            label="Catalog (immutable after creation)"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={busy}>
            {submitting ? 'Creating…' : 'Create campaign'}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
};

const EditUnitCampaignDialog: React.FC<{
  campaign: GqlUnitCampaignAdmin;
  unitId: string;
  onClose: () => void;
}> = ({ campaign, unitId, onClose }) => {
  const [name, setName] = useState(campaign.campaignName);
  const [year, setYear] = useState<number>(campaign.campaignYear);
  const [active, setActive] = useState(campaign.isActive);
  const [error, setError] = useState<string | null>(null);
  const [updateCampaign, { loading: submitting }] = useMutation(UPDATE_UNIT_CAMPAIGN, {
    refetchQueries: [{ query: UNIT_CAMPAIGNS, variables: { unitId } }],
    onCompleted: () => onClose(),
    onError: (e) => setError(mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e))),
  });

  const handleClose = () => {
    if (submitting) return;
    setError(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !year) {
      setError('Enter a campaign name and year.');
      return;
    }
    setError(null);
    try {
      await updateCampaign({
        variables: {
          input: {
            unitCampaignId: campaign.unitCampaignId,
            version: { expectedVersion: campaign.version },
            campaignName: name.trim(),
            campaignYear: year,
            isActive: active,
            idempotency: { idempotencyKey: newUnitIdempotencyKey() },
          },
        },
      });
    } catch {
      // GraphQL errors are surfaced by the onError callback; swallow to avoid an unhandled rejection.
    }
  };

  return (
    <Dialog open onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit campaign</DialogTitle>
      <Box component="form" noValidate onSubmit={(e) => void handleSubmit(e)}>
        <DialogContent>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField
            fullWidth
            required
            label="Campaign name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            sx={{ mb: 2 }}
          />
          <CampaignYearField label="Year" value={year} onChange={setYear} sx={{ mb: 2 }} />
          <FormControlLabel
            control={<Switch checked={active} onChange={(e) => setActive(e.target.checked)} />}
            label="Active"
            sx={{ display: 'block' }}
            data-testid="edit-campaign-active-toggle"
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }} data-testid="edit-catalog-immutable-note">
            The catalog is fixed when a campaign is created and cannot be changed here.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={submitting}>
            {submitting ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
};

const CampaignRoster: React.FC<{
  campaign: GqlUnitCampaignAdmin;
  onRemove: (membership: GqlUnitCampaignMembership) => void;
}> = ({ campaign, onRemove }) => {
  const { data, loading, error } = useQuery<{
    unitCampaignRoster: { items: GqlUnitCampaignMembership[] };
  }>(UNIT_CAMPAIGN_ROSTER, { variables: { unitCampaignId: campaign.unitCampaignId } });

  if (loading) return <Typography variant="body2" color="text.secondary">Loading roster…</Typography>;
  if (error) return <Alert severity="error">Unable to load the roster.</Alert>;

  const items = selectRoster(data);
  if (items.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
        No one has joined this campaign yet.
      </Typography>
    );
  }
  return (
    <Stack spacing={1} data-testid="roster-list">
      {items.map((m) => (
        <RosterRow key={`${m.campaignId}-${m.profileId}`} membership={m} onRemove={onRemove} />
      ))}
    </Stack>
  );
};

interface RosterRowProps {
  membership: GqlUnitCampaignMembership;
  onRemove: (membership: GqlUnitCampaignMembership) => void;
}

const RosterRow: React.FC<RosterRowProps> = ({ membership, onRemove }) => (
  <Box
    sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 0.5 }}
    data-testid={`roster-row-${membership.status}`}
  >
    <Box>
      <Typography>
        {membership.campaignId}{' '}
        <Chip size="small" color={membership.status === 'ACTIVE' ? 'success' : 'default'} label={statusLabel(membership.status)} />
      </Typography>
      <Typography variant="caption" color="text.secondary">
        Joined {new Date(membership.joinedAt).toLocaleDateString()}
        {membership.status === 'REMOVED' && membership.removedAt
          ? ` · removed ${new Date(membership.removedAt).toLocaleDateString()}`
          : ''}
      </Typography>
    </Box>
    {membership.status === 'ACTIVE' && (
      <Button size="small" color="error" onClick={() => onRemove(membership)} data-testid="remove-membership">
        Remove
      </Button>
    )}
  </Box>
);

const UnitCampaignDetail: React.FC<{
  campaign: GqlUnitCampaignAdmin;
  onEdit: (c: GqlUnitCampaignAdmin) => void;
}> = ({ campaign, onEdit }) => {
  const { data: catalogData } = useQuery<{ unitCampaignCatalog: GqlUnitCampaignCatalog }>(
    UNIT_CAMPAIGN_CATALOG,
    { variables: { unitCampaignId: campaign.unitCampaignId } },
  );
  const [removeTarget, setRemoveTarget] = useState<GqlUnitCampaignMembership | null>(null);
  const removeOutcome = useRef<{ state: 'pending' | 'success' | 'error'; error: string | null }>({
    state: 'pending',
    error: null,
  });
  const [removeMembership] = useMutation(REMOVE_UNIT_CAMPAIGN_MEMBERSHIP, {
    refetchQueries: [{ query: UNIT_CAMPAIGN_ROSTER, variables: { unitCampaignId: campaign.unitCampaignId } }],
    onCompleted: () => {
      removeOutcome.current = { state: 'success', error: null };
      setRemoveTarget(null);
    },
    onError: (e) => {
      removeOutcome.current = {
        state: 'error',
        error: mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e)),
      };
    },
  });

  const handleConfirmRemove = async () => {
    if (!removeTarget) return;
    removeOutcome.current = { state: 'pending', error: null };
    try {
      await removeMembership({
        variables: {
          input: {
            unitCampaignId: campaign.unitCampaignId,
            campaignId: removeTarget.campaignId,
            expectedMembershipVersion: removeTarget.version,
            expectedGuardVersion: removeTarget.version,
            idempotency: { idempotencyKey: newUnitIdempotencyKey() },
          },
        },
      });
    } catch {
      // GraphQL errors are captured by the onError callback; swallow to avoid an unhandled rejection.
    }
    if (removeOutcome.current.state === 'error') {
      throw new Error(removeOutcome.current.error ?? 'Something went wrong.');
    }
  };

  const catalogName = catalogData ? catalogData.unitCampaignCatalog.catalogName : '—';

  return (
    <CardContent>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">
          {campaign.campaignName} ({campaign.campaignYear})
        </Typography>
        <Stack direction="row" spacing={1}>
          <Chip size="small" color={campaign.isActive ? 'success' : 'default'} label={campaign.isActive ? 'Active' : 'Inactive'} />
          <Button size="small" variant="outlined" onClick={() => onEdit(campaign)} data-testid="edit-campaign-button">
            Edit
          </Button>
        </Stack>
      </Box>
      <Typography variant="body2" sx={{ mb: 2 }}>
        Join code: <code data-testid="join-code-display">{campaign.joinCode}</code>
      </Typography>
      <Typography variant="body2" sx={{ mb: 1 }} data-testid="catalog-display">
        Catalog: {catalogName} (fixed at creation)
      </Typography>
      <Divider sx={{ my: 1 }} />
      <Typography variant="subtitle2" sx={{ my: 1 }}>
        Roster
      </Typography>
      <CampaignRoster campaign={campaign} onRemove={setRemoveTarget} />
      <ConfirmDialog
        open={Boolean(removeTarget)}
        title="Remove this Scout from the roster?"
        onClose={() => setRemoveTarget(null)}
        onConfirm={handleConfirmRemove}
        confirmLabel="Remove"
        confirmColor="error"
      >
        <Typography>
          Removing blocks new signups but preserves existing signups, work, credit, orders, and history.
        </Typography>
      </ConfirmDialog>
    </CardContent>
  );
};

const CampaignsLoadError: React.FC<{ error: Error; onRetry: () => void }> = ({ error, onRetry }) => (
  <Box>
    <ErrorAlert message={error.message || 'Unable to load campaigns.'} />
    <Button variant="outlined" onClick={() => void onRetry()}>
      Retry
    </Button>
  </Box>
);

interface CampaignRowProps {
  campaign: GqlUnitCampaignAdmin;
  isSelected: boolean;
  onSelect: (unitCampaignId: string) => void;
}

const CampaignRow: React.FC<CampaignRowProps> = ({ campaign, isSelected, onSelect }) => (
  <Card variant={isSelected ? 'outlined' : 'elevation'}>
    <CardActionArea onClick={() => onSelect(campaign.unitCampaignId)} sx={{ py: 1.5, px: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography>
          {campaign.campaignName} ({campaign.campaignYear})
        </Typography>
        <Chip size="small" color={campaign.isActive ? 'success' : 'default'} label={campaign.isActive ? 'Active' : 'Inactive'} />
      </Box>
    </CardActionArea>
  </Card>
);

const CampaignList: React.FC<{
  campaigns: GqlUnitCampaignAdmin[];
  selectedId: string | null;
  onSelect: (unitCampaignId: string) => void;
}> = ({ campaigns, selectedId, onSelect }) =>
  campaigns.length === 0 ? (
    <EmptyState title="No campaigns yet" message="Create a Show & Sell campaign for this unit." />
  ) : (
    <Stack spacing={1} sx={{ mb: 3 }}>
      {campaigns.map((c) => (
        <CampaignRow key={c.unitCampaignId} campaign={c} isSelected={c.unitCampaignId === selectedId} onSelect={onSelect} />
      ))}
    </Stack>
  );

const UnitCampaignsSection: React.FC<{ unitId: string }> = ({ unitId }) => {
  const { data, loading, error, refetch } = useQuery<{
    unitCampaigns: { items: GqlUnitCampaignAdmin[] };
  }>(UNIT_CAMPAIGNS, { variables: { unitId } });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<GqlUnitCampaignAdmin | null>(null);

  if (loading) return <LoadingState minHeight="200px" />;
  if (error) return <CampaignsLoadError error={error} onRetry={() => void refetch()} />;

  const campaigns = selectUnitCampaigns(data);
  const selected = campaigns.find((c) => c.unitCampaignId === selectedId);

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">Campaigns</Typography>
        <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
          Create campaign
        </Button>
      </Box>
      <CampaignList campaigns={campaigns} selectedId={selectedId} onSelect={setSelectedId} />
      {selected && <Card><UnitCampaignDetail campaign={selected} onEdit={setEditing} /></Card>}
      <CreateUnitCampaignDialog
        open={createOpen}
        unitId={unitId}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => setSelectedId(id)}
      />
      {editing && <EditUnitCampaignDialog campaign={editing} unitId={unitId} onClose={() => setEditing(null)} />}
    </Box>
  );
};

export default UnitCampaignsSection;
