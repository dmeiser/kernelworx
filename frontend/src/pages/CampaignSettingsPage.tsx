/**
 * CampaignSettingsPage - Campaign-specific settings only
 *
 * Note: Profile-level settings (invites, shares, profile deletion) have been moved
 * to ProfileManagementPage to clarify that invites belong to profiles, not campaigns.
 */

import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@apollo/client/react';
import {
  Box,
  Typography,
  Paper,
  Stack,
  TextField,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  AlertTitle,
} from '@mui/material';
import { Delete as DeleteIcon, Warning as WarningIcon } from '@mui/icons-material';
import { GET_CAMPAIGN, UPDATE_CAMPAIGN, DELETE_CAMPAIGN, LIST_MANAGED_CATALOGS, LIST_MY_CATALOGS } from '../lib/graphql';
import { ensureCampaignId, ensureCatalogId, toUrlId } from '../lib/ids';
import type { Campaign, Catalog } from '../types';

// Helper to extract date part from ISO string
const extractDatePart = (isoDate: string | undefined): string => isoDate?.split('T')[0] || '';

// Helper to safely decode URL component
const decodeUrlParam = (encoded: string | undefined): string => (encoded ? decodeURIComponent(encoded) : '');

// Helper to get catalogs with fallback
const getPublicCatalogs = (data: { listManagedCatalogs?: Catalog[] } | undefined): Catalog[] =>
  data?.listManagedCatalogs || [];

const getMyCatalogs = (data: { listMyCatalogs?: Catalog[] } | undefined): Catalog[] => data?.listMyCatalogs || [];

// Helper to get campaign from query data
const getCampaign = (data: { getCampaign: Campaign } | undefined): Campaign | undefined => data?.getCampaign;

// Helper to check if unit-related fields have changed
const hasUnitFieldsChanged = (campaign: Campaign | undefined, formName: string, formCatalog: string): boolean => {
  if (!campaign?.sharedCampaignCode) return false;
  return formName !== campaign.campaignName || formCatalog !== campaign.catalogId;
};

// Helper to validate save inputs
const canSave = (campaignId: string, campaignName: string, catalogId: string): boolean =>
  Boolean(campaignId && campaignName.trim() && catalogId);

// Helper to build update input
const buildUpdateInput = (
  dbCampaignId: string,
  campaignName: string,
  startDate: string,
  endDate: string,
  catalogId: string,
) => ({
  campaignId: dbCampaignId,
  campaignName: campaignName.trim(),
  startDate: startDate || undefined,
  endDate: endDate || undefined,
  catalogId: ensureCatalogId(catalogId),
});
// Helper to determine if query should be skipped
const shouldSkipCampaignQuery = (id: string): boolean => !id;

// Helper to check if delete is allowed
const canDeleteCampaign = (campaignId: string): boolean => Boolean(campaignId);

// Helper to check if campaign has shared campaign code
const hasSharedCampaignCode = (campaign: Campaign | undefined): boolean => Boolean(campaign?.sharedCampaignCode);

// Type for save click action result
type SaveAction = 'confirm' | 'save';

// Helper to determine save action based on changes
const getSaveAction = (hasUnitRelatedChanges: boolean): SaveAction => (hasUnitRelatedChanges ? 'confirm' : 'save');

// Helper component for loading state
const LoadingState: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="200px">
    <CircularProgress />
  </Box>
);

// Helper to conditionally update campaign
const maybeUpdateCampaign = async (
  isValid: boolean,
  updateCampaign: (options: { variables: { input: object } }) => Promise<unknown>,
  input: object,
): Promise<void> => {
  if (isValid) {
    await updateCampaign({ variables: { input } });
  }
};

// Helper to conditionally delete campaign
const maybeDeleteCampaign = async (
  canDelete: boolean,
  deleteCampaign: (options: { variables: { campaignId: string } }) => Promise<unknown>,
  campaignId: string,
): Promise<void> => {
  if (canDelete) {
    await deleteCampaign({ variables: { campaignId } });
  }
};

