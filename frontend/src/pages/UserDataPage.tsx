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
  Stack,
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
import { LoadingState } from '../components/LoadingState';
import { MfaSetupRequiredState } from '../components/MfaSetupRequiredState';
import { useAdminMfa } from '../hooks/useAdminMfa';
import { isMfaRequiredError } from '../lib/mfaErrors';
import { NavBreadcrumbs } from '../components/NavBreadcrumbs';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { formatDisplayDate } from '../lib/date-utils';
import type { GqlSellerProfile, GqlCatalog, GqlAdminUser } from '../types';

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

// --- Presentational tab subcomponents -------------------------------------------
//
// Each tab's render tree (loading / error / empty / populated status handling and
// its table) is a small presentational component so the page component itself stays
// a flat coordinator: hooks + early returns + <Tab>s + <TabPanel><*Tab/></TabPanel>
// (issue #532).

interface GuardedListProps {
  loading: boolean;
  error?: Error;
  errorPrefix?: string;
  empty: boolean;
  emptyMessage: string;
  children: React.ReactNode;
}

// Shared loading/error/empty guard: early-returns a status node, otherwise renders
// the populated branch passed as children — callers carry no `&&` guard chains of
// their own.
const GuardedList: React.FC<GuardedListProps> = ({ loading, error, errorPrefix, empty, emptyMessage, children }) => {
  if (loading) return <LoadingState py={4} />;
  if (error) return <Alert severity="error">{errorPrefix}{error.message}</Alert>;
  if (empty) return <Alert severity="info">{emptyMessage}</Alert>;
  return <>{children}</>;
};

// True when a query or the admin-MFA gate signals an MFA requirement (used by the
// page to fold a five-way `||` chain into a lookup).
const mfaErrorIn = (error: Error | undefined): boolean => (error ? isMfaRequiredError(error) : false);

// Filter the user's campaigns to one profile (was an inline ternary in the page).
const campaignsForProfile = (campaigns: Campaign[], profileId: string | null): Campaign[] =>
  profileId ? campaigns.filter((c) => c.profileId === profileId) : [];

interface ProfilesTabProps {
  loading: boolean;
  error?: Error;
  profiles: GqlSellerProfile[];
  onTransfer: (profileId: string) => void;
}

const ProfilesTab: React.FC<ProfilesTabProps> = ({ loading, error, profiles, onTransfer }) => (
  <>
    <Typography variant="h6" gutterBottom>
      Seller Profiles
    </Typography>
    <GuardedList
      loading={loading}
      error={error}
      errorPrefix="Error loading profiles: "
      empty={profiles.length === 0}
      emptyMessage="No profiles found for this user."
    >
      <ProfilesTable profiles={profiles} onTransfer={onTransfer} />
    </GuardedList>
  </>
);

interface ProfilesTableProps {
  profiles: GqlSellerProfile[];
  onTransfer: (profileId: string) => void;
}

const ProfilesTable: React.FC<ProfilesTableProps> = ({ profiles, onTransfer }) => (
  <TableContainer sx={{ overflowX: 'auto' }}>
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
            <TableCell>{formatDisplayDate(profile.createdAt) || '—'}</TableCell>
            <TableCell align="right">
              <Button
                size="small"
                startIcon={<TransferIcon />}
                onClick={() => onTransfer(profile.profileId)}
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
);

interface CatalogsTabProps {
  loading: boolean;
  error?: Error;
  catalogs: GqlCatalog[];
}

const CatalogsTab: React.FC<CatalogsTabProps> = ({ loading, error, catalogs }) => (
  <>
    <Typography variant="h6" gutterBottom>
      Product Catalogs
    </Typography>
    <GuardedList
      loading={loading}
      error={error}
      errorPrefix="Error loading catalogs: "
      empty={catalogs.length === 0}
      emptyMessage="No catalogs found for this user."
    >
      <CatalogsTable catalogs={catalogs} />
    </GuardedList>
  </>
);

interface CatalogsTableProps {
  catalogs: GqlCatalog[];
}

const CatalogsTable: React.FC<CatalogsTableProps> = ({ catalogs }) => (
  <TableContainer sx={{ overflowX: 'auto' }}>
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
              <CatalogTypeChip catalogType={catalog.catalogType} />
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
);

const CatalogTypeChip: React.FC<{ catalogType: string }> = ({ catalogType }) => (
  <Chip
    label={catalogType === 'ADMIN_MANAGED' ? 'Managed' : 'User'}
    size="small"
    color={catalogType === 'ADMIN_MANAGED' ? 'primary' : 'default'}
  />
);

