/**
 * Profiles page - List of owned and shared seller profiles
 */

import React, { useState, useEffect } from "react";
import { useQuery, useMutation } from "@apollo/client/react";
import { useNavigate } from "react-router-dom";
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
} from "@mui/material";
import { Add as AddIcon, CardGiftcard as GiftIcon } from "@mui/icons-material";
import { ProfileCard } from "../components/ProfileCard";
import { CreateProfileDialog } from "../components/CreateProfileDialog";
import { EditProfileDialog } from "../components/EditProfileDialog";
import {
  LIST_MY_PROFILES,
  LIST_SHARED_PROFILES,
  CREATE_SELLER_PROFILE,
  UPDATE_SELLER_PROFILE,
  DELETE_SELLER_PROFILE,
  GET_MY_ACCOUNT,
  UPDATE_MY_PREFERENCES,
} from "../lib/graphql";

interface Profile {
  profileId: string;
  sellerName: string;
  unitType?: string;
  unitNumber?: number;
  isOwner: boolean;
  permissions: string[];
}

interface EditingProfile {
  profileId: string;
  sellerName: string;
  unitType?: string;
  unitNumber?: number;
}

export const ProfilesPage: React.FC = () => {
  const navigate = useNavigate();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<EditingProfile | null>(
    null,
  );
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deletingProfileId, setDeletingProfileId] = useState<string | null>(
    null,
  );

  // Fetch account preferences
  const { data: accountData, loading: accountLoading } = useQuery<{
    getMyAccount: { accountId: string; preferences?: string };
  }>(GET_MY_ACCOUNT);

  // Parse preferences from account data
  const preferences = React.useMemo(() => {
    if (!accountData?.getMyAccount) {
      return { showReadOnlyProfiles: true };
    }
    try {
      const prefs = accountData.getMyAccount.preferences;
      if (!prefs || prefs === "") {
        return { showReadOnlyProfiles: true };
      }
      return JSON.parse(prefs);
    } catch (error) {
      console.warn("Failed to parse preferences:", error);
      return { showReadOnlyProfiles: true };
    }
  }, [accountData]);

  // Show read-only profiles preference
  const [showReadOnlyProfiles, setShowReadOnlyProfiles] = useState(true);

  // Update local state when preferences load
  useEffect(() => {
    setShowReadOnlyProfiles(preferences.showReadOnlyProfiles ?? true);
  }, [preferences]);

  // Update preferences mutation
  const [updatePreferences] = useMutation(UPDATE_MY_PREFERENCES);

  // Save preference to DynamoDB when it changes
  const handleToggleReadOnly = async (checked: boolean) => {
    setShowReadOnlyProfiles(checked);
    try {
      await updatePreferences({
        variables: {
          preferences: JSON.stringify({
            ...preferences,
            showReadOnlyProfiles: checked,
          }),
        },
      });
    } catch (error) {
      console.error("Failed to update preferences:", error);
      // Revert on error
      setShowReadOnlyProfiles(!checked);
    }
  };

  // Fetch owned profiles
  const {
    data: myProfilesData,
    loading: myProfilesLoading,
    error: myProfilesError,
    refetch: refetchMyProfiles,
  } = useQuery<{ listMyProfiles: Profile[] }>(LIST_MY_PROFILES);

  // Fetch shared profiles
  const {
    data: sharedProfilesData,
    loading: sharedProfilesLoading,
    error: sharedProfilesError,
    refetch: refetchSharedProfiles,
  } = useQuery<{ listSharedProfiles: Profile[] }>(LIST_SHARED_PROFILES);

  // Create profile mutation
  const [createProfile] = useMutation(CREATE_SELLER_PROFILE, {
    onCompleted: () => {
      refetchMyProfiles();
    },
  });

  // Update profile mutation
  const [updateProfile] = useMutation(UPDATE_SELLER_PROFILE, {
    onCompleted: () => {
      refetchMyProfiles();
      refetchSharedProfiles();
    },
  });

  // Delete profile mutation
  const [deleteProfile] = useMutation(DELETE_SELLER_PROFILE, {
    onCompleted: () => {
      setDeleteConfirmOpen(false);
      setDeletingProfileId(null);
      refetchMyProfiles();
    },
  });

  const handleCreateProfile = async (
    sellerName: string,
    unitType?: string,
    unitNumber?: number,
  ) => {
    await createProfile({ variables: { sellerName, unitType, unitNumber } });
  };

  const handleUpdateProfile = async (
    profileId: string,
    sellerName: string,
    unitType?: string,
    unitNumber?: number,
  ) => {
    await updateProfile({
      variables: { profileId, sellerName, unitType, unitNumber },
    });
  };

  const handleDeleteProfile = async () => {
    if (!deletingProfileId) return;
    await deleteProfile({ variables: { profileId: deletingProfileId } });
  };

  const myProfiles: Profile[] = myProfilesData?.listMyProfiles || [];
  const allSharedProfiles: Profile[] =
    sharedProfilesData?.listSharedProfiles || [];
  
  // Debug logging for intermittent shared profile loading issues
  console.log("ProfilesPage shared profiles debug:", {
    sharedProfilesLoading,
    sharedProfilesError: sharedProfilesError?.message,
    graphQLErrors: sharedProfilesError?.graphQLErrors?.map(e => ({
      message: e.message,
      path: e.path,
      extensions: e.extensions
    })),
    networkError: sharedProfilesError?.networkError,
    sharedProfilesData,
    allSharedProfilesCount: allSharedProfiles.length,
    showReadOnlyProfiles,
  });
  
  const sharedProfiles = allSharedProfiles.filter(
    (profile) => {
      const hasWrite = profile.permissions.includes("WRITE");
      // When showReadOnlyProfiles is true: show all profiles
      // When showReadOnlyProfiles is false: show only profiles with WRITE permission
      const included = showReadOnlyProfiles || hasWrite;
      console.log(`Profile "${profile.sellerName}": permissions=${JSON.stringify(profile.permissions)}, hasWrite=${hasWrite}, showReadOnly=${showReadOnlyProfiles}, included=${included}`);
      return included;
    }
  );

  const loading = myProfilesLoading || sharedProfilesLoading || accountLoading;
  const error = myProfilesError || sharedProfilesError;

  if (loading && myProfiles.length === 0 && sharedProfiles.length === 0) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="400px"
      >
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {/* Header */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        mb={3}
      >
        <Stack direction="row" alignItems="center" spacing={2}>
          <Typography variant="h4" component="h1">
            My Seller Profiles
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
          <Button
            variant="outlined"
            startIcon={<GiftIcon />}
            onClick={() => navigate("/accept-invite")}
          >
            Accept Invite
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => setCreateDialogOpen(true)}
          >
            Create Seller
          </Button>
        </Stack>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          Failed to load profiles: {error.message}
        </Alert>
      )}

      {/* Owned Profiles */}
      {myProfiles.length > 0 && (
        <Box mb={4}>
          <Typography variant="h6" gutterBottom>
            Seller Profiles I Own
          </Typography>
          <Grid container spacing={2}>
            {myProfiles.map((profile) => (
              <Grid key={profile.profileId} size={{ xs: 12, sm: 6, md: 4 }}>
                <ProfileCard
                  profileId={profile.profileId}
                  sellerName={profile.sellerName}
                  unitType={profile.unitType}
                  unitNumber={profile.unitNumber}
                  isOwner={profile.isOwner}
                  permissions={profile.permissions}
                />
              </Grid>
            ))}
          </Grid>
        </Box>
      )}

      {/* Shared Profiles */}
      {sharedProfiles.length > 0 && (
        <Box>
          {myProfiles.length > 0 && <Divider sx={{ my: 4 }} />}
          <Typography variant="h6" gutterBottom>
            Seller Profiles Shared With Me
          </Typography>
          <Grid container spacing={2}>
            {sharedProfiles.map((profile) => (
              <Grid key={profile.profileId} size={{ xs: 12, sm: 6, md: 4 }}>
                <ProfileCard
                  profileId={profile.profileId}
                  sellerName={profile.sellerName}
                  unitType={profile.unitType}
                  unitNumber={profile.unitNumber}
                  isOwner={profile.isOwner}
                  permissions={profile.permissions}
                />
              </Grid>
            ))}
          </Grid>
        </Box>
      )}

      {/* Empty State */}
      {myProfiles.length === 0 && sharedProfiles.length === 0 && !loading && (
        <Alert severity="info">
          You don't have any seller profiles yet. Click "Create Seller" to get
          started!
        </Alert>
      )}

      {/* Dialogs */}
      <CreateProfileDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onSubmit={handleCreateProfile}
      />

      {editingProfile && (
        <EditProfileDialog
          open={true}
          profileId={editingProfile.profileId}
          currentName={editingProfile.sellerName}
          currentUnitType={editingProfile.unitType}
          currentUnitNumber={editingProfile.unitNumber}
          onClose={() => setEditingProfile(null)}
          onSubmit={handleUpdateProfile}
        />
      )}

      {/* Delete Profile Confirmation Dialog */}
      <Dialog
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
      >
        <DialogTitle>Delete Profile?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete this profile? All seasons and orders
            will be permanently deleted. This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmOpen(false)}>Cancel</Button>
          <Button
            onClick={handleDeleteProfile}
            color="error"
            variant="contained"
          >
            Delete Permanently
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
