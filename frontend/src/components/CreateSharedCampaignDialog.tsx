/**
 * CreateSharedCampaignDialog - Dialog for creating a new shared campaign
 */

import React, { useState, useEffect } from "react";
import { useMutation, useQuery } from "@apollo/client/react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Stack,
  Alert,
  AlertTitle,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Box,
  CircularProgress,
} from "@mui/material";
import {
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
  CREATE_SHARED_CAMPAIGN,
} from "../lib/graphql";

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
}

interface CreateSharedCampaignDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  canCreate: boolean;
}

const UNIT_TYPES = ["Pack", "Troop", "Crew", "Ship", "Post"];
const US_STATES = [
  "AL",
  "AK",
  "AZ",
  "AR",
  "CA",
  "CO",
  "CT",
  "DE",
  "FL",
  "GA",
  "HI",
  "ID",
  "IL",
  "IN",
  "IA",
  "KS",
  "KY",
  "LA",
  "ME",
  "MD",
  "MA",
  "MI",
  "MN",
  "MS",
  "MO",
  "MT",
  "NE",
  "NV",
  "NH",
  "NJ",
  "NM",
  "NY",
  "NC",
  "ND",
  "OH",
  "OK",
  "OR",
  "PA",
  "RI",
  "SC",
  "SD",
  "TN",
  "TX",
  "UT",
  "VT",
  "VA",
  "WA",
  "WV",
  "WI",
  "WY",
];

const BASE_URL = window.location.origin;
const MAX_CREATOR_MESSAGE_LENGTH = 300;

export const CreateSharedCampaignDialog: React.FC<
  CreateSharedCampaignDialogProps