interface CampaignsTabProps {
  loading: boolean;
  error?: Error;
  profiles: GqlSellerProfile[];
  campaigns: Campaign[];
  allCampaignsCount: number;
  selectedProfile: string | null;
  onSelectProfile: (profileId: string) => void;
  editingCampaignId: string | null;
  editingSharedCode: string;
  onEditCode: (campaignId: string, code: string) => void;
  onSaveCode: (campaignId: string, code: string | null) => void;
  onCancelCode: () => void;
  onClearCode: () => void;
}

const CampaignsTab: React.FC<CampaignsTabProps> = ({
  loading,
  error,
  profiles,
  campaigns,
  allCampaignsCount,
  selectedProfile,
  onSelectProfile,
  editingCampaignId,
  editingSharedCode,
  onEditCode,
  onSaveCode,
  onCancelCode,
  onClearCode,
}) => (
  <>
    <Typography variant="h6" gutterBottom>
      Profile Campaigns
    </Typography>

    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
      Select a profile to view and manage its campaigns.
    </Typography>

    <GuardedList
      loading={loading}
      error={error}
      errorPrefix="Error loading campaigns: "
      empty={profiles.length === 0}
      emptyMessage="No profiles to manage campaigns for."
    >
      <Alert severity="info" sx={{ mb: 2 }}>
        Total campaigns loaded: {allCampaignsCount}
      </Alert>
      <ProfilePicker profiles={profiles} selected={selectedProfile} onSelect={onSelectProfile} />

      {selectedProfile &&
        (campaigns.length === 0 ? (
          <Alert severity="info">
            No campaigns found for this profile. (Total campaigns in system: {allCampaignsCount})
          </Alert>
        ) : (
          <CampaignsTable
            campaigns={campaigns}
            editingCampaignId={editingCampaignId}
            editingSharedCode={editingSharedCode}
            onEditCode={onEditCode}
            onSaveCode={onSaveCode}
            onCancelCode={onCancelCode}
            onClearCode={onClearCode}
          />
        ))}
    </GuardedList>
  </>
);

// The profile selector button row shared by the Campaigns and Shares tabs.
interface ProfilePickerProps {
  profiles: GqlSellerProfile[];
  selected: string | null;
  onSelect: (profileId: string) => void;
}

const ProfilePicker: React.FC<ProfilePickerProps> = ({ profiles, selected, onSelect }) => (
  <Box sx={{ mb: 3 }}>
    {profiles.map((profile) => (
      <Button
        key={profile.profileId}
        variant={selected === profile.profileId ? 'contained' : 'outlined'}
        onClick={() => onSelect(profile.profileId)}
        sx={{ mr: 1, mb: 1 }}
      >
        {profile.sellerName}
      </Button>
    ))}
  </Box>
);

interface CampaignsTableProps {
  campaigns: Campaign[];
  editingCampaignId: string | null;
  editingSharedCode: string;
  onEditCode: (campaignId: string, code: string) => void;
  onSaveCode: (campaignId: string, code: string | null) => void;
  onCancelCode: () => void;
  onClearCode: () => void;
}

const CampaignsTable: React.FC<CampaignsTableProps> = ({
  campaigns,
  editingCampaignId,
  editingSharedCode,
  onEditCode,
  onSaveCode,
  onCancelCode,
  onClearCode,
}) => (
  <TableContainer sx={{ overflowX: 'auto' }}>
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
          <CampaignRow
            key={campaign.campaignId}
            campaign={campaign}
            editing={editingCampaignId === campaign.campaignId}
            editingSharedCode={editingSharedCode}
            onEditCode={onEditCode}
            onSaveCode={onSaveCode}
            onCancelCode={onCancelCode}
            onClearCode={onClearCode}
          />
        ))}
      </TableBody>
    </Table>
  </TableContainer>
);

interface CampaignRowProps {
  campaign: Campaign;
  editing: boolean;
  editingSharedCode: string;
  onEditCode: (campaignId: string, code: string) => void;
  onSaveCode: (campaignId: string, code: string | null) => void;
  onCancelCode: () => void;
  onClearCode: () => void;
}

