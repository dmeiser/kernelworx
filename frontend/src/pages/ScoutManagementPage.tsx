/**
 * ScoutProfileManagementPage - Scout profile-level settings and sharing
 *
 * Manages scout profile-specific functionality:
 * - Scout profile name and metadata
 * - Invite codes for sharing
 * - Share management (view who has access)
 * - Delete scout profile (with campaign cleanup)
 *
 * Separated from CampaignSettingsPage to clarify that invites are scout profile-level,
 * not campaign-level.
 */

import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@apollo/client/react';
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
} from '@mui/material';
import { Delete as DeleteIcon, ContentCopy as CopyIcon, Add as AddIcon } from '@mui/icons-material';
import {
  GET_PROFILE,
  UPDATE_SELLER_PROFILE,
  DELETE_SELLER_PROFILE,
  CREATE_PROFILE_INVITE,
  DELETE_PROFILE_INVITE,
  LIST_INVITES_BY_PROFILE,
  LIST_SHARES_BY_PROFILE,
  REVOKE_SHARE,
  TRANSFER_PROFILE_OWNERSHIP,
} from '../lib/graphql';
import { ensureProfileId } from '../lib/ids';

// Helper to get display email for a share
const getShareDisplayEmail = (share: Share): string =>
  share.targetAccount?.email || `User ${share.targetAccountId.substring(0, 8)}...`;

// Helper to get full name from target account if available
const getShareFullName = (share: Share): string | null => {
  const account = share.targetAccount;
  if (account?.givenName && account?.familyName) {
    return `${account.givenName} ${account.familyName}`;
  }
  return null;
};

// Helper to safely decode URL component
const decodeUrlParam = (encoded: string | undefined): string => (encoded ? decodeURIComponent(encoded) : '');

// Helper to determine if query should be skipped
const shouldSkipQuery = (id: string): boolean => !id;

// Helper to get profile from query data
const getProfile = (data: { getProfile: Profile } | undefined): Profile | undefined => data?.getProfile;

// Helper to get invites from query data
const getInvites = (data: { listInvitesByProfile: ProfileInvite[] } | undefined): ProfileInvite[] =>
  data?.listInvitesByProfile || [];

// Helper to get shares from query data
const getShares = (data: { listSharesByProfile: Share[] } | undefined): Share[] => data?.listSharesByProfile || [];

// Helper to get user display name for confirmation
const getUserDisplayName = (email: string | undefined, accountId: string): string =>
  email || `User ${accountId.substring(0, 8)}...`;

// Helper to validate save operation
const canSaveProfile = (profileId: string, profileName: string): boolean => Boolean(profileId && profileName.trim());

// Helper to format date string
const formatDate = (dateString: string): string => new Date(dateString).toLocaleDateString();

// Helper to check if a date has expired
const isExpired = (expiresAt: string): boolean => new Date(expiresAt) < new Date();

// Helper to copy code to clipboard
const copyToClipboard = (code: string): void => {
  navigator.clipboard.writeText(code);
};

// Helper to get button text for updating state
const getSaveButtonText = (isUpdating: boolean): string => (isUpdating ? 'Saving...' : 'Save Changes');

// Helper to get copy button text
const getCopyButtonText = (copiedCode: string | null, currentCode: string): string =>
  copiedCode === currentCode ? 'Copied!' : 'Copy';

// Helper to check if save button should be disabled
const isSaveDisabled = (updating: boolean, newName: string, originalName: string): boolean =>
  updating || newName === originalName;

// Helper to check if create invite button should be disabled
const isCreateInviteDisabled = (creating: boolean, permissions: string[]): boolean =>
  creating || permissions.length === 0;

// Helper to get create invite button text
const getCreateInviteText = (isCreating: boolean): string => (isCreating ? 'Creating...' : 'Generate New Invite');

// Helper to check if invites list is empty
const hasInvites = (invites: ProfileInvite[]): boolean => invites.length > 0;

// Helper to check if shares list is empty
const hasShares = (shares: Share[]): boolean => shares.length > 0;

// Helper to get delete invite button text
const getDeleteInviteButtonText = (isDeleting: boolean): string => (isDeleting ? 'Deleting...' : 'Delete');

// Helper to get delete profile button text
const getDeleteProfileButtonText = (isDeleting: boolean): string => (isDeleting ? 'Deleting...' : 'Delete Permanently');

// Helper to check if create invite is allowed
const canCreateInvite = (profileId: string): boolean => Boolean(profileId);

