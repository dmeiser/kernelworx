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
} from '@mui/icons-material';
import {
  LIST_MANAGED_CATALOGS,
  ADMIN_SEARCH_USER,
  ADMIN_RESET_USER_PASSWORD,
  ADMIN_DELETE_USER,
  ADMIN_DELETE_USER_ORDERS,
  ADMIN_DELETE_USER_CAMPAIGNS,
  ADMIN_DELETE_USER_SHARES,
  ADMIN_DELETE_USER_PROFILES,
  ADMIN_DELETE_USER_CATALOGS,
  CREATE_MANAGED_CATALOG,
  UPDATE_CATALOG,
  DELETE_CATALOG,
} from '../lib/graphql';
import { CatalogEditorDialog } from '../components/CatalogEditorDialog';
import type { Catalog, AdminUser } from '../types';
import type {
  GqlAdminDeleteUserMutation,
  GqlAdminDeleteUserMutationVariables,
  GqlAdminDeleteUserOrdersMutation,
  GqlAdminDeleteUserOrdersMutationVariables,
  GqlAdminDeleteUserCampaignsMutation,
  GqlAdminDeleteUserCampaignsMutationVariables,
  GqlAdminDeleteUserSharesMutation,
  GqlAdminDeleteUserSharesMutationVariables,
  GqlAdminDeleteUserProfilesMutation,
  GqlAdminDeleteUserProfilesMutationVariables,
  GqlAdminDeleteUserCatalogsMutation,
  GqlAdminDeleteUserCatalogsMutationVariables,
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

const LoadingSpinner: React.FC = () => (
  <Box display="flex" justifyContent="center" py={4}>
    <CircularProgress />
  </Box>
);

const ErrorAlert: React.FC<{ message: string }> = ({ message }) => (
  <Alert severity="error">Failed to load: {message}</Alert>
);

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
  user: AdminUser;
  onResetPassword: (user: AdminUser) => void;
  onDeleteUser: (user: AdminUser) => void;
  onViewDetails: (user: AdminUser) => void;
}

const UserRow: React.FC<UserRowProps> = ({ user, onResetPassword, onDeleteUser, onViewDetails }) => (
  <TableRow hover sx={{ cursor: 'pointer' }} onClick={() => onViewDetails(user)}>
    <TableCell>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="body2">{user.email}</Typography>
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
    <TableCell>
      <Typography variant="body2">{user.displayName ?? '—'}</Typography>
    </TableCell>
    <TableCell>
      <UserStatusChip status={user.status} enabled={user.enabled} />
    </TableCell>
    <TableCell>
      {user.isAdmin ? (
        <Chip icon={<AdminIcon />} label="Admin" color="primary" size="small" />
      ) : (
        <Chip label="User" color="default" size="small" variant="outlined" />
      )}
    </TableCell>
    <TableCell>
      <Typography variant="body2" color="text.secondary">
        {user.createdAt ? new Date(user.createdAt).toLocaleDateString() : '—'}
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
  searchedUsers: AdminUser[];
  hasSearched: boolean;
  onResetPassword: (user: AdminUser) => void;
  onDeleteUser: (user: AdminUser) => void;
  onViewDetails: (user: AdminUser) => void;
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
  // eslint-disable-next-line complexity -- multiple conditional renders for search states
}) => {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && searchQuery.trim()) {
      onSearch();
    }
  };

  return (
    <>
      <Box display="flex" gap={2} mb={3}>
        <TextField
          fullWidth
          label="Search User"
          placeholder="Search by email, name, or account ID"
          value={searchQuery}
          onChange={(e) => onSearchQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
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
        <Button variant="contained" onClick={onSearch} disabled={loading || !searchQuery.trim()} sx={{ minWidth: 100 }}>
          {loading ? <CircularProgress size={24} /> : 'Search'}
        </Button>
      </Box>

      {error && <ErrorAlert message={error.message} />}

      {!hasSearched && !error && (
        <Alert severity="info">
          Search for a user by email, name, or account ID. Partial matches are supported (e.g., &quot;john&quot; finds
          &quot;john.doe@example.com&quot;).
        </Alert>
      )}

      {hasSearched && !loading && !error && searchedUsers.length === 0 && (
        <Alert severity="warning">No user found matching &quot;{searchQuery}&quot;.</Alert>
      )}

      {searchedUsers.length > 0 && (
        <>
          {searchedUsers.length > 1 && (
            <Alert severity="info" sx={{ mb: 2 }}>
              Found {searchedUsers.length} users matching &quot;{searchQuery}&quot;
            </Alert>
          )}
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Email</TableCell>
                  <TableCell>Name</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Role</TableCell>
                  <TableCell>Created</TableCell>
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
      )}
    </>
  );
};

