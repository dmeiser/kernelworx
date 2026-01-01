/**
 * CreateCampaignPage component - Page for creating a new sales campaign
 *
 * Supports two modes:
 * 1. Shared Campaign mode: Accessed via /c/:sharedCampaignCode - all fields locked except profile selection
 * 2. Manual mode: Accessed via /create-campaign - all fields editable with optional unit info
 */

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useMutation, useQuery, useLazyQuery } from "@apollo/client/react";
import {
  Box,
  Typography,
  Alert,
  AlertTitle,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Checkbox,
  FormControlLabel,
  Stack,
  Paper,
  Divider,
  CircularProgress,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Card,
  CardContent,
  Snackbar,
} from "@mui/material";
import {
  ExpandMore as ExpandMoreIcon,
  Campaign as CampaignIcon,
  Info as InfoIcon,
} from "@mui/icons-material";
import {
  GET_SHARED_CAMPAIGN,
  FIND_SHARED_CAMPAIGNS,
  LIST_MY_PROFILES,
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
  CREATE_CAMPAIGN,
  LIST_CAMPAIGNS_BY_PROFILE,
} from "../lib/graphql";
import { ensureProfileId, ensureCatalogId, toUrlId } from "../lib/ids";

// Types
interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  catalog: {
    catalogId: string;
    catalogName: string;
  };
  campaignName: string;
  campaignYear: number;
  startDate: string | null;
  endDate: string | null;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  creatorMessage: string;
  description: string | null;
  isActive: boolean;
}

interface SellerProfile {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
}

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
  isDeleted?: boolean;
}

const UNIT_TYPES = [
  { value: "", label: "None" },
  { value: "Pack", label: "Pack (Cub Scouts)" },
  { value: "Troop", label: "Troop (Scouts BSA)" },
  { value: "Crew", label: "Crew (Venturing)" },
  { value: "Ship", label: "Ship (Sea Scouts)" },
  { value: "Post", label: "Post (Exploring)" },
  { value: "Club", label: "Club (Exploring)" },
];

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
  "DC",
];

const CAMPAIGN_OPTIONS = ["Fall", "Spring", "Summer", "Winter"];

// Expose a test override for debounce duration so tests can make discovery deterministic
export let SHARED_DISCOVERY_DEBOUNCE_MS = 500;
export const setDiscoveryDebounceMs = (ms: number) => {
  SHARED_DISCOVERY_DEBOUNCE_MS = ms;
};