const CampaignRow: React.FC<CampaignRowProps> = ({
  campaign,
  editing,
  editingSharedCode,
  onEditCode,
  onSaveCode,
  onCancelCode,
  onClearCode,
}) => (
  <TableRow>
    <TableCell>{campaign.campaignName}</TableCell>
    <TableCell>{campaign.campaignYear}</TableCell>
    <TableCell>
      <Typography variant="body2">
        {formatDisplayDate(campaign.startDate) || '—'} - {formatDisplayDate(campaign.endDate) || '—'}
      </Typography>
    </TableCell>
    <TableCell>
      <Typography variant="body2" fontSize="0.75rem">
        {campaign.catalogId}
      </Typography>
    </TableCell>
    <TableCell>
      <CampaignSharedCodeCell
        campaign={campaign}
        editing={editing}
        editingSharedCode={editingSharedCode}
        onEditCode={onEditCode}
      />
    </TableCell>
    <TableCell align="right">
      <CampaignActionsCell
        campaign={campaign}
        editing={editing}
        editingSharedCode={editingSharedCode}
        onEditCode={onEditCode}
        onSaveCode={onSaveCode}
        onCancelCode={onCancelCode}
        onClearCode={onClearCode}
      />
    </TableCell>
  </TableRow>
);

// The Shared Code cell: inline editor while editing, the current code otherwise.
const CampaignSharedCodeCell: React.FC<
  Omit<CampaignRowProps, 'onSaveCode' | 'onCancelCode' | 'onClearCode'>
> = ({
  campaign,
  editing,
  editingSharedCode,
  onEditCode,
}) =>
  editing ? (
    <TextField
      size="small"
      value={editingSharedCode}
      onChange={(e) => onEditCode(campaign.campaignId, e.target.value)}
      placeholder="Enter code or leave blank to remove"
      helperText="Clear field to unassociate"
      fullWidth
    />
  ) : (
    <Typography variant="body2" fontFamily="monospace">
      {campaign.sharedCampaignCode || '—'}
    </Typography>
  );

// The Actions cell: save/cancel/clear while editing, the Edit trigger otherwise.
const CampaignActionsCell: React.FC<CampaignRowProps> = ({
  campaign,
  editing,
  editingSharedCode,
  onEditCode,
  onSaveCode,
  onCancelCode,
  onClearCode,
}) =>
  editing ? (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" justifyContent="flex-end">
      <Button size="small" onClick={() => onSaveCode(campaign.campaignId, editingSharedCode || null)}>
        Save
      </Button>
      <Button size="small" onClick={onCancelCode}>
        Cancel
      </Button>
      {editingSharedCode && (
        <Button size="small" onClick={onClearCode} color="warning">
          Clear
        </Button>
      )}
    </Stack>
  ) : (
    <Button
      size="small"
      startIcon={<EditIcon />}
      onClick={() => onEditCode(campaign.campaignId, campaign.sharedCampaignCode || '')}
      variant="outlined"
    >
      Edit
    </Button>
  );

interface SharedCampaignsTabProps {
  loading: boolean;
  error?: Error;
  sharedCampaigns: SharedCampaign[];
}

const SharedCampaignsTab: React.FC<SharedCampaignsTabProps> = ({ loading, error, sharedCampaigns }) => (
  <>
    <Typography variant="h6" gutterBottom>
      Shared Campaigns Created by User
    </Typography>

    <GuardedList
      loading={loading}
      error={error}
      errorPrefix="Error loading shared campaigns: "
      empty={sharedCampaigns.length === 0}
      emptyMessage="No shared campaigns found for this user."
    >
      <SharedCampaignsTable sharedCampaigns={sharedCampaigns} />
    </GuardedList>
  </>
);

interface SharedCampaignsTableProps {
  sharedCampaigns: SharedCampaign[];
}

const SharedCampaignsTable: React.FC<SharedCampaignsTableProps> = ({ sharedCampaigns }) => (
  <TableContainer sx={{ overflowX: 'auto' }}>
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
            <TableCell>{formatDisplayDate(sharedCampaign.startDate) || '—'}</TableCell>
            <TableCell>{formatDisplayDate(sharedCampaign.endDate) || '—'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </TableContainer>
);

interface SharesTabProps {
  profiles: GqlSellerProfile[];
  shares: Share[];
  sharesLoading: boolean;
  selectedProfile: string | null;
  onSelectProfile: (profileId: string) => void;
  onRevoke: (targetAccountId: string, email: string) => void;
}

const SharesTab: React.FC<SharesTabProps> = ({ profiles, ...rest }) => (
  <>
    <Typography variant="h6" gutterBottom>
      Profile Shares
    </Typography>

    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
      Select a profile to view and manage who has access to it.
    </Typography>

    {profiles.length === 0 ? (
      <Alert severity="info">No profiles to manage shares for.</Alert>
    ) : (
      <SharesTabContent profiles={profiles} {...rest} />
    )}
  </>
);

const SharesTabContent: React.FC<SharesTabProps> = ({
  profiles,
  shares,
  sharesLoading,
  selectedProfile,
  onSelectProfile,
  onRevoke,
}) => (
  <>
    <ProfilePicker profiles={profiles} selected={selectedProfile} onSelect={onSelectProfile} />

    {selectedProfile && (
      <GuardedList
        loading={sharesLoading}
        empty={shares.length === 0}
        emptyMessage="No shares found for this profile."
      >
        <SharesTable shares={shares} onRevoke={onRevoke} />
      </GuardedList>
    )}
  </>
);

interface SharesTableProps {
  shares: Share[];
  onRevoke: (targetAccountId: string, email: string) => void;
}

const SharesTable: React.FC<SharesTableProps> = ({ shares, onRevoke }) => (
  <TableContainer sx={{ overflowX: 'auto' }}>
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
          <ShareRow key={share.targetAccountId} share={share} onRevoke={onRevoke} />
        ))}
      </TableBody>
    </Table>
  </TableContainer>
);

