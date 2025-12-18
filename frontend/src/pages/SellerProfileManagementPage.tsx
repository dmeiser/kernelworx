/**
 * SellerProfileManagementPage - Seller profile-level settings and sharing
 *
 * Manages seller profile-specific functionality:
 * - Seller profile name and metadata
 * - Invite codes for sharing
 * - Share management (view who has access)
 * - Delete seller profile (with season cleanup)
 *
 * Separated from SeasonSettingsPage to clarify that invites are seller profile-level,
 * not season-level.
 */

import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@apollo/client/react";
import {
  Box,
  Typography,
  Paper,
  Stack,
  TextField,
  Button,
  Alert,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Checkbox,
  FormControlLabel,
} from "@mui/material";
import {
  Delete as DeleteIcon,
  ContentCopy as CopyIcon,
  Add as AddIcon,
  Close as CloseIcon,
} from "@mui/icons-material";
import {
  GET_PROFILE,
  UPDATE_SELLER_PROFILE,
  DELETE_SELLER_PROFILE,
  CREATE_PROFILE_INVITE,
  DELETE_PROFILE_INVITE,
  LIST_INVITES_BY_PROFILE,
  LIST_SHARES_BY_PROFILE,
} from "../lib/graphql";

interface Profile {
  profileId: string;
  accountId: string;
  sellerName: string;
  email?: string;
  phone?: string;
  createdAt: string;
}

interface ProfileInvite {
  inviteCode: string;
  profileId: string;
  permissions: string[];
  expiresAt: string;
  createdAt: string;
  createdByAccountId: string;
}

interface Share {
  shareId: string;
  profileId: string;
  targetAccountId: string;
  permissions: string[];
  createdAt: string;
  createdByAccountId: string;
}

