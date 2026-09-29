/**
 * AdminPage - Admin console for managing users, profiles, and system-wide settings
 *
 * Only visible when user has isAdmin=true
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useLazyQuery } from '@apollo/client/react';
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
  Button,
  IconButton,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Snackbar,
  TextField,
  InputAdornment,
} from '@mui/material';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import { PageHeader } from '../components/PageHeader';
import { AmrTripwireBanner } from '../components/AmrTripwireBanner';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { useSnackbar } from '../hooks/useSnackbar';
import {
  Inventory as CatalogIcon,
  Info as InfoIcon,
  Person as PersonIcon,
  LockReset as LockResetIcon,
  Delete as DeleteIcon,
  AdminPanelSettings as AdminIcon,
  CheckCircle as VerifiedIcon,
  Cancel as UnverifiedIcon,
  Add as AddIcon,
  Edit as EditIcon,
  Search as SearchIcon,
  Close as CloseIcon,
} from '@mui/icons-material';
import {
  LIST_MANAGED_CATALOGS,
  ADMIN_SEARCH_USER,
  ADMIN_RESET_USER_PASSWORD,
  ADMIN_PURGE_USER_ACCOUNT,
  ADMIN_DELETE_USER_ORDERS,
  ADMIN_DELETE_USER_CAMPAIGNS,
  ADMIN_DELETE_USER_SHARES,
  ADMIN_DELETE_USER_PROFILES,
  ADMIN_GET_USER_PROFILES,
  CREATE_MANAGED_CATALOG,
  UPDATE_CATALOG,
  DELETE_CATALOG,
} from '../lib/graphql';
import { CatalogEditorDialog } from '../components/CatalogEditorDialog';
import { MfaSetupRequiredState } from '../components/MfaSetupRequiredState';
import { useAdminMfa } from '../hooks/useAdminMfa';
import { isMfaRequiredError, MFA_REQUIRED_ERROR_CODE } from '../lib/mfaErrors';
import { formatDisplayDate } from '../lib/date-utils';
import type { GqlCatalog, GqlAdminUser, GqlProductInput } from '../types/graphql-generated';
import type {
  GqlAdminPurgeUserAccountMutation,
  GqlAdminPurgeUserAccountMutationVariables,
  GqlAdminDeleteUserOrdersMutation,
  GqlAdminDeleteUserOrdersMutationVariables,
  GqlAdminDeleteUserCampaignsMutation,
  GqlAdminDeleteUserCampaignsMutationVariables,
  GqlAdminDeleteUserSharesMutation,
  GqlAdminDeleteUserSharesMutationVariables,
  GqlAdminDeleteUserProfilesMutation,
  GqlAdminDeleteUserProfilesMutationVariables,
  GqlAdminGetUserProfilesQuery,
  GqlAdminGetUserProfilesQueryVariables,
} from '../types/graphql-generated';

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

// --- User Status Chip ---
const UserStatusChip: React.FC<{ status: string; enabled: boolean }> = ({ status, enabled }) => {
  if (!enabled) {
    return <Chip label="Disabled" color="error" size="small" />;
  }
  switch (status) {
    case 'CONFIRMED':
      return <Chip label="Active" color="success" size="small" />;
    case 'UNCONFIRMED':
      return <Chip label="Unconfirmed" color="warning" size="small" />;
    case 'FORCE_CHANGE_PASSWORD':
      return <Chip label="Password Reset" color="warning" size="small" />;
    default:
      return <Chip label={status} color="default" size="small" />;
  }
};

// --- User Row ---
interface UserRowProps {
  user: GqlAdminUser;
  onResetPassword: (user: GqlAdminUser) => void;
  onDeleteUser: (user: GqlAdminUser) => void;
  onViewDetails: (user: GqlAdminUser) => void;
}

const UserRow: React.FC<UserRowProps> = ({ user, onResetPassword, onDeleteUser, onViewDetails }) => (
  <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => onViewDetails(user)}>
    <TableCell>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ minWidth: 0, flexWrap: 'wrap' }}>
        <Typography variant="body2" sx={{ wordBreak: 'break-word', minWidth: 0 }}>
          {user.email}
        </Typography>
        {user.emailVerified ? (
          <Tooltip title="Email verified">
            <VerifiedIcon fontSize="small" color="success" />
          </Tooltip>
        ) : (
          <Tooltip title="Email not verified">
            <UnverifiedIcon fontSize="small" color="warning" />
          </Tooltip>
        )}
      </Stack>
    </TableCell>
    <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>
      <Typography variant="body2">{user.displayName ?? '—'}</Typography>
    </TableCell>
    <TableCell>
      <UserStatusChip status={user.status} enabled={user.enabled} />
    </TableCell>
    <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>
      {user.isAdmin ? (
        <Chip icon={<AdminIcon />} label="Admin" color="primary" size="small" />
      ) : (
        <Chip label="User" color="default" size="small" variant="outlined" />
      )}
    </TableCell>
    <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>
      <Typography variant="body2" color="text.secondary">
        {formatDisplayDate(user.createdAt) || '—'}
      </Typography>
    </TableCell>
    <TableCell align="right">
      <Tooltip title="Reset password">
        <IconButton
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            onResetPassword(user);
          }}
          aria-label={`Reset password for ${user.email}`}
        >
          <LockResetIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Delete user">
        <IconButton
          size="small"
          color="error"
          onClick={(e) => {
            e.stopPropagation();
            onDeleteUser(user);
          }}
          aria-label={`Delete user ${user.email}`}
        >
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </TableCell>
  </TableRow>
);

// --- Users Tab Content ---
interface UsersTabContentProps {
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  onSearch: () => void;
  loading: boolean;
  error: Error | undefined;
  searchedUsers: GqlAdminUser[];
  hasSearched: boolean;
  onResetPassword: (user: GqlAdminUser) => void;
  onDeleteUser: (user: GqlAdminUser) => void;
  onViewDetails: (user: GqlAdminUser) => void;
}

const UsersTabContent: React.FC<UsersTabContentProps> = ({
  searchQuery,
  onSearchQueryChange,
  onSearch,
  loading,
  error,
  searchedUsers,
  hasSearched,
  onResetPassword,
  onDeleteUser,
  onViewDetails,
}) => (
  <>
    <UserSearchBar
      searchQuery={searchQuery}
      onSearchQueryChange={onSearchQueryChange}
      onSearch={onSearch}
      loading={loading}
    />
    <UserSearchResults
      searchQuery={searchQuery}
      loading={loading}
      error={error}
      searchedUsers={searchedUsers}
      hasSearched={hasSearched}
      onResetPassword={onResetPassword}
      onDeleteUser={onDeleteUser}
      onViewDetails={onViewDetails}
    />
  </>
);

interface UserSearchBarProps {
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  onSearch: () => void;
  loading: boolean;
}

const UserSearchBar: React.FC<UserSearchBarProps> = ({ searchQuery, onSearchQueryChange, onSearch, loading }) => {
  const canSearch = !!searchQuery.trim() && !loading;
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && searchQuery.trim()) {
      onSearch();
    }
  };

  return (
    <Box display="flex" gap={2} mb={3} sx={{ minWidth: 0 }}>
      <TextField
        fullWidth
        label="Search User"
        placeholder="Search by email, name, or account ID (3+ characters)"
        value={searchQuery}
        onChange={(e) => onSearchQueryChange(e.target.value)}
        onKeyDown={handleKeyDown}
        sx={{ flex: 1, minWidth: 0 }}
        slotProps={{
          input: {
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon />
              </InputAdornment>
            ),
          },
        }}
      />
      <Button variant="contained" onClick={onSearch} disabled={!canSearch} sx={{ minWidth: 100 }}>
        {loading ? <CircularProgress size={24} /> : 'Search'}
      </Button>
    </Box>
  );
};

type UserSearchResultsProps = Omit<UsersTabContentProps, 'onSearchQueryChange' | 'onSearch'>;

// The search-state guard: error, not-yet-searched hint, no-results warning, or the
// results table — one early return per state instead of `&&` chains in the tab.
const UserSearchResults: React.FC<UserSearchResultsProps> = ({
  searchQuery,
  loading,
  error,
  searchedUsers,
  hasSearched,
  onResetPassword,
  onDeleteUser,
  onViewDetails,
}) => {
  if (error) {
    return <ErrorAlert message={`Failed to load: ${error.message}`} />;
  }
  if (!hasSearched) {
    return (
      <Alert severity="info">
        Search for a user by email, name, or account ID. Queries must be at least 3 characters. Partial matches are
        supported (e.g., &quot;john&quot; finds &quot;john.doe@example.com&quot;).
      </Alert>
    );
  }
  if (searchedUsers.length === 0) {
    // A search is in flight: no results yet and nothing to report.
    if (loading) return null;
    return <Alert severity="warning">No user found matching &quot;{searchQuery}&quot;.</Alert>;
  }

  return (
    <UserSearchResultsTable
      searchedUsers={searchedUsers}
      searchQuery={searchQuery}
      onResetPassword={onResetPassword}
      onDeleteUser={onDeleteUser}
      onViewDetails={onViewDetails}
    />
  );
};

interface UserSearchResultsTableProps {
  searchedUsers: GqlAdminUser[];
  searchQuery: string;
  onResetPassword: (user: GqlAdminUser) => void;
  onDeleteUser: (user: GqlAdminUser) => void;
  onViewDetails: (user: GqlAdminUser) => void;
}

const UserSearchResultsTable: React.FC<UserSearchResultsTableProps> = ({
  searchedUsers,
  searchQuery,
  onResetPassword,
  onDeleteUser,
  onViewDetails,
}) => (
  <>
    {searchedUsers.length > 1 && (
      <Alert severity="info" sx={{ mb: 2 }}>
        Found {searchedUsers.length} users matching &quot;{searchQuery}&quot;
      </Alert>
    )}
    <TableContainer sx={{ width: '100%', overflowX: 'auto' }}>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Email</TableCell>
            <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>Name</TableCell>
            <TableCell>Status</TableCell>
            <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>Role</TableCell>
            <TableCell sx={{ display: { xs: 'none', sm: 'table-cell' } }}>Created</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {searchedUsers.map((user) => (
            <UserRow
              key={user.accountId}
              user={user}
              onResetPassword={onResetPassword}
              onDeleteUser={onDeleteUser}
              onViewDetails={onViewDetails}
            />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  </>
);

// --- Catalog Card ---
interface CatalogCardProps {
  catalog: GqlCatalog;
  onEdit: (catalog: GqlCatalog) => void;
  onDelete: (catalog: GqlCatalog) => void;
}

const CatalogCard: React.FC<CatalogCardProps> = ({ catalog, onEdit, onDelete }) => (
  <Paper variant="outlined" sx={{ p: 2 }}>
    <Stack direction="row" justifyContent="space-between" alignItems="start" flexWrap="wrap" gap={1}>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography variant="subtitle1" fontWeight="medium" sx={{ wordBreak: 'break-word' }}>
          {catalog.catalogName ?? 'Unnamed Catalog'}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {(catalog.products ?? []).length} products
        </Typography>
      </Box>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
        <Chip
          label={catalog.catalogType === 'ADMIN_MANAGED' ? 'Managed' : 'User'}
          color={catalog.catalogType === 'ADMIN_MANAGED' ? 'primary' : 'default'}
          size="small"
        />
        <Tooltip title="Edit Catalog">
          <IconButton size="small" onClick={() => onEdit(catalog)} color="primary" aria-label="Edit catalog">
            <EditIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Delete Catalog">
          <IconButton size="small" onClick={() => onDelete(catalog)} color="error" aria-label="Delete catalog">
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
    </Stack>
  </Paper>
);

// --- Catalogs Tab Content ---
interface CatalogsTabContentProps {
  loading: boolean;
  error: Error | undefined;
  catalogs: GqlCatalog[];
  onCreateCatalog: () => void;
  onEditCatalog: (catalog: GqlCatalog) => void;
  onDeleteCatalog: (catalog: GqlCatalog) => void;
}

const CatalogsTabContent: React.FC<CatalogsTabContentProps> = ({
  loading,
  error,
  catalogs,
  onCreateCatalog,
  onEditCatalog,
  onDeleteCatalog,
}) => {
  if (loading) {
    return <LoadingState py={4} />;
  }
  if (error) {
    return <ErrorAlert message={`Failed to load: ${error.message}`} />;
  }

  return (
    <>
      <Stack direction="row" justifyContent="flex-end" mb={2}>
        <Button variant="contained" startIcon={<AddIcon />} onClick={onCreateCatalog}>
          New Catalog
        </Button>
      </Stack>
      {catalogs.length === 0 ? (
        <Alert severity="info">No managed catalogs found. Create your first global catalog!</Alert>
      ) : (
        <Stack spacing={2}>
          {catalogs.map((catalog, index) => (
            <CatalogCard
              key={catalog.catalogId ?? `catalog-${index}`}
              catalog={catalog}
              onEdit={onEditCatalog}
              onDelete={onDeleteCatalog}
            />
          ))}
        </Stack>
      )}
    </>
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
        <Typography variant="body1">AWS AppSync GraphQL</Typography>
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
  </>
);

// --- Delete User Dialog ---
interface DeleteUserProgressState {
  step: string;
  completed: string[];
  error?: string;
}

interface DeleteUserDialogProps {
  target: GqlAdminUser | null;
  progress: DeleteUserProgressState | null;
  deletingUser: boolean;
  onCancel: () => void;
  onConfirmDelete: () => void;
}

const DeleteUserDialog: React.FC<DeleteUserDialogProps> = ({
  target,
  progress,
  deletingUser,
  onCancel,
  onConfirmDelete,
}) => (
  <Dialog open={!!target} onClose={onCancel} maxWidth="sm" fullWidth>
    <DialogTitle>Delete User</DialogTitle>
    <DialogContent>
      {!progress ? (
        <DialogContentText>
          Are you sure you want to permanently delete the user <strong>{target?.email}</strong>?
          <br />
          <br />
          This will delete all their data including:
          <ul>
            <li>Sales/orders</li>
            <li>Campaigns</li>
            <li>Shares</li>
            <li>Profiles (Scouts)</li>
            <li>User account</li>
          </ul>
          Their custom catalogs are preserved and will not be deleted.
          <br />
          This action cannot be undone.
        </DialogContentText>
      ) : (
        <DeleteUserProgressView progress={progress} />
      )}
    </DialogContent>
    <DeleteUserDialogActions
      progress={progress}
      deletingUser={deletingUser}
      onCancel={onCancel}
      onConfirmDelete={onConfirmDelete}
    />
  </Dialog>
);

// The in-progress cascade view: current step, completed steps, and any error.
const DeleteUserProgressView: React.FC<{ progress: DeleteUserProgressState }> = ({ progress }) => (
  <Box>
    {/* Current step */}
    <Box display="flex" alignItems="center" gap={2} mb={2}>
      {!progress.error && <CircularProgress size={20} />}
      <Typography variant="body1" color={progress.error ? 'error' : 'text.primary'} fontWeight="medium">
        {progress.step}
      </Typography>
    </Box>

    {/* Completed steps */}
    {progress.completed.length > 0 && (
      <Box sx={{ pl: 2, borderLeft: 2, borderColor: 'success.main', mb: 2 }}>
        {progress.completed.map((msg, i) => (
          <Typography key={i} variant="body2" color="text.secondary">
            ✓ {msg}
          </Typography>
        ))}
      </Box>
    )}

    {/* Error message */}
    {progress.error && (
      <Alert severity="error" sx={{ mt: 2 }}>
        {progress.error}
      </Alert>
    )}
  </Box>
);