interface ShareRowProps {
  share: Share;
  onRevoke: (targetAccountId: string, email: string) => void;
}

const ShareRow: React.FC<ShareRowProps> = ({ share, onRevoke }) => (
  <TableRow>
    <TableCell>
      <ShareTargetCell account={share.targetAccount} />
    </TableCell>
    <TableCell>
      {share.permissions?.map((perm) => (
        <Chip key={perm} label={perm} size="small" sx={{ mr: 0.5 }} />
      ))}
    </TableCell>
    <TableCell>{formatDisplayDate(share.createdAt) || '—'}</TableCell>
    <TableCell align="right">
      <Button
        size="small"
        startIcon={<DeleteIcon />}
        onClick={() => onRevoke(share.targetAccountId, share.targetAccount?.email || 'this user')}
        color="error"
        variant="outlined"
      >
        Revoke
      </Button>
    </TableCell>
  </TableRow>
);

// The shared-user identity cell: email plus an optional display-name line.
const ShareTargetCell: React.FC<{ account?: Share['targetAccount'] }> = ({ account }) => {
  if (!account) {
    return <Typography variant="body2">Unknown</Typography>;
  }
  return (
    <>
      <Typography variant="body2">{account.email || 'Unknown'}</Typography>
      {(account.givenName || account.familyName) && (
        <Typography variant="caption" color="text.secondary">
          {account.givenName} {account.familyName}
        </Typography>
      )}
    </>
  );
};

// The search-results list inside the transfer dialog: filters out the current
// account and highlights the selected row (the `?.`/`||` derivations and
// conditionals live here rather than in the page component).
interface NewOwnerListProps {
  results: GqlAdminUser[];
  accountId: string;
  selectedAccountId: string | null;
  onSelect: (user: GqlAdminUser) => void;
}

const NewOwnerList: React.FC<NewOwnerListProps> = ({ results, accountId, selectedAccountId, onSelect }) => {
  const candidates = results.filter((u) => u.accountId !== accountId);
  return (
    <Box mt={2}>
      <Typography variant="subtitle2" gutterBottom>
        Select new owner:
      </Typography>
      {candidates.map((searchUser) => (
        <Box
          key={searchUser.accountId}
          sx={{
            p: 1,
            mb: 1,
            border: 1,
            borderColor: selectedAccountId === searchUser.accountId ? 'primary.main' : 'divider',
            borderRadius: 1,
            cursor: 'pointer',
            bgcolor: selectedAccountId === searchUser.accountId ? 'action.selected' : 'background.paper',
          }}
          onClick={() => onSelect(searchUser)}
        >
          <Typography variant="body2">{searchUser.email}</Typography>
          <Typography variant="caption" color="text.secondary">
            {searchUser.displayName || 'No name'}
          </Typography>
        </Box>
      ))}
    </Box>
  );
};

// The transfer-ownership dialog: search state, result selection, and confirm
// action (presentational; all handlers are props).
interface TransferDialogProps {
  open: boolean;
  onClose: () => void;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSearch: () => void;
  searchLoading: boolean;
  searchResults: GqlAdminUser[];
  accountId: string;
  selectedOwner: GqlAdminUser | null;
  onSelectOwner: (user: GqlAdminUser) => void;
  onConfirm: () => void;
  transferring: boolean;
}

const TransferDialog: React.FC<TransferDialogProps> = ({ open, onClose, ...rest }) => (
  <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
    <DialogTitle>Transfer Profile Ownership</DialogTitle>
    <TransferDialogBody {...rest} />
    <TransferDialogActions onClose={onClose} {...rest} />
  </Dialog>
);