> = ({ open, onClose, onSuccess, canCreate }) => {
  // Form state
  const [catalogId, setCatalogId] = useState("");
  const [campaignName, setCampaignName] = useState("");
  const [campaignYear, setCampaignYear] = useState(new Date().getFullYear());
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [unitType, setUnitType] = useState("");
  const [unitNumber, setUnitNumber] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [creatorMessage, setCreatorMessage] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch catalogs
  const { data: publicCatalogsData, loading: publicLoading } = useQuery<{
    listPublicCatalogs: Catalog[];
  }>(LIST_PUBLIC_CATALOGS);

  const { data: myCatalogsData, loading: myLoading } = useQuery<{
    listMyCatalogs: Catalog[];
  }>(LIST_MY_CATALOGS);

  const publicCatalogs = publicCatalogsData?.listPublicCatalogs || [];
  const myCatalogs = myCatalogsData?.listMyCatalogs || [];

  // Deduplicate: remove catalogs from public list that are also in my list
  const myIdSet = new Set(myCatalogs.map((c) => c.catalogId));
  const filteredPublicCatalogs = publicCatalogs.filter(
    (c) => !myIdSet.has(c.catalogId),
  );

  const catalogsLoading = publicLoading || myLoading;

  // Create mutation
  const [createSharedCampaign] = useMutation(CREATE_SHARED_CAMPAIGN);

  // Reset form when dialog opens/closes
  useEffect(() => {
    if (open) {
      setCatalogId("");
      setCampaignName("");
      setCampaignYear(new Date().getFullYear());
      setStartDate("");
      setEndDate("");
      setUnitType("");
      setUnitNumber("");
      setCity("");
      setState("");
      setCreatorMessage("");
      setDescription("");
      setError(null);
    }
  }, [open]);

  const isFormValid = () => {
    return (
      catalogId &&
      campaignName.trim() &&
      campaignYear &&
      unitType &&
      unitNumber &&
      city.trim() &&
      state &&
      creatorMessage.length <= MAX_CREATOR_MESSAGE_LENGTH
    );
  };

  const handleSubmit = async () => {
    if (!isFormValid()) {
      setError("Please fill in all required fields");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await createSharedCampaign({
        variables: {
          input: {
            catalogId,
            campaignName: campaignName.trim(),
            campaignYear,
            startDate: startDate || undefined,
            endDate: endDate || undefined,
            unitType,
            unitNumber: parseInt(unitNumber, 10),
            city: city.trim(),
            state,
            creatorMessage: creatorMessage.trim() || undefined,
            description: description.trim() || undefined,
          },
        },
      });

      onSuccess();
    } catch (err) {
      const errorMessage =
        err instanceof Error
          ? err.message
          : "Failed to create campaign sharedCampaign";
      setError(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  const previewLink = `${BASE_URL}/c/[generated-code]`;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Create Shared Campaign</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ mt: 1 }}>
          {/* Warning Banner */}
          <Alert severity="warning">
            <AlertTitle>Important</AlertTitle>
            If someone stops sharing their profile with you, you will lose
            access to their data. The share is controlled by the profile owner.
          </Alert>

          {!canCreate && (
            <Alert severity="error">
              You have reached the maximum of 50 active shared campaigns.
              Please deactivate an existing shared campaign before creating a new one.
            </Alert>
          )}

          {error && <Alert severity="error">{error}</Alert>}

          {/* Catalog Selection */}
          <FormControl fullWidth required disabled={catalogsLoading}>
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
                <MenuItem disabled>Loading catalogs...</MenuItem>
              )}
              {!catalogsLoading &&
                filteredPublicCatalogs.length === 0 &&
                myCatalogs.length === 0 && (
                  <MenuItem disabled>No catalogs available</MenuItem>
                )}

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
                  </MenuItem>
                )),
              ]}

              {/* My Catalogs Section */}
              {myCatalogs.length > 0 && [
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
                ...myCatalogs.map((catalog) => (
                  <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
                    {catalog.catalogName}
                  </MenuItem>
                )),
              ]}
            </Select>
          </FormControl>

          {/* Campaign Information */}
          <Stack direction="row" spacing={2}>
            <TextField
              label="Campaign Name"
              value={campaignName}
              onChange={(e) => setCampaignName(e.target.value)}
              placeholder="e.g., Fall, Spring"
              required
              fullWidth
            />
            <TextField
              label="Campaign Year"
              type="number"
              value={campaignYear}
              onChange={(e) => setCampaignYear(parseInt(e.target.value, 10) || 0)}
              required
              sx={{ width: 150 }}
              inputProps={{ min: 2020, max: 2100 }}
            />
          </Stack>

          {/* Optional Dates */}
          <Stack direction="row" spacing={2}>
            <TextField
              label="Start Date (Optional)"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              fullWidth
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              label="End Date (Optional)"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              fullWidth
              InputLabelProps={{ shrink: true }}
            />
          </Stack>

          {/* Unit Information */}
          <Typography variant="subtitle2" color="text.secondary">
            Unit Information (Required)
          </Typography>
          <Stack direction="row" spacing={2}>
            <FormControl required sx={{ minWidth: 150 }}>
              <InputLabel>Unit Type</InputLabel>
              <Select
                value={unitType}
                onChange={(e) => setUnitType(e.target.value)}
                label="Unit Type"
              >
                {UNIT_TYPES.map((type) => (
                  <MenuItem key={type} value={type}>
                    {type}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Unit Number"
              type="number"
              value={unitNumber}
              onChange={(e) => setUnitNumber(e.target.value)}
              required
              sx={{ width: 150 }}
              inputProps={{ min: 1 }}
            />
            <TextField
              label="City"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              required
              fullWidth
            />
            <FormControl required sx={{ minWidth: 100 }}>
              <InputLabel>State</InputLabel>
              <Select
                value={state}
                onChange={(e) => setState(e.target.value)}
                label="State"
              >
                {US_STATES.map((s) => (
                  <MenuItem key={s} value={s}>
                    {s}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>

          {/* Creator Message */}
          <TextField
            label="Message to Scouts (Optional)"
            value={creatorMessage}
            onChange={(e) => setCreatorMessage(e.target.value)}
            placeholder="Enter a message that will be shown to scouts when they use this link"
            multiline
            rows={2}
            fullWidth
            inputProps={{ maxLength: MAX_CREATOR_MESSAGE_LENGTH }}
            helperText={`${creatorMessage.length}/${MAX_CREATOR_MESSAGE_LENGTH} characters`}
            error={creatorMessage.length > MAX_CREATOR_MESSAGE_LENGTH}
          />

          {/* Description (for internal use) */}
          <TextField
            label="Description (For Your Reference)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Internal description to help you manage your shared campaigns"
            fullWidth
          />

          {/* Link Preview */}
          <Box sx={{ bgcolor: "grey.100", p: 2, borderRadius: 1 }}>
            <Typography variant="caption" color="text.secondary">
              Shareable Link Preview:
            </Typography>
            <Typography
              variant="body2"
              fontFamily="monospace"
              sx={{ wordBreak: "break-all" }}
            >
              {previewLink}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              (The actual code will be generated when you create the shared campaign)
            </Typography>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={!isFormValid() || isSubmitting || !canCreate}
          startIcon={isSubmitting ? <CircularProgress size={16} /> : undefined}
        >
          {isSubmitting ? "Creating..." : "Create Shared Campaign"}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
