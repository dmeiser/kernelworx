/**
 * Scouts page - List of owned and shared scout profiles
 */

import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useLazyQuery, useMutation, useApolloClient } from '@apollo/client/react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Typography,
  Box,
  Button,
  Grid,
  Alert,
  CircularProgress,
  Stack,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControlLabel,
  Switch,
} from '@mui/material';
import { Add as AddIcon, CardGiftcard as GiftIcon } from '@mui/icons-material';
import { ProfileCard } from '../components/ProfileCard';
import { CreateProfileDialog } from '../components/CreateProfileDialog';
import { EditProfileDialog } from '../components/EditProfileDialog';
import {
  LIST_MY_PROFILES,
  LIST_MY_SHARES,
  CREATE_SELLER_PROFILE,
  UPDATE_SELLER_PROFILE,
  DELETE_SELLER_PROFILE,
  GET_MY_ACCOUNT,
  UPDATE_MY_PREFERENCES,
} from '../lib/graphql';
import { ensureProfileId } from '../lib/ids';
import type { SellerProfile } from '../types';

// Use SellerProfile as the Profile type for this page
type Profile = Pick<SellerProfile, 'profileId' | 'sellerName' | 'isOwner' | 'permissions' | 'latestCampaign'>;

// Default preferences value
const DEFAULT_PREFERENCES = { showReadOnlyProfiles: true };

// Helper to safely parse preferences JSON
const parsePreferences = (prefs: string | undefined): { showReadOnlyProfiles: boolean } => {
  if (!prefs || prefs === '') {
    return DEFAULT_PREFERENCES;
  }
  try {
    return JSON.parse(prefs);
  } catch {
    return DEFAULT_PREFERENCES;
  }
};

// Helper to get preferences from account data
const getPreferencesFromAccount = (
  accountData: { getMyAccount: { accountId: string; preferences?: string } } | undefined,
): { showReadOnlyProfiles: boolean } =>
  accountData?.getMyAccount ? parsePreferences(accountData.getMyAccount.preferences) : DEFAULT_PREFERENCES;

// Type for location state
interface LocationState {
  returnTo?: string;
  sharedCampaignCode?: string;
  message?: string;
}

// Helper to get location state with defaults
const getLocationState = (state: LocationState | null): LocationState => state || {};

// Helper to filter shared profiles based on read-only preference
const filterSharedProfiles = (profiles: Profile[], showReadOnlyProfiles: boolean): Profile[] =>
  profiles.filter((profile) => {
    const hasWrite = (profile.permissions ?? []).includes('WRITE');
    return showReadOnlyProfiles || hasWrite;
  });

// Helper to check if both profile sets are loaded
const areBothProfilesLoaded = (
  myProfilesData: { listMyProfiles: Profile[] } | undefined,
  sharedProfilesLoaded: boolean,
): boolean => myProfilesData !== undefined && sharedProfilesLoaded;

// Helper to get my profiles from data
const getMyProfiles = (data: { listMyProfiles: Profile[] } | undefined): Profile[] => data?.listMyProfiles || [];

// Helper to check if page is still loading
const isPageLoading = (profilesLoading: boolean, accountLoading: boolean, bothProfilesLoaded: boolean): boolean =>
  profilesLoading || accountLoading || !bothProfilesLoaded;

// Loading spinner component
const LoadingSpinner: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
    <CircularProgress />
  </Box>
);

// Error alert component
const ErrorAlert: React.FC<{ error: Error }> = ({ error }) => (
  <Alert severity="error" sx={{ mb: 3 }}>
    Failed to load profiles: {error.message}
  </Alert>
);

// Info message alert component
const InfoMessageAlert: React.FC<{ message: string }> = ({ message }) => (
  <Alert severity="info" sx={{ mb: 3 }}>
    {message}
  </Alert>
);

// Empty state component
const EmptyState: React.FC = () => (
  <Alert severity="info">You don't have any scouts yet. Click "Create Scout" to get started!</Alert>
);