const TransferDialogBody: React.FC<Omit<TransferDialogProps, 'open' | 'onClose'>> = ({
  searchQuery,
  onSearchQueryChange,
  onSearch,
  searchLoading,
  searchResults,
  accountId,
  selectedOwner,
  onSelectOwner,
}) => (
  <DialogContent>
    <Typography variant="body2" color="text.secondary" gutterBottom>
      Search for the new owner by email address
    </Typography>

    <OwnerSearchField
      searchQuery={searchQuery}
      onSearchQueryChange={onSearchQueryChange}
      onSearch={onSearch}
      searchLoading={searchLoading}
    />

    {searchLoading && <CircularProgress size={24} />}

    {searchResults.length > 0 && (
      <NewOwnerList
        results={searchResults}
        accountId={accountId}
        selectedAccountId={selectedOwner ? selectedOwner.accountId : null}
        onSelect={onSelectOwner}
      />
    )}
  </DialogContent>
);

interface OwnerSearchFieldProps {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSearch: () => void;
  searchLoading: boolean;
}

const OwnerSearchField: React.FC<OwnerSearchFieldProps> = ({
  searchQuery,
  onSearchQueryChange,
  onSearch,
  searchLoading,
}) => {
  const canSearch = searchQuery.trim() && !searchLoading;
  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') onSearch();
  };
  return (
    <TextField
      fullWidth
      label="New Owner Email"
      value={searchQuery}
      onChange={(e) => onSearchQueryChange(e.target.value)}
      onKeyDown={handleSearchKeyDown}
      sx={{ mt: 2 }}
      InputProps={{
        endAdornment: (
          <InputAdornment position="end">
            <IconButton onClick={onSearch} disabled={!canSearch} aria-label="Search new owner">
              <SearchIcon />
            </IconButton>
          </InputAdornment>
        ),
      }}
    />
  );
};

const TransferDialogActions: React.FC<Omit<TransferDialogProps, 'open'>> = ({
  onClose,
  onConfirm,
  selectedOwner,
  transferring,
}) => (
  <DialogActions>
    <Button onClick={onClose}>Cancel</Button>
    <Button
      onClick={onConfirm}
      variant="contained"
      disabled={!selectedOwner || transferring}
      startIcon={transferring ? <CircularProgress size={16} /> : <TransferIcon />}
    >
      {transferring ? 'Transferring...' : 'Confirm Transfer'}
    </Button>
  </DialogActions>
);

// All account-scoped admin queries share the same variables/skip config;
// factoring it out keeps each useQuery call a plain two-argument read.
const accountQueryOptions = (accountId: string | undefined) => ({
  variables: { accountId },
  skip: !accountId,
});

// Query-result field accessors: each one owns its `?.`/`||` fallback so the hook
// body reads as plain derivations.
const profilesOf = (data: { adminGetUserProfiles: GqlSellerProfile[] } | undefined): GqlSellerProfile[] =>
  data?.adminGetUserProfiles || [];
const catalogsOf = (data: { adminGetUserCatalogs: GqlCatalog[] } | undefined): GqlCatalog[] =>
  data?.adminGetUserCatalogs || [];
const campaignsOf = (data: { adminGetUserCampaigns: Campaign[] } | undefined): Campaign[] =>
  data?.adminGetUserCampaigns || [];
const sharedCampaignsOf = (data: { adminGetUserSharedCampaigns: SharedCampaign[] } | undefined): SharedCampaign[] =>
  data?.adminGetUserSharedCampaigns || [];
const sharesOf = (data: { adminGetProfileShares: Share[] } | undefined): Share[] =>
  data?.adminGetProfileShares || [];
const searchResultsOf = (data: { adminSearchUser: GqlAdminUser[] } | undefined): GqlAdminUser[] =>
  data?.adminSearchUser || [];

// True when any of the page's queries signals an MFA requirement.
const anyMfaError = (...errors: (Error | undefined)[]): boolean => errors.some(mfaErrorIn);

// `console.error` only during local development (mutation error telemetry).
const logDevError = (message: string, error: unknown): void => {
  if (import.meta.env.DEV) {
    console.error(message, error);
  }
};

