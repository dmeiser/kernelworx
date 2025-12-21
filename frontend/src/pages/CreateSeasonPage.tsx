/**
 * CreateSeasonPage component - Page for creating a new sales season
 *
 * Supports two modes:
 * 1. Prefill mode: Accessed via /c/:prefillCode - all fields locked except profile selection
 * 2. Manual mode: Accessed via /create-season - all fields editable with optional unit info
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
  GET_CAMPAIGN_PREFILL,
  FIND_CAMPAIGN_PREFILLS,
  LIST_MY_PROFILES,
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
  CREATE_SEASON,
  LIST_SEASONS_BY_PROFILE,
} from "../lib/graphql";

// Types
interface CampaignPrefill {
  prefillCode: string;
  catalogId: string;
  catalog: {
    catalogId: string;
    catalogName: string;
  };
  seasonName: string;
  seasonYear: number;
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

const SEASON_OPTIONS = ["Fall", "Spring", "Summer", "Winter"];

export const CreateSeasonPage: React.FC = () => {
  const { prefillCode } = useParams<{ prefillCode: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  // Redirect state from login
  const savedPrefillCode = location.state?.prefillCode;
  const effectivePrefillCode = prefillCode || savedPrefillCode;

  // Form state
  const [profileId, setProfileId] = useState("");
  const [seasonName, setSeasonName] = useState("Fall");
  const [seasonYear, setSeasonYear] = useState(new Date().getFullYear());
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

  // Query for prefill data if prefillCode provided
  const {
    data: prefillData,
    loading: prefillLoading,
    error: prefillError,
  } = useQuery<{ getCampaignPrefill: CampaignPrefill | null }>(
    GET_CAMPAIGN_PREFILL,
    {
      variables: { prefillCode: effectivePrefillCode },
      skip: !effectivePrefillCode,
    },
  );

  const prefill = prefillData?.getCampaignPrefill;
  const isPrefillMode = !!effectivePrefillCode && !!prefill && prefill.isActive;

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
  }>(LIST_PUBLIC_CATALOGS, { skip: isPrefillMode });

  const { data: myCatalogsData, loading: myLoading } = useQuery<{
    listMyCatalogs: Catalog[];
  }>(LIST_MY_CATALOGS, { skip: isPrefillMode });

  const publicCatalogs = publicCatalogsData?.listPublicCatalogs || [];
  const myCatalogs = myCatalogsData?.listMyCatalogs || [];

  // Deduplicate and filter deleted catalogs
  const myIdSet = new Set(myCatalogs.map((c) => c.catalogId));
  const filteredPublicCatalogs = publicCatalogs.filter(
    (c) => !myIdSet.has(c.catalogId) && c.isDeleted !== true,
  );
  const filteredMyCatalogs = myCatalogs.filter((c) => c.isDeleted !== true);

  const catalogsLoading = publicLoading || myLoading;

  // Lazy query for prefill discovery in manual mode
  const [findPrefills, { data: discoveredPrefillsData }] = useLazyQuery<{
    findCampaignPrefills: CampaignPrefill[];
  }>(FIND_CAMPAIGN_PREFILLS);

  const discoveredPrefills = discoveredPrefillsData?.findCampaignPrefills || [];

  // Create season mutation
  const [createSeason] = useMutation<{
    createSeason: {
      seasonId: string;
      seasonName: string;
      seasonYear: number;
    };
  }>(CREATE_SEASON, {
    refetchQueries: [
      { query: LIST_MY_PROFILES },
      { query: LIST_SEASONS_BY_PROFILE, variables: { profileId } },
    ],
  });

  // Auto-select profile if only one exists
  useEffect(() => {
    if (!profilesLoading && profiles.length === 1 && !profileId) {
      setProfileId(profiles[0].profileId);
    }
  }, [profilesLoading, profiles, profileId]);

  // Redirect to profile creation if user has no profiles in prefill mode
  useEffect(() => {
    if (
      isPrefillMode &&
      !profilesLoading &&
      profiles.length === 0 &&
      effectivePrefillCode
    ) {
      // User needs to create a profile first
      navigate("/profiles", {
        state: {
          returnTo: `/c/${effectivePrefillCode}`,
          prefillCode: effectivePrefillCode,
          message: "Create a seller profile to use this campaign link",
        },
        replace: true,
      });
    }
  }, [
    isPrefillMode,
    profilesLoading,
    profiles.length,
    effectivePrefillCode,
    navigate,
  ]);

  // Set form values from prefill when loaded
  useEffect(() => {
    if (prefill && prefill.isActive) {
      setSeasonName(prefill.seasonName);
      setSeasonYear(prefill.seasonYear);
      setCatalogId(prefill.catalogId);
      setStartDate(prefill.startDate || "");
      setEndDate(prefill.endDate || "");
      setUnitType(prefill.unitType);
      setUnitNumber(String(prefill.unitNumber));
      setCity(prefill.city);
      setState(prefill.state);
    }
  }, [prefill]);

  // Debounced prefill discovery in manual mode
  const debouncedFindPrefills = useMemo(() => {
    let timeoutId: NodeJS.Timeout;
    return (params: {
      unitType: string;
      unitNumber: string;
      city: string;
      state: string;
      seasonName: string;
      seasonYear: number;
    }) => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        if (
          params.unitType &&
          params.unitNumber &&
          params.city &&
          params.state &&
          params.seasonName &&
          params.seasonYear
        ) {
          findPrefills({
            variables: {
              unitType: params.unitType,
              unitNumber: parseInt(params.unitNumber, 10),
              city: params.city,
              state: params.state,
              seasonName: params.seasonName,
              seasonYear: params.seasonYear,
            },
          });
        }
      }, 500);
    };
  }, [findPrefills]);

  // Trigger prefill discovery when unit+season fields change in manual mode
  useEffect(() => {
    if (!isPrefillMode && unitType && unitNumber && city && state) {
      debouncedFindPrefills({
        unitType,
        unitNumber,
        city,
        state,
        seasonName,
        seasonYear,
      });
    }
  }, [
    isPrefillMode,
    unitType,
    unitNumber,
    city,
    state,
    seasonName,
    seasonYear,
    debouncedFindPrefills,
  ]);

  const handleUsePrefill = useCallback(
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
    if (!isPrefillMode && unitType) {
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
        // Convert date strings to ISO datetime format for AWSDateTime
        ...(startDate && { startDate: new Date(startDate).toISOString() }),
        ...(endDate && { endDate: new Date(endDate).toISOString() }),
      };

      if (isPrefillMode && effectivePrefillCode) {
        // Prefill mode - use prefillCode
        input.prefillCode = effectivePrefillCode;
        input.shareWithCreator = shareWithCreator;
      } else {
        // Manual mode - include all fields
        input.seasonName = seasonName;
        input.seasonYear = seasonYear;
        input.catalogId = catalogId;

        if (unitType && unitNumber && city && state) {
          input.unitType = unitType;
          input.unitNumber = parseInt(unitNumber, 10);
          input.city = city;
          input.state = state;
        }
      }

      const { data } = await createSeason({
        variables: { input },
      });

      const createdSeason = data?.createSeason;
      if (createdSeason) {
        if (isPrefillMode && shareWithCreator) {
          setToastMessage({
            message: `Season created and shared with ${prefill?.createdByName}!`,
            severity: "success",
          });
        } else {
          setToastMessage({
            message: "Season created successfully!",
            severity: "success",
          });
        }
        navigate(
          `/profiles/${encodeURIComponent(profileId)}/seasons/${encodeURIComponent(createdSeason.seasonId)}`,
        );
      }
    } catch (error) {
      console.error("Failed to create season:", error);
      setToastMessage({
        message: "Failed to create season. Please try again.",
        severity: "error",
      });
    } finally {
      setSubmitting(false);
    }
  };

  // Loading states
  if (effectivePrefillCode && prefillLoading) {
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

  // Prefill not found or inactive
  if (effectivePrefillCode && (!prefill || !prefill.isActive)) {
    return (
      <Box maxWidth="md" mx="auto" p={3}>
        <Alert severity="error">
          <AlertTitle>Campaign Not Found</AlertTitle>
          This campaign link is no longer valid. The campaign may have been
          deactivated or the link may be incorrect.
        </Alert>
        <Button
          variant="contained"
          onClick={() => navigate("/profiles")}
          sx={{ mt: 2 }}
        >
          Go to Profiles
        </Button>
      </Box>
    );
  }

  // Prefill error
  if (prefillError) {
    return (
      <Box maxWidth="md" mx="auto" p={3}>
        <Alert severity="error">
          <AlertTitle>Error Loading Campaign</AlertTitle>
          {prefillError.message}
        </Alert>
        <Button
          variant="contained"
          onClick={() => navigate("/profiles")}
          sx={{ mt: 2 }}
        >
          Go to Profiles
        </Button>
      </Box>
    );
  }

  const isFormValid = isPrefillMode
    ? !!profileId
    : !!profileId && !!seasonName && !!catalogId;

  return (
    <Box maxWidth="md" mx="auto" p={3}>
      <Typography variant="h4" gutterBottom>
        Create New Season
      </Typography>

      {/* Prefill Banner */}
      {isPrefillMode && prefill && (
        <Card sx={{ mb: 3, bgcolor: "info.light" }}>
          <CardContent>
            <Stack direction="row" spacing={2} alignItems="flex-start">
              <CampaignIcon sx={{ fontSize: 40, color: "info.dark" }} />
              <Box>
                <Typography variant="h6" color="info.dark">
                  Campaign by {prefill.createdByName}
                </Typography>
                {prefill.creatorMessage && (
                  <Typography
                    variant="body1"
                    sx={{ mt: 1, fontStyle: "italic" }}
                  >
                    "{prefill.creatorMessage}"
                  </Typography>
                )}
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ mt: 1 }}
                >
                  {prefill.unitType} {prefill.unitNumber} • {prefill.city},{" "}
                  {prefill.state} • {prefill.seasonName} {prefill.seasonYear}
                </Typography>
              </Box>
            </Stack>
          </CardContent>
        </Card>
      )}

      {/* Discovered Prefills Alert (manual mode) */}
      {!isPrefillMode && discoveredPrefills.length > 0 && (
        <Alert
          severity="info"
          sx={{ mb: 3 }}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() =>
                handleUsePrefill(discoveredPrefills[0].prefillCode)
              }
            >
              Use Campaign
            </Button>
          }
        >
          <AlertTitle>Existing Campaign Found!</AlertTitle>
          We found an existing {seasonName} {seasonYear} campaign for {unitType}{" "}
          {unitNumber} in {city}, {state} created by{" "}
          {discoveredPrefills[0].createdByName}. Would you like to use their
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

          {/* Locked fields in prefill mode */}
          {isPrefillMode && prefill && (
            <>
              <TextField
                fullWidth
                label="Catalog"
                value={prefill.catalog.catalogName}
                disabled
                helperText="Set by campaign creator"
              />
              <Stack direction="row" spacing={2}>
                <TextField
                  fullWidth
                  label="Season"
                  value={prefill.seasonName}
                  disabled
                />
                <TextField
                  fullWidth
                  label="Year"
                  value={prefill.seasonYear}
                  disabled
                />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField
                  fullWidth
                  label="Unit Type"
                  value={prefill.unitType}
                  disabled
                />
                <TextField
                  fullWidth
                  label="Unit Number"
                  value={prefill.unitNumber}
                  disabled
                />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField
                  fullWidth
                  label="City"
                  value={prefill.city}
                  disabled
                />
                <TextField
                  fullWidth
                  label="State"
                  value={prefill.state}
                  disabled
                />
              </Stack>
            </>
          )}

          {/* Editable fields in manual mode */}
          {!isPrefillMode && (
            <>
              {/* Season Name and Year */}
              <Stack direction="row" spacing={2}>
                <FormControl fullWidth disabled={submitting}>
                  <InputLabel>Season Name *</InputLabel>
                  <Select
                    value={seasonName}
                    onChange={(e) => setSeasonName(e.target.value)}
                    label="Season Name *"
                  >
                    {SEASON_OPTIONS.map((season) => (
                      <MenuItem key={season} value={season}>
                        {season}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  fullWidth
                  label="Year *"
                  type="number"
                  value={seasonYear}
                  onChange={(e) => setSeasonYear(parseInt(e.target.value, 10))}
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
              disabled={submitting || isPrefillMode}
              InputLabelProps={{ shrink: true }}
              helperText={isPrefillMode ? "Set by campaign creator" : ""}
            />
            <TextField
              fullWidth
              label="End Date (Optional)"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              disabled={submitting || isPrefillMode}
              InputLabelProps={{ shrink: true }}
              helperText={isPrefillMode ? "Set by campaign creator" : ""}
            />
          </Stack>

          {/* Share with creator checkbox (prefill mode only) */}
          {isPrefillMode && prefill && (
            <Box sx={{ bgcolor: "warning.light", p: 2, borderRadius: 1 }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={shareWithCreator}
                    onChange={(e) => setShareWithCreator(e.target.checked)}
                    disabled={submitting}
                  />
                }
                label={`Share this profile with ${prefill.createdByName}`}
              />
              <Alert severity="warning" sx={{ mt: 1 }}>
                <AlertTitle>Important</AlertTitle>
                Sharing gives {prefill.createdByName} read access to ALL current
                and future seasons for this profile. You can revoke this access
                at any time from your profile settings.
              </Alert>
            </Box>
          )}

          <Divider />

          {/* Submit Button */}
          <Stack direction="row" spacing={2} justifyContent="flex-end">
            <Button
              variant="outlined"
              onClick={() => navigate(-1)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              variant="contained"
              onClick={handleSubmit}
              disabled={!isFormValid || submitting}
            >
              {submitting ? "Creating..." : "Create Season"}
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
