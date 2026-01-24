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
  CircularProgress,
  Alert,
  Button,
  IconButton,
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
  Delete as DeleteIcon,
  Edit as EditIcon,
} from '@mui/icons-material';
import {
  ADMIN_GET_USER_PROFILES,
  ADMIN_GET_USER_CATALOGS,
  ADMIN_GET_USER_CAMPAIGNS,
  ADMIN_GET_USER_SHARED_CAMPAIGNS,
  ADMIN_GET_PROFILE_SHARES,
  TRANSFER_PROFILE_OWNERSHIP,
  ADMIN_SEARCH_USER,
  ADMIN_DELETE_SHARE,
  ADMIN_UPDATE_CAMPAIGN_SHARED_CODE,
} from '../lib/graphql';
import type { SellerProfile, Catalog, AdminUser } from '../types';

interface Campaign {
  campaignId: string;
  profileId: string;
  campaignName: string;
  campaignYear: number;
  catalogId: string;
  startDate?: string;
  endDate?: string;
  sharedCampaignCode?: string;
  createdAt?: string;
  updatedAt?: string;
}

interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  campaignName: string;
  campaignYear: number;
  startDate?: string;
  endDate?: string;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  createdAt?: string;
}

interface Share {
  shareId: string;
  profileId: string;
  targetAccountId: string;
  targetAccount?: {
    accountId: string;
    email: string;
    givenName?: string;
    familyName?: string;
  };
  permissions: string[];
  createdAt?: string;
}

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

