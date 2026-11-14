/**
 * One Unit Campaign: join code, settings, roster, and catalog (Show & Sell §1.6.3).
 *
 * The catalog line is the part reviewers look for. It is displayed, never selectable:
 * inventory balances, Order origin, and event product identity all key on the catalog
 * chosen at creation, so re-pointing an existing campaign would silently re-point that
 * history too. Selling something else means another campaign, and the copy says that
 * where the chooser would have been. A `catalogId` smuggled into an update is refused
 * by the server, and the refusal is shown rather than retried (catalog-change
 * rejection).
 */

import React, { useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  IconButton,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { GET_UNIT_CAMPAIGN, GET_UNIT_CAMPAIGN_CATALOG, UPDATE_UNIT_CAMPAIGN } from '../lib/graphql';
import { CampaignCatalogTable } from '../components/CampaignCatalogTable';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ErrorAlert, ErrorNote } from '../components/ErrorAlert';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { QueryGate } from '../components/QueryGate';
import { UnitRosterPanel } from '../components/UnitRosterPanel';
import { SHOW_SELL_BASE, createWriteIntent, newIdempotencyKey, refreshQuery, unitCampaignStatusLabel } from '../lib/units';
import type {
  GqlGetUnitCampaignCatalogQuery,
  GqlGetUnitCampaignQuery,
  GqlUnitCampaignAdmin,
} from '../types/graphql-generated';

type CampaignTab = 'roster' | 'catalog';
type Campaign = GqlUnitCampaignAdmin;

interface PendingToggle {
  isActive: boolean;
  idempotencyKey: string;
}

function readCampaign(data: GqlGetUnitCampaignQuery | undefined): Campaign | null {
  return data?.unitCampaign ?? null;
}

export const UnitCampaignWorkspacePage: React.FC = () => {
  const { unitCampaignId = '' } = useParams();
  const [tab, setTab] = useState<CampaignTab>('roster');
  const campaignQuery = useQuery<GqlGetUnitCampaignQuery>(GET_UNIT_CAMPAIGN, { variables: { unitCampaignId } });

  if (campaignQuery.loading && !campaignQuery.data) return <LoadingState />;
  return (
    <CampaignWorkspaceBody
      campaign={readCampaign(campaignQuery.data)}
      unitCampaignId={unitCampaignId}
      tab={tab}
      onTabChange={setTab}
      onCampaignChanged={campaignQuery.refetch}
    />
  );
};

/**
 * "Not yours" and "no longer here" answer identically: the query is admin-only, and a
 * difference between the two would let someone confirm that a campaign exists.
 */
const CampaignWorkspaceBody: React.FC<{
  campaign: Campaign | null;
  unitCampaignId: string;
  tab: CampaignTab;
  onTabChange: (tab: CampaignTab) => void;
  onCampaignChanged: () => Promise<unknown>;
}> = ({ campaign, unitCampaignId, tab, onTabChange, onCampaignChanged }) => {
  if (!campaign) return <ErrorAlert message="This campaign is not yours, or it no longer exists." />;
  return (
    <>
      <CampaignHeader campaign={campaign} />
      <JoinCodeCard campaign={campaign} />
      <CampaignSettingsCard campaign={campaign} onSaved={onCampaignChanged} />
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={tab} onChange={(_event, value: CampaignTab) => onTabChange(value)} aria-label="Campaign sections">
          <Tab label="Roster" value="roster" data-testid="tab-roster" />
          <Tab label="Catalog" value="catalog" data-testid="tab-catalog" />
        </Tabs>
      </Box>
      <CampaignTabPanel tab={tab} unitCampaignId={unitCampaignId} />
    </>
  );
};