// --- Catalog Card ---
interface CatalogCardProps {
  catalog: Catalog;
  onEdit: (catalog: Catalog) => void;
  onDelete: (catalog: Catalog) => void;
}

const CatalogCard: React.FC<CatalogCardProps> = ({ catalog, onEdit, onDelete }) => (
  <Paper variant="outlined" sx={{ p: 2 }}>
    <Stack direction="row" justifyContent="space-between" alignItems="start">
      <Box>
        <Typography variant="subtitle1" fontWeight="medium">
          {catalog.catalogName ?? 'Unnamed Catalog'}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {(catalog.products ?? []).length} products
        </Typography>
      </Box>
      <Stack direction="row" spacing={1} alignItems="center">
        <Chip
          label={catalog.catalogType === 'ADMIN_MANAGED' ? 'Managed' : 'User'}
          color={catalog.catalogType === 'ADMIN_MANAGED' ? 'primary' : 'default'}
          size="small"
        />
        <Tooltip title="Edit Catalog">
          <IconButton size="small" onClick={() => onEdit(catalog)} color="primary">
            <EditIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Delete Catalog">
          <IconButton size="small" onClick={() => onDelete(catalog)} color="error">
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
  catalogs: Catalog[];
  onCreateCatalog: () => void;
  onEditCatalog: (catalog: Catalog) => void;
  onDeleteCatalog: (catalog: Catalog) => void;
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
    return <LoadingSpinner />;
  }
  if (error) {
    return <ErrorAlert message={error.message} />;
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

// --- Main Component ---
// eslint-disable-next-line complexity -- Admin page with multiple tabs and state management
export const AdminPage: React.FC = () => {
  const navigate = useNavigate();
  const [currentTab, setCurrentTab] = useState(0);

  // User search state
  const [userSearchQuery, setUserSearchQuery] = useState('');
  const [searchedUsers, setSearchedUsers] = useState<AdminUser[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

  // Dialog states
  const [resetPasswordUser, setResetPasswordUser] = useState<AdminUser | null>(null);
  const [deleteUserTarget, setDeleteUserTarget] = useState<AdminUser | null>(null);
  const [snackbarMessage, setSnackbarMessage] = useState<string | null>(null);

  // Catalog editor state
  const [catalogEditorOpen, setCatalogEditorOpen] = useState(false);
  const [editingCatalog, setEditingCatalog] = useState<Catalog | null>(null);
  const [deleteCatalogTarget, setDeleteCatalogTarget] = useState<Catalog | null>(null);

  // Cascading delete progress state
  const [deleteProgress, setDeleteProgress] = useState<{
    step: string;
    completed: string[];
    error?: string;
  } | null>(null);

  // Search users (lazy query)
  const [searchUser, { loading: usersLoading, error: usersError, data: searchUserData }] = useLazyQuery<{
    adminSearchUser: AdminUser[];
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
  } = useQuery<{ listManagedCatalogs: Catalog[] }>(LIST_MANAGED_CATALOGS);

  // Mutations
  const [resetPassword, { loading: resettingPassword }] = useMutation(ADMIN_RESET_USER_PASSWORD, {
    onCompleted: () => {
      setSnackbarMessage(`Password reset email sent to ${resetPasswordUser?.email}`);
      setResetPasswordUser(null);
    },
    onError: (error) => {
      setSnackbarMessage(`Error: ${error.message}`);
    },
  });

  // Catalog mutations
  const [createManagedCatalog] = useMutation(CREATE_MANAGED_CATALOG, {
    onCompleted: () => {
      setSnackbarMessage('Catalog created successfully');
      refetchCatalogs();
    },
    onError: (error) => {
      setSnackbarMessage(`Error creating catalog: ${error.message}`);
    },
  });
  const [updateCatalog] = useMutation(UPDATE_CATALOG, {
    onCompleted: () => {
      setSnackbarMessage('Catalog updated successfully');
      refetchCatalogs();
    },
    onError: (error) => {
      setSnackbarMessage(`Error updating catalog: ${error.message}`);
    },
  });
  const [deleteCatalog] = useMutation(DELETE_CATALOG, {
    onCompleted: () => {
      setSnackbarMessage('Catalog deleted successfully');
      refetchCatalogs();
    },
    onError: (error) => {
      setSnackbarMessage(`Error deleting catalog: ${error.message}`);
    },
  });

  // Cascading delete mutations (called sequentially)
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
  const [deleteUserCatalogs] = useMutation<
    GqlAdminDeleteUserCatalogsMutation,
    GqlAdminDeleteUserCatalogsMutationVariables
  >(ADMIN_DELETE_USER_CATALOGS);
  const [deleteUser] = useMutation<GqlAdminDeleteUserMutation, GqlAdminDeleteUserMutationVariables>(ADMIN_DELETE_USER);

  const catalogs = catalogsData?.listManagedCatalogs || [];

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

  const handleSearchUser = () => {
    if (!userSearchQuery.trim()) return;
    searchUser({ variables: { query: userSearchQuery.trim() } });
  };

  // --- Catalog Handlers ---
  const handleCreateCatalog = () => {
    setEditingCatalog(null);
    setCatalogEditorOpen(true);
  };

  const handleEditCatalog = (catalog: Catalog) => {
    setEditingCatalog(catalog);
    setCatalogEditorOpen(true);
  };

  const handleDeleteCatalog = (catalog: Catalog) => {
    setDeleteCatalogTarget(catalog);
  };

  const confirmDeleteCatalog = async () => {
    if (!deleteCatalogTarget) return;
    await deleteCatalog({ variables: { catalogId: deleteCatalogTarget.catalogId } });
    setDeleteCatalogTarget(null);
  };

  const handleSaveCatalog = async (catalogData: {
    catalogName: string;
    isPublic: boolean;
    products: Array<{
      productId?: string;
      productName: string;
      description?: string;
      price: number;
    }>;
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

  const handleResetPassword = (user: AdminUser) => {
    setResetPasswordUser(user);
  };

  const handleDeleteUser = (user: AdminUser) => {
    setDeleteUserTarget(user);
  };

  const confirmResetPassword = () => {
    if (resetPasswordUser) {
      resetPassword({ variables: { email: resetPasswordUser.email } });
    }
  };

  // eslint-disable-next-line complexity -- Cascading delete requires sequential steps
  const confirmDeleteUser = async () => {
    if (!deleteUserTarget) return;

    const accountId = deleteUserTarget.accountId;
    const completed: string[] = [];

    try {
      // Step 1: Delete orders
      setDeleteProgress({ step: 'Deleting sales/orders...', completed });
      const ordersResult = await deleteUserOrders({ variables: { accountId } });
      completed.push(`Deleted ${ordersResult.data?.adminDeleteUserOrders ?? 0} orders`);

      // Step 2: Delete campaigns
      setDeleteProgress({ step: 'Deleting campaigns...', completed: [...completed] });
      const campaignsResult = await deleteUserCampaigns({ variables: { accountId } });
      completed.push(`Deleted ${campaignsResult.data?.adminDeleteUserCampaigns ?? 0} campaigns`);

      // Step 3: Delete shares
      setDeleteProgress({ step: 'Deleting shares...', completed: [...completed] });
      const sharesResult = await deleteUserShares({ variables: { accountId } });
      completed.push(`Deleted ${sharesResult.data?.adminDeleteUserShares ?? 0} shares`);

      // Step 4: Delete profiles
      setDeleteProgress({ step: 'Deleting profiles...', completed: [...completed] });
      const profilesResult = await deleteUserProfiles({ variables: { accountId } });
      completed.push(`Deleted ${profilesResult.data?.adminDeleteUserProfiles ?? 0} profiles`);

      // Step 5: Delete catalogs
      setDeleteProgress({ step: 'Deleting catalogs...', completed: [...completed] });
      const catalogsResult = await deleteUserCatalogs({ variables: { accountId } });
      completed.push(`Deleted ${catalogsResult.data?.adminDeleteUserCatalogs ?? 0} catalogs`);

      // Step 6: Delete user from Cognito + DynamoDB
      setDeleteProgress({ step: 'Deleting user account...', completed: [...completed] });
      await deleteUser({ variables: { accountId } });
      completed.push('User account deleted');

      // Success!
      setDeleteProgress(null);
      setDeleteUserTarget(null);
      setSnackbarMessage(`User ${deleteUserTarget.email} deleted successfully`);
      // Clear the searched users since one has been deleted
      setSearchedUsers([]);
      setHasSearched(false);
    } catch (error) {
      setDeleteProgress({
        step: 'Error occurred',
        completed,
        error: error instanceof Error ? error.message : 'Unknown error',
      });
    }
  };

  const cancelDelete = () => {
    setDeleteUserTarget(null);
    setDeleteProgress(null);
  };

  const deletingUser = deleteProgress !== null;

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
          <Tab label="Users" icon={<PersonIcon />} iconPosition="start" />
          <Tab label="Catalogs" icon={<CatalogIcon />} iconPosition="start" />
          <Tab label="System Info" icon={<InfoIcon />} iconPosition="start" />
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
            onViewDetails={(user) => navigate(`/admin/user-data/${user.accountId}`)}
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

      {/* Delete Catalog Confirmation Dialog */}
      <Dialog open={!!deleteCatalogTarget} onClose={() => setDeleteCatalogTarget(null)}>
        <DialogTitle>Delete Catalog</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to delete <strong>{deleteCatalogTarget?.catalogName}</strong>?
            <br />
            <br />
            This catalog will no longer be available for new campaigns, but existing campaigns using it will continue to
            work.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteCatalogTarget(null)}>Cancel</Button>
          <Button onClick={confirmDeleteCatalog} color="error">
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      {/* Reset Password Confirmation Dialog */}
      <Dialog open={!!resetPasswordUser} onClose={() => setResetPasswordUser(null)}>
        <DialogTitle>Reset Password</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Send a password reset email to <strong>{resetPasswordUser?.email}</strong>?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetPasswordUser(null)} disabled={resettingPassword}>
            Cancel
          </Button>
          <Button onClick={confirmResetPassword} color="primary" disabled={resettingPassword}>
            {resettingPassword ? 'Sending...' : 'Send Reset Email'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete User Confirmation Dialog */}
      <Dialog open={!!deleteUserTarget} onClose={cancelDelete} maxWidth="sm" fullWidth>
        <DialogTitle>Delete User</DialogTitle>
        <DialogContent>
          {!deleteProgress ? (
            <DialogContentText>
              Are you sure you want to permanently delete the user <strong>{deleteUserTarget?.email}</strong>?
              <br />
              <br />
              This will delete all their data including:
              <ul>
                <li>Sales/orders</li>
                <li>Campaigns</li>
                <li>Shares</li>
                <li>Profiles (Scouts)</li>
                <li>Custom catalogs</li>
                <li>User account</li>
              </ul>
              This action cannot be undone.
            </DialogContentText>
          ) : (
            <Box>
              {/* Current step */}
              <Box display="flex" alignItems="center" gap={2} mb={2}>
                {!deleteProgress.error && <CircularProgress size={20} />}
                <Typography variant="body1" color={deleteProgress.error ? 'error' : 'text.primary'} fontWeight="medium">
                  {deleteProgress.step}
                </Typography>
              </Box>

              {/* Completed steps */}
              {deleteProgress.completed.length > 0 && (
                <Box sx={{ pl: 2, borderLeft: 2, borderColor: 'success.main', mb: 2 }}>
                  {deleteProgress.completed.map((msg, i) => (
                    <Typography key={i} variant="body2" color="text.secondary">
                      ✓ {msg}
                    </Typography>
                  ))}
                </Box>
              )}

              {/* Error message */}
              {deleteProgress.error && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {deleteProgress.error}
                </Alert>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={cancelDelete} disabled={deletingUser && !deleteProgress?.error}>
            {deleteProgress?.error ? 'Close' : 'Cancel'}
          </Button>
          {!deleteProgress && (
            <Button onClick={confirmDeleteUser} color="error">
              Delete User
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* Snackbar for notifications */}
      <Snackbar
        open={!!snackbarMessage}
        autoHideDuration={6000}
        onClose={() => setSnackbarMessage(null)}
        message={snackbarMessage}
      />
    </Box>
  );
};