// True when the cascade stopped on an error (the dialog then offers Close).
const cascadeFailed = (progress: DeleteUserProgressState | null): boolean => Boolean(progress?.error);

const DeleteUserDialogActions: React.FC<DeleteUserDialogProps> = ({
  progress,
  deletingUser,
  onCancel,
  onConfirmDelete,
}) => (
  <DialogActions>
    <Button onClick={onCancel} disabled={deletingUser && !cascadeFailed(progress)}>
      {cascadeFailed(progress) ? 'Close' : 'Cancel'}
    </Button>
    {!progress && (
      <Button
        onClick={() => {
          void onConfirmDelete();
        }}
        color="error"
      >
        Delete User
      </Button>
    )}
  </DialogActions>
);

// `error.message` when the thrown value is an Error, else a generic fallback.
const errorMessageOf = (error: unknown): string => (error instanceof Error ? error.message : 'Unknown error');

const managedCatalogsOf = (data: { listManagedCatalogs: GqlCatalog[] } | undefined): GqlCatalog[] =>
  data?.listManagedCatalogs || [];

// Signal the admin-MFA gate that a mutation was rejected for missing MFA.
const dispatchMfaRequiredEvent = (): void => {
  window.dispatchEvent(
    new CustomEvent('mfa-required', {
      detail: { errorCode: MFA_REQUIRED_ERROR_CODE, message: 'MFA required' },
    }),
  );
};

