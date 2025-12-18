/**
 * Profiles page - List of owned and shared seller profiles
 */

import React, { useState } from "react";
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
} from "../lib/graphql";

interface Profile {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
}

interface EditingProfile {
  profileId: string;
  sellerName: string;
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

  const handleCreateProfile = async (sellerName: string) => {
    await createProfile({ variables: { sellerName } });
  };

  const handleUpdateProfile = async (profileId: string, sellerName: string) => {
    await updateProfile({ variables: { profileId, sellerName } });
  };

  const handleDeleteProfile = async () => {
    if (!deletingProfileId) return;
    await deleteProfile({ variables: { profileId: deletingProfileId } });
  };

  const myProfiles: Profile[] = myProfilesData?.listMyProfiles || [];
  const sharedProfiles: Profile[] =
    sharedProfilesData?.listSharedProfiles || [];

  const loading = myProfilesLoading || sharedProfilesLoading;
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
        <Typography variant="h4" component="h1">
          My Seller Profiles
        </Typography>
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