// Helper to check if delete invite is allowed
const canDeleteInvite = (deletingInviteCode: string | null, profileId: string): boolean =>
  Boolean(deletingInviteCode && profileId);

// Helper to check if delete profile is allowed
const canDeleteProfile = (profileId: string): boolean => Boolean(profileId);

// Helper to confirm revoke share action
const confirmRevokeShare = (userName: string): boolean =>
  window.confirm(`Are you sure you want to revoke access for ${userName}?`);

// Helper to confirm transfer ownership action
const confirmTransferOwnership = (userName: string): boolean =>
  window.confirm(
    `Are you sure you want to transfer ownership to ${userName}?\n\nThis action cannot be undone. You will lose ownership of this profile and all associated campaigns.`,
  );

// Helper to conditionally save profile
const maybeSaveProfile = async (
  canSave: boolean,
  setUpdating: (v: boolean) => void,
  updateProfile: (options: { variables: { profileId: string; sellerName: string } }) => Promise<unknown>,
  dbProfileId: string,
  profileName: string,
): Promise<void> => {
  if (canSave) {
    setUpdating(true);
    try {
      await updateProfile({
        variables: {
          profileId: dbProfileId,
          sellerName: profileName.trim(),
        },
      });
    } finally {
      setUpdating(false);
    }
  }
};

// Helper to conditionally create invite
const maybeCreateInvite = async (
  canCreate: boolean,
  createInvite: (options: { variables: { input: { profileId: string; permissions: string[] } } }) => Promise<unknown>,
  dbProfileId: string,
  invitePermissions: string[],
  setInvitePermissions: (v: string[]) => void,
): Promise<void> => {
  if (canCreate) {
    await createInvite({
      variables: {
        input: {
          profileId: dbProfileId,
          permissions: invitePermissions,
        },
      },
    });
    setInvitePermissions(['READ']);
  }
};

// Helper to conditionally delete invite
const maybeDeleteInvite = async (
  canDelete: boolean,
  deleteInvite: (options: { variables: { profileId: string; inviteCode: string } }) => Promise<unknown>,
  dbProfileId: string,
  deletingInviteCode: string | null,
): Promise<void> => {
  if (canDelete && deletingInviteCode) {
    await deleteInvite({
      variables: { profileId: dbProfileId, inviteCode: deletingInviteCode },
    });
  }
};

// Helper to handle revoke share with confirmation
const handleRevokeShareWithConfirmation = async (
  userName: string,
  revokeShare: (options: { variables: { input: { profileId: string; targetAccountId: string } } }) => Promise<unknown>,
  dbProfileId: string,
  targetAccountId: string,
): Promise<void> => {
  const confirmed = confirmRevokeShare(userName);
  if (confirmed) {
    try {
      await revokeShare({
        variables: {
          input: {
            profileId: dbProfileId,
            targetAccountId,
          },
        },
      });
    } catch (err) {
      console.error('Error revoking share:', err);
      alert('Failed to revoke access');
    }
  }
};

// Helper to handle transfer ownership with confirmation
const handleTransferOwnershipWithConfirmation = async (
  userName: string,
  transferOwnership: (options: {
    variables: { input: { profileId: string; newOwnerAccountId: string } };
  }) => Promise<unknown>,
  dbProfileId: string,
  targetAccountId: string,
): Promise<void> => {
  const confirmed = confirmTransferOwnership(userName);
  if (confirmed) {
    try {
      await transferOwnership({
        variables: {
          input: {
            profileId: dbProfileId,
            newOwnerAccountId: targetAccountId,
          },
        },
      });
    } catch (err) {
      console.error('Error transferring ownership:', err);
      alert('Failed to transfer ownership');
    }
  }
};

// Helper to conditionally delete profile
const maybeDeleteProfile = async (
  canDelete: boolean,
  setDeletingProfile: (v: boolean) => void,
  deleteProfile: (options: { variables: { profileId: string } }) => Promise<unknown>,
  dbProfileId: string,
): Promise<void> => {
  if (canDelete) {
    setDeletingProfile(true);
    try {
      await deleteProfile({
        variables: { profileId: dbProfileId },
      });
    } finally {
      setDeletingProfile(false);
    }
  }
};

// Helper component for invite status chip
const InviteStatusChip: React.FC<{ expiresAt: string }> = ({ expiresAt }) =>
  isExpired(expiresAt) ? (
    <Chip label="Expired" size="small" color="error" variant="outlined" />
  ) : (
    <Chip label="Active" size="small" color="success" variant="outlined" />
  );

