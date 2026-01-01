/**
 * CampaignSettingsPage - Campaign-specific settings only
 *
 * Note: Profile-level settings (invites, shares, profile deletion) have been moved
 * to ProfileManagementPage to clarify that invites belong to profiles, not campaigns.
 */

import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@apollo/client/react";
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
} from "@mui/material";
import {
  Delete as DeleteIcon,
  Warning as WarningIcon,
} from "@mui/icons-material";
import {
  GET_CAMPAIGN,
  UPDATE_CAMPAIGN,
  DELETE_CAMPAIGN,
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
} from "../lib/graphql";
import { ensureCampaignId, ensureCatalogId } from "../lib/ids";

interface Campaign {
  campaignId: string;
  campaignName: string;
  campaignYear: number;
  startDate: string;
  endDate?: string;
  catalogId: string;
  profileId: string;
  sharedCampaignCode?: string;
  unitType?: string;
  unitNumber?: number;
  city?: string;
  state?: string;
}

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
  isDeleted?: boolean;
}

export const CampaignSettingsPage: React.FC = () => {
  const { profileId: encodedProfileId, campaignId: encodedCampaignId } = useParams<{
    profileId: string;
    campaignId: string;
  }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const campaignId = encodedCampaignId ? decodeURIComponent(encodedCampaignId) : "";
  const dbCampaignId = ensureCampaignId(campaignId);
  const navigate = useNavigate();
  const [campaignName, setCampaignName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [catalogId, setCatalogId] = useState("");
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [unitChangeConfirmOpen, setUnitChangeConfirmOpen] = useState(false);

  // Fetch campaign
  const {
    data: campaignData,
    loading,
    refetch,
  } = useQuery<{ getCampaign: Campaign }>(GET_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: !dbCampaignId,
  });

  // Fetch catalogs
  const { data: publicCatalogsData } = useQuery<{
    listPublicCatalogs: Catalog[];
  }>(LIST_PUBLIC_CATALOGS);

  const { data: myCatalogsData } = useQuery<{
    listMyCatalogs: Catalog[];
  }>(LIST_MY_CATALOGS);

  const publicCatalogs = publicCatalogsData?.listPublicCatalogs || [];
  const myCatalogs = myCatalogsData?.listMyCatalogs || [];
  const allCatalogs = [...publicCatalogs, ...myCatalogs].filter(
    (c) => c.isDeleted !== true,
  );

  // Initialize form when campaign loads
  React.useEffect(() => {
    if (campaignData?.getCampaign) {
      setCampaignName(campaignData.getCampaign.campaignName);
      setStartDate(campaignData.getCampaign.startDate?.split("T")[0] || "");
      setEndDate(campaignData.getCampaign.endDate?.split("T")[0] || "");
      setCatalogId(campaignData.getCampaign.catalogId);
    }
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
      navigate(`/scouts/${encodeURIComponent(profileId || "")}/campaigns`);
    },
  });

  const campaign = campaignData?.getCampaign;

  // Check if unit-related fields have changed (campaignName, catalogId)
  const hasUnitRelatedChanges =
    campaign?.sharedCampaignCode &&
    (campaignName !== campaign.campaignName || catalogId !== campaign.catalogId);

  const handleSaveClick = () => {
    if (hasUnitRelatedChanges) {
      setUnitChangeConfirmOpen(true);
    } else {
      handleSaveChanges();
    }
  };

  const handleSaveChanges = async () => {
    setUnitChangeConfirmOpen(false);
    if (!campaignId || !campaignName.trim() || !catalogId) return;

    await updateCampaign({
      variables: {
        input: {
          campaignId: dbCampaignId,
          campaignName: campaignName.trim(),
          startDate: startDate || undefined,
          endDate: endDate || undefined,
          catalogId: ensureCatalogId(catalogId),
        },
      },
    });
  };

  const handleDeleteCampaign = async () => {
    if (!campaignId) return;
    await deleteCampaign({ variables: { campaignId: dbCampaignId } });
  };

  if (loading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="200px"
      >
        <CircularProgress />
      </Box>
    );
  }

  const hasChanges =
    campaign &&
    (campaignName !== campaign.campaignName ||
      startDate !== (campaign.startDate?.split("T")[0] || "") ||
      endDate !== (campaign.endDate?.split("T")[0] || "") ||
      catalogId !== campaign.catalogId);

  return (
    <Box>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mb: 3 }}
      >
        <Typography variant="h5">Campaign Settings</Typography>
        <Button
          variant="text"
          color="primary"
          onClick={() =>
            navigate(`/scouts/${encodeURIComponent(profileId)}/manage`)
          }
        >
          Manage Scout
        </Button>
      </Stack>

      {/* Basic Settings */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Basic Information
        </Typography>

        {/* Warning for sharedCampaign-created campaigns */}
        {campaign?.sharedCampaignCode && (
          <Alert severity="warning" icon={<WarningIcon />} sx={{ mb: 3 }}>
            <AlertTitle>Shared Campaign</AlertTitle>
            This campaign was created from a shared campaign link. Changing the catalog,
            campaign name, or unit information may cause this campaign to no longer
            appear correctly in campaign reports for your unit.
          </Alert>
        )}

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
            <Select
              value={catalogId}
              onChange={(e) => setCatalogId(e.target.value)}
              label="Product Catalog"
            >
              {allCatalogs.map((catalog) => (
                <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
                  {catalog.catalogName}
                  {catalog.catalogType === "ADMIN_MANAGED" && " (Official)"}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button
            variant="contained"
            onClick={handleSaveClick}
            disabled={!hasChanges || updating}
          >
            {updating ? "Saving..." : "Save Changes"}
          </Button>
        </Stack>
      </Paper>

      {/* Danger Zone */}
      <Paper
        sx={{
          p: 3,
          borderColor: "error.main",
          borderWidth: 1,
          borderStyle: "solid",
        }}
      >
        <Typography variant="h6" gutterBottom color="error">
          Danger Zone
        </Typography>
        <Typography variant="body2" color="text.secondary" paragraph>
          Deleting this campaign will permanently remove all orders and data. This
          action cannot be undone.
        </Typography>
        <Button
          variant="outlined"
          color="error"
          startIcon={<DeleteIcon />}
          onClick={() => setDeleteConfirmOpen(true)}
        >
          Delete Campaign
        </Button>
      </Paper>

      {/* Delete Campaign Confirmation Dialog */}
      <Dialog
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
      >
        <DialogTitle>Delete Campaign?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete "{campaign?.campaignName}"? All orders
            and data will be permanently deleted. This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmOpen(false)}>Cancel</Button>
          <Button
            onClick={handleDeleteCampaign}
            color="error"
            variant="contained"
          >
            Delete Permanently
          </Button>
        </DialogActions>
      </Dialog>

      {/* Unit-Related Changes Confirmation Dialog */}
      <Dialog
        open={unitChangeConfirmOpen}
        onClose={() => setUnitChangeConfirmOpen(false)}
      >
        <DialogTitle>Confirm Changes to Shared Campaign</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            <AlertTitle>This may affect unit reports</AlertTitle>
            You are changing the campaign name or catalog of a campaign that was
            created from a campaign link.
          </Alert>
          <Typography>
            These changes may cause this campaign to no longer appear correctly in
            unit reports for your unit. Are you sure you want to continue?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUnitChangeConfirmOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSaveChanges}
            color="warning"
            variant="contained"
          >
            Save Anyway
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