const CampaignHeader: React.FC<{ campaign: Campaign }> = ({ campaign }) => {
  const navigate = useNavigate();
  return (
    <PageHeader
      title={campaign.campaignName}
      subtitle={`${campaign.campaignYear} · ${unitCampaignStatusLabel(campaign.isActive)}`}
      backButton={{
        onClick: () => void navigate(`${SHOW_SELL_BASE}/units/${campaign.unitId}`),
        label: 'Back to Unit',
        'aria-label': 'Back to Unit',
      }}
      action={
        <Chip
          label={unitCampaignStatusLabel(campaign.isActive)}
          color={campaign.isActive ? 'success' : 'default'}
          data-testid="campaign-status"
        />
      }
    />
  );
};

const CampaignTabPanel: React.FC<{ tab: CampaignTab; unitCampaignId: string }> = ({ tab, unitCampaignId }) => {
  if (tab === 'catalog') return <CampaignCatalogCard unitCampaignId={unitCampaignId} />;
  return <UnitRosterPanel unitCampaignId={unitCampaignId} />;
};

const JoinCodeCard: React.FC<{ campaign: Campaign }> = ({ campaign }) => {
  const [revealed, setRevealed] = useState(true);
  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="subtitle1">
            Join code: <strong data-testid="join-code">{revealed ? campaign.joinCode : '••••••••••••••••'}</strong>
          </Typography>
          <IconButton
            size="small"
            aria-label={revealed ? 'Hide join code' : 'Show join code'}
            data-testid="reveal-join-code"
            onClick={() => setRevealed((value) => !value)}
          >
            <VisibilityIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            aria-label="Copy join code"
            data-testid="copy-join-code"
            onClick={() => void navigator.clipboard?.writeText(campaign.joinCode)}
          >
            <ContentCopyIcon fontSize="small" />
          </IconButton>
        </Stack>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Scouts enter this code on the join screen. It stays valid while the campaign is open, and one code serves the
          whole roster.
        </Typography>
      </CardContent>
    </Card>
  );
};

/**
 * The two fields a campaign owns that may change — name and year — plus open/close.
 * The catalog is named as fixed in this same card, because that is where an admin
 * hoping to change it would look for the control.
 */
const CampaignSettingsCard: React.FC<{ campaign: Campaign; onSaved: () => Promise<unknown> }> = ({
  campaign,
  onSaved,
}) => {
  const [name, setName] = useState(campaign.campaignName);
  const [year, setYear] = useState(campaign.campaignYear);
  const [error, setError] = useState<string | null>(null);
  const [pendingToggle, setPendingToggle] = useState<PendingToggle | null>(null);
  // One key per edit intent: the same body sent again replays the original write,
  // and a different body is a different write. The card outlives its saves, so the
  // key cannot be one per mount.
  const intent = useRef(createWriteIntent());
  const [updateCampaign, { loading }] = useMutation(UPDATE_UNIT_CAMPAIGN);

  const save = async () => {
    setError(null);
    try {
      const body = {
        unitCampaignId: campaign.unitCampaignId,
        campaignName: name.trim(),
        campaignYear: year,
        version: { expectedVersion: campaign.version },
      };
      await updateCampaign({
        variables: { input: { ...body, idempotency: { idempotencyKey: intent.current.keyFor(body) } } },
      });
    } catch (mutationError) {
      setError(describeUpdateFailure(mutationError, 'Could not save the campaign settings.'));
    }
    await refreshQuery(onSaved);
  };

  const applyToggle = async (toggle: PendingToggle) => {
    setPendingToggle(null);
    try {
      await updateCampaign({
        variables: {
          input: {
            unitCampaignId: campaign.unitCampaignId,
            isActive: toggle.isActive,
            version: { expectedVersion: campaign.version },
            idempotency: { idempotencyKey: toggle.idempotencyKey },
          },
        },
      });
    } catch (mutationError) {
      setError(describeUpdateFailure(mutationError, 'Could not change this campaign.'));
    }
    await refreshQuery(onSaved);
  };

  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Campaign settings
        </Typography>
        <Stack spacing={2}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="Campaign name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={loading}
              data-testid="campaign-name"
              sx={{ flexGrow: 1 }}
            />
            <TextField
              label="Campaign year"
              value={year}
              onChange={(event) => setYear(Number(event.target.value))}
              disabled={loading}
              inputMode="numeric"
              data-testid="campaign-year"
            />
          </Stack>
          <CatalogIsFixedNote catalogId={campaign.catalogId} />
          <ErrorNote message={error} />
          <Stack direction="row" spacing={2}>
            <SaveSettingsButton loading={loading} disabled={!settingsChanged(name, year, campaign)} onSave={save} />
            <ActiveToggleButton
              isActive={campaign.isActive}
              onAskToggle={(isActive) => setPendingToggle({ isActive, idempotencyKey: newIdempotencyKey() })}
            />
          </Stack>
        </Stack>
      </CardContent>
      <ToggleConfirm pending={pendingToggle} onCancel={() => setPendingToggle(null)} onConfirm={applyToggle} />
    </Card>
  );
};