// Helper to check if new invite code should be shown
const hasNewInviteCode = (code: string | null): boolean => Boolean(code);

// Helper component for loading state
const LoadingSpinner: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
    <CircularProgress />
  </Box>
);

// Helper component for profile not found error
const ProfileNotFoundError: React.FC = () => <Alert severity="error">Profile not found</Alert>;

// Helper component for new invite code alert
const NewInviteCodeAlert: React.FC<{
  inviteCode: string | null;
  copiedCode: string | null;
  onCopy: (code: string) => void;
}> = ({ inviteCode, copiedCode, onCopy }) =>
  hasNewInviteCode(inviteCode) && inviteCode ? (
    <Alert severity="success" sx={{ mb: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="body2">
          <strong>New Invite Code:</strong> {inviteCode}
        </Typography>
        <Button size="small" startIcon={<CopyIcon />} onClick={() => onCopy(inviteCode)}>
          {getCopyButtonText(copiedCode, inviteCode)}
        </Button>
      </Stack>
    </Alert>
  ) : null;

// Helper to toggle permission in array
const togglePermission = (
  permission: string,
  checked: boolean,
  setPermissions: React.Dispatch<React.SetStateAction<string[]>>,
): void => {
  if (checked) {
    setPermissions((prev) => (prev.includes(permission) ? prev : [...prev, permission]));
  } else {
    setPermissions((prev) => prev.filter((p) => p !== permission));
  }
};

// Helper to initialize profile name from profile data
const initializeProfileName = (profile: Profile | undefined, setProfileName: (v: string) => void): void => {
  if (profile) {
    setProfileName(profile.sellerName);
  }
};

// Helper to render optional full name
const FullNameDisplay: React.FC<{ fullName: string | null }> = ({ fullName }) =>
  fullName ? (
    <Typography variant="caption" color="text.secondary" display="block">
      {fullName}
    </Typography>
  ) : null;

// Helper component for a single share row
const ShareRow: React.FC<{
  share: Share;
  onTransferOwnership: (targetAccountId: string, email: string | undefined) => void;
  onRevokeShare: (targetAccountId: string, email: string | undefined) => void;
}> = ({ share, onTransferOwnership, onRevokeShare }) => {
  const displayEmail = getShareDisplayEmail(share);
  const fullName = getShareFullName(share);
  return (
    <TableRow key={share.shareId}>
      <TableCell>
        <Typography variant="body2">{displayEmail}</Typography>
        <FullNameDisplay fullName={fullName} />
      </TableCell>
      <TableCell>
        <Chip label={share.permissions.join(', ')} size="small" variant="outlined" />
      </TableCell>
      <TableCell>{formatDate(share.createdAt)}</TableCell>
      <TableCell align="right">
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button
            size="small"
            variant="outlined"
            onClick={() => onTransferOwnership(share.targetAccountId, share.targetAccount?.email)}
            title="Transfer ownership to this user"
          >
            Transfer Ownership
          </Button>
          <IconButton
            size="small"
            color="error"
            onClick={() => onRevokeShare(share.targetAccountId, share.targetAccount?.email)}
            title="Revoke access"
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Stack>
      </TableCell>
    </TableRow>
  );
};

// Helper component for shares section (only renders if shares exist)
const SharesSection: React.FC<{
  shares: Share[];
  onTransferOwnership: (targetAccountId: string, email: string | undefined) => void;
  onRevokeShare: (targetAccountId: string, email: string | undefined) => void;
}> = ({ shares, onTransferOwnership, onRevokeShare }) =>
  hasShares(shares) ? (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Who Has Access
      </Typography>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
        Accounts with access to your profile (via share links or redeemed invites).
      </Typography>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
              <TableCell>User</TableCell>
              <TableCell>Permissions</TableCell>
              <TableCell>Shared</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {shares.map((share) => (
              <ShareRow
                key={share.shareId}
                share={share}
                onTransferOwnership={onTransferOwnership}
                onRevokeShare={onRevokeShare}
              />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  ) : null;

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
  targetAccount?: {
    email: string;
    givenName?: string;
    familyName?: string;
  };
  permissions: string[];
  createdAt: string;
  createdByAccountId: string;
}

export const ScoutManagementPage: React.FC = () => {
  const { profileId: encodedProfileId } = useParams<{
    profileId: string;
  }>();
  const profileId = decodeUrlParam(encodedProfileId);
  const dbProfileId = ensureProfileId(profileId);
  const navigate = useNavigate();

  const [profileName, setProfileName] = useState('');
  const [updating, setUpdating] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deletingProfile, setDeletingProfile] = useState(false);
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [invitePermissions, setInvitePermissions] = useState<string[]>(['READ']);
  const [deleteInviteConfirmOpen, setDeleteInviteConfirmOpen] = useState(false);
  const [deletingInviteCode, setDeletingInviteCode] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  /* v8 ignore start -- Dialog backdrop click handlers cannot be simulated in jsdom */
  const handleInviteDialogDismiss = () => {
    setDeleteInviteConfirmOpen(false);
    setDeletingInviteCode(null);
  };
  const handleDeleteDialogDismiss = () => setDeleteConfirmOpen(false);
  /* v8 ignore stop */

  // Fetch profile
  const {
    data: profileData,
    loading,
    refetch,
  } = useQuery<{
    getProfile: Profile;
  }>(GET_PROFILE, {
    variables: { profileId: dbProfileId! },
    skip: shouldSkipQuery(dbProfileId!),
  });

  // Fetch invites
  const { data: invitesData, refetch: refetchInvites } = useQuery<{
    listInvitesByProfile: ProfileInvite[];
  }>(LIST_INVITES_BY_PROFILE, {
    variables: { profileId: dbProfileId! },
    skip: shouldSkipQuery(dbProfileId!),
  });

  // Fetch shares (accounts with access to this profile)
  const { data: sharesData } = useQuery<{
    listSharesByProfile: Share[];
  }>(LIST_SHARES_BY_PROFILE, {
    variables: { profileId: dbProfileId! },
    skip: shouldSkipQuery(dbProfileId!),
  });

  // Initialize form when profile loads
  React.useEffect(() => {
    const p = getProfile(profileData);
    initializeProfileName(p, setProfileName);
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
      navigate('/scouts');
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
  const [deleteInvite, { loading: deletingInvite }] = useMutation(DELETE_PROFILE_INVITE, {
    onCompleted: () => {
      setDeleteInviteConfirmOpen(false);
      setDeletingInviteCode(null);
      refetchInvites();
    },
  });

  // Revoke share
  const [revokeShare] = useMutation(REVOKE_SHARE, {
    refetchQueries: [{ query: LIST_SHARES_BY_PROFILE, variables: { profileId: dbProfileId } }],
  });

  // Transfer ownership
  const [transferOwnership] = useMutation(TRANSFER_PROFILE_OWNERSHIP, {
    refetchQueries: [{ query: GET_PROFILE, variables: { profileId: dbProfileId } }],
    onCompleted: () => {
      navigate('/scouts');
    },
  });

  const profile = getProfile(profileData);
  const invites = getInvites(invitesData);
  const shares = getShares(sharesData);

  const handleSaveChanges = async () => {
    const canSave = canSaveProfile(profileId, profileName);
    if (!dbProfileId) return;
    await maybeSaveProfile(canSave, setUpdating, updateProfile, dbProfileId, profileName);
  };

  const handleCreateInvite = async () => {
    const canCreate = canCreateInvite(profileId);
    if (!dbProfileId) return;
    await maybeCreateInvite(canCreate, createInvite, dbProfileId, invitePermissions, setInvitePermissions);
  };

  const handleDeleteInvite = async () => {
    const canDelete = canDeleteInvite(deletingInviteCode, profileId);
    if (!dbProfileId) return;
    await maybeDeleteInvite(canDelete, deleteInvite, dbProfileId, deletingInviteCode);
  };

  /* v8 ignore start -- async handlers requiring complex GraphQL mocking and confirmation dialogs */
  const handleRevokeShare = async (targetAccountId: string, email?: string) => {
    const userName = getUserDisplayName(email, targetAccountId);
    if (!dbProfileId) return;
    await handleRevokeShareWithConfirmation(userName, revokeShare, dbProfileId, targetAccountId);
  };

  const handleTransferOwnership = async (targetAccountId: string, email?: string) => {
    const userName = getUserDisplayName(email, targetAccountId);
    if (!dbProfileId) return;
    await handleTransferOwnershipWithConfirmation(userName, transferOwnership, dbProfileId, targetAccountId);
  };
  /* v8 ignore stop */

  const handleDeleteProfile = async () => {
    const canDelete = canDeleteProfile(profileId);
    if (!dbProfileId) return;
    await maybeDeleteProfile(canDelete, setDeletingProfile, deleteProfile, dbProfileId);
  };

  const handleCopyCode = (code: string) => {
    copyToClipboard(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  if (loading) {
    return <LoadingSpinner />;
  }

  if (!profile) {
    return <ProfileNotFoundError />;
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        Scout Management: {profile.sellerName}
      </Typography>

      <Stack spacing={4}>
        {/* Profile Settings Section */}
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Scout Information
          </Typography>
          <Stack spacing={2}>
            {/* v8 ignore next 6 -- MUI TextField onChange not testable in jsdom */}
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
              disabled={isSaveDisabled(updating, profileName, profile.sellerName)}
            >
              {getSaveButtonText(updating)}
            </Button>
          </Stack>
        </Paper>

        {/* Invite Codes Section */}
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Invite Codes
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            Generate invite codes to share this profile with others. Codes expire after 14 days.
          </Typography>

          <NewInviteCodeAlert inviteCode={inviteCode} copiedCode={copiedCode} onCopy={handleCopyCode} />

          <Stack spacing={2} sx={{ mb: 2 }}>
            <Typography variant="subtitle2">Permissions for new invites:</Typography>
            <Stack direction="row" spacing={2}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={invitePermissions.includes('READ')}
                    onChange={(e) => togglePermission('READ', e.target.checked, setInvitePermissions)}
                  />
                }
                label="Read (view campaigns and orders)"
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={invitePermissions.includes('WRITE')}
                    onChange={(e) => togglePermission('WRITE', e.target.checked, setInvitePermissions)}
                  />
                }
                label="Write (edit campaigns and orders)"
              />
            </Stack>
          </Stack>

          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={handleCreateInvite}
            disabled={isCreateInviteDisabled(creatingInvite, invitePermissions)}
            sx={{ mb: 2 }}
          >
            {getCreateInviteText(creatingInvite)}
          </Button>

          {hasInvites(invites) ? (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
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
                          <IconButton size="small" onClick={() => handleCopyCode(invite.inviteCode)}>
                            <CopyIcon fontSize="small" />
                          </IconButton>
                        </Stack>
                      </TableCell>
                      <TableCell>
                        <Chip label={invite.permissions.join(', ')} size="small" variant="outlined" />
                      </TableCell>
                      <TableCell>{formatDate(invite.createdAt)}</TableCell>
                      <TableCell>{formatDate(invite.expiresAt)}</TableCell>
                      <TableCell>
                        <InviteStatusChip expiresAt={invite.expiresAt} />
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
        <SharesSection
          shares={shares}
          onTransferOwnership={handleTransferOwnership}
          onRevokeShare={handleRevokeShare}
        />

        {/* Delete Profile Section */}
        <Paper sx={{ p: 3, backgroundColor: '#fff3cd' }}>
          <Typography variant="h6" gutterBottom color="error">
            Danger Zone
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            Permanently delete this scout and all associated campaigns and orders. This action cannot be undone.
          </Typography>
          <Button variant="contained" color="error" onClick={() => setDeleteConfirmOpen(true)}>
            Delete Scout
          </Button>
        </Paper>
      </Stack>

      {/* Delete Invite Confirmation Dialog */}
      <Dialog open={deleteInviteConfirmOpen} onClose={handleInviteDialogDismiss}>
        <DialogTitle>Delete Invite Code?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete invite code <strong>{deletingInviteCode}</strong>? This action cannot be
            undone.
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
          <Button onClick={handleDeleteInvite} color="error" variant="contained" disabled={deletingInvite}>
            {getDeleteInviteButtonText(deletingInvite)}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Profile Confirmation Dialog */}
      <Dialog open={deleteConfirmOpen} onClose={handleDeleteDialogDismiss}>
        <DialogTitle>Delete Seller Profile?</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete seller profile <strong>{profile.sellerName}</strong>?
          </Typography>
          <Typography variant="body2" color="error" sx={{ mt: 2 }}>
            This will permanently delete:
          </Typography>
          <ul>
            <li>The scout and all metadata</li>
            <li>All campaigns and associated data</li>
            <li>All orders and order items</li>
            <li>All active invite codes and shares</li>
          </ul>
          <Typography variant="body2" color="error">
            This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirmOpen(false)} disabled={deletingProfile}>
            Cancel
          </Button>
          <Button onClick={handleDeleteProfile} color="error" variant="contained" disabled={deletingProfile}>
            {getDeleteProfileButtonText(deletingProfile)}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
