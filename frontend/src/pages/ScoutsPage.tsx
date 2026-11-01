/**
 * Scouts page - List of owned and shared scout profiles
 */

import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useLazyQuery, useMutation, useApolloClient } from '@apollo/client/react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Typography, Box, Button, Grid, Alert, Stack, Divider, FormControlLabel, Switch } from '@mui/material';
import { Add as AddIcon, CardGiftcard as GiftIcon } from '@mui/icons-material';
import { ProfileCard } from '../components/ProfileCard';
import { CreateProfileDialog } from '../components/CreateProfileDialog';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import {
  LIST_MY_PROFILES,
  LIST_MY_SHARES,
  CREATE_SELLER_PROFILE,
  GET_MY_ACCOUNT,
  UPDATE_MY_PREFERENCES,
} from '../lib/graphql';
import { fetchAllMyProfiles, type MyProfile } from '../lib/myProfiles';

// Use the listMyProfiles page item as the Profile type for this page
type Profile = MyProfile;

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
  myProfilesData: { listMyProfiles: { profiles: Profile[] } } | undefined,
  sharedProfilesLoaded: boolean,
): boolean => myProfilesData !== undefined && sharedProfilesLoaded;

// Helper to get my profiles from data
const getMyProfiles = (data: { listMyProfiles: { profiles: Profile[] } } | undefined): Profile[] =>
  data?.listMyProfiles.profiles || [];

// Helper to check if page is still loading
const isPageLoading = (profilesLoading: boolean, accountLoading: boolean, bothProfilesLoaded: boolean): boolean =>
  profilesLoading || accountLoading || !bothProfilesLoaded;

// Info message alert component
const InfoMessageAlert: React.FC<{ message: string }> = ({ message }) => (
  <Alert severity="info" sx={{ mb: 3 }}>
    {message}
  </Alert>
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
              latestCampaign={profile.latestCampaign ?? undefined}
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
              latestCampaign={profile.latestCampaign ?? undefined}
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
  loadAccount: () => Promise<unknown>,
  loadMyProfiles: () => Promise<unknown>,
  loadSharedProfiles: () => Promise<unknown>,
): void => {
  if (shouldTrigger) {
    queriesTriggeredRef.current = true;
    void loadAccount();
    void loadMyProfiles();
    void loadSharedProfiles();
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
      void navigate(returnPath, {
        replace: true,
        state: { fromProfileCreation: true },
      });
    }, 1500);
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
    if (import.meta.env.DEV) {
      console.error('Failed to update preferences:', error);
    }
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
    if (import.meta.env.DEV) {
      console.error('Failed to load shared profiles:', err);
    }
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
  error ? <ErrorAlert message={`Failed to load profiles: ${error.message}`} /> : null;

// Helper component for conditional info message
const ConditionalInfoAlert: React.FC<{ message: string | undefined }> = ({ message }) =>
  message ? <InfoMessageAlert message={message} /> : null;

// Helper component for conditional empty state
const ConditionalEmptyState: React.FC<{
  myProfiles: Profile[];
  filteredSharedProfiles: Profile[];
  loading: boolean;
}> = ({ myProfiles, filteredSharedProfiles, loading }) =>
  shouldShowEmptyState(myProfiles, filteredSharedProfiles, loading) ? (
    <EmptyState title="No Scouts Yet" message='Click "Create Scout" to add your first seller profile.' />
  ) : null;

export const ScoutsPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, loading: authLoading } = useAuth();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

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
    fetchPolicy: 'cache-first',
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

  // Fetch owned profiles. listMyProfiles is server-side paginated (capped
  // pages, #328), so walk every nextToken page to get the full set.
  const apolloClient = useApolloClient();
  const [myProfiles, setMyProfiles] = useState<Profile[]>([]);
  const [myProfilesLoaded, setMyProfilesLoaded] = useState(false);
  const [myProfilesLoading, setMyProfilesLoading] = useState(false);
  const [myProfilesError, setMyProfilesError] = useState<Error | null>(null);

  const loadMyProfiles = React.useCallback(async () => {
    setMyProfilesLoading(true);
    try {
      setMyProfiles(await fetchAllMyProfiles(apolloClient));
      setMyProfilesLoaded(true);
      setMyProfilesError(null);
    } catch (err) {
      // Mark loaded so the page renders and surfaces the error alert instead
      // of spinning forever on the loading state.
      setMyProfilesLoaded(true);
      setMyProfilesError(err as Error);
    } finally {
      setMyProfilesLoading(false);
    }
  }, [apolloClient]);

  // Shared profiles state - we fetch shares then individual profiles
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
    onCompleted: () => {
      void loadMyProfiles()
        .then(() => {
          handleReturnNavigation(returnPath, (path, opts) => {
            void navigate(path, opts);
          });
        })
        .catch(() => {});
    },
  });

  const handleCreateProfile = async (sellerName: string) => {
    await createProfile({ variables: { sellerName } });
  };

  const myProfilesData = myProfilesLoaded ? { listMyProfiles: { profiles: myProfiles } } : undefined;
  const filteredSharedProfiles = filterSharedProfiles(sharedProfiles, showReadOnlyProfiles);
  const profilesLoading = combineLoadingStates(myProfilesLoading, sharedProfilesLoading);
  const bothProfilesLoaded = areBothProfilesLoaded(myProfilesData, sharedProfilesLoaded);
  const pageLoading = isPageLoading(profilesLoading, accountLoading, bothProfilesLoaded);
  const error = combineErrors(myProfilesError, sharedProfilesError);

  if (pageLoading) {
    return <LoadingState />;
  }

  /* v8 ignore start -- JSX return block tested via MockedProvider tests, MUI components have limited testability in jsdom */
  return (
    <Box>
      <PageHeader
        title="My Scouts"
        action={
          <Stack direction={{ xs: 'column', sm: 'row' }} alignItems="center" spacing={2}>
            <FormControlLabel
              control={
                <Switch
                  checked={showReadOnlyProfiles}
                  onChange={(e) => {
                    void handleToggleReadOnly(e.target.checked);
                  }}
                  size="small"
                />
              }
              label={
                <Typography variant="body2" color="text.secondary">
                  Show read-only
                </Typography>
              }
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} flexWrap="wrap">
              <Button
                variant="outlined"
                startIcon={<GiftIcon />}
                onClick={() => {
                  void navigate('/accept-invite');
                }}
              >
                Accept Invite
              </Button>
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateDialogOpen(true)}>
                Create Scout
              </Button>
            </Stack>
          </Stack>
        }
      />

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
  updatePreferencesWithRollback,
  loadSharedProfilesWithErrorHandling,
  handleSharedProfilesError,
  getSharedProfilesFromResult,
};
/* eslint-enable react-refresh/only-export-components */