function settingsChanged(name: string, year: number, campaign: Campaign): boolean {
  return name.trim() !== campaign.campaignName || year !== campaign.campaignYear;
}

function describeUpdateFailure(mutationError: unknown, fallback: string): string {
  return (mutationError as Error).message || fallback;
}

const CatalogIsFixedNote: React.FC<{ catalogId: string }> = ({ catalogId }) => (
  <Alert severity="info" data-testid="catalog-immutable-note">
    Catalog: <strong data-testid="catalog-id">{catalogId}</strong>. This cannot change after creation — to sell from
    another catalog, create another campaign.
  </Alert>
);

const SaveSettingsButton: React.FC<{ loading: boolean; disabled: boolean; onSave: () => Promise<void> }> = ({
  loading,
  disabled,
  onSave,
}) => (
  <Button
    variant="contained"
    onClick={() => void onSave()}
    disabled={loading || disabled}
    data-testid="save-campaign"
  >
    {loading ? 'Saving…' : 'Save settings'}
  </Button>
);

const ActiveToggleButton: React.FC<{ isActive: boolean; onAskToggle: (isActive: boolean) => void }> = ({
  isActive,
  onAskToggle,
}) => (
  <Button
    variant="outlined"
    color={isActive ? 'error' : 'primary'}
    onClick={() => onAskToggle(!isActive)}
    data-testid="toggle-campaign"
  >
    {isActive ? 'Close campaign' : 'Open campaign'}
  </Button>
);

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

/** Opening and closing say the same thing about what is *not* touched; stated once, both directions. */
interface ToggleWording {
  open: boolean;
  title: string;
  label: string;
  color: 'warning' | 'primary';
  body: string;
}

function toggleWordings(pending: PendingToggle | null): ToggleWording {
  if (!pending) return { open: false, title: '', label: '', color: 'primary', body: '' };
  if (pending.isActive) {
    return {
      open: true,
      title: 'Open this campaign?',
      label: 'Open campaign',
      color: 'primary',
      body: 'Opening lets Scouts with the join code participate again. Nothing else changes.',
    };
  }
  return {
    open: true,
    title: 'Close this campaign?',
    label: 'Close campaign',
    color: 'warning',
    body: 'Closing stops new joins and new participation. Roster history, orders, and obligations stay as they are.',
  };
}

const CampaignCatalogCard: React.FC<{ unitCampaignId: string }> = ({ unitCampaignId }) => {
  const catalog = useQuery<GqlGetUnitCampaignCatalogQuery>(GET_UNIT_CAMPAIGN_CATALOG, { variables: { unitCampaignId } });
  const view = catalog.data?.unitCampaignCatalog ?? null;
  return (
    <QueryGate
      query={catalog}
      loading={<LoadingState minHeight="200px" />}
      failure={<ErrorAlert message="Could not load this campaign's catalog." />}
    >
      <CatalogBody catalog={view} />
    </QueryGate>
  );
};

const CatalogBody: React.FC<{ catalog: GqlGetUnitCampaignCatalogQuery['unitCampaignCatalog'] }> = ({ catalog }) => {
  if (!catalog) return <ErrorAlert message="This campaign has no catalog." />;
  return <CampaignCatalogTable catalog={catalog} />;
};