export const CreateCampaignPage: React.FC = () => {
  const { sharedCampaignCode } = useParams<{ sharedCampaignCode: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  // Redirect state from login
  const savedSharedCampaignCode = location.state?.sharedCampaignCode;
  const effectiveSharedCampaignCode = sharedCampaignCode || savedSharedCampaignCode;

  // Form state
  const [profileId, setProfileId] = useState("");
  const [campaignName, setCampaignName] = useState("Fall");
  const [campaignYear, setCampaignYear] = useState(new Date().getFullYear());
  const [catalogId, setCatalogId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [unitType, setUnitType] = useState("");
  const [unitNumber, setUnitNumber] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [shareWithCreator, setShareWithCreator] = useState(true);
  const [unitSectionExpanded, setUnitSectionExpanded] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [toastMessage, setToastMessage] = useState<{
    message: string;
    severity: "success" | "error";
  } | null>(null);

  // Query for shared campaign data if sharedCampaignCode provided
  const {
    data: sharedCampaignData,
    loading: sharedCampaignLoading,
    error: sharedCampaignError,
  } = useQuery<{ getSharedCampaign: SharedCampaign | null }>(
    GET_SHARED_CAMPAIGN,
    {
      variables: { sharedCampaignCode: effectiveSharedCampaignCode },
      skip: !effectiveSharedCampaignCode,
    },
  );

  const sharedCampaign = sharedCampaignData?.getSharedCampaign;
  const isSharedCampaignMode = !!effectiveSharedCampaignCode && !!sharedCampaign && sharedCampaign.isActive;

  // Query for user's profiles
  const {
    data: profilesData,
    loading: profilesLoading,
    refetch: refetchProfiles,
  } = useQuery<{
    listMyProfiles: SellerProfile[];
  }>(LIST_MY_PROFILES);

  const profiles = useMemo(
    () => profilesData?.listMyProfiles || [],
    [profilesData],
  );

  // Refetch profiles when returning from profile creation
  useEffect(() => {
    if (location.state?.fromProfileCreation) {
      refetchProfiles();
    }
  }, [location.state, refetchProfiles]);

  // Query for catalogs (only in manual mode)
  const { data: publicCatalogsData, loading: publicLoading } = useQuery<{
    listPublicCatalogs: Catalog[];
  }>(LIST_PUBLIC_CATALOGS, { skip: isSharedCampaignMode });

  const { data: myCatalogsData, loading: myLoading } = useQuery<{
    listMyCatalogs: Catalog[];
  }>(LIST_MY_CATALOGS, { skip: isSharedCampaignMode });

  const publicCatalogs = publicCatalogsData?.listPublicCatalogs || [];
  const myCatalogs = myCatalogsData?.listMyCatalogs || [];

  // Deduplicate and filter deleted catalogs
  const myIdSet = new Set(myCatalogs.map((c) => c.catalogId));
  const filteredPublicCatalogs = publicCatalogs.filter(
    (c) => !myIdSet.has(c.catalogId) && c.isDeleted !== true,
  );
  const filteredMyCatalogs = myCatalogs.filter((c) => c.isDeleted !== true);

  const catalogsLoading = publicLoading || myLoading;

  // Lazy query for shared campaign discovery in manual mode
  const [findSharedCampaigns, { data: discoveredSharedCampaignsData }] = useLazyQuery<{
    findSharedCampaigns: SharedCampaign[];
  }>(FIND_SHARED_CAMPAIGNS);

  const discoveredSharedCampaigns = discoveredSharedCampaignsData?.findSharedCampaigns || [];

  // Create campaign mutation
  const [createCampaign] = useMutation<{
    createCampaign: {
      campaignId: string;
      campaignName: string;
      campaignYear: number;
    };
  }>(CREATE_CAMPAIGN, {
    refetchQueries: [
      { query: LIST_MY_PROFILES },
      { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: ensureProfileId(profileId) } },
    ],
  });

  // Auto-select profile if only one exists
  useEffect(() => {
    if (!profilesLoading && profiles.length === 1 && !profileId) {
      setProfileId(profiles[0].profileId);
    }
  }, [profilesLoading, profiles, profileId]);

  // Redirect to profile creation if user has no profiles in shared campaign mode
  useEffect(() => {
    if (
      isSharedCampaignMode &&
      !profilesLoading &&
      profiles.length === 0 &&
      effectiveSharedCampaignCode
    ) {
      // User needs to create a profile first
      navigate("/scouts", {
        state: {
          returnTo: `/c/${effectiveSharedCampaignCode}`,
          sharedCampaignCode: effectiveSharedCampaignCode,
          message: "Create a scout to use this campaign link",
        },
        replace: true,
      });
    }
  }, [
    isSharedCampaignMode,
    profilesLoading,
    profiles.length,
    effectiveSharedCampaignCode,
    navigate,
  ]);

  // Set form values from shared campaign when loaded
  useEffect(() => {
    if (sharedCampaign && sharedCampaign.isActive) {
      setCampaignName(sharedCampaign.campaignName);
      setCampaignYear(sharedCampaign.campaignYear);
      setCatalogId(sharedCampaign.catalogId);
      setStartDate(sharedCampaign.startDate || "");
      setEndDate(sharedCampaign.endDate || "");
      setUnitType(sharedCampaign.unitType);
      setUnitNumber(String(sharedCampaign.unitNumber));
      setCity(sharedCampaign.city);
      setState(sharedCampaign.state);
    }
  }, [sharedCampaign]);

// Debounced shared campaign discovery in manual mode
const debouncedFindSharedCampaigns = useMemo(() => {
  let timeoutId: NodeJS.Timeout;
  return (params: {
    unitType: string;
    unitNumber: string;
    city: string;
    state: string;
    campaignName: string;
    campaignYear: number;
  }) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => {
      if (
        params.unitType &&
        params.unitNumber &&
        params.city &&
        params.state &&
        params.campaignName &&
        params.campaignYear
      ) {
        findSharedCampaigns({
          variables: {
            unitType: params.unitType,
            unitNumber: parseInt(params.unitNumber, 10),
            city: params.city,
            state: params.state,
            campaignName: params.campaignName,
            campaignYear: params.campaignYear,
          },
        });
      }
    }, SHARED_DISCOVERY_DEBOUNCE_MS);
    };
  }, [findSharedCampaigns]);

  // Trigger shared campaign discovery when unit+campaign fields change in manual mode
  useEffect(() => {
    if (!isSharedCampaignMode && unitType && unitNumber && city && state) {
      debouncedFindSharedCampaigns({
        unitType,
        unitNumber,
        city,
        state,
        campaignName,
        campaignYear,
      });
    }
  }, [
    isSharedCampaignMode,
    unitType,
    unitNumber,
    city,
    state,
    campaignName,
    campaignYear,
    debouncedFindSharedCampaigns,
  ]);

  const handleUseSharedCampaign = useCallback(
    (code: string) => {
      navigate(`/c/${code}`);
    },
    [navigate],
  );

  const handleSubmit = async () => {
    if (!profileId) {
      setToastMessage({
        message: "Please select a profile",
        severity: "error",
      });
      return;
    }

    // Validate unit fields if any are provided (in manual mode)
    if (!isSharedCampaignMode && unitType) {
      if (!unitNumber || !city || !state) {
        setToastMessage({
          message:
            "When specifying a unit, all fields (unit number, city, state) are required",
          severity: "error",
        });
        return;
      }
    }

    setSubmitting(true);
    try {
      const input: Record<string, unknown> = {
        profileId,
        startDate: startDate ? new Date(startDate).toISOString() : undefined,
        endDate: endDate ? new Date(endDate).toISOString() : undefined,
      };

      if (isSharedCampaignMode && effectiveSharedCampaignCode) {
        // shared campaign mode - use sharedCampaignCode
        input.sharedCampaignCode = effectiveSharedCampaignCode;
        input.shareWithCreator = shareWithCreator;
      } else {
        // Manual mode - include all fields
        input.campaignName = campaignName;
        input.campaignYear = campaignYear;
        input.catalogId = ensureCatalogId(catalogId);

        if (unitType && unitNumber && city && state) {
          input.unitType = unitType;
          input.unitNumber = parseInt(unitNumber, 10);
          input.city = city;
          input.state = state;
        }
      }

      const { data } = await createCampaign({
        variables: { input },
      });

      const createdCampaign = data?.createCampaign;
      if (createdCampaign) {
        if (isSharedCampaignMode && shareWithCreator) {
          setToastMessage({
            message: `Campaign created and shared with ${sharedCampaign?.createdByName}!`,
            severity: "success",
          });
        } else {
          setToastMessage({
            message: "Campaign created successfully!",
            severity: "success",
          });
        }
        navigate(
          `/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(createdCampaign.campaignId)}`,
        );
      }
    } catch (error) {
        console.error("Failed to create campaign:", error);
      setToastMessage({
        message: "Failed to create campaign. Please try again.",
        severity: "error",
      });
    } finally {
      setSubmitting(false);
    }
  };

  // Loading states
  if (effectiveSharedCampaignCode && sharedCampaignLoading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="50vh"
      >
        <CircularProgress />
      </Box>
    );
  }

  // shared campaign not found or inactive
  if (effectiveSharedCampaignCode && (!sharedCampaign || !sharedCampaign.isActive)) {
    return (
      <Box maxWidth="md" mx="auto" p={3}>
        <Alert severity="error">
          <AlertTitle>Campaign Not Found</AlertTitle>
          This campaign link is no longer valid. The campaign may have been
          deactivated or the link may be incorrect.
        </Alert>
        <Button
          variant="contained"
          onClick={() => navigate("/scouts")}
          sx={{ mt: 2 }}
        >
          Go to Profiles
        </Button>
      </Box>
    );
  }

  // shared campaign error
  if (sharedCampaignError) {
    return (
      <Box maxWidth="md" mx="auto" p={3}>
        <Alert severity="error">
          <AlertTitle>Error Loading Campaign</AlertTitle>
          {sharedCampaignError.message}
        </Alert>
        <Button
          variant="contained"
          onClick={() => navigate("/scouts")}
          sx={{ mt: 2 }}
        >
          Go to Profiles
        </Button>
      </Box>
    );
  }

  const isFormValid = isSharedCampaignMode
    ? !!profileId
    : !!profileId && !!campaignName && !!catalogId;

  return (
    <Box maxWidth="md" mx="auto" p={3}>
      <Typography variant="h4" gutterBottom>
        Create New Campaign
      </Typography>

      {/* Shared Campaign Banner */}
      {isSharedCampaignMode && sharedCampaign && (
        <Card sx={{ mb: 3, bgcolor: "info.light" }}>
          <CardContent>
            <Stack direction="row" spacing={2} alignItems="flex-start">
              <CampaignIcon sx={{ fontSize: 40, color: "info.dark" }} />
              <Box>
                <Typography variant="h6" color="info.dark">
                  Campaign by {sharedCampaign.createdByName}
                </Typography>
                {sharedCampaign.creatorMessage && (
                  <Typography
                    variant="body1"
                    sx={{ mt: 1, fontStyle: "italic" }}
                  >
                    "{sharedCampaign.creatorMessage}"
                  </Typography>
                )}
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ mt: 1 }}
                >
                  {sharedCampaign.unitType} {sharedCampaign.unitNumber} • {sharedCampaign.city},{" "}
                  {sharedCampaign.state} • {sharedCampaign.campaignName} {sharedCampaign.campaignYear}
                </Typography>
              </Box>
            </Stack>
          </CardContent>
        </Card>
      )}

      {/* Discovered shared campaigns Alert (manual mode) */}
      {!isSharedCampaignMode && discoveredSharedCampaigns.length > 0 && (
        <Alert
          severity="info"
          sx={{ mb: 3 }}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() =>
                handleUseSharedCampaign(discoveredSharedCampaigns[0].sharedCampaignCode)
              }
            >
              Use Campaign
            </Button>
          }
        >
          <AlertTitle>Existing Campaign Found!</AlertTitle>
          We found an existing {campaignName} {campaignYear} campaign for {unitType}{" "}
          {unitNumber} in {city}, {state} created by{" "}
          {discoveredSharedCampaigns[0].createdByName}. Would you like to use their
          settings?
        </Alert>
      )}

      <Paper sx={{ p: 3 }}>
        <Stack spacing={3}>
          {/* Profile Selection */}
          <FormControl fullWidth disabled={submitting}>
            <InputLabel>Select Profile *</InputLabel>
            <Select
              value={profileId}
              onChange={(e) => setProfileId(e.target.value)}
              label="Select Profile *"
            >
              {profilesLoading && (
                <MenuItem disabled>
                  <CircularProgress size={20} sx={{ mr: 1 }} />
                  Loading profiles...
                </MenuItem>
              )}
              {profiles.length === 0 && !profilesLoading && (
                <MenuItem disabled>No profiles available</MenuItem>
              )}
              {profiles.map((profile) => (
                <MenuItem key={profile.profileId} value={profile.profileId}>
                  {profile.sellerName}
                  {profile.isOwner ? " (Owner)" : " (Shared)"}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Divider />

          {/* Locked fields in shared campaign mode */}
          {isSharedCampaignMode && sharedCampaign && (
            <>
              <TextField
                fullWidth
                label="Catalog"
                value={sharedCampaign.catalog.catalogName}
                disabled
                helperText="Set by campaign creator"
              />
              <Stack direction="row" spacing={2}>
                <TextField
                  fullWidth
                  label="Campaign"
                  value={sharedCampaign.campaignName}
                  disabled
                />
                <TextField
                  fullWidth
                  label="Year"
                  value={sharedCampaign.campaignYear}
                  disabled
                />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField
                  fullWidth
                  label="Unit Type"
                  value={sharedCampaign.unitType}
                  disabled
                />
                <TextField
                  fullWidth
                  label="Unit Number"
                  value={sharedCampaign.unitNumber}
                  disabled
                />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField
                  fullWidth
                  label="City"
                  value={sharedCampaign.city}
                  disabled
                />
                <TextField
                  fullWidth
                  label="State"
                  value={sharedCampaign.state}
                  disabled
                />
              </Stack>
            </>
          )}

          {/* Editable fields in manual mode */}
          {!isSharedCampaignMode && (
            <>
              {/* Campaign Name and Year */}
              <Stack direction="row" spacing={2}>
                <FormControl fullWidth disabled={submitting}>
                  <InputLabel>Campaign Name *</InputLabel>
                  <Select
                    value={campaignName}
                    onChange={(e) => setCampaignName(e.target.value)}
                    label="Campaign Name *"
                  >
                    {CAMPAIGN_OPTIONS.map((campaign) => (
                      <MenuItem key={campaign} value={campaign}>
                        {campaign}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  fullWidth
                  label="Year *"
                  type="number"
                  value={campaignYear}
                  onChange={(e) => setCampaignYear(parseInt(e.target.value, 10))}
                  disabled={submitting}
                  inputProps={{
                    min: 2020,
                    max: new Date().getFullYear() + 5,
                    step: 1,
                  }}
                />
              </Stack>

              {/* Catalog Selection */}
              <FormControl fullWidth disabled={submitting || catalogsLoading}>
                <InputLabel>Product Catalog *</InputLabel>
                <Select
                  value={catalogId}
                  onChange={(e) => setCatalogId(e.target.value)}
                  label="Product Catalog *"
                  MenuProps={{
                    slotProps: {
                      paper: {
                        sx: { maxHeight: 300 },
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
                      <MenuItem
                        key={catalog.catalogId}
                        value={catalog.catalogId}
                      >
                        {catalog.catalogName}
                        {catalog.catalogType === "ADMIN_MANAGED" &&
                          " (Official)"}
                      </MenuItem>
                    )),
                  ]}

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
                      <MenuItem
                        key={catalog.catalogId}
                        value={catalog.catalogId}
                      >
                        {catalog.catalogName}
                        {catalog.catalogType === "ADMIN_MANAGED" &&
                          " (Official)"}
                      </MenuItem>
                    )),
                  ]}
                </Select>
              </FormControl>

              {/* Optional Unit Information */}
              <Accordion
                expanded={unitSectionExpanded}
                onChange={(_, expanded) => setUnitSectionExpanded(expanded)}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography>
                    Unit Information (Optional){" "}
                    {unitType && (
                      <Typography component="span" color="primary">
                        - {unitType} {unitNumber}
                      </Typography>
                    )}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Stack spacing={2}>
                    <Alert severity="info" icon={<InfoIcon />}>
                      Adding unit information enables participation in unit
                      reports and allows coordination with other unit members.
                    </Alert>
                    <Stack direction="row" spacing={2}>
                      <FormControl fullWidth disabled={submitting}>
                        <InputLabel>Unit Type</InputLabel>
                        <Select
                          value={unitType}
                          onChange={(e) => setUnitType(e.target.value)}
                          label="Unit Type"
                        >
                          {UNIT_TYPES.map((option) => (
                            <MenuItem key={option.value} value={option.value}>
                              {option.label}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <TextField
                        fullWidth
                        label="Unit Number"
                        type="number"
                        value={unitNumber}
                        onChange={(e) => setUnitNumber(e.target.value)}
                        disabled={submitting || !unitType}
                        inputProps={{ min: 1, step: 1 }}
                        helperText={
                          unitType ? "Required" : "Select unit type first"
                        }
                      />
                    </Stack>
                    <Stack direction="row" spacing={2}>
                      <TextField
                        fullWidth
                        label="City"
                        value={city}
                        onChange={(e) => setCity(e.target.value)}
                        disabled={submitting || !unitType}
                        helperText={
                          unitType ? "Required for unit identification" : ""
                        }
                      />
                      <FormControl fullWidth disabled={submitting || !unitType}>
                        <InputLabel>State</InputLabel>
                        <Select
                          value={state}
                          onChange={(e) => setState(e.target.value)}
                          label="State"
                        >
                          <MenuItem value="">Select State</MenuItem>
                          {US_STATES.map((s) => (
                            <MenuItem key={s} value={s}>
                              {s}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </Stack>
                  </Stack>
                </AccordionDetails>
              </Accordion>
            </>
          )}

          {/* Optional Start/End Dates */}
          <Stack direction="row" spacing={2}>
            <TextField
              fullWidth
              label="Start Date (Optional)"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              disabled={submitting || isSharedCampaignMode}
              InputLabelProps={{ shrink: true }}
              helperText={isSharedCampaignMode ? "Set by campaign creator" : ""}
            />
            <TextField
              fullWidth
              label="End Date (Optional)"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              disabled={submitting || isSharedCampaignMode}
              InputLabelProps={{ shrink: true }}
              helperText={isSharedCampaignMode ? "Set by campaign creator" : ""}
            />
          </Stack>

          {/* Share with creator checkbox (sharedCampaign mode only) */}
          {isSharedCampaignMode && sharedCampaign && (
            <Box sx={{ bgcolor: "warning.light", p: 2, borderRadius: 1 }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={shareWithCreator}
                    onChange={(e) => setShareWithCreator(e.target.checked)}
                    disabled={submitting}
                  />
                }
                label={`Share this profile with ${sharedCampaign.createdByName}`}
              />
              <Alert severity="warning" sx={{ mt: 1 }}>
                <AlertTitle>Important</AlertTitle>
                Sharing gives {sharedCampaign.createdByName} read access to ALL current
                and future campaigns for this profile. You can revoke this access
                at any time from your profile settings.
              </Alert>
            </Box>
          )}

          <Divider />

          {/* Submit Button */}
          <Stack direction="row" spacing={2} justifyContent="flex-end">
            <Button
              variant="outlined"
              onClick={() => navigate("/scouts")}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              variant="contained"
              onClick={handleSubmit}
              disabled={!isFormValid || submitting}
            >
              {submitting ? "Creating..." : "Create Campaign"}
            </Button>
          </Stack>
        </Stack>
      </Paper>

      {/* Toast notification */}
      <Snackbar
        open={!!toastMessage}
        autoHideDuration={6000}
        onClose={() => setToastMessage(null)}
      >
        <Alert
          onClose={() => setToastMessage(null)}
          severity={toastMessage?.severity}
          sx={{ width: "100%" }}
        >
          {toastMessage?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};
