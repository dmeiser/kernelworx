/**
 * User Settings Page
 *
 * Allows users to:
 * - View and edit account information
 * - Change password
 * - Set up multi-factor authentication (TOTP)
 * - Register and manage passkeys (WebAuthn)
 */

import { useEffect } from "react";
import { useQuery, useMutation } from "@apollo/client/react";
import {
  Box,
  Typography,
  Stack,
  Alert,
  CircularProgress,
  IconButton,
} from "@mui/material";
import { ArrowBack as BackIcon } from "@mui/icons-material";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { GET_MY_ACCOUNT, UPDATE_MY_ACCOUNT } from "../lib/graphql";
import {
  usePasswordChange,
  useMfa,
  usePasskeys,
  useEmailUpdate,
  useProfileEdit,
} from "../hooks";
import {
  PasswordSection,
  MfaSection,
  PasskeySection,
  AccountInfoSection,
  EditProfileDialog,
  ChangeEmailDialog,
} from "../components/settings";

interface Account {
  accountId: string;
  email: string;
  givenName?: string;
  familyName?: string;
  city?: string;
  state?: string;
  unitType?: string;
  unitNumber?: string;
  isAdmin: boolean;
  createdAt: string;
  updatedAt: string;
}

export const UserSettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const { logout, account: authAccount } = useAuth();

  // Custom hooks for feature-specific state and handlers
  const passwordHook = usePasswordChange();
  const mfaHook = useMfa();
  const passkeyHook = usePasskeys();
  const emailHook = useEmailUpdate();
  const profileHook = useProfileEdit();

  // Account query and mutation
  const {
    data: accountData,
    loading: accountLoading,
    error: accountError,
    refetch,
  } = useQuery<{ getMyAccount: Account }>(GET_MY_ACCOUNT);

  const [updateMyAccount, { loading: updating }] = useMutation(
    UPDATE_MY_ACCOUNT,
    {
      onCompleted: () => {
        profileHook.setUpdateSuccess(true);
        profileHook.setUpdateError(null);
        profileHook.setEditDialogOpen(false);
        refetch();
        setTimeout(() => profileHook.setUpdateSuccess(false), 3000);
      },
      onError: (err) => {
        profileHook.setUpdateError(err.message);
        profileHook.setUpdateSuccess(false);
      },
    },
  );

  // Merge GraphQL account data with AuthContext account (which has isAdmin from JWT token)
  const account = authAccount
    ? {
        ...accountData?.getMyAccount,
        isAdmin: authAccount.isAdmin, // Always use isAdmin from JWT token, not GraphQL
      }
    : accountData?.getMyAccount;

  // Load MFA and passkey status on mount
  useEffect(() => {
    mfaHook.checkMfaStatus();
    passkeyHook.loadPasskeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Specific functions are stable via useCallback
  }, [mfaHook.checkMfaStatus, passkeyHook.loadPasskeys]);

  // Wrapper handlers for cross-feature interactions
  const handleSetupMFA = () =>
    mfaHook.handleSetupMFA(passkeyHook.passkeys, passkeyHook.loadPasskeys);

  const handleRegisterPasskey = () =>
    passkeyHook.handleRegisterPasskey(
      mfaHook.mfaEnabled,
      mfaHook.setMfaEnabled,
    );

  // Wrapper handlers for email hook (needs access to account email, logout, navigate)
  const handleRequestEmailUpdate = () =>
    emailHook.handleRequestEmailUpdate(account?.email);

  const handleConfirmEmailUpdate = () =>
    emailHook.handleConfirmEmailUpdate(logout, navigate);

  const handleOpenEditDialog = () => profileHook.handleOpenEditDialog(account);

  const handleSaveProfile = async () => {
    await updateMyAccount({
      variables: {
        input: {
          givenName: profileHook.givenName || null,
          familyName: profileHook.familyName || null,
          city: profileHook.city || null,
          state: profileHook.state || null,
          unitType: profileHook.unitType || null,
          unitNumber: profileHook.unitNumber
            ? parseInt(profileHook.unitNumber, 10)
            : null,
        },
      },
    });
  };

  if (accountLoading) {
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

  if (accountError) {
    return (
      <Alert severity="error">
        Failed to load account information: {accountError.message}
      </Alert>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 3 }}>
        <IconButton onClick={() => navigate("/settings")} edge="start">
          <BackIcon />
        </IconButton>
        <Typography variant="h4" component="h1">
          User Settings
        </Typography>
      </Stack>

      {profileHook.updateSuccess && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Profile updated successfully
        </Alert>
      )}

      {profileHook.updateError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to update profile: {profileHook.updateError}
        </Alert>
      )}

      {/* Account Information */}
      <AccountInfoSection
        account={account}
        onEditProfile={handleOpenEditDialog}
        onChangeEmail={emailHook.handleOpenEmailDialog}
      />

      {/* Change Password Section */}
      <PasswordSection hook={passwordHook} />

      {/* Multi-Factor Authentication Section */}
      <MfaSection
        mfaHook={mfaHook}
        passkeyCount={passkeyHook.passkeys.length}
        onSetupMFA={handleSetupMFA}
      />

      {/* Passkeys Section */}
      <PasskeySection
        passkeyHook={passkeyHook}
        mfaEnabled={mfaHook.mfaEnabled}
        onRegisterPasskey={handleRegisterPasskey}
      />

      {/* Edit Profile Dialog */}
      <EditProfileDialog
        profileHook={profileHook}
        updating={updating}
        onSave={handleSaveProfile}
      />

      {/* Change Email Dialog */}
      <ChangeEmailDialog
        emailHook={emailHook}
        currentEmail={account?.email}
        onRequestUpdate={handleRequestEmailUpdate}
        onConfirmUpdate={handleConfirmEmailUpdate}
      />
    </Box>
  );
};