// Data hook: owns the page's queries, derivations, and mutations so the page
// component body carries no optional-chain/fallback or MFA-chain branches
// (issue #532).
function useUserDataData(accountId: string | undefined, isMfaRequired: boolean) {
  // Fetch user's profiles
  const {
    data: profilesData,
    loading: profilesLoading,
    error: profilesError,
    refetch: refetchProfiles,
  } = useQuery<{ adminGetUserProfiles: GqlSellerProfile[] }>(ADMIN_GET_USER_PROFILES, accountQueryOptions(accountId));

  // Fetch user's catalogs
  const {
    data: catalogsData,
    loading: catalogsLoading,
    error: catalogsError,
  } = useQuery<{ adminGetUserCatalogs: GqlCatalog[] }>(ADMIN_GET_USER_CATALOGS, accountQueryOptions(accountId));

  // Fetch user's campaigns
  const {
    data: campaignsData,
    loading: campaignsLoading,
    error: campaignsError,
    refetch: refetchCampaigns,
  } = useQuery<{ adminGetUserCampaigns: Campaign[] }>(ADMIN_GET_USER_CAMPAIGNS, accountQueryOptions(accountId));

  // Fetch user's shared campaigns
  const {
    data: sharedCampaignsData,
    loading: sharedCampaignsLoading,
    error: sharedCampaignsError,
  } = useQuery<{ adminGetUserSharedCampaigns: SharedCampaign[] }>(
    ADMIN_GET_USER_SHARED_CAMPAIGNS,
    accountQueryOptions(accountId)
  );

  const [selectedProfileForCampaigns, setSelectedProfileForCampaigns] = useState<string | null>(null);
  const [selectedProfileForShares, setSelectedProfileForShares] = useState<string | null>(null);

  // Campaign shared-code editing state. Lives next to the mutation so a failed
  // save keeps the field in edit mode for a retry (only onCompleted clears it).
  const [editingCampaignId, setEditingCampaignId] = useState<string | null>(null);
  const [editingSharedCode, setEditingSharedCode] = useState('');

  // Fetch shares for the selected profile
  const {
    data: sharesData,
    loading: sharesLoading,
    refetch: refetchShares,
  } = useQuery<{ adminGetProfileShares: Share[] }>(ADMIN_GET_PROFILE_SHARES, {
    variables: { profileId: selectedProfileForShares },
    skip: !selectedProfileForShares,
  });

  // (Shares is profile-scoped, not account-scoped, so it keeps its own options.)

  // Search for a new profile owner
  const [searchNewOwner, { data: searchData, loading: searchLoading }] = useLazyQuery<{
    adminSearchUser: GqlAdminUser[];
  }>(ADMIN_SEARCH_USER);

  // Transfer ownership mutation. The transfer-dialog state lives next to it so
  // a failed transfer keeps the dialog open with the search and selection
  // intact for a retry (only onCompleted closes and clears, matching the
  // shared-code editing state above).
  const [transferProfileId, setTransferProfileId] = useState<string | null>(null);
  const [newOwnerSearch, setNewOwnerSearch] = useState('');
  const [selectedNewOwner, setSelectedNewOwner] = useState<GqlAdminUser | null>(null);
  const [transferOwnership, { loading: transferring }] = useMutation(TRANSFER_PROFILE_OWNERSHIP, {
    onCompleted: () => {
      setTransferProfileId(null);
      setNewOwnerSearch('');
      setSelectedNewOwner(null);
      void refetchProfiles();
    },
    onError: (error) => logDevError('Transfer failed:', error),
  });

  // Revoke-share confirm-dialog state: success-only close (the dialog stays
  // open with the 'Revoking...' feedback while the mutation is in flight).
  const [revokeShareTarget, setRevokeShareTarget] = useState<{
    profileId: string;
    targetAccountId: string;
    email: string;
  } | null>(null);

  // Delete share mutation
  const [deleteShare, { loading: deletingShare }] = useMutation(ADMIN_DELETE_SHARE, {
    onCompleted: () => {
      setRevokeShareTarget(null);
    },
    onError: (error) => logDevError('Revoke share failed:', error),
  });

  // Update campaign shared code mutation
  const [updateCampaignSharedCode] = useMutation(ADMIN_UPDATE_CAMPAIGN_SHARED_CODE, {
    onCompleted: () => {
      setEditingCampaignId(null);
      setEditingSharedCode('');
      void refetchCampaigns();
    },
    onError: (error) => logDevError('Update shared code failed:', error),
  });

  const editSharedCode = (campaignId: string, code: string) => {
    setEditingCampaignId(campaignId);
    setEditingSharedCode(code);
  };

  const saveSharedCode = (campaignId: string, code: string | null) => {
    void updateCampaignSharedCode({
      variables: {
        campaignId,
        sharedCampaignCode: code,
      },
    });
  };

  const cancelSharedCode = () => {
    setEditingCampaignId(null);
    setEditingSharedCode('');
  };

  const clearSharedCode = () => {
    setEditingSharedCode('');
  };

  const profiles = profilesOf(profilesData);
  const catalogs = catalogsOf(catalogsData);
  const allCampaigns = campaignsOf(campaignsData);

  // Filter campaigns by selected profile
  const campaigns = campaignsForProfile(allCampaigns, selectedProfileForCampaigns);

  const sharedCampaigns = sharedCampaignsOf(sharedCampaignsData);
  const shares = sharesOf(sharesData);
  const searchResults = searchResultsOf(searchData);

  const mfaRequired = isMfaRequired || anyMfaError(profilesError, catalogsError, campaignsError, sharedCampaignsError);

  const searchOwner = (query: string) => {
    void searchNewOwner({ variables: { query: query.trim() } });
  };

  const confirmTransfer = (profileId: string, owner: GqlAdminUser) => {
    void transferOwnership({
      variables: {
        input: {
          profileId,
          newOwnerAccountId: owner.accountId,
        },
      },
    });
  };

  const revokeShare = (profileId: string, targetAccountId: string) => {
    void (async () => {
      await deleteShare({
        variables: {
          profileId,
          targetAccountId,
        },
      });
      void refetchShares();
    })();
  };

  const handleTransferClick = (profileId: string) => {
    setTransferProfileId(profileId);
    setNewOwnerSearch('');
    setSelectedNewOwner(null);
  };

  const handleSearchNewOwner = () => {
    if (newOwnerSearch.trim()) {
      searchOwner(newOwnerSearch);
    }
  };

  const handleConfirmTransfer = () => {
    if (transferProfileId && selectedNewOwner) {
      confirmTransfer(transferProfileId, selectedNewOwner);
    }
  };

  const handleCancelTransfer = () => {
    setTransferProfileId(null);
    setNewOwnerSearch('');
    setSelectedNewOwner(null);
  };

  const handleRevokeShare = (targetAccountId: string, email: string) => {
    setRevokeShareTarget({
      profileId: selectedProfileForShares ?? '',
      targetAccountId,
      email,
    });
  };

  const handleConfirmRevokeShare = () => {
    if (!revokeShareTarget) return;
    revokeShare(revokeShareTarget.profileId, revokeShareTarget.targetAccountId);
  };

  const handleCancelRevoke = () => {
    setRevokeShareTarget(null);
  };

  return {
    profiles,
    profilesLoading,
    profilesError,
    catalogs,
    catalogsLoading,
    catalogsError,
    allCampaigns,
    campaigns,
    campaignsLoading,
    campaignsError,
    sharedCampaigns,
    sharedCampaignsLoading,
    sharedCampaignsError,
    shares,
    sharesLoading,
    searchResults,
    searchLoading,
    transferring,
    deletingShare,
    transferProfileId,
    newOwnerSearch,
    setNewOwnerSearch,
    selectedNewOwner,
    setSelectedNewOwner,
    handleTransferClick,
    handleSearchNewOwner,
    handleConfirmTransfer,
    handleCancelTransfer,
    revokeShareTarget,
    handleRevokeShare,
    handleConfirmRevokeShare,
    handleCancelRevoke,
    selectedProfileForCampaigns,
    setSelectedProfileForCampaigns,
    selectedProfileForShares,
    setSelectedProfileForShares,
    mfaRequired,
    editingCampaignId,
    editingSharedCode,
    editSharedCode,
    saveSharedCode,
    cancelSharedCode,
    clearSharedCode,
  };
}