export const SellerProfileManagementPage: React.FC = () => {
  const { profileId: encodedProfileId } = useParams<{
    profileId: string;
  }>();
  const profileId = encodedProfileId
    ? decodeURIComponent(encodedProfileId)
    : "";
  const navigate = useNavigate();

  const [profileName, setProfileName] = useState("");
  const [updating, setUpdating] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deletingProfile, setDeletingProfile] = useState(false);
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [invitePermissions, setInvitePermissions] = useState<string[]>([
    "READ",
  ]);
  const [deleteInviteConfirmOpen, setDeleteInviteConfirmOpen] = useState(false);
  const [deletingInviteCode, setDeletingInviteCode] = useState<string | null>(
    null,
  );
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  // Fetch profile
  const {
    data: profileData,
    loading,
    refetch,
  } = useQuery<{
    getProfile: Profile;
  }>(GET_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  // Fetch invites
  const { data: invitesData, refetch: refetchInvites } = useQuery<{
    listInvitesByProfile: ProfileInvite[];
  }>(LIST_INVITES_BY_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  // Fetch shares (accounts with access to this profile)
  const { data: sharesData, refetch: refetchShares } = useQuery<{
    listSharesByProfile: Share[];
  }>(LIST_SHARES_BY_PROFILE, {
    variables: { profileId },
    skip: !profileId,
  });

  // Initialize form when profile loads
  React.useEffect(() => {
    if (profileData?.getProfile) {
      setProfileName(profileData.getProfile.sellerName);
    }
  }, [profileData]);

  // Update profile mutation
  const [updateProfile] = useMutation(UPDATE_SELLER_PROFILE, {
    onCompleted: () => {
      refetch();
    },
  });

  // Delete profile mutation
  const [deleteProfile] = useMutation(DELETE_SELLER_PROFILE, {
    onCompleted: () => {
      navigate("/profiles");
    },
  });

  // Create profile invite
  const [createInvite, { loading: creatingInvite }] = useMutation<{
    createProfileInvite: { inviteCode: string };
  }>(CREATE_PROFILE_INVITE, {
    onCompleted: (data) => {
      setInviteCode(data.createProfileInvite.inviteCode);
      refetchInvites();
    },
  });

  // Delete profile invite
  const [deleteInvite, { loading: deletingInvite }] = useMutation(
    DELETE_PROFILE_INVITE,
    {
      onCompleted: () => {
        setDeleteInviteConfirmOpen(false);
        setDeletingInviteCode(null);
        refetchInvites();
      },
    },
  );

  const profile = profileData?.getProfile;
  const invites = invitesData?.listInvitesByProfile || [];
  const shares = sharesData?.listSharesByProfile || [];

  const handleSaveChanges = async () => {
    if (!profileId || !profileName.trim()) return;

    setUpdating(true);
    try {
      await updateProfile({
        variables: {
          profileId,
          sellerName: profileName.trim(),
        },
      });
    } finally {
      setUpdating(false);
    }
  };

  const handleCreateInvite = async () => {
    if (!profileId) return;
    await createInvite({
      variables: {
        input: {
          profileId,
          permissions: invitePermissions,
        },
      },
    });
    setInvitePermissions(["READ"]); // Reset to default after creation
  };

  const handleDeleteInvite = async () => {
    if (!deletingInviteCode || !profileId) return;
    await deleteInvite({
      variables: { profileId, inviteCode: deletingInviteCode },
    });
  };

  const handleDeleteProfile = async () => {
    if (!profileId) return;
    setDeletingProfile(true);
    try {
      await deleteProfile({
        variables: { profileId },
      });
    } finally {
      setDeletingProfile(false);
    }
  };

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString();
  };

  const isExpired = (expiresAt: string) => {
    return new Date(expiresAt) < new Date();
  };

  if (loading) {
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

  if (!profile) {
    return <Alert severity="error">Profile not found</Alert>;
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        Seller Profile Management: {profile.sellerName}
      </Typography>

      <Stack spacing={4}>
        {/* Profile Settings Section */}
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Seller Profile Information
          </Typography>
          <Stack spacing={2}>
            <TextField
              fullWidth
              label="Seller Name"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              disabled={updating}
            />
            <Button
              variant="contained"
              onClick={handleSaveChanges}
              disabled={updating || profileName === profile.sellerName}
            >
              {updating ? "Saving..." : "Save Changes"}
            </Button>
          </Stack>
        </Paper>

        {/* Invite Codes Section */}
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Invite Codes
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            Generate invite codes to share this profile with others. Codes
            expire after 14 days.
          </Typography>

          {inviteCode && (
            <Alert severity="success" sx={{ mb: 2 }}>
              <Stack direction="row" spacing={2} alignItems="center">
                <Typography variant="body2">
                  <strong>New Invite Code:</strong> {inviteCode}
                </Typography>
                <Button
                  size="small"
                  startIcon={<CopyIcon />}
                  onClick={() => handleCopyCode(inviteCode)}
                >
                  {copiedCode === inviteCode ? "Copied!" : "Copy"}
                </Button>
              </Stack>
            </Alert>
          )}

          <Stack spacing={2} sx={{ mb: 2 }}>
            <Typography variant="subtitle2">
              Permissions for new invites:
            </Typography>
            <Stack direction="row" spacing={2}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={invitePermissions.includes("READ")}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setInvitePermissions((prev) =>
                          prev.includes("READ") ? prev : [...prev, "READ"],
                        );
                      } else {
                        setInvitePermissions((prev) =>
                          prev.filter((p) => p !== "READ"),
                        );
                      }
                    }}
                  />
                }
                label="Read (view seasons and orders)"
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={invitePermissions.includes("WRITE")}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setInvitePermissions((prev) =>
                          prev.includes("WRITE") ? prev : [...prev, "WRITE"],
                        );
                      } else {
                        setInvitePermissions((prev) =>
                          prev.filter((p) => p !== "WRITE"),
                        );
                      }
                    }}
                  />
                }
                label="Write (edit seasons and orders)"
              />
            </Stack>
          </Stack>

          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={handleCreateInvite}
            disabled={creatingInvite || invitePermissions.length === 0}
            sx={{ mb: 2 }}
          >
            {creatingInvite ? "Creating..." : "Generate New Invite"}
          </Button>

          {invites.length > 0 ? (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ backgroundColor: "#f5f5f5" }}>
                    <TableCell>Invite Code</TableCell>
                    <TableCell>Permissions</TableCell>
                    <TableCell>Created</TableCell>
                    <TableCell>Expires</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {invites.map((invite) => (
                    <TableRow key={invite.inviteCode}>
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="body2" fontFamily="monospace">
                            {invite.inviteCode}
                          </Typography>
                          <IconButton
                            size="small"
                            onClick={() => handleCopyCode(invite.inviteCode)}
                          >
                            <CopyIcon fontSize="small" />
                          </IconButton>
                        </Stack>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={invite.permissions.join(", ")}
                          size="small"
                          variant="outlined"
                        />
                      </TableCell>
                      <TableCell>{formatDate(invite.createdAt)}</TableCell>
                      <TableCell>{formatDate(invite.expiresAt)}</TableCell>
                      <TableCell>
                        {isExpired(invite.expiresAt) ? (
                          <Chip
                            label="Expired"
                            size="small"
                            color="error"
                            variant="outlined"
                          />
                        ) : (
                          <Chip
                            label="Active"
                            size="small"
                            color="success"
                            variant="outlined"
                          />
                        )}
                      </TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => {
                            setDeletingInviteCode(invite.inviteCode);
                            setDeleteInviteConfirmOpen(true);
                          }}
                          disabled={deletingInvite}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Typography variant="body2" color="textSecondary">
              No active invites. Create one to share your profile.
            </Typography>
          )}
        </Paper>

        {/* Shares Section */}
        {shares.length > 0 && (
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Who Has Access
            </Typography>
            <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
              Accounts with access to your profile (via share links or redeemed
              invites).
            </Typography>

            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ backgroundColor: "#f5f5f5" }}>
                    <TableCell>User</TableCell>
                    <TableCell>Permissions</TableCell>
                    <TableCell>Shared</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {shares.map((share) => (
                    <TableRow key={share.shareId}>
                      <TableCell>
                        <Typography 
                          variant="body2" 
                          fontFamily="monospace"
                          title={`Account ID: ${share.targetAccountId}`}
                          sx={{ cursor: "help" }}
                        >
                          User {share.targetAccountId.substring(0, 8)}...
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={share.permissions.join(", ")}
                          size="small"
                          variant="outlined"
                        />
                      </TableCell>
                      <TableCell>{formatDate(share.createdAt)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        )}

        {/* Delete Profile Section */}
        <Paper sx={{ p: 3, backgroundColor: "#fff3cd" }}>
          <Typography variant="h6" gutterBottom color="error">
            Danger Zone
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            Permanently delete this seller profile and all associated seasons
            and orders. This action cannot be undone.
          </Typography>
          <Button
            variant="contained"
            color="error"
            onClick={() => setDeleteConfirmOpen(true)}
          >
            Delete Seller Profile
          </Button>
        </Paper>
      </Stack>

      {/* Delete Invite Confirmation Dialog */}
      <Dialog
        open={deleteInviteConfirmOpen}
        onClose={() => {
          setDeleteInviteConfirmOpen(false);
          setDeletingInviteCode(null);
        }}
      >
        <DialogTitle>Delete Invite Code?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete invite code{" "}
            <strong>{deletingInviteCode}</strong>? This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setDeleteInviteConfirmOpen(false);
              setDeletingInviteCode(null);
            }}
            disabled={deletingInvite}
          >
            Cancel
          </Button>
          <Button
            onClick={handleDeleteInvite}
            color="error"
            variant="contained"
            disabled={deletingInvite}
          >
            {deletingInvite ? "Deleting..." : "Delete"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Profile Confirmation Dialog */}
      <Dialog
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
      >
        <DialogTitle>Delete Seller Profile?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete seller profile{" "}
            <strong>{profile.sellerName}</strong>?
          </Typography>
          <Typography variant="body2" color="error" sx={{ mt: 2 }}>
            This will permanently delete:
          </Typography>
          <ul>
            <li>The seller profile and all metadata</li>
            <li>All seasons and associated data</li>
            <li>All orders and order items</li>
            <li>All active invite codes and shares</li>
          </ul>
          <Typography variant="body2" color="error">
            This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setDeleteConfirmOpen(false)}
            disabled={deletingProfile}
          >
            Cancel
          </Button>
          <Button
            onClick={handleDeleteProfile}
            color="error"
            variant="contained"
            disabled={deletingProfile}
          >
            {deletingProfile ? "Deleting..." : "Delete Permanently"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
