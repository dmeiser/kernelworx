/**
 * AdminPage - Admin console for managing users, profiles, and system-wide settings
 *
 * Only visible when user has isAdmin=true
 */

import React, { useState } from 'react';
import { useQuery } from '@apollo/client/react';
import {
  Box,
  Typography,
  Paper,
  Tabs,
  Tab,
  Alert,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Stack,
} from '@mui/material';
import { People as PeopleIcon, Inventory as CatalogIcon, Info as InfoIcon } from '@mui/icons-material';
import { LIST_MY_PROFILES, LIST_MANAGED_CATALOGS } from '../lib/graphql';
import type { SellerProfile, Catalog } from '../types';

// --- Type Definitions ---
interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

// --- Helper Components ---
function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`admin-tabpanel-${index}`}
      aria-labelledby={`admin-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ py: 3 }}>{children}</Box>}
    </div>
  );
}

const LoadingSpinner: React.FC = () => (
  <Box display="flex" justifyContent="center" py={4}>
    <CircularProgress />
  </Box>
);

const ErrorAlert: React.FC<{ message: string }> = ({ message }) => (
  <Alert severity="error">Failed to load: {message}</Alert>
);

// --- Profile Table Row ---
// eslint-disable-next-line complexity -- Component displays multiple profile fields with null-safe access
const ProfileRow: React.FC<{ profile: SellerProfile }> = ({ profile }) => (
  <TableRow hover>
    <TableCell>
      <Typography variant="body2" fontFamily="monospace">
        {profile.profileId?.substring(0, 12) ?? 'Unknown'}...
      </Typography>
    </TableCell>
    <TableCell>
      <Typography variant="body2" fontWeight="medium">
        {profile.sellerName ?? 'Unknown'}
      </Typography>
    </TableCell>
    <TableCell>
      <Typography variant="body2" color="text.secondary">
        {profile.ownerAccountId?.substring(0, 12) ?? 'Unknown'}...
      </Typography>
    </TableCell>
    <TableCell>
      {profile.isOwner ? (
        <Chip label="Owner" color="primary" size="small" />
      ) : (
        <Chip label="Shared" color="default" size="small" />
      )}
    </TableCell>
  </TableRow>
);

// --- Profiles Tab Content ---
interface ProfilesTabContentProps {
  loading: boolean;
  error: Error | undefined;
  profiles: SellerProfile[];
}

const ProfilesTabContent: React.FC<ProfilesTabContentProps> = ({ loading, error, profiles }) => {
  if (loading) {
    return <LoadingSpinner />;
  }
  if (error) {
    return <ErrorAlert message={error.message} />;
  }
  if (profiles.length === 0) {
    return <Alert severity="info">No profiles found in the system.</Alert>;
  }
  return (
    <TableContainer>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Profile ID</TableCell>
            <TableCell>Seller Name</TableCell>
            <TableCell>Owner</TableCell>
            <TableCell>Status</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {profiles.map((profile, index) => (
            <ProfileRow key={profile.profileId ?? `profile-${index}`} profile={profile} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

// --- Catalog Card ---
const CatalogCard: React.FC<{ catalog: Catalog }> = ({ catalog }) => (
  <Paper variant="outlined" sx={{ p: 2 }}>
    <Stack direction="row" justifyContent="space-between" alignItems="start">
      <Box>
        <Typography variant="subtitle1" fontWeight="medium">
          {catalog.catalogName ?? 'Unnamed Catalog'}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {catalog.catalogType ?? 'Unknown Type'}
        </Typography>
      </Box>
      <Chip
        label={catalog.isPublic ? 'Public' : 'Private'}
        color={catalog.isPublic ? 'success' : 'default'}
        size="small"
      />
    </Stack>
  </Paper>
);

// --- Catalogs Tab Content ---
interface CatalogsTabContentProps {
  loading: boolean;
  error: Error | undefined;
  catalogs: Catalog[];
}

const CatalogsTabContent: React.FC<CatalogsTabContentProps> = ({ loading, error, catalogs }) => {
  if (loading) {
    return <LoadingSpinner />;
  }
  if (error) {
    return <ErrorAlert message={error.message} />;
  }
  if (catalogs.length === 0) {
    return <Alert severity="info">No catalogs found. Create your first catalog!</Alert>;
  }
  return (
    <Stack spacing={2}>
      {catalogs.map((catalog, index) => (
        <CatalogCard key={catalog.catalogId ?? `catalog-${index}`} catalog={catalog} />
      ))}
    </Stack>
  );
};

// --- System Info Tab Content ---
const SystemInfoTabContent: React.FC = () => (
  <>
    <Typography variant="h6" gutterBottom>
      System Information
    </Typography>
    <Stack spacing={2}>
      <Box>
        <Typography variant="subtitle2" color="text.secondary">
          Application Version
        </Typography>
        <Typography variant="body1">1.0.0-beta</Typography>
      </Box>
      <Box>
        <Typography variant="subtitle2" color="text.secondary">
          Backend API
        </Typography>
        <Typography variant="body1">AWS AppSync GraphQL (api.dev.psm.repeatersolutions.com)</Typography>
      </Box>
      <Box>
        <Typography variant="subtitle2" color="text.secondary">
          Database
        </Typography>
        <Typography variant="body1">Amazon DynamoDB (On-Demand)</Typography>
      </Box>
      <Box>
        <Typography variant="subtitle2" color="text.secondary">
          Authentication
        </Typography>
        <Typography variant="body1">AWS Cognito (Social Login Enabled)</Typography>
      </Box>
      <Box>
        <Typography variant="subtitle2" color="text.secondary">
          File Storage
        </Typography>
        <Typography variant="body1">Amazon S3 (Reports & Exports)</Typography>
      </Box>
    </Stack>
    <Alert severity="info" sx={{ mt: 3 }}>
      <strong>Admin Features In Development:</strong>
      <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
        <li>User management (view all users, reset passwords, disable accounts)</li>
        <li>Profile management (transfer ownership, hard delete)</li>
        <li>Order management (view all orders, restore soft-deleted, hard delete)</li>
        <li>Catalog CRUD (create, edit, delete official catalogs and products)</li>
        <li>System analytics (usage stats, popular products, sales trends)</li>
        <li>Audit logs (view all admin actions and changes)</li>
      </ul>
    </Alert>
  </>
);

// --- Main Component ---
export const AdminPage: React.FC = () => {
  const [currentTab, setCurrentTab] = useState(0);

  // Fetch all profiles (admin can see all)
  const {
    data: profilesData,
    loading: profilesLoading,
    error: profilesError,
  } = useQuery<{ listMyProfiles: SellerProfile[] }>(LIST_MY_PROFILES);

  // Fetch public catalogs
  const {
    data: catalogsData,
    loading: catalogsLoading,
    error: catalogsError,
  } = useQuery<{ listManagedCatalogs: Catalog[] }>(LIST_MANAGED_CATALOGS);

  const profiles = profilesData?.listMyProfiles || [];
  const catalogs = catalogsData?.listManagedCatalogs || [];

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

  return (
    <Box>
      <Typography variant="h4" component="h1" gutterBottom>
        Admin Console
      </Typography>

      <Alert severity="warning" sx={{ mb: 3 }}>
        <strong>Administrator Access:</strong> You have elevated privileges. Use this console responsibly.
      </Alert>

      {/* Tabs */}
      <Paper sx={{ mb: 3 }}>
        <Tabs value={currentTab} onChange={handleTabChange}>
          <Tab label="Profiles" icon={<PeopleIcon />} iconPosition="start" />
          <Tab label="Catalogs" icon={<CatalogIcon />} iconPosition="start" />
          <Tab label="System Info" icon={<InfoIcon />} iconPosition="start" />
        </Tabs>
      </Paper>

      {/* Tab Panels */}
      <TabPanel value={currentTab} index={0}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            All Scouts
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            View all scouts in the system. Full CRUD operations coming in future updates.
          </Typography>
          <ProfilesTabContent loading={profilesLoading} error={profilesError} profiles={profiles} />
        </Paper>
      </TabPanel>

      <TabPanel value={currentTab} index={1}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Product Catalogs
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            Manage official product catalogs. Create, edit, and deactivate catalog items.
          </Typography>
          <CatalogsTabContent loading={catalogsLoading} error={catalogsError} catalogs={catalogs} />
          <Alert severity="info" sx={{ mt: 3 }}>
            <strong>Coming Soon:</strong> Full catalog management (create, edit, delete items). For now, use the AWS
            Console or GraphQL API directly.
          </Alert>
        </Paper>
      </TabPanel>

      <TabPanel value={currentTab} index={2}>
        <Paper sx={{ p: 3 }}>
          <SystemInfoTabContent />
        </Paper>
      </TabPanel>
    </Box>
  );
};
