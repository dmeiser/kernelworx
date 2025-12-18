/**
 * CreateSeasonDialog component - Dialog for creating a new sales season
 */

import React, { useState, useEffect } from "react";
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

interface CreateSeasonDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (
    seasonName: string,
    startDate: string,
    endDate: string | null,
    catalogId: string,
  ) => Promise<void>;
}

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
}

export const CreateSeasonDialog: React.FC<CreateSeasonDialogProps> = ({
  open,
  onClose,
  onSubmit,
}) => {
  const [seasonName, setSeasonName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [catalogId, setCatalogId] = useState("");
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
  
  // Deduplicate by catalogId and separate into sections
  // Catalogs that appear in both lists (user owns a public catalog) go to "My Catalogs"
  const myIdSet = new Set(myCatalogs.map(c => c.catalogId));
  const filteredPublicCatalogs = publicCatalogs.filter(
    c => !myIdSet.has(c.catalogId)
  );
  
  const catalogsLoading = publicLoading || myLoading;

  // Set default start date to today
  useEffect(() => {
    if (open && !startDate) {
      const today = new Date().toISOString().split("T")[0];
      setStartDate(today);
    }
  }, [open, startDate]);

  const handleSubmit = async () => {
    if (!seasonName.trim() || !startDate || !catalogId) return;

    setLoading(true);
    try {
      await onSubmit(seasonName.trim(), startDate, endDate || null, catalogId);
      // Reset form
      setSeasonName("");
      setStartDate("");
      setEndDate("");
      setCatalogId("");
      onClose();
    } catch (error) {
      console.error("Failed to create season:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    if (!loading) {
      setSeasonName("");
      setStartDate("");
      setEndDate("");
      setCatalogId("");
      onClose();
    }
  };

  const isFormValid =
    seasonName.trim() &&
    startDate &&
    catalogId &&
    (!endDate || endDate >= startDate);

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create New Sales Season</DialogTitle>
      <DialogContent>
        <Stack spacing={3} pt={1}>
          {/* Season Name */}
          <TextField
            autoFocus
            fullWidth
            label="Season Name"
            placeholder="e.g., Fall 2025 Popcorn Sale"
            value={seasonName}
            onChange={(e) => setSeasonName(e.target.value)}
            disabled={loading}
            helperText="A descriptive name for this sales season"
          />

          {/* Start Date */}
          <TextField
            fullWidth
            label="Start Date"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            disabled={loading}
            InputLabelProps={{ shrink: true }}
          />

          {/* End Date (Optional) */}
          <TextField
            fullWidth
            label="End Date (Optional)"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            disabled={loading}
            InputLabelProps={{ shrink: true }}
            helperText="Leave blank if the season is ongoing"
            error={!!endDate && endDate < startDate}
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
              {!catalogsLoading && myCatalogs.length === 0 && filteredPublicCatalogs.length === 0 && (
                <MenuItem disabled>No catalogs available</MenuItem>
              )}
              
              {/* My Catalogs Section */}
              {myCatalogs.length > 0 && [
                <MenuItem key="my-header" disabled sx={{ fontWeight: 600, backgroundColor: "#f5f5f5", opacity: 1 }}>
                  My Catalogs
                </MenuItem>,
                ...myCatalogs.map((catalog) => (
                  <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
                    {catalog.catalogName}
                    {catalog.catalogType === "ADMIN_MANAGED" && " (Official)"}
                  </MenuItem>
                ))
              ]}
              
              {/* Public Catalogs Section */}
              {filteredPublicCatalogs.length > 0 && [
                <MenuItem key="public-header" disabled sx={{ fontWeight: 600, backgroundColor: "#f5f5f5", opacity: 1 }}>
                  Public Catalogs
                </MenuItem>,
                ...filteredPublicCatalogs.map((catalog) => (
                  <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
                    {catalog.catalogName}
                    {catalog.catalogType === "ADMIN_MANAGED" && " (Official)"}
                  </MenuItem>
                ))
              ]}
            </Select>
          </FormControl>

          {myCatalogs.length === 0 && filteredPublicCatalogs.length === 0 && !catalogsLoading && (
            <Alert severity="warning">
              No product catalogs are available. You'll need a catalog to create
              a season.
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
          {loading ? "Creating..." : "Create Season"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
