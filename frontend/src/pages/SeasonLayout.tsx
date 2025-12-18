/**
 * SeasonLayout - Tabbed layout for season views
 *
 * Provides navigation between:
 * - Orders (default)
 * - Summary
 * - Reports
 * - Settings
 */

import React from "react";
import {
  Routes,
  Route,
  Navigate,
  useParams,
  useNavigate,
  useLocation,
} from "react-router-dom";
import { useQuery } from "@apollo/client/react";
import {
  Box,
  Tabs,
  Tab,
  Typography,
  Stack,
  IconButton,
  Breadcrumbs,
  Link,
  CircularProgress,
  Alert,
} from "@mui/material";
import {
  ArrowBack as ArrowBackIcon,
  ShoppingCart as OrdersIcon,
  Assessment as ReportsIcon,
  Settings as SettingsIcon,
} from "@mui/icons-material";
import { OrdersPage } from "./OrdersPage";
import { ReportsPage } from "./ReportsPage";
import { SeasonSettingsPage } from "./SeasonSettingsPage";
import { GET_SEASON, GET_PROFILE } from "../lib/graphql";

interface Season {
  seasonId: string;
  seasonName: string;
  profileId: string;
  startDate: string;
  endDate?: string;
  catalogId: string;
}

interface Profile {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
}

export const SeasonLayout: React.FC = () => {
  const { profileId: encodedProfileId, seasonId: encodedSeasonId } = useParams<{
    profileId: string;
    seasonId: string;
  }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const seasonId = encodedSeasonId ? decodeURIComponent(encodedSeasonId) : "";
  const navigate = useNavigate();
  const location = useLocation();

  // Determine current tab from URL
  const currentPath = location.pathname.split("/").pop();
  const tabValue = ["orders", "reports", "settings"].includes(currentPath || "")
    ? currentPath
    : "orders";

  // Fetch season data
  const {
    data: seasonData,
    loading: seasonLoading,
    error: seasonError,
  } = useQuery<{ getSeason: Season }>(GET_SEASON, {
    variables: { seasonId },
    skip: !seasonId,
  });

  // Debug logging
  if (seasonError) {
    console.error("Season query error:", seasonError);
    const apolloError = seasonError as any;
    console.log("Season error details:", {
      message: seasonError.message,
      graphQLErrors: apolloError.graphQLErrors,
      networkError: apolloError.networkError,
    });
  }

  // Fetch profile data
  const { data: profileData, loading: profileLoading } = useQuery<{
    getProfile: Profile;
  }>(GET_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  const season = seasonData?.getSeason;
  const profile = profileData?.getProfile;
  const hasWritePermission = profile && (profile.isOwner || profile.permissions?.includes('WRITE'));
  const loading = seasonLoading || profileLoading;

  const handleTabChange = (_event: React.SyntheticEvent, newValue: string) => {
    navigate(
      `/profiles/${encodeURIComponent(profileId)}/seasons/${encodeURIComponent(seasonId)}/${newValue}`,
    );
  };

  if (loading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="400px"
      >
        <CircularProgress />
      </Box>
    );
  }

  if (seasonError || !season) {
    return (
      <Alert severity="error">
        Season not found or you don't have access to this season.
      </Alert>
    );
  }

  return (
    <Box>
      {/* Breadcrumbs */}
      <Breadcrumbs sx={{ mb: 2 }}>
        <Link
          component="button"
          variant="body1"
          onClick={() => navigate("/profiles")}
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          Profiles
        </Link>
        <Link
          component="button"
          variant="body1"
          onClick={() =>
            navigate(`/profiles/${encodeURIComponent(profileId)}/seasons`)
          }
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          {profile?.sellerName || "Loading..."}
        </Link>
        <Typography color="text.primary">{season.seasonName}</Typography>
      </Breadcrumbs>

      {/* Header */}
      <Stack direction="row" alignItems="center" spacing={2} mb={3}>
        <IconButton
          edge="start"
          color="inherit"
          onClick={() =>
            navigate(`/profiles/${encodeURIComponent(profileId)}/seasons`)
          }
          sx={{ mr: 2 }}
        >
          <ArrowBackIcon />
        </IconButton>
        <Box flexGrow={1}>
          <Typography variant="h4" component="h1">
            {season.seasonName}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {new Date(season.startDate).toLocaleDateString("en-US", {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
            {season.endDate &&
              ` - ${new Date(season.endDate).toLocaleDateString("en-US", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}`}
          </Typography>
        </Box>
      </Stack>

      {/* Tabs */}
      <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 3 }}>
        <Tabs value={tabValue} onChange={handleTabChange}>
          <Tab
            label="Orders"
            value="orders"
            icon={<OrdersIcon />}
            iconPosition="start"
          />
          <Tab
            label="Reports"
            value="reports"
            icon={<ReportsIcon />}
            iconPosition="start"
          />
          {hasWritePermission && (
            <Tab
              label="Settings"
              value="settings"
              icon={<SettingsIcon />}
              iconPosition="start"
            />
          )}
        </Tabs>
      </Box>

      {/* Tab Content */}
      <Routes>
        <Route path="orders" element={<OrdersPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="settings" element={<SeasonSettingsPage />} />
        <Route path="/" element={<Navigate to="orders" replace />} />
        <Route path="*" element={<Navigate to="orders" replace />} />
      </Routes>
    </Box>
  );
};
