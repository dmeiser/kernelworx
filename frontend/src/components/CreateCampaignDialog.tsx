/**
 * CreateCampaignDialog component - Dialog for creating a new sales campaign
 */

import React, { useState } from "react";
import { useQuery } from "@apollo/client/react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Stack,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  CircularProgress,
} from "@mui/material";
import { LIST_PUBLIC_CATALOGS, LIST_MY_CATALOGS } from "../lib/graphql";

interface CreateCampaignDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (
    campaignName: string,
    campaignYear: number,
    catalogId: string,
    startDate?: string,
    endDate?: string,
  ) => Promise<void>;
}

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
  isDeleted?: boolean;
}

export const CreateCampaignDialog: React.FC<CreateCampaignDialogProps> = ({
  open,
  onClose,
  onSubmit,
}) => {
  const [campaignName, setCampaignName] = useState("");
  const [campaignYear, setCampaignYear] = useState(new Date().getFullYear());
  const [catalogId, setCatalogId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);

  // Fetch catalogs
  const { data: publicCatalogsData, loading: publicLoading } = useQuery<{
    listPublicCatalogs: Catalog[];
  }>(LIST_PUBLIC_CATALOGS);

  const { data: myCatalogsData, loading: myLoading } = useQuery<{
    listMyCatalogs: Catalog[];
  }>(LIST_MY_CATALOGS);

  const publicCatalogs = publicCatalogsData?.listPublicCatalogs || [];
  const myCatalogs = myCatalogsData?.listMyCatalogs || [];

  // Deduplicate by catalogId and separate into sections, filter deleted catalogs
  // Catalogs that appear in both lists (user owns a public catalog) go to "My Catalogs"
  const myIdSet = new Set(myCatalogs.map((c) => c.catalogId));
  const filteredPublicCatalogs = publicCatalogs.filter(
    (c) => !myIdSet.has(c.catalogId) && c.isDeleted !== true,
  );
  const filteredMyCatalogs = myCatalogs.filter((c) => c.isDeleted !== true);

  const catalogsLoading = publicLoading || myLoading;

  const handleSubmit = async () => {
    if (!campaignName.trim() || !catalogId) return;

    setLoading(true);
    try {
      await onSubmit(
        campaignName.trim(),
        campaignYear,
        catalogId,
        startDate || undefined,
        endDate || undefined,
      );
      // Reset form
      setCampaignName("");
      setCampaignYear(new Date().getFullYear());
      setCatalogId("");
      setStartDate("");
      setEndDate("");
      onClose();
    } catch (error) {
      console.error("Failed to create campaign:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      setCampaignName("");
      setCampaignYear(new Date().getFullYear());
      setCatalogId("");
      setStartDate("");
      setEndDate("");
      onClose();
    }
  };

  const isFormValid = campaignName.trim() && catalogId;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create New Sales Campaign</DialogTitle>
      <DialogContent>
        <Stack spacing={3} pt={1}>
          {/* Campaign Name */}
          <TextField
            fullWidth
            label="Campaign Name"
            value={campaignName}
            onChange={(e) => setCampaignName(e.target.value)}
            disabled={loading}
            helperText="Name for this sales campaign (e.g., Fall 2025, Spring Fundraiser)"
          />

          {/* Campaign Year */}
          <TextField
            fullWidth
            label="Year"
            type="number"
            value={campaignYear}
            onChange={(e) => setCampaignYear(parseInt(e.target.value, 10))}
            disabled={loading}
            inputProps={{
              min: 2020,
              max: new Date().getFullYear() + 5,
              step: 1,
            }}
            helperText="Year of this sales campaign"
          />

          {/* Start Date */}
          <TextField
            fullWidth
            label="Start Date (Optional)"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            disabled={loading}
            InputLabelProps={{
              shrink: true,
            }}
            slotProps={{
              input: {
                inputProps: {
                  max: endDate || undefined,
                },
              },
            }}
            helperText="When sales campaign begins"
          />

          {/* End Date */}
          <TextField
            fullWidth
            label="End Date (Optional)"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            disabled={loading}
            InputLabelProps={{
              shrink: true,
            }}
            slotProps={{
              input: {
                inputProps: {
                  min: startDate || undefined,
                },
              },
            }}
            helperText="When sales campaign ends"
          />

          {/* Catalog Selection */}
          <FormControl fullWidth disabled={loading || catalogsLoading}>
            <InputLabel>Product Catalog</InputLabel>
            <Select
              value={catalogId}
              onChange={(e) => setCatalogId(e.target.value)}
              label="Product Catalog"
              MenuProps={{
                slotProps: {
                  paper: {
                    sx: {
                      maxHeight: 300,
                    },
                  },
                },
              }}
            >
              {catalogsLoading && (
                <MenuItem disabled>
                  <CircularProgress size={20} sx={{ mr: 1 }} />
                  Loading catalogs...
                </MenuItem>
              )}
              {!catalogsLoading &&
                filteredMyCatalogs.length === 0 &&
                filteredPublicCatalogs.length === 0 && (
                  <MenuItem disabled>No catalogs available</MenuItem>
                )}

              {/* My Catalogs Section */}
              {filteredMyCatalogs.length > 0 && [
                <MenuItem
                  key="my-header"
                  disabled
                  sx={{
                    fontWeight: 600,
                    backgroundColor: "#f5f5f5",
                    opacity: 1,
                  }}
                >
                  My Catalogs
                </MenuItem>,
                ...filteredMyCatalogs.map((catalog) => (
                  <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
                    {catalog.catalogName}
                    {catalog.catalogType === "ADMIN_MANAGED" && " (Official)"}
                  </MenuItem>
                )),
              ]}

              {/* Public Catalogs Section */}
              {filteredPublicCatalogs.length > 0 && [
                <MenuItem
                  key="public-header"
                  disabled
                  sx={{
                    fontWeight: 600,
                    backgroundColor: "#f5f5f5",
                    opacity: 1,
                  }}
                >
                  Public Catalogs
                </MenuItem>,
                ...filteredPublicCatalogs.map((catalog) => (
                  <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
                    {catalog.catalogName}
                    {catalog.catalogType === "ADMIN_MANAGED" && " (Official)"}
                  </MenuItem>
                )),
              ]}
            </Select>
          </FormControl>

          {filteredMyCatalogs.length === 0 &&
            filteredPublicCatalogs.length === 0 &&
            !catalogsLoading && (
              <Alert severity="warning">
                No product catalogs are available. You'll need a catalog to
                create a campaign.
              </Alert>
            )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={!isFormValid || loading}
        >
          {loading ? "Creating..." : "Create Campaign"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
