/**
 * CampaignLayout - Tabbed layout for campaign views
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
import { OrderEditorPage } from "./OrderEditorPage";
import { ReportsPage } from "./ReportsPage";
import { CampaignSettingsPage } from "./CampaignSettingsPage";
import { GET_CAMPAIGN, GET_PROFILE } from "../lib/graphql";

interface Campaign {
  campaignId: string;
  campaignName: string;
  campaignYear: number;
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

export const CampaignLayout: React.FC = () => {
  const { profileId: encodedProfileId, campaignId: encodedCampaignId } = useParams<{
    profileId: string;
    campaignId: string;
  }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const campaignId = encodedCampaignId ? decodeURIComponent(encodedCampaignId) : "";
  const navigate = useNavigate();
  const location = useLocation();

  // Determine current tab from URL
  const currentPath = location.pathname.split("/").pop();
  const tabValue = ["orders", "reports", "settings"].includes(currentPath || "")
    ? currentPath
    : "orders";

  // Fetch campaign data
  const {
    data: campaignData,
    loading: campaignLoading,
    error: campaignError,
  } = useQuery<{ getCampaign: Campaign }>(GET_CAMPAIGN, {
    variables: { campaignId },
    skip: !campaignId,
  });

  // Debug logging
  if (campaignError) {
    console.error("Campaign query error:", campaignError);
    const apolloError = campaignError as {
      graphQLErrors?: unknown;
      networkError?: unknown;
    };
    console.log("Campaign error details:", {
      message: campaignError.message,
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

  const campaign = campaignData?.getCampaign;
  const profile = profileData?.getProfile;
  const hasWritePermission =
    profile && (profile.isOwner || profile.permissions?.includes("WRITE"));
  const loading = campaignLoading || profileLoading;

  const handleTabChange = (_event: React.SyntheticEvent, newValue: string) => {
    navigate(
      `/scouts/${encodeURIComponent(profileId)}/campaigns/${encodeURIComponent(campaignId)}/${newValue}`,
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

  if (campaignError || !campaign) {
    return (
      <Alert severity="error">
        Campaign not found or you don't have access to this campaign.
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
          onClick={() => navigate("/scouts")}
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          Scouts
        </Link>
        <Link
          component="button"
          variant="body1"
          onClick={() =>
            navigate(`/scouts/${encodeURIComponent(profileId)}/campaigns`)
          }
          sx={{ textDecoration: "none", cursor: "pointer" }}
        >
          {profile?.sellerName || "Loading..."}
        </Link>
        <Typography color="text.primary">
          {campaign.campaignName} {campaign.campaignYear}
        </Typography>
      </Breadcrumbs>

      {/* Header */}
      <Stack direction="row" alignItems="center" spacing={2} mb={3}>
        <IconButton
          edge="start"
          color="inherit"
          onClick={() =>
            navigate(`/scouts/${encodeURIComponent(profileId)}/campaigns`)
          }
          sx={{ mr: 2 }}
        >
          <ArrowBackIcon />
        </IconButton>
        <Box flexGrow={1}>
          <Typography variant="h4" component="h1">
            {campaign.campaignName} {campaign.campaignYear}
          </Typography>
          {(campaign.startDate || campaign.endDate) && (
            <Typography variant="body2" color="text.secondary">
              {campaign.startDate &&
                new Date(campaign.startDate).toLocaleDateString("en-US", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              {campaign.endDate &&
                ` - ${new Date(campaign.endDate).toLocaleDateString("en-US", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}`}
            </Typography>
          )}
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
        <Route path="orders/new" element={<OrderEditorPage />} />
        <Route path="orders/:orderId/edit" element={<OrderEditorPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="settings" element={<CampaignSettingsPage />} />
        <Route path="/" element={<Navigate to="orders" replace />} />
        <Route path="*" element={<Navigate to="orders" replace />} />
      </Routes>
    </Box>
  );
};