// Helper component for shared campaign warning
const SharedCampaignWarning: React.FC<{ campaign: Campaign | undefined }> = ({ campaign }) =>
  hasSharedCampaignCode(campaign) ? (
    <Alert severity="warning" icon={<WarningIcon />} sx={{ mb: 3 }}>
      <AlertTitle>Shared Campaign</AlertTitle>
      This campaign was created from a shared campaign link. Changing the catalog, campaign name, or unit information
      may cause this campaign to no longer appear correctly in campaign reports for your unit.
    </Alert>
  ) : null;

// Helper to get catalog type suffix
const getCatalogTypeSuffix = (catalogType: string): string => (catalogType === 'ADMIN_MANAGED' ? ' (Official)' : '');

// Helper to check if campaign form fields have changed
const checkFormChanges = (
  formName: string,
  formStart: string,
  formEnd: string,
  formCatalog: string,
  campaign: Campaign | undefined,
): boolean => {
  if (!campaign) return false;
  const origStart = extractDatePart(campaign.startDate);
  const origEnd = extractDatePart(campaign.endDate);
  return (
    formName !== campaign.campaignName ||
    formStart !== origStart ||
    formEnd !== origEnd ||
    formCatalog !== campaign.catalogId
  );
};

// Helper to get all non-deleted catalogs
const getAllCatalogs = (publicCatalogs: Catalog[], myCatalogs: Catalog[]): Catalog[] =>
  [...publicCatalogs, ...myCatalogs].filter((c) => c.isDeleted !== true);

// Helper to initialize form fields from campaign
const initializeFormFromCampaign = (
  campaign: Campaign | undefined,
  setCampaignName: (v: string) => void,
  setStartDate: (v: string) => void,
  setEndDate: (v: string) => void,
  setCatalogId: (v: string) => void,
): void => {
  if (campaign) {
    setCampaignName(campaign.campaignName);
    setStartDate(extractDatePart(campaign.startDate));
    setEndDate(extractDatePart(campaign.endDate));
    setCatalogId(campaign.catalogId);
  }
};

