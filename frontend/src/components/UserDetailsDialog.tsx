/**
 * UserDetailsDialog - Shows all data owned by a user with ability to edit/transfer
 *
 * Displays:
 * - User information
 * - All profiles (with transfer ownership)
 * - All catalogs (with transfer ownership)
 * - Campaigns (through profiles)
 * - Orders (through campaigns)
 */

import React, { useState } from 'react';
import { useQuery, useMutation, useLazyQuery } from '@apollo/client/react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
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
  IconButton,
  Tooltip,
  TextField,
  InputAdornment,
} from '@mui/material';
import { SwapHoriz as TransferIcon, Close as CloseIcon, Search as SearchIcon } from '@mui/icons-material';
import {
  ADMIN_GET_USER_PROFILES,
  ADMIN_GET_USER_CATALOGS,
  TRANSFER_PROFILE_OWNERSHIP,
  ADMIN_SEARCH_USER,
} from '../lib/graphql';
import type { AdminUser, SellerProfile, Catalog } from '../types';

interface UserDetailsDialogProps {
  open: boolean;
  onClose: () => void;
  user: AdminUser | null;
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div role="tabpanel" hidden={value !== index} id={`user-details-tabpanel-${index}`} {...other}>
      {value === index && <Box sx={{ py: 2 }}>{children}</Box>}
    </div>
  );
}

// eslint-disable-next-line complexity -- Complex rendering logic for tabs, transfer dialog, and multiple states
export const UserDetailsDialog: React.FC<UserDetailsDialogProps> = ({ open, onClose, user }) => {
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
    variables: { accountId: user?.accountId },
    skip: !user?.accountId,
  });

  // Fetch user's catalogs
  const {
    data: catalogsData,
    loading: catalogsLoading,
    error: catalogsError,
  } = useQuery<{ adminGetUserCatalogs: Catalog[] }>(ADMIN_GET_USER_CATALOGS, {
    variables: { accountId: user?.accountId },
    skip: !user?.accountId,
  });

  // Search for new owner
  const [searchNewOwner, { data: searchData, loading: searchLoading }] = useLazyQuery<{
    adminSearchUser: AdminUser[];
  }>(ADMIN_SEARCH_USER);

  // Transfer profile ownership
  const [transferOwnership, { loading: transferring }] = useMutation(TRANSFER_PROFILE_OWNERSHIP, {
    onCompleted: () => {
      setTransferProfileId(null);
      setSelectedNewOwner(null);
      setNewOwnerSearch('');
      refetchProfiles();
    },
  });

  const profiles = profilesData?.adminGetUserProfiles || [];
  const catalogs = catalogsData?.adminGetUserCatalogs || [];
  const searchResults = searchData?.adminSearchUser || [];

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

  const handleSearchNewOwner = () => {
    if (newOwnerSearch.trim()) {
      searchNewOwner({ variables: { query: newOwnerSearch.trim() } });
    }
  };

  const handleTransferProfile = () => {
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

  if (!user) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Box>
            <Typography variant="h6">{user.email}</Typography>
            <Typography variant="body2" color="text.secondary">
              {user.displayName || 'No name set'}
            </Typography>
          </Box>
          <IconButton onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Stack>
      </DialogTitle>
      <DialogContent>
        <Tabs value={currentTab} onChange={handleTabChange}>
          <Tab label={`Profiles (${profiles.length})`} />
          <Tab label={`Catalogs (${catalogs.length})`} />
        </Tabs>

        {/* Profiles Tab */}
        <TabPanel value={currentTab} index={0}>
          {profilesLoading ? (
            <CircularProgress />
          ) : profilesError ? (
            <Alert severity="error">Error loading profiles: {profilesError.message}</Alert>
          ) : profiles.length === 0 ? (
            <Alert severity="info">No profiles found</Alert>
          ) : (
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Profile ID</TableCell>
                    <TableCell>Seller Name</TableCell>
                    <TableCell>Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {profiles.map((profile) => (
                    <TableRow key={profile.profileId}>
                      <TableCell>
                        <Typography variant="body2" fontFamily="monospace">
                          {profile.profileId?.substring(0, 24)}...
                        </Typography>
                      </TableCell>
                      <TableCell>{profile.sellerName || '—'}</TableCell>
                      <TableCell>
                        <Tooltip title="Transfer Ownership">
                          <IconButton size="small" onClick={() => setTransferProfileId(profile.profileId ?? null)}>
                            <TransferIcon />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </TabPanel>

        {/* Catalogs Tab */}
        <TabPanel value={currentTab} index={1}>
          {catalogsLoading ? (
            <CircularProgress />
          ) : catalogsError ? (
            <Alert severity="error">Error loading catalogs: {catalogsError.message}</Alert>
          ) : catalogs.length === 0 ? (
            <Alert severity="info">No catalogs found</Alert>
          ) : (
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
        </TabPanel>
      </DialogContent>

      {/* Transfer Ownership Dialog */}
      <Dialog open={!!transferProfileId} onClose={() => setTransferProfileId(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Transfer Profile Ownership</DialogTitle>
        <DialogContent>
          <Typography variant="body2" paragraph>
            Search for the new owner by email or name:
          </Typography>
          <TextField
            fullWidth
            value={newOwnerSearch}
            onChange={(e) => setNewOwnerSearch(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSearchNewOwner()}
            placeholder="Search by email or name..."
            InputProps={{
              endAdornment: (
                <InputAdornment position="end">
                  <IconButton onClick={handleSearchNewOwner} disabled={searchLoading}>
                    <SearchIcon />
                  </IconButton>
                </InputAdornment>
              ),
            }}
            sx={{ mb: 2 }}
          />

          {searchLoading && <CircularProgress size={24} />}

          {searchResults.length > 0 && (
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Select new owner:
              </Typography>
              {searchResults
                .filter((u) => u.accountId !== user?.accountId)
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
          <Button onClick={() => setTransferProfileId(null)}>Cancel</Button>
          <Button onClick={handleTransferProfile} variant="contained" disabled={!selectedNewOwner || transferring}>
            {transferring ? 'Transferring...' : 'Transfer Ownership'}
          </Button>
        </DialogActions>
      </Dialog>
    </Dialog>
  );
};
