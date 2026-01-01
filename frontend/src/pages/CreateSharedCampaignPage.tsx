/**
 * CreateSharedCampaignPage - Dedicated page for creating campaign shared campaigns
 * Mobile-friendly full-page form
 */

import React, { useState } from "react";
import { useMutation, useQuery } from "@apollo/client/react";
import { useNavigate } from "react-router-dom";
import {
  Typography,
  Box,
  Button,
  TextField,
  Stack,
  Alert,
  AlertTitle,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
  Paper,
  Container,
  Divider,
} from "@mui/material";
import { ArrowBack as BackIcon, Save as SaveIcon } from "@mui/icons-material";
import {
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
  CREATE_SHARED_CAMPAIGN,
  LIST_MY_SHARED_CAMPAIGNS,
} from "../lib/graphql";

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
  isDeleted?: boolean;
}

interface SharedCampaign {
  sharedCampaignCode: string;
  isActive: boolean;
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
const MAX_ACTIVE_SHARED_CAMPAIGNS = 50;

export const CreateSharedCampaignPage: React.FC = () => {
  const navigate = useNavigate();

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

  // Fetch active shared campaign count
  const { data: sharedCampaignsData } = useQuery<{
    listMySharedCampaigns: SharedCampaign[];
  }>(LIST_MY_SHARED_CAMPAIGNS, { fetchPolicy: "network-only" });
  const sharedCampaigns = sharedCampaignsData?.listMySharedCampaigns || [];
  const activeSharedCampaignCount = sharedCampaigns.filter((p) => p.isActive).length;
  const canCreate = activeSharedCampaignCount < MAX_ACTIVE_SHARED_CAMPAIGNS;

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
  // NOTE: Intentionally NOT filtering deleted catalogs here - campaign shared campaign creation
  // should allow selection of deleted catalogs for existing shared campaigns that use them
  const myIdSet = new Set(myCatalogs.map((c) => c.catalogId));
  const filteredPublicCatalogs = publicCatalogs.filter(
    (c) => !myIdSet.has(c.catalogId),
  );

  const catalogsLoading = publicLoading || myLoading;

  // Create mutation
  const [createSharedCampaign] = useMutation(CREATE_SHARED_CAMPAIGN);

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
      window.scrollTo({ top: 0, behavior: "smooth" });
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

      // Navigate back to shared campaigns page
      navigate("/shared-campaigns");
    } catch (err) {
      const errorMessage =
        err instanceof Error
          ? err.message
          : "Failed to create shared campaign";
      setError(errorMessage);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const previewLink = `${BASE_URL}/c/[generated-code]`;

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      {/* Header */}
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 3 }}>
        <Button
          startIcon={<BackIcon />}
          onClick={() => navigate("/shared-campaigns")}
          disabled={isSubmitting}
        >
          Back
        </Button>
        <Typography variant="h4" component="h1">
          Create Shared Campaign
        </Typography>
      </Stack>

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <Stack spacing={3}>
          {/* Warning Banner */}
          <Alert severity="warning">
            <AlertTitle>Important</AlertTitle>
            If someone stops sharing their profile with you, you will lose
            access to their data. The share is controlled by the profile owner.
          </Alert>

          {!canCreate && (
            <Alert severity="error">
              You have reached the maximum of {MAX_ACTIVE_SHARED_CAMPAIGNS} active
              shared campaigns. Please deactivate an existing shared campaign before
              creating a new one.
            </Alert>
          )}

          {error && <Alert severity="error">{error}</Alert>}

          {/* Catalog Selection */}
          <Box>
            <Typography variant="h6" gutterBottom>
              Product Catalog
            </Typography>
            <FormControl fullWidth required disabled={catalogsLoading}>
              <InputLabel>Select Catalog</InputLabel>
              <Select
                value={catalogId}
                onChange={(e) => setCatalogId(e.target.value)}
                label="Select Catalog"
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
          </Box>

          <Divider />

          {/* Campaign Information */}
          <Box>
            <Typography variant="h6" gutterBottom>
              Campaign Information
            </Typography>
            <Stack spacing={2}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
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
                  onChange={(e) =>
                    setCampaignYear(parseInt(e.target.value, 10) || 0)
                  }
                  required
                  sx={{ minWidth: { xs: "100%", sm: 150 } }}
                  inputProps={{ min: 2020, max: 2100 }}
                />
              </Stack>

              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
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
            </Stack>
          </Box>

          <Divider />

          {/* Unit Information */}
          <Box>
            <Typography variant="h6" gutterBottom>
              Unit Information
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              All fields required
            </Typography>
            <Stack spacing={2}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <FormControl required fullWidth>
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
                  fullWidth
                  inputProps={{ min: 1 }}
                />
              </Stack>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <TextField
                  label="City"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  required
                  fullWidth
                />
                <FormControl required fullWidth>
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
            </Stack>
          </Box>

          <Divider />

          {/* Messages & Description */}
          <Box>
            <Typography variant="h6" gutterBottom>
              Additional Information
            </Typography>
            <Stack spacing={2}>
              <TextField
                label="Message to Scouts (Optional)"
                value={creatorMessage}
                onChange={(e) => setCreatorMessage(e.target.value)}
                placeholder="Enter a message that will be shown to scouts when they use this link"
                multiline
                rows={3}
                fullWidth
                inputProps={{ maxLength: MAX_CREATOR_MESSAGE_LENGTH }}
                helperText={`${creatorMessage.length}/${MAX_CREATOR_MESSAGE_LENGTH} characters`}
                error={creatorMessage.length > MAX_CREATOR_MESSAGE_LENGTH}
              />

              <TextField
                label="Description (For Your Reference)"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Internal description to help you manage your shared campaigns"
                fullWidth
              />
            </Stack>
          </Box>

          <Divider />

          {/* Link Preview */}
          <Box sx={{ bgcolor: "grey.100", p: 2, borderRadius: 1 }}>
            <Typography variant="subtitle2" gutterBottom>
              Shareable Link Preview:
            </Typography>
            <Typography
              variant="body2"
              fontFamily="monospace"
              sx={{ wordBreak: "break-all", mb: 1 }}
            >
              {previewLink}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              The actual code will be generated when you create the shared campaign
            </Typography>
          </Box>

          {/* Action Buttons */}
          <Stack
            direction={{ xs: "column-reverse", sm: "row" }}
            spacing={2}
            justifyContent="flex-end"
          >
            <Button
              onClick={() => navigate("/shared-campaigns")}
              disabled={isSubmitting}
              fullWidth={false}
              sx={{ minWidth: { xs: "100%", sm: 120 } }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              variant="contained"
              disabled={!isFormValid() || isSubmitting || !canCreate}
              startIcon={
                isSubmitting ? <CircularProgress size={16} /> : <SaveIcon />
              }
              fullWidth={false}
              sx={{ minWidth: { xs: "100%", sm: 200 } }}
            >
              {isSubmitting ? "Creating..." : "Create Shared Campaign"}
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Container>
  );
};