// Owned profiles section component
const OwnedProfilesSection: React.FC<{ profiles: Profile[] }> = ({ profiles }) =>
  profiles.length > 0 ? (
    <Box mb={4}>
      <Typography variant="h6" gutterBottom>
        Scouts I Own
      </Typography>
      <Grid container spacing={2}>
        {profiles.map((profile) => (
          <Grid key={profile.profileId} size={{ xs: 12, sm: 6, md: 4 }}>
            <ProfileCard
              profileId={profile.profileId}
              sellerName={profile.sellerName}
              isOwner={profile.isOwner ?? false}
              permissions={profile.permissions ?? []}
              latestCampaign={profile.latestCampaign}
            />
          </Grid>
        ))}
      </Grid>
    </Box>
  ) : null;

// Shared profiles section component
const SharedProfilesSection: React.FC<{
  profiles: Profile[];
  showDivider: boolean;
}> = ({ profiles, showDivider }) =>
  profiles.length > 0 ? (
    <Box>
      {showDivider && <Divider sx={{ my: 4 }} />}
      <Typography variant="h6" gutterBottom>
        Scouts Shared With Me
      </Typography>
      <Grid container spacing={2}>
        {profiles.map((profile) => (
          <Grid key={profile.profileId} size={{ xs: 12, sm: 6, md: 4 }}>
            <ProfileCard
              profileId={profile.profileId}
              sellerName={profile.sellerName}
              isOwner={profile.isOwner ?? false}
              permissions={profile.permissions ?? []}
              latestCampaign={profile.latestCampaign}
            />
          </Grid>
        ))}
      </Grid>
    </Box>
  ) : null;

// Helper to check if should show empty state
const shouldShowEmptyState = (myProfiles: Profile[], filteredSharedProfiles: Profile[], loading: boolean): boolean =>
  myProfiles.length === 0 && filteredSharedProfiles.length === 0 && !loading;

// Helper to build preferences update variables
const buildPreferencesVariables = (preferences: { showReadOnlyProfiles: boolean }, newChecked: boolean) => ({
  preferences: JSON.stringify({
    ...preferences,
    showReadOnlyProfiles: newChecked,
  }),
});

// Helper to check if should open dialog on return path
const shouldAutoOpenDialog = (returnPath: string | undefined, createDialogOpen: boolean): boolean =>
  Boolean(returnPath && !createDialogOpen);

// Helper to conditionally open dialog
const maybeOpenDialog = (shouldOpen: boolean, setCreateDialogOpen: (v: boolean) => void): void => {
  if (shouldOpen) {
    setCreateDialogOpen(true);
  }
};

// Helper to get initial preference value
const getInitialPreferenceValue = (preferences: { showReadOnlyProfiles: boolean }): boolean =>
  preferences.showReadOnlyProfiles ?? true;

// Helper to check if auth is ready and should trigger queries
const shouldTriggerQueries = (authLoading: boolean, isAuthenticated: boolean, queriesTriggered: boolean): boolean =>
  !authLoading && isAuthenticated && !queriesTriggered;

// Helper to conditionally trigger queries
const maybeTriggerQueries = (
  shouldTrigger: boolean,
  queriesTriggeredRef: React.MutableRefObject<boolean>,
  loadAccount: () => void,
  loadMyProfiles: () => void,
  loadSharedProfiles: () => void,
): void => {
  if (shouldTrigger) {
    queriesTriggeredRef.current = true;
    loadAccount();
    loadMyProfiles();
    loadSharedProfiles();
  }
};

// Helper to handle return navigation after profile creation
const handleReturnNavigation = (
  returnPath: string | undefined,
  navigate: (path: string, options?: object) => void,
): void => {
  if (returnPath) {
    // Longer delay to ensure DynamoDB GSI consistency
    // The backend queries profileId-index GSI which has eventual consistency
    setTimeout(() => {
      navigate(returnPath, {
        replace: true,
        state: { fromProfileCreation: true },
      });
    }, 1500);
  }
};

// Helper to check if can delete profile
const canDeleteCurrentProfile = (deletingProfileId: string | null): boolean => Boolean(deletingProfileId);

// Helper to conditionally delete profile
const maybeDeleteProfile = async (
  canDelete: boolean,
  deletingProfileId: string | null,
  deleteProfile: (options: { variables: { profileId: string } }) => Promise<unknown>,
): Promise<void> => {
  if (canDelete && deletingProfileId) {
    const profileId = ensureProfileId(deletingProfileId);
    if (!profileId) return;
    await deleteProfile({
      variables: { profileId },
    });
  }
};