export const UserDataPage: React.FC = () => {
  const { isMfaRequired } = useAdminMfa();
  const { accountId } = useParams<{ accountId: string }>();
  const navigate = useNavigate();

  // Data + derivations (profiles, catalogs, campaigns, shared campaigns, shares,
  // search, MFA gate, and the transfer/revoke/shared-code mutations) live in
  // useUserDataData so the page component body stays a flat coordinator.
  const {
    profiles,
    profilesLoading,
    profilesError,
    catalogs,
    catalogsLoading,
    catalogsError,
    allCampaigns,
    campaigns,
    campaignsLoading,
    campaignsError,
    sharedCampaigns,
    sharedCampaignsLoading,
    sharedCampaignsError,
    shares,
    sharesLoading,
    searchResults,
    searchLoading,
    transferring,
    deletingShare,
    transferProfileId,
    newOwnerSearch,
    setNewOwnerSearch,
    selectedNewOwner,
    setSelectedNewOwner,
    handleTransferClick,
    handleSearchNewOwner,
    handleConfirmTransfer,
    handleCancelTransfer,
    revokeShareTarget,
    handleRevokeShare,
    handleConfirmRevokeShare,
    handleCancelRevoke,
    selectedProfileForCampaigns,
    setSelectedProfileForCampaigns,
    selectedProfileForShares,
    setSelectedProfileForShares,
    mfaRequired,
    editingCampaignId,
    editingSharedCode,
    editSharedCode,
    saveSharedCode,
    cancelSharedCode,
    clearSharedCode,
  } = useUserDataData(accountId, isMfaRequired);

  const [currentTab, setCurrentTab] = useState(0);

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

  if (!accountId) {
    return (
      <Box p={3}>
        <Alert severity="error">No account ID provided</Alert>
      </Box>
    );
  }

  if (mfaRequired) {
    return <MfaSetupRequiredState />;
  }

  const profileIdWithoutPrefix = accountId.replace('ACCOUNT#', '');

  return (
    <Box>
      <NavBreadcrumbs
        items={[
          {
            label: 'Admin Console',
            onClick: () => {
              void navigate('/admin');
            },
            icon: <BackIcon fontSize="small" />,
          },
          { label: `User Data: ${profileIdWithoutPrefix}` },
        ]}
      />

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
        <Tabs
          value={currentTab}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
        >
          <Tab id="user-data-tab-0" aria-controls="user-data-tabpanel-0" label={`Profiles (${profiles.length})`} />
          <Tab id="user-data-tab-1" aria-controls="user-data-tabpanel-1" label={`Catalogs (${catalogs.length})`} />
          <Tab id="user-data-tab-2" aria-controls="user-data-tabpanel-2" label={`Campaigns (${campaigns.length})`} />
          <Tab
            id="user-data-tab-3"
            aria-controls="user-data-tabpanel-3"
            label={`Shared Campaigns (${sharedCampaigns.length})`}
          />
          <Tab id="user-data-tab-4" aria-controls="user-data-tabpanel-4" label={`Shares`} />
        </Tabs>
      </Paper>

      {/* Profiles Tab */}
      <TabPanel value={currentTab} index={0}>
        <Paper sx={{ p: 3 }}>
          <ProfilesTab
            loading={profilesLoading}
            error={profilesError}
            profiles={profiles}
            onTransfer={handleTransferClick}
          />
        </Paper>
      </TabPanel>

      {/* Catalogs Tab */}
      <TabPanel value={currentTab} index={1}>
        <Paper sx={{ p: 3 }}>
          <CatalogsTab loading={catalogsLoading} error={catalogsError} catalogs={catalogs} />
        </Paper>
      </TabPanel>

      {/* Campaigns Tab */}
      <TabPanel value={currentTab} index={2}>
        <Paper sx={{ p: 3 }}>
          <CampaignsTab
            loading={campaignsLoading}
            error={campaignsError}
            profiles={profiles}
            campaigns={campaigns}
            allCampaignsCount={allCampaigns.length}
            selectedProfile={selectedProfileForCampaigns}
            onSelectProfile={setSelectedProfileForCampaigns}
            editingCampaignId={editingCampaignId}
            editingSharedCode={editingSharedCode}
            onEditCode={editSharedCode}
            onSaveCode={saveSharedCode}
            onCancelCode={cancelSharedCode}
            onClearCode={clearSharedCode}
          />
        </Paper>
      </TabPanel>

      {/* Shared Campaigns Tab */}
      <TabPanel value={currentTab} index={3}>
        <Paper sx={{ p: 3 }}>
          <SharedCampaignsTab
            loading={sharedCampaignsLoading}
            error={sharedCampaignsError}
            sharedCampaigns={sharedCampaigns}
          />
        </Paper>
      </TabPanel>

      {/* Shares Tab */}
      <TabPanel value={currentTab} index={4}>
        <Paper sx={{ p: 3 }}>
          <SharesTab
            profiles={profiles}
            shares={shares}
            sharesLoading={sharesLoading}
            selectedProfile={selectedProfileForShares}
            onSelectProfile={setSelectedProfileForShares}
            onRevoke={handleRevokeShare}
          />
        </Paper>
      </TabPanel>

      {/* Transfer Ownership Dialog */}
      <TransferDialog
        open={!!transferProfileId}
        onClose={handleCancelTransfer}
        searchQuery={newOwnerSearch}
        onSearchQueryChange={setNewOwnerSearch}
        onSearch={handleSearchNewOwner}
        searchLoading={searchLoading}
        searchResults={searchResults}
        accountId={accountId}
        selectedOwner={selectedNewOwner}
        onSelectOwner={setSelectedNewOwner}
        onConfirm={handleConfirmTransfer}
        transferring={transferring}
      />

      <ConfirmDialog
        open={!!revokeShareTarget}
        title="Revoke Access?"
        onClose={handleCancelRevoke}
        onConfirm={handleConfirmRevokeShare}
        confirmLabel="Revoke"
        confirmColor="error"
        isLoading={deletingShare}
        loadingLabel="Revoking..."
      >
        <Typography>Are you sure you want to revoke {revokeShareTarget?.email}'s access to this profile?</Typography>
      </ConfirmDialog>
    </Box>
  );
};
