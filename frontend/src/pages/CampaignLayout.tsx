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
import { ensureProfileId, ensureCampaignId, toUrlId } from "../lib/ids";

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

// --- Helper Functions ---

function decodeParam(encoded: string | undefined): string {
  return encoded ? decodeURIComponent(encoded) : "";
}

function getTabValue(pathname: string): string {
  const currentPath = pathname.split("/").pop() || "";
  const validTabs = ["orders", "reports", "settings"];
  return validTabs.includes(currentPath) ? currentPath : "orders";
}

function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatDateRange(startDate?: string, endDate?: string): string | null {
  if (!startDate && !endDate) return null;
  const start = startDate ? formatDate(startDate) : "";
  const end = endDate ? ` - ${formatDate(endDate)}` : "";
  return `${start}${end}`;
}

function logCampaignError(error: Error): void {
  console.error("Campaign query error:", error);
  const apolloError = error as {
    graphQLErrors?: unknown;
    networkError?: unknown;
  };
  console.log("Campaign error details:", {
    message: error.message,
    graphQLErrors: apolloError.graphQLErrors,
    networkError: apolloError.networkError,
  });
}

// --- Sub-Components ---

const LoadingState: React.FC = () => (
  <Box
    display="flex"
    justifyContent="center"
    alignItems="center"
    minHeight="400px"
  >
    <CircularProgress />
  </Box>
);

const ErrorState: React.FC = () => (
  <Alert severity="error">
    Campaign not found or you don't have access to this campaign.
  </Alert>
);

interface CampaignBreadcrumbsProps {
  profileId: string;
  sellerName: string;
  campaignName: string;
  campaignYear: number;
  onNavigate: (path: string) => void;
}

const CampaignBreadcrumbs: React.FC<CampaignBreadcrumbsProps> = ({
  profileId,
  sellerName,
  campaignName,
  campaignYear,
  onNavigate,
}) => (
  <Breadcrumbs sx={{ mb: 2 }}>
    <Link
      component="button"
      variant="body1"
      onClick={() => onNavigate("/scouts")}
      sx={{ textDecoration: "none", cursor: "pointer" }}
    >
      Scouts
    </Link>
    <Link
      component="button"
      variant="body1"
      onClick={() => onNavigate(`/scouts/${toUrlId(profileId)}/campaigns`)}
      sx={{ textDecoration: "none", cursor: "pointer" }}
    >
      {sellerName}
    </Link>
    <Typography color="text.primary">
      {campaignName} {campaignYear}
    </Typography>
  </Breadcrumbs>
);

interface CampaignHeaderProps {
  campaign: Campaign;
  onBack: () => void;
}

const CampaignHeader: React.FC<CampaignHeaderProps> = ({
  campaign,
  onBack,
}) => {
  const dateRange = formatDateRange(campaign.startDate, campaign.endDate);

  return (
    <Stack direction="row" alignItems="center" spacing={2} mb={3}>
      <IconButton edge="start" color="inherit" onClick={onBack} sx={{ mr: 2 }}>
        <ArrowBackIcon />
      </IconButton>
      <Box flexGrow={1}>
        <Typography variant="h4" component="h1">
          {campaign.campaignName} {campaign.campaignYear}
        </Typography>
        {dateRange && (
          <Typography variant="body2" color="text.secondary">
            {dateRange}
          </Typography>
        )}
      </Box>
    </Stack>
  );
};

interface CampaignTabsProps {
  tabValue: string;
  hasWritePermission: boolean;
  onTabChange: (event: React.SyntheticEvent, newValue: string) => void;
}

const CampaignTabs: React.FC<CampaignTabsProps> = ({
  tabValue,
  hasWritePermission,
  onTabChange,
}) => (
  <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 3 }}>
    <Tabs value={tabValue} onChange={onTabChange}>
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
);

const CampaignRoutes: React.FC = () => (
  <Routes>
    <Route path="orders/new" element={<OrderEditorPage />} />
    <Route path="orders/:orderId/edit" element={<OrderEditorPage />} />
    <Route path="orders" element={<OrdersPage />} />
    <Route path="reports" element={<ReportsPage />} />
    <Route path="settings" element={<CampaignSettingsPage />} />
    <Route path="/" element={<Navigate to="orders" replace />} />
    <Route path="*" element={<Navigate to="orders" replace />} />
  </Routes>
);

// --- Custom Hook ---

function getWritePermission(profile: Profile | undefined): boolean {
  if (!profile) return false;
  return profile.isOwner || profile.permissions?.includes("WRITE") || false;
}

function useCampaignQuery(dbCampaignId: string | null) {
  const result = useQuery<{ getCampaign: Campaign }>(GET_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: !dbCampaignId,
  });

  if (result.error) {
    logCampaignError(result.error);
  }

  return {
    campaign: result.data?.getCampaign,
    loading: result.loading,
    error: result.error,
  };
}

function useProfileQuery(dbProfileId: string | null) {
  const result = useQuery<{ getProfile: Profile }>(GET_PROFILE, {
    variables: { profileId: dbProfileId },
    skip: !dbProfileId,
  });

  return {
    profile: result.data?.getProfile,
    loading: result.loading,
  };
}

function useNavigationHandlers(profileId: string, campaignId: string) {
  const navigate = useNavigate();

  const handleTabChange = (_event: React.SyntheticEvent, newValue: string) => {
    const url = `/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(campaignId)}/${newValue}`;
    navigate(url);
  };

  const handleBack = () => {
    navigate(`/scouts/${toUrlId(profileId)}/campaigns`);
  };

  return { navigate, handleTabChange, handleBack };
}

function useRouteParams() {
  const { profileId: encodedProfileId, campaignId: encodedCampaignId } =
    useParams<{ profileId: string; campaignId: string }>();
  const profileId = decodeParam(encodedProfileId);
  const campaignId = decodeParam(encodedCampaignId);
  return { profileId, campaignId };
}

// --- Content Component ---

interface CampaignContentProps {
  profileId: string;
  tabValue: string;
  campaign: Campaign;
  profile: Profile | undefined;
  navHandlers: ReturnType<typeof useNavigationHandlers>;
}

const CampaignContent: React.FC<CampaignContentProps> = ({
  profileId,
  tabValue,
  campaign,
  profile,
  navHandlers,
}) => (
  <Box>
    <CampaignBreadcrumbs
      profileId={profileId}
      sellerName={profile?.sellerName || "Loading..."}
      campaignName={campaign.campaignName}
      campaignYear={campaign.campaignYear}
      onNavigate={navHandlers.navigate}
    />
    <CampaignHeader campaign={campaign} onBack={navHandlers.handleBack} />
    <CampaignTabs
      tabValue={tabValue}
      hasWritePermission={getWritePermission(profile)}
      onTabChange={navHandlers.handleTabChange}
    />
    <CampaignRoutes />
  </Box>
);

// --- Main Component ---

export const CampaignLayout: React.FC = () => {
  const { profileId, campaignId } = useRouteParams();
  const tabValue = getTabValue(useLocation().pathname);

  const campaignQuery = useCampaignQuery(ensureCampaignId(campaignId));
  const profileQuery = useProfileQuery(ensureProfileId(profileId));
  const navHandlers = useNavigationHandlers(profileId, campaignId);

  if (campaignQuery.loading || profileQuery.loading) return <LoadingState />;
  if (campaignQuery.error || !campaignQuery.campaign) return <ErrorState />;

  return (
    <CampaignContent
      profileId={profileId}
      tabValue={tabValue}
      campaign={campaignQuery.campaign}
      profile={profileQuery.profile}
      navHandlers={navHandlers}
    />
  );
};