/* eslint-disable complexity -- UserDataPage has multiple tabs and data management flows */
export const UserDataPage: React.FC = () => {
  const { accountId } = useParams<{ accountId: string }>();
  const navigate = useNavigate();
  const [currentTab, setCurrentTab] = useState(0);
  const [transferProfileId, setTransferProfileId] = useState<string | null>(null);
  const [newOwnerSearch, setNewOwnerSearch] = useState('');
  const [selectedNewOwner, setSelectedNewOwner] = useState<AdminUser | null>(null);
  const [editingCampaignId, setEditingCampaignId] = useState<string | null>(null);
  const [editingSharedCode, setEditingSharedCode] = useState('');
  const [selectedProfileForCampaigns, setSelectedProfileForCampaigns] = useState<string | null>(null);

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

  // Fetch user's campaigns
  const {
    data: campaignsData,
    loading: campaignsLoading,
    error: campaignsError,
    refetch: refetchCampaigns,
  } = useQuery<{ adminGetUserCampaigns: Campaign[] }>(ADMIN_GET_USER_CAMPAIGNS, {
    variables: { accountId },
    skip: !accountId,
  });

  // Fetch user's shared campaigns
  const {
    data: sharedCampaignsData,
    loading: sharedCampaignsLoading,
    error: sharedCampaignsError,
  } = useQuery<{ adminGetUserSharedCampaigns: SharedCampaign[] }>(ADMIN_GET_USER_SHARED_CAMPAIGNS, {
    variables: { accountId },
    skip: !accountId,
  });

  // Fetch shares for all profiles
  const [selectedProfileForShares, setSelectedProfileForShares] = useState<string | null>(null);
  const {
    data: sharesData,
    loading: sharesLoading,
    refetch: refetchShares,
  } = useQuery<{ adminGetProfileShares: Share[] }>(ADMIN_GET_PROFILE_SHARES, {
    variables: { profileId: selectedProfileForShares },
    skip: !selectedProfileForShares,
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

  // Delete share mutation
  const [deleteShare] = useMutation(ADMIN_DELETE_SHARE, {
    onCompleted: () => {
      refetchShares();
    },
    onError: (error) => {
      console.error('Delete share failed:', error);
    },
  });

  // Update campaign shared code mutation
  const [updateCampaignSharedCode] = useMutation(ADMIN_UPDATE_CAMPAIGN_SHARED_CODE, {
    onCompleted: () => {
      setEditingCampaignId(null);
      setEditingSharedCode('');
      refetchCampaigns();
    },
    onError: (error) => {
      console.error('Update shared code failed:', error);
    },
  });

  const profiles = profilesData?.adminGetUserProfiles || [];
  const catalogs = catalogsData?.adminGetUserCatalogs || [];
  const allCampaigns = campaignsData?.adminGetUserCampaigns || [];

  // Filter campaigns by selected profile
  const campaigns = selectedProfileForCampaigns
    ? allCampaigns.filter((c) => c.profileId === selectedProfileForCampaigns)
    : [];

  const sharedCampaigns = sharedCampaignsData?.adminGetUserSharedCampaigns || [];
  const shares = sharesData?.adminGetProfileShares || [];
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
          <Tab label={`Campaigns (${campaigns.length})`} />
          <Tab label={`Shared Campaigns (${sharedCampaigns.length})`} />
          <Tab label={`Shares`} />
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

      {/* Campaigns Tab */}
      <TabPanel value={currentTab} index={2}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Profile Campaigns
          </Typography>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Select a profile to view and manage its campaigns.
          </Typography>

          {campaignsLoading && (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress />
              <Typography variant="body2" sx={{ ml: 2 }}>
                Loading campaigns...
              </Typography>
            </Box>
          )}

          {campaignsError && <Alert severity="error">Error loading campaigns: {campaignsError.message}</Alert>}

          {!campaignsLoading && !campaignsError && profiles.length === 0 && (
            <Alert severity="info">No profiles to manage campaigns for.</Alert>
          )}

          {!campaignsLoading && !campaignsError && profiles.length > 0 && (
            <>
              <Alert severity="info" sx={{ mb: 2 }}>
                Total campaigns loaded: {allCampaigns.length}
              </Alert>
              <Box sx={{ mb: 3 }}>
                {profiles.map((profile) => (
                  <Button
                    key={profile.profileId}
                    variant={selectedProfileForCampaigns === profile.profileId ? 'contained' : 'outlined'}
                    onClick={() => setSelectedProfileForCampaigns(profile.profileId)}
                    sx={{ mr: 1, mb: 1 }}
                  >
                    {profile.sellerName}
                  </Button>
                ))}
              </Box>

              {selectedProfileForCampaigns && (
                <>
                  {campaigns.length === 0 && (
                    <Alert severity="info">
                      No campaigns found for this profile. (Total campaigns in system: {allCampaigns.length})
                    </Alert>
                  )}

                  {campaigns.length > 0 && (
                    <TableContainer>
                      <Table>
                        <TableHead>
                          <TableRow>
                            <TableCell>Campaign Name</TableCell>
                            <TableCell>Year</TableCell>
                            <TableCell>Dates</TableCell>
                            <TableCell>Catalog</TableCell>
                            <TableCell>Shared Code</TableCell>
                            <TableCell align="right">Actions</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {campaigns.map((campaign) => (
                            <TableRow key={campaign.campaignId}>
                              <TableCell>{campaign.campaignName}</TableCell>
                              <TableCell>{campaign.campaignYear}</TableCell>
                              <TableCell>
                                <Typography variant="body2">
                                  {campaign.startDate ? new Date(campaign.startDate).toLocaleDateString() : '—'} -{' '}
                                  {campaign.endDate ? new Date(campaign.endDate).toLocaleDateString() : '—'}
                                </Typography>
                              </TableCell>
                              <TableCell>
                                <Typography variant="body2" fontSize="0.75rem">
                                  {campaign.catalogId}
                                </Typography>
                              </TableCell>
                              <TableCell>
                                {editingCampaignId === campaign.campaignId ? (
                                  <Box>
                                    <TextField
                                      size="small"
                                      value={editingSharedCode}
                                      onChange={(e) => setEditingSharedCode(e.target.value)}
                                      placeholder="Enter code or leave blank to remove"
                                      helperText="Clear field to unassociate"
                                      fullWidth
                                    />
                                  </Box>
                                ) : (
                                  <Typography variant="body2" fontFamily="monospace">
                                    {campaign.sharedCampaignCode || '—'}
                                  </Typography>
                                )}
                              </TableCell>
                              <TableCell align="right">
                                {editingCampaignId === campaign.campaignId ? (
                                  <>
                                    <Button
                                      size="small"
                                      onClick={() => {
                                        updateCampaignSharedCode({
                                          variables: {
                                            campaignId: campaign.campaignId,
                                            sharedCampaignCode: editingSharedCode || null,
                                          },
                                        });
                                      }}
                                    >
                                      Save
                                    </Button>
                                    <Button
                                      size="small"
                                      onClick={() => {
                                        setEditingCampaignId(null);
                                        setEditingSharedCode('');
                                      }}
                                    >
                                      Cancel
                                    </Button>
                                    {editingSharedCode && (
                                      <Button size="small" onClick={() => setEditingSharedCode('')} color="warning">
                                        Clear
                                      </Button>
                                    )}
                                  </>
                                ) : (
                                  <Button
                                    size="small"
                                    startIcon={<EditIcon />}
                                    onClick={() => {
                                      setEditingCampaignId(campaign.campaignId);
                                      setEditingSharedCode(campaign.sharedCampaignCode || '');
                                    }}
                                    variant="outlined"
                                  >
                                    Edit
                                  </Button>
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                </>
              )}
            </>
          )}
        </Paper>
      </TabPanel>

      {/* Shared Campaigns Tab */}
      <TabPanel value={currentTab} index={3}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Shared Campaigns Created by User
          </Typography>

          {sharedCampaignsLoading && (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress />
            </Box>
          )}

          {sharedCampaignsError && (
            <Alert severity="error">Error loading shared campaigns: {sharedCampaignsError.message}</Alert>
          )}

          {!sharedCampaignsLoading && !sharedCampaignsError && sharedCampaigns.length === 0 && (
            <Alert severity="info">No shared campaigns found for this user.</Alert>
          )}

          {!sharedCampaignsLoading && !sharedCampaignsError && sharedCampaigns.length > 0 && (
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Shared Code</TableCell>
                    <TableCell>Campaign Name</TableCell>
                    <TableCell>Unit</TableCell>
                    <TableCell>Start Date</TableCell>
                    <TableCell>End Date</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {sharedCampaigns.map((sharedCampaign) => (
                    <TableRow key={sharedCampaign.sharedCampaignCode}>
                      <TableCell>
                        <Typography variant="body2" fontFamily="monospace" fontWeight="bold">
                          {sharedCampaign.sharedCampaignCode}
                        </Typography>
                      </TableCell>
                      <TableCell>{sharedCampaign.campaignName}</TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {sharedCampaign.unitType} #{sharedCampaign.unitNumber}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {sharedCampaign.city}, {sharedCampaign.state}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        {sharedCampaign.startDate ? new Date(sharedCampaign.startDate).toLocaleDateString() : '—'}
                      </TableCell>
                      <TableCell>
                        {sharedCampaign.endDate ? new Date(sharedCampaign.endDate).toLocaleDateString() : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Paper>
      </TabPanel>

      {/* Shares Tab */}
      <TabPanel value={currentTab} index={4}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Profile Shares
          </Typography>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Select a profile to view and manage who has access to it.
          </Typography>

          {profiles.length === 0 ? (
            <Alert severity="info">No profiles to manage shares for.</Alert>
          ) : (
            <>
              <Box sx={{ mb: 3 }}>
                {profiles.map((profile) => (
                  <Button
                    key={profile.profileId}
                    variant={selectedProfileForShares === profile.profileId ? 'contained' : 'outlined'}
                    onClick={() => setSelectedProfileForShares(profile.profileId)}
                    sx={{ mr: 1, mb: 1 }}
                  >
                    {profile.sellerName}
                  </Button>
                ))}
              </Box>

              {selectedProfileForShares && (
                <>
                  {sharesLoading && (
                    <Box display="flex" justifyContent="center" py={4}>
                      <CircularProgress />
                    </Box>
                  )}

                  {!sharesLoading && shares.length === 0 && (
                    <Alert severity="info">No shares found for this profile.</Alert>
                  )}

                  {!sharesLoading && shares.length > 0 && (
                    <TableContainer>
                      <Table>
                        <TableHead>
                          <TableRow>
                            <TableCell>User Email</TableCell>
                            <TableCell>Permissions</TableCell>
                            <TableCell>Granted</TableCell>
                            <TableCell align="right">Actions</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {shares.map((share) => (
                            <TableRow key={share.targetAccountId}>
                              <TableCell>
                                <Typography variant="body2">{share.targetAccount?.email || 'Unknown'}</Typography>
                                {(share.targetAccount?.givenName || share.targetAccount?.familyName) && (
                                  <Typography variant="caption" color="text.secondary">
                                    {share.targetAccount.givenName} {share.targetAccount.familyName}
                                  </Typography>
                                )}
                              </TableCell>
                              <TableCell>
                                {share.permissions?.map((perm) => (
                                  <Chip key={perm} label={perm} size="small" sx={{ mr: 0.5 }} />
                                ))}
                              </TableCell>
                              <TableCell>
                                {share.createdAt ? new Date(share.createdAt).toLocaleDateString() : '—'}
                              </TableCell>
                              <TableCell align="right">
                                <Button
                                  size="small"
                                  startIcon={<DeleteIcon />}
                                  onClick={() => {
                                    const email = share.targetAccount?.email || 'this user';
                                    if (
                                      window.confirm(
                                        `Are you sure you want to revoke ${email}'s access to this profile?`,
                                      )
                                    ) {
                                      deleteShare({
                                        variables: {
                                          profileId: selectedProfileForShares,
                                          targetAccountId: share.targetAccountId,
                                        },
                                      });
                                    }
                                  }}
                                  color="error"
                                  variant="outlined"
                                >
                                  Revoke
                                </Button>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                </>
              )}
            </>
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
