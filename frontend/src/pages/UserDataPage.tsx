/**
 * UserDataPage - Admin page for viewing and managing all data owned by a specific user
 *
 * Displays:
 * - User information
 * - All profiles (with transfer ownership)
 * - All catalogs
 * - All campaigns (through profiles)
 * - All orders (through campaigns)
 *
 * Route: /admin/user-data/:accountId
 */

import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useLazyQuery } from '@apollo/client/react';
import {
  Box,
  Typography,
  Paper,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Stack,
  CircularProgress,
  Alert,
  Button,
  IconButton,
  Tooltip,
  TextField,
  InputAdornment,
  Breadcrumbs,
  Link,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import {
  SwapHoriz as TransferIcon,
  ArrowBack as BackIcon,
  Search as SearchIcon,
} from '@mui/icons-material';
import {
  ADMIN_GET_USER_PROFILES,
  ADMIN_GET_USER_CATALOGS,
  TRANSFER_PROFILE_OWNERSHIP,
  ADMIN_SEARCH_USER,
} from '../lib/graphql';
import type { SellerProfile, Catalog, AdminUser } from '../types';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`user-data-tabpanel-${index}`}
      aria-labelledby={`user-data-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ py: 3 }}>{children}</Box>}
    </div>
  );
}

export const UserDataPage: React.FC = () => {
  const { accountId } = useParams<{ accountId: string }>();
  const navigate = useNavigate();
  const [currentTab, setCurrentTab] = useState(0);
  const [transferProfileId, setTransferProfileId] = useState<string | null>(null);
  const [newOwnerSearch, setNewOwnerSearch] = useState('');
  const [selectedNewOwner, setSelectedNewOwner] = useState<AdminUser | null>(null);

  // Fetch user's profiles
  const {
    data: profilesData,
    loading: profilesLoading,
    error: profilesError,
    refetch: refetchProfiles,
  } = useQuery<{ adminGetUserProfiles: SellerProfile[] }>(ADMIN_GET_USER_PROFILES, {
    variables: { accountId },
    skip: !accountId,
  });

  // Fetch user's catalogs
  const {
    data: catalogsData,
    loading: catalogsLoading,
    error: catalogsError,
  } = useQuery<{ adminGetUserCatalogs: Catalog[] }>(ADMIN_GET_USER_CATALOGS, {
    variables: { accountId },
    skip: !accountId,
  });

  // Search for new owner
  const [searchNewOwner, { data: searchData, loading: searchLoading }] = useLazyQuery<{
    adminSearchUser: AdminUser[];
  }>(ADMIN_SEARCH_USER);

  // Transfer ownership mutation
  const [transferOwnership, { loading: transferring }] = useMutation(TRANSFER_PROFILE_OWNERSHIP, {
    onCompleted: () => {
      setTransferProfileId(null);
      setNewOwnerSearch('');
      setSelectedNewOwner(null);
      refetchProfiles();
    },
    onError: (error) => {
      console.error('Transfer failed:', error);
    },
  });

  const profiles = profilesData?.adminGetUserProfiles || [];
  const catalogs = catalogsData?.adminGetUserCatalogs || [];
  const searchResults = searchData?.adminSearchUser || [];

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

  const handleTransferClick = (profileId: string) => {
    setTransferProfileId(profileId);
    setNewOwnerSearch('');
    setSelectedNewOwner(null);
  };

  const handleSearchNewOwner = () => {
    if (newOwnerSearch.trim()) {
      searchNewOwner({ variables: { query: newOwnerSearch.trim() } });
    }
  };

  const handleConfirmTransfer = () => {
    if (transferProfileId && selectedNewOwner) {
      transferOwnership({
        variables: {
          input: {
            profileId: transferProfileId,
            newOwnerAccountId: selectedNewOwner.accountId,
          },
        },
      });
    }
  };

  const handleCancelTransfer = () => {
    setTransferProfileId(null);
    setNewOwnerSearch('');
    setSelectedNewOwner(null);
  };

  if (!accountId) {
    return (
      <Box p={3}>
        <Alert severity="error">No account ID provided</Alert>
      </Box>
    );
  }

  const profileIdWithoutPrefix = accountId.replace('ACCOUNT#', '');

  return (
    <Box>
      {/* Breadcrumbs */}
      <Breadcrumbs sx={{ mb: 2 }}>
        <Link
          component="button"
          variant="body1"
          onClick={() => navigate('/admin')}
          sx={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 0.5 }}
        >
          <BackIcon fontSize="small" />
          Admin Console
        </Link>
        <Typography color="text.primary">User Data: {profileIdWithoutPrefix}</Typography>
      </Breadcrumbs>

      {/* User Info Header */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h5" gutterBottom>
          User Data Management
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Account ID: {accountId}
        </Typography>
      </Paper>

      {/* Tabs */}
      <Paper sx={{ mb: 3 }}>
        <Tabs value={currentTab} onChange={handleTabChange}>
          <Tab label={`Profiles (${profiles.length})`} />
          <Tab label={`Catalogs (${catalogs.length})`} />
        </Tabs>
      </Paper>

      {/* Profiles Tab */}
      <TabPanel value={currentTab} index={0}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Seller Profiles
          </Typography>

          {profilesLoading && (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress />
            </Box>
          )}

          {profilesError && <Alert severity="error">Error loading profiles: {profilesError.message}</Alert>}

          {!profilesLoading && !profilesError && profiles.length === 0 && (
            <Alert severity="info">No profiles found for this user.</Alert>
          )}

          {!profilesLoading && !profilesError && profiles.length > 0 && (
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Profile ID</TableCell>
                    <TableCell>Seller Name</TableCell>
                    <TableCell>Created</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {profiles.map((profile) => (
                    <TableRow key={profile.profileId}>
                      <TableCell>
                        <Typography variant="body2" fontFamily="monospace">
                          {profile.profileId}
                        </Typography>
                      </TableCell>
                      <TableCell>{profile.sellerName}</TableCell>
                      <TableCell>
                        {profile.createdAt ? new Date(profile.createdAt).toLocaleDateString() : '—'}
                      </TableCell>
                      <TableCell align="right">
                        <Button
                          size="small"
                          startIcon={<TransferIcon />}
                          onClick={() => handleTransferClick(profile.profileId)}
                          variant="outlined"
                        >
                          Transfer
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Paper>
      </TabPanel>

      {/* Catalogs Tab */}
      <TabPanel value={currentTab} index={1}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Product Catalogs
          </Typography>

          {catalogsLoading && (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress />
            </Box>
          )}

          {catalogsError && <Alert severity="error">Error loading catalogs: {catalogsError.message}</Alert>}

          {!catalogsLoading && !catalogsError && catalogs.length === 0 && (
            <Alert severity="info">No catalogs found for this user.</Alert>
          )}

          {!catalogsLoading && !catalogsError && catalogs.length > 0 && (
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Catalog Name</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell>Products</TableCell>
                    <TableCell>Public</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {/* eslint-disable-next-line complexity -- Catalog table row with conditional chips */}
                  {catalogs.map((catalog) => (
                    <TableRow key={catalog.catalogId}>
                      <TableCell>{catalog.catalogName}</TableCell>
                      <TableCell>
                        <Chip
                          label={catalog.catalogType === 'ADMIN_MANAGED' ? 'Managed' : 'User'}
                          size="small"
                          color={catalog.catalogType === 'ADMIN_MANAGED' ? 'primary' : 'default'}
                        />
                      </TableCell>
                      <TableCell>{catalog.products?.length || 0}</TableCell>
                      <TableCell>
                        <Chip label={catalog.isPublic ? 'Yes' : 'No'} size="small" />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Paper>
      </TabPanel>

      {/* Transfer Ownership Dialog */}
      <Dialog open={!!transferProfileId} onClose={handleCancelTransfer} maxWidth="sm" fullWidth>
        <DialogTitle>Transfer Profile Ownership</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Search for the new owner by email address
          </Typography>

          <TextField
            fullWidth
            label="New Owner Email"
            value={newOwnerSearch}
            onChange={(e) => setNewOwnerSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearchNewOwner()}
            sx={{ mt: 2 }}
            InputProps={{
              endAdornment: (
                <InputAdornment position="end">
                  <IconButton onClick={handleSearchNewOwner} disabled={!newOwnerSearch.trim() || searchLoading}>
                    <SearchIcon />
                  </IconButton>
                </InputAdornment>
              ),
            }}
          />

          {searchLoading && <CircularProgress size={24} />}

          {searchResults.length > 0 && (
            <Box mt={2}>
              <Typography variant="subtitle2" gutterBottom>
                Select new owner:
              </Typography>
              {searchResults
                .filter((u) => u.accountId !== accountId)
                // eslint-disable-next-line complexity -- User selection row with conditional styling for selected state
                .map((searchUser) => (
                  <Box
                    key={searchUser.accountId}
                    sx={{
                      p: 1,
                      mb: 1,
                      border: 1,
                      borderColor: selectedNewOwner?.accountId === searchUser.accountId ? 'primary.main' : 'divider',
                      borderRadius: 1,
                      cursor: 'pointer',
                      bgcolor:
                        selectedNewOwner?.accountId === searchUser.accountId ? 'action.selected' : 'background.paper',
                    }}
                    onClick={() => setSelectedNewOwner(searchUser)}
                  >
                    <Typography variant="body2">{searchUser.email}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {searchUser.displayName || 'No name'}
                    </Typography>
                  </Box>
                ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelTransfer}>Cancel</Button>
          <Button
            onClick={handleConfirmTransfer}
            variant="contained"
            disabled={!selectedNewOwner || transferring}
            startIcon={transferring ? <CircularProgress size={16} /> : <TransferIcon />}
          >
            {transferring ? 'Transferring...' : 'Confirm Transfer'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