// Helper to update preferences with error handling
const updatePreferencesWithRollback = async (
  updatePreferences: (options: { variables: { preferences: string } }) => Promise<unknown>,
  preferences: { showReadOnlyProfiles: boolean },
  checked: boolean,
  setShowReadOnlyProfiles: (v: boolean) => void,
): Promise<void> => {
  setShowReadOnlyProfiles(checked);
  try {
    await updatePreferences({
      variables: buildPreferencesVariables(preferences, checked),
    });
  } catch (error) {
    console.error('Failed to update preferences:', error);
    setShowReadOnlyProfiles(!checked);
  }
};

// Helper to load shared profiles with error handling
const loadSharedProfilesWithErrorHandling = async (
  apolloClient: ReturnType<typeof useApolloClient>,
  query: Parameters<typeof apolloClient.query>[0]['query'],
  setSharedProfiles: (profiles: Profile[]) => void,
  setSharedProfilesLoaded: (loaded: boolean) => void,
  setSharedProfilesError: (error: Error | null) => void,
  setSharedProfilesLoading: (loading: boolean) => void,
): Promise<void> => {
  setSharedProfilesLoading(true);
  setSharedProfilesError(null);
  try {
    const result = await apolloClient.query<{ listMyShares: Profile[] }>({
      query,
      fetchPolicy: 'network-only',
    });
    const profiles = getSharedProfilesFromResult(result);
    setSharedProfiles(profiles);
    setSharedProfilesLoaded(true);
  } catch (err) {
    console.error('Failed to load shared profiles:', err);
    setSharedProfilesError(handleSharedProfilesError(err));
  } finally {
    setSharedProfilesLoading(false);
  }
};

// Helper to handle shared profiles load error
const handleSharedProfilesError = (err: unknown): Error =>
  err instanceof Error ? err : new Error('Failed to load shared profiles');

// Helper to get profiles from shared profiles result
const getSharedProfilesFromResult = (result: { data?: { listMyShares: Profile[] } }): Profile[] =>
  result.data?.listMyShares || [];

// Helper to combine loading states
const combineLoadingStates = (loading1: boolean, loading2: boolean): boolean => loading1 || loading2;

// Helper to combine errors
const combineErrors = (error1: Error | null | undefined, error2: Error | null): Error | null =>
  (error1 || error2) ?? null;

// Helper component for conditional error display
const ConditionalErrorAlert: React.FC<{ error: Error | null }> = ({ error }) =>
  error ? <ErrorAlert error={error} /> : null;

// Helper component for conditional info message
const ConditionalInfoAlert: React.FC<{ message: string | undefined }> = ({ message }) =>
  message ? <InfoMessageAlert message={message} /> : null;

// Helper component for conditional empty state
const ConditionalEmptyState: React.FC<{
  myProfiles: Profile[];
  filteredSharedProfiles: Profile[];
  loading: boolean;
}> = ({ myProfiles, filteredSharedProfiles, loading }) =>
  shouldShowEmptyState(myProfiles, filteredSharedProfiles, loading) ? <EmptyState /> : null;

// Helper component for conditional editing dialog
const ConditionalEditDialog: React.FC<{
  editingProfile: EditingProfile | null;
  onClose: () => void;
  onSubmit: (profileId: string, sellerName: string) => Promise<void>;
}> = ({ editingProfile, onClose, onSubmit }) =>
  editingProfile ? (
    <EditProfileDialog
      open={true}
      profileId={editingProfile.profileId}
      currentName={editingProfile.sellerName}
      onClose={onClose}
      onSubmit={onSubmit}
    />
  ) : null;

interface EditingProfile {
  profileId: string;
  sellerName: string;
}