// --- Main Component ---
export const AdminPage: React.FC = () => {
  const { isMfaRequired } = useAdminMfa();
  const navigate = useNavigate();
  const [currentTab, setCurrentTab] = useState(0);

  // User search state
  const [userSearchQuery, setUserSearchQuery] = useState('');
  const [searchedUsers, setSearchedUsers] = useState<GqlAdminUser[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

  // Dialog states
  const [resetPasswordUser, setResetPasswordUser] = useState<GqlAdminUser | null>(null);
  const [deleteUserTarget, setDeleteUserTarget] = useState<GqlAdminUser | null>(null);
  const {
    message: snackbarMessage,
    open: snackbarOpen,
    key: snackbarKey,
    show: showSnackbar,
    close: closeSnackbar,
  } = useSnackbar();

  // Catalog editor state
  const [catalogEditorOpen, setCatalogEditorOpen] = useState(false);
  const [editingCatalog, setEditingCatalog] = useState<GqlCatalog | null>(null);
  const [deleteCatalogTarget, setDeleteCatalogTarget] = useState<GqlCatalog | null>(null);

  // Cascading delete progress state
  const [deleteProgress, setDeleteProgress] = useState<DeleteUserProgressState | null>(null);

  // Search users (lazy query)
  const [searchUser, { loading: usersLoading, error: usersError, data: searchUserData }] = useLazyQuery<{
    adminSearchUser: GqlAdminUser[];
  }>(ADMIN_SEARCH_USER, {
    fetchPolicy: 'network-only',
  });

  // Update searched users state when data changes
  React.useEffect(() => {
    if (searchUserData !== undefined) {
      setSearchedUsers(searchUserData.adminSearchUser);
      setHasSearched(true);
    }
  }, [searchUserData]);

  // Fetch catalogs
  const {
    data: catalogsData,
    loading: catalogsLoading,
    error: catalogsError,
    refetch: refetchCatalogs,
  } = useQuery<{ listManagedCatalogs: GqlCatalog[] }>(LIST_MANAGED_CATALOGS);

  const mfaRequired = isMfaRequired || [usersError, catalogsError].some(isMfaRequiredError);

  // Mutations
  const [resetPassword, { loading: resettingPassword }] = useMutation(ADMIN_RESET_USER_PASSWORD);

  // Catalog mutations
  const [createManagedCatalog] = useMutation(CREATE_MANAGED_CATALOG, {
    onCompleted: () => {
      showSnackbar('Catalog created successfully');
      void refetchCatalogs();
    },
    onError: (error) => {
      showSnackbar(`Error creating catalog: ${error.message}`);
    },
  });
  const [updateCatalog] = useMutation(UPDATE_CATALOG, {
    onCompleted: () => {
      showSnackbar('Catalog updated successfully');
      void refetchCatalogs();
    },
    onError: (error) => {
      showSnackbar(`Error updating catalog: ${error.message}`);
    },
  });
  const [deleteCatalog] = useMutation(DELETE_CATALOG, {
    onCompleted: () => {
      showSnackbar('Catalog deleted successfully');
      void refetchCatalogs();
    },
  });

  // Deletion is client-side by decision (#521). The client issues the
  // per-entity deletes it can reach, then adminPurgeUserAccount for the two
  // things a browser cannot do: the accounts record and the Cognito user.
  // Catalogs are deliberately never deleted.
  const [deleteUserOrders] = useMutation<GqlAdminDeleteUserOrdersMutation, GqlAdminDeleteUserOrdersMutationVariables>(
    ADMIN_DELETE_USER_ORDERS,
  );
  const [deleteUserCampaigns] = useMutation<
    GqlAdminDeleteUserCampaignsMutation,
    GqlAdminDeleteUserCampaignsMutationVariables
  >(ADMIN_DELETE_USER_CAMPAIGNS);
  const [deleteUserShares] = useMutation<GqlAdminDeleteUserSharesMutation, GqlAdminDeleteUserSharesMutationVariables>(
    ADMIN_DELETE_USER_SHARES,
  );
  const [deleteUserProfiles] = useMutation<
    GqlAdminDeleteUserProfilesMutation,
    GqlAdminDeleteUserProfilesMutationVariables
  >(ADMIN_DELETE_USER_PROFILES);
  const [purgeUserAccount] = useMutation<GqlAdminPurgeUserAccountMutation, GqlAdminPurgeUserAccountMutationVariables>(
    ADMIN_PURGE_USER_ACCOUNT,
  );
  // The purge needs the profile IDs read BEFORE the profile rows are deleted,
  // because the server sweeps the profile-keyed residue by them (#521).
  const [getUserProfilesForPurge] = useLazyQuery<GqlAdminGetUserProfilesQuery, GqlAdminGetUserProfilesQueryVariables>(
    ADMIN_GET_USER_PROFILES,
    {
      fetchPolicy: 'network-only',
    },
  );

  const catalogs = managedCatalogsOf(catalogsData);

  // The cascading-delete steps, run sequentially by confirmDeleteUser. Each step
  // reports its deleted count so the progress view can list completed steps.
  // Catalogs are never deleted (#521), so there is deliberately no catalog step here.
  const cascadeSteps: Array<{ label: string; run: (accountId: string) => Promise<string> }> = [
    {
      label: 'Deleting sales/orders...',
      run: async (accountId) =>
        `Deleted ${(await deleteUserOrders({ variables: { accountId } })).data?.adminDeleteUserOrders ?? 0} orders`,
    },
    {
      label: 'Deleting campaigns...',
      run: async (accountId) =>
        `Deleted ${(await deleteUserCampaigns({ variables: { accountId } })).data?.adminDeleteUserCampaigns ?? 0} campaigns`,
    },
    {
      label: 'Deleting shares...',
      run: async (accountId) =>
        `Deleted ${(await deleteUserShares({ variables: { accountId } })).data?.adminDeleteUserShares ?? 0} shares`,
    },
  ];

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

  const handleSearchUser = () => {
    /* v8 ignore start -- Search button is disabled and Enter key handler prevents empty queries */
    if (!userSearchQuery.trim()) return;
    /* v8 ignore stop */
    setSearchedUsers([]);
    setHasSearched(false);
    void searchUser({ variables: { query: userSearchQuery.trim() } });
  };

  // --- Catalog Handlers ---
  const handleCreateCatalog = () => {
    setEditingCatalog(null);
    setCatalogEditorOpen(true);
  };

  const handleEditCatalog = (catalog: GqlCatalog) => {
    setEditingCatalog(catalog);
    setCatalogEditorOpen(true);
  };

  const handleDeleteCatalog = (catalog: GqlCatalog) => {
    setDeleteCatalogTarget(catalog);
  };

  const confirmDeleteCatalog = async () => {
    /* v8 ignore start -- Delete catalog dialog only opens when a target is selected */
    if (!deleteCatalogTarget) return;
    /* v8 ignore stop */
    await deleteCatalog({ variables: { catalogId: deleteCatalogTarget.catalogId } });
  };

  const handleSaveCatalog = async (catalogData: {
    catalogName: string;
    isPublic: boolean;
    products: GqlProductInput[];
  }) => {
    if (editingCatalog) {
      await updateCatalog({
        variables: { catalogId: editingCatalog.catalogId, input: catalogData },
      });
    } else {
      await createManagedCatalog({ variables: { input: catalogData } });
    }
    setCatalogEditorOpen(false);
    setEditingCatalog(null);
  };

  const handleResetPassword = (user: GqlAdminUser) => {
    setResetPasswordUser(user);
  };

  const handleDeleteUser = (user: GqlAdminUser) => {
    setDeleteUserTarget(user);
  };

  const confirmResetPassword = async () => {
    /* v8 ignore start -- Reset password dialog only opens when a user is selected */
    if (!resetPasswordUser) return;
    /* v8 ignore stop */
    const targetEmail = resetPasswordUser.email;
    try {
      await resetPassword({ variables: { email: targetEmail } });
      showSnackbar(`Password reset email sent to ${targetEmail}`);
    } catch (error) {
      if (isMfaRequiredError(error)) {
        dispatchMfaRequiredEvent();
      }
      showSnackbar(`Error resetting password: ${errorMessageOf(error)}`);
    }
  };

  const deleteProfiles = async (accountId: string): Promise<{ countMessage: string; profileIds: string[] }> => {
    // The server purge sweeps the profile-keyed residue (invites, S3
    // reports) by profile ID, so the IDs must be read while the profile
    // rows still exist (#521).
    const profilesData = await getUserProfilesForPurge({ variables: { accountId } });
    const profileIds = (profilesData.data?.adminGetUserProfiles ?? []).map((profile) => profile.profileId);
    const profilesResult = await deleteUserProfiles({ variables: { accountId } });
    return {
      countMessage: `Deleted ${profilesResult.data?.adminDeleteUserProfiles ?? 0} profiles`,
      profileIds,
    };
  };

  const confirmDeleteUser = async () => {
    /* v8 ignore start -- Delete user dialog only opens when a target is selected */
    if (!deleteUserTarget) return;
    /* v8 ignore stop */

    const targetEmail = deleteUserTarget.email;
    const accountId = deleteUserTarget.accountId;
    const completed: string[] = [];

    try {
      for (const step of cascadeSteps) {
        setDeleteProgress({ step: step.label, completed: [...completed] });
        completed.push(await step.run(accountId));
      }

      setDeleteProgress({ step: 'Deleting profiles...', completed: [...completed] });
      const { countMessage, profileIds } = await deleteProfiles(accountId);
      completed.push(countMessage);

      // Last: the accounts record and the Cognito user, which a browser with
      // no AWS credentials cannot delete itself.
      setDeleteProgress({ step: 'Deleting user account...', completed: [...completed] });
      await purgeUserAccount({ variables: { accountId, profileIds } });
      completed.push('User account deleted');

      // Success!
      setDeleteProgress(null);
      setDeleteUserTarget(null);
      showSnackbar(`User ${targetEmail} deleted successfully`);
      // Clear the searched users since one has been deleted
      setSearchedUsers([]);
      setHasSearched(false);
    } catch (error) {
      if (isMfaRequiredError(error)) {
        dispatchMfaRequiredEvent();
      }
      setDeleteProgress({
        step: 'Error occurred',
        completed,
        error: errorMessageOf(error),
      });
    }
  };

  const cancelDelete = () => {
    setDeleteUserTarget(null);
    setDeleteProgress(null);
  };

  const deletingUser = deleteProgress !== null;

  if (mfaRequired) {
    return <MfaSetupRequiredState />;
  }

  return (
    <Box>
      <PageHeader title="Admin Console" />

      <AmrTripwireBanner />

      <Alert severity="warning" sx={{ mb: 3 }}>
        <strong>Administrator Access:</strong> You have elevated privileges. Use this console responsibly.
      </Alert>

      {/* Tabs */}
      <Paper sx={{ mb: 3 }}>
        <Tabs value={currentTab} onChange={handleTabChange} variant="fullWidth">
          <Tab
            id="admin-tab-0"
            aria-controls="admin-tabpanel-0"
            label="Users"
            icon={<PersonIcon />}
            iconPosition="start"
          />
          <Tab
            id="admin-tab-1"
            aria-controls="admin-tabpanel-1"
            label="Catalogs"
            icon={<CatalogIcon />}
            iconPosition="start"
          />
          <Tab
            id="admin-tab-2"
            aria-controls="admin-tabpanel-2"
            label="System Info"
            icon={<InfoIcon />}
            iconPosition="start"
          />
        </Tabs>
      </Paper>

      {/* Tab Panels */}
      <TabPanel value={currentTab} index={0}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            User Management
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            Search for users by email address or account ID.
          </Typography>
          <UsersTabContent
            searchQuery={userSearchQuery}
            onSearchQueryChange={setUserSearchQuery}
            onSearch={handleSearchUser}
            loading={usersLoading}
            error={usersError}
            searchedUsers={searchedUsers}
            hasSearched={hasSearched}
            onResetPassword={handleResetPassword}
            onDeleteUser={handleDeleteUser}
            onViewDetails={(user) => {
              void navigate(`/admin/user-data/${encodeURIComponent(user.accountId)}`);
            }}
          />
        </Paper>
      </TabPanel>

      <TabPanel value={currentTab} index={1}>
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Shared Product Catalogs
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            Manage admin-created product catalogs shared with all users.
          </Typography>
          <CatalogsTabContent
            loading={catalogsLoading}
            error={catalogsError}
            catalogs={catalogs}
            onCreateCatalog={handleCreateCatalog}
            onEditCatalog={handleEditCatalog}
            onDeleteCatalog={handleDeleteCatalog}
          />
        </Paper>
      </TabPanel>

      <TabPanel value={currentTab} index={2}>
        <Paper sx={{ p: 3 }}>
          <SystemInfoTabContent />
        </Paper>
      </TabPanel>

      {/* Catalog Editor Dialog */}
      <CatalogEditorDialog
        open={catalogEditorOpen}
        onClose={() => {
          setCatalogEditorOpen(false);
          setEditingCatalog(null);
        }}
        onSave={handleSaveCatalog}
        initialCatalog={editingCatalog}
      />

      <ConfirmDialog
        open={!!deleteCatalogTarget}
        title="Delete Catalog"
        onClose={() => setDeleteCatalogTarget(null)}
        onConfirm={confirmDeleteCatalog}
        confirmLabel="Delete"
        confirmColor="error"
      >
        <Typography>
          Are you sure you want to delete <strong>{deleteCatalogTarget?.catalogName}</strong>?
          <br />
          <br />
          This catalog will no longer be available for new campaigns, but existing campaigns using it will continue to
          work.
        </Typography>
      </ConfirmDialog>

      <ConfirmDialog
        open={!!resetPasswordUser}
        title="Reset Password"
        onClose={() => setResetPasswordUser(null)}
        onConfirm={confirmResetPassword}
        confirmLabel="Send Reset Email"
        confirmColor="primary"
        isLoading={resettingPassword}
        loadingLabel="Sending..."
      >
        <Typography>
          Send a password reset email to <strong>{resetPasswordUser?.email}</strong>?
        </Typography>
      </ConfirmDialog>

      {/* Delete User Confirmation Dialog */}
      <DeleteUserDialog
        target={deleteUserTarget}
        progress={deleteProgress}
        deletingUser={deletingUser}
        onCancel={cancelDelete}
        onConfirmDelete={() => {
          void confirmDeleteUser();
        }}
      />

      <Snackbar
        key={snackbarKey}
        open={snackbarOpen}
        autoHideDuration={6000}
        onClose={closeSnackbar}
        message={snackbarMessage}
        action={
          <IconButton size="small" aria-label="close" color="inherit" onClick={closeSnackbar}>
            <CloseIcon fontSize="small" />
          </IconButton>
        }
      />
    </Box>
  );
};