// eslint-disable-next-line complexity -- Component already well modularized; complexity 6 is acceptable
export const CampaignSettingsPage: React.FC = () => {
  const { profileId: encodedProfileId, campaignId: encodedCampaignId } = useParams<{
    profileId: string;
    campaignId: string;
  }>();
  const profileId = decodeUrlParam(encodedProfileId);
  const campaignId = decodeUrlParam(encodedCampaignId);
  const dbCampaignId = ensureCampaignId(campaignId);
  const navigate = useNavigate();
  const [campaignName, setCampaignName] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [catalogId, setCatalogId] = useState('');
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [unitChangeConfirmOpen, setUnitChangeConfirmOpen] = useState(false);

  // Fetch campaign
  const {
    data: campaignData,
    loading,
    refetch,
  } = useQuery<{ getCampaign: Campaign }>(GET_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: shouldSkipCampaignQuery(dbCampaignId ?? ''),
  });

  // Fetch catalogs
  const { data: publicCatalogsData } = useQuery<{
    listManagedCatalogs: Catalog[];
  }>(LIST_MANAGED_CATALOGS);

  const { data: myCatalogsData } = useQuery<{
    listMyCatalogs: Catalog[];
  }>(LIST_MY_CATALOGS);

  const publicCatalogs = getPublicCatalogs(publicCatalogsData);
  const myCatalogs = getMyCatalogs(myCatalogsData);
  const allCatalogs = getAllCatalogs(publicCatalogs, myCatalogs);

  // Initialize form when campaign loads
  React.useEffect(() => {
    const c = getCampaign(campaignData);
    initializeFormFromCampaign(c, setCampaignName, setStartDate, setEndDate, setCatalogId);
  }, [campaignData]);

  // Update campaign mutation
  const [updateCampaign, { loading: updating }] = useMutation(UPDATE_CAMPAIGN, {
    onCompleted: () => {
      refetch();
    },
  });

  // Delete campaign mutation
  const [deleteCampaign] = useMutation(DELETE_CAMPAIGN, {
    onCompleted: () => {
      navigate(`/scouts/${toUrlId(profileId)}/campaigns`);
    },
  });

  const campaign = getCampaign(campaignData);

  // Check if unit-related fields have changed (campaignName, catalogId)
  const hasUnitRelatedChanges = hasUnitFieldsChanged(campaign, campaignName, catalogId);

  const handleSaveClick = () => {
    const action = getSaveAction(hasUnitRelatedChanges);
    const actions: Record<SaveAction, () => void> = {
      confirm: () => setUnitChangeConfirmOpen(true),
      save: handleSaveChanges,
    };
    actions[action]();
  };

  const handleSaveChanges = async () => {
    setUnitChangeConfirmOpen(false);
    const isValid = canSave(campaignId, campaignName, catalogId);
    if (!dbCampaignId) return;
    const input = buildUpdateInput(dbCampaignId, campaignName, startDate, endDate, catalogId);
    await maybeUpdateCampaign(isValid, updateCampaign, input);
  };

  const handleDeleteCampaign = async () => {
    const canDelete = canDeleteCampaign(campaignId);
    if (!dbCampaignId) return;
    await maybeDeleteCampaign(canDelete, deleteCampaign, dbCampaignId);
  };

  if (loading) {
    return <LoadingState />;
  }

  const hasChanges = checkFormChanges(campaignName, startDate, endDate, catalogId, campaign);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Typography variant="h5">Campaign Settings</Typography>
        <Button variant="text" color="primary" onClick={() => navigate(`/scouts/${toUrlId(profileId)}/manage`)}>
          Manage Scout
        </Button>
      </Stack>

      {/* Basic Settings */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Basic Information
        </Typography>

        {/* Warning for sharedCampaign-created campaigns */}
        <SharedCampaignWarning campaign={campaign} />

        <Stack spacing={3}>
          <TextField
            fullWidth
            label="Campaign Name"
            value={campaignName}
            onChange={(e) => setCampaignName(e.target.value)}
            disabled={updating}
          />
          <TextField
            fullWidth
            label="Start Date"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            disabled={updating}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            fullWidth
            label="End Date (Optional)"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            disabled={updating}
            InputLabelProps={{ shrink: true }}
          />
          <FormControl fullWidth disabled={updating}>
            <InputLabel>Product Catalog</InputLabel>
            <Select value={catalogId ?? ''} onChange={(e) => setCatalogId(e.target.value)} label="Product Catalog">
              {allCatalogs.map((catalog) => (
                <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
                  {catalog.catalogName}
                  {getCatalogTypeSuffix(catalog.catalogType ?? '')}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button variant="contained" onClick={handleSaveClick} disabled={!hasChanges || updating}>
            {updating ? 'Saving...' : 'Save Changes'}
          </Button>
        </Stack>
      </Paper>

      {/* Danger Zone */}
      <Paper
        sx={{
          p: 3,
          borderColor: 'error.main',
          borderWidth: 1,
          borderStyle: 'solid',
        }}
      >
        <Typography variant="h6" gutterBottom color="error">
          Danger Zone
        </Typography>
        <Typography variant="body2" color="text.secondary" paragraph>
          Deleting this campaign will permanently remove all orders and data. This action cannot be undone.
        </Typography>
        <Button variant="outlined" color="error" startIcon={<DeleteIcon />} onClick={() => setDeleteConfirmOpen(true)}>
          Delete Campaign
        </Button>
      </Paper>

      {/* Delete Campaign Confirmation Dialog */}
      <Dialog open={deleteConfirmOpen} onClose={() => setDeleteConfirmOpen(false)}>
        <DialogTitle>Delete Campaign?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete "{campaign?.campaignName}"? All orders and data will be permanently deleted.
            This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmOpen(false)}>Cancel</Button>
          <Button onClick={handleDeleteCampaign} color="error" variant="contained">
            Delete Permanently
          </Button>
        </DialogActions>
      </Dialog>

      {/* Unit-Related Changes Confirmation Dialog */}
      <Dialog open={unitChangeConfirmOpen} onClose={() => setUnitChangeConfirmOpen(false)}>
        <DialogTitle>Confirm Changes to Shared Campaign</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            <AlertTitle>This may affect unit reports</AlertTitle>
            You are changing the campaign name or catalog of a campaign that was created from a campaign link.
          </Alert>
          <Typography>
            These changes may cause this campaign to no longer appear correctly in unit reports for your unit. Are you
            sure you want to continue?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUnitChangeConfirmOpen(false)}>Cancel</Button>
          <Button onClick={handleSaveChanges} color="warning" variant="contained">
            Save Anyway
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