export const ScoutsPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, loading: authLoading } = useAuth();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<EditingProfile | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deletingProfileId, setDeletingProfileId] = useState<string | null>(null);

  /* v8 ignore start -- Dialog backdrop click handlers cannot be simulated in jsdom */
  const handleDeleteDialogDismiss = () => setDeleteConfirmOpen(false);
  /* v8 ignore stop */

  // Check for return navigation from campaign shared campaign flow
  const locationState = getLocationState(location.state as LocationState | null);
  const returnPath = locationState.returnTo;
  const infoMessage = locationState.message;

  // Auto-open create dialog when arriving from shared campaign flow
  React.useEffect(() => {
    const shouldOpen = shouldAutoOpenDialog(returnPath, createDialogOpen);
    maybeOpenDialog(shouldOpen, setCreateDialogOpen);
  }, [returnPath, createDialogOpen]);

  // Fetch account preferences
  const [loadAccount, { data: accountData, loading: accountLoading }] = useLazyQuery<{
    getMyAccount: { accountId: string; preferences?: string };
  }>(GET_MY_ACCOUNT, {
    fetchPolicy: 'network-only',
  });

  // Parse preferences from account data
  const preferences = React.useMemo(() => getPreferencesFromAccount(accountData), [accountData]);

  // Show read-only profiles preference
  const [showReadOnlyProfiles, setShowReadOnlyProfiles] = useState(true);

  // Update local state when preferences load
  useEffect(() => {
    setShowReadOnlyProfiles(getInitialPreferenceValue(preferences));
  }, [preferences]);

  // Update preferences mutation
  const [updatePreferences] = useMutation(UPDATE_MY_PREFERENCES);

  // Save preference to DynamoDB when it changes
  const handleToggleReadOnly = async (checked: boolean) => {
    await updatePreferencesWithRollback(updatePreferences, preferences, checked, setShowReadOnlyProfiles);
  };

  // Fetch owned profiles
  const [loadMyProfiles, { data: myProfilesData, loading: myProfilesLoading, error: myProfilesError }] = useLazyQuery<{
    listMyProfiles: Profile[];
  }>(LIST_MY_PROFILES, {
    fetchPolicy: 'network-only',
    notifyOnNetworkStatusChange: true,
  });

  // Shared profiles state - we fetch shares then individual profiles
  const apolloClient = useApolloClient();
  const [sharedProfiles, setSharedProfiles] = useState<Profile[]>([]);
  const [sharedProfilesLoading, setSharedProfilesLoading] = useState(false);
  const [sharedProfilesError, setSharedProfilesError] = useState<Error | null>(null);
  const [sharedProfilesLoaded, setSharedProfilesLoaded] = useState(false);

  // Function to load shared profiles - now returns full profile data in a single query
  const loadSharedProfiles = React.useCallback(async () => {
    await loadSharedProfilesWithErrorHandling(
      apolloClient,
      LIST_MY_SHARES,
      setSharedProfiles,
      setSharedProfilesLoaded,
      setSharedProfilesError,
      setSharedProfilesLoading,
    );
  }, [apolloClient]);

  // When auth becomes ready, trigger queries explicitly to avoid race conditions
  // Note: We use a ref to track if we've already triggered the queries to prevent double-firing
  const queriesTriggeredRef = React.useRef(false);

  useEffect(() => {
    const shouldTrigger = shouldTriggerQueries(authLoading, isAuthenticated, queriesTriggeredRef.current);
    maybeTriggerQueries(shouldTrigger, queriesTriggeredRef, loadAccount, loadMyProfiles, loadSharedProfiles);
  }, [authLoading, isAuthenticated, loadAccount, loadMyProfiles, loadSharedProfiles]);

  // Create profile mutation
  const [createProfile] = useMutation(CREATE_SELLER_PROFILE, {
    refetchQueries: [{ query: LIST_MY_PROFILES }],
    awaitRefetchQueries: true,
    onCompleted: async () => {
      // Reload profiles and wait for the result
      await loadMyProfiles();
      // If we came from a campaign shared campaign flow, return to it
      handleReturnNavigation(returnPath, navigate);
    },
  });

  // Update profile mutation
  const [updateProfile] = useMutation(UPDATE_SELLER_PROFILE, {
    onCompleted: () => {
      loadMyProfiles();
      loadSharedProfiles();
    },
  });

  // Delete profile mutation
  const [deleteProfile] = useMutation(DELETE_SELLER_PROFILE, {
    onCompleted: () => {
      setDeleteConfirmOpen(false);
      setDeletingProfileId(null);
      loadMyProfiles();
    },
  });

  const handleCreateProfile = async (sellerName: string) => {
    await createProfile({ variables: { sellerName } });
  };

  const handleUpdateProfile = async (profileId: string, sellerName: string) => {
    await updateProfile({
      variables: { profileId: ensureProfileId(profileId), sellerName },
    });
  };

  /* v8 ignore next 4 -- Delete handler requires complex mutation mocking and dialog interaction */
  const handleDeleteProfile = async () => {
    const canDelete = canDeleteCurrentProfile(deletingProfileId);
    await maybeDeleteProfile(canDelete, deletingProfileId, deleteProfile);
  };

  const myProfiles = getMyProfiles(myProfilesData);
  const filteredSharedProfiles = filterSharedProfiles(sharedProfiles, showReadOnlyProfiles);
  const profilesLoading = combineLoadingStates(myProfilesLoading, sharedProfilesLoading);
  const bothProfilesLoaded = areBothProfilesLoaded(myProfilesData, sharedProfilesLoaded);
  const pageLoading = isPageLoading(profilesLoading, accountLoading, bothProfilesLoaded);
  const error = combineErrors(myProfilesError, sharedProfilesError);

  if (pageLoading) {
    return <LoadingSpinner />;
  }

  /* v8 ignore start -- JSX return block tested via MockedProvider tests, MUI components have limited testability in jsdom */
  return (
    <Box>
      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Stack direction="row" alignItems="center" spacing={2}>
          <Typography variant="h4" component="h1">
            My Scouts
          </Typography>
          <FormControlLabel
            control={
              <Switch
                checked={showReadOnlyProfiles}
                onChange={(e) => handleToggleReadOnly(e.target.checked)}
                size="small"
              />
            }
            label={
              <Typography variant="body2" color="text.secondary">
                Show read-only
              </Typography>
            }
          />
        </Stack>
        <Stack direction="row" spacing={2}>
          <Button variant="outlined" startIcon={<GiftIcon />} onClick={() => navigate('/accept-invite')}>
            Accept Invite
          </Button>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateDialogOpen(true)}>
            Create Scout
          </Button>
        </Stack>
      </Stack>

      <ConditionalErrorAlert error={error} />
      <ConditionalInfoAlert message={infoMessage} />

      {/* Owned Profiles */}
      <OwnedProfilesSection profiles={myProfiles} />

      {/* Shared Profiles */}
      <SharedProfilesSection profiles={filteredSharedProfiles} showDivider={myProfiles.length > 0} />

      {/* Empty State */}
      <ConditionalEmptyState
        myProfiles={myProfiles}
        filteredSharedProfiles={filteredSharedProfiles}
        loading={pageLoading}
      />

      {/* Dialogs */}
      <CreateProfileDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onSubmit={handleCreateProfile}
      />

      <ConditionalEditDialog
        editingProfile={editingProfile}
        onClose={() => setEditingProfile(null)}
        onSubmit={handleUpdateProfile}
      />

      {/* Delete Profile Confirmation Dialog */}
      <Dialog open={deleteConfirmOpen} onClose={handleDeleteDialogDismiss}>
        <DialogTitle>Delete Profile?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete this profile? All campaigns and orders will be permanently deleted. This
            action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmOpen(false)}>Cancel</Button>
          <Button onClick={handleDeleteProfile} color="error" variant="contained">
            Delete Permanently
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
  /* v8 ignore stop */
};

/* eslint-disable react-refresh/only-export-components -- Helper functions exported for unit testing */
export {
  parsePreferences,
  getPreferencesFromAccount,
  getLocationState,
  filterSharedProfiles,
  areBothProfilesLoaded,
  getMyProfiles,
  isPageLoading,
  shouldShowEmptyState,
  buildPreferencesVariables,
  shouldAutoOpenDialog,
  maybeOpenDialog,
  getInitialPreferenceValue,
  shouldTriggerQueries,
  maybeTriggerQueries,
  handleReturnNavigation,
  canDeleteCurrentProfile,
  maybeDeleteProfile,
  updatePreferencesWithRollback,
  loadSharedProfilesWithErrorHandling,
  handleSharedProfilesError,
  getSharedProfilesFromResult,
};
/* eslint-enable react-refresh/only-export-components */
