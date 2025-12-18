/**
 * User Settings Page
 *
 * Allows users to:
 * - View and edit account information
 * - Change password
 * - Set up multi-factor authentication (TOTP)
 * - Register and manage passkeys (WebAuthn)
 */

import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@apollo/client/react";
import {
  Box,
  Button,
  TextField,
  Typography,
  Paper,
  Stack,
  Alert,
  CircularProgress,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Chip,
} from "@mui/material";
import {
  ArrowBack as BackIcon,
  VpnKey as PasswordIcon,
  Security as SecurityIcon,
  QrCode2 as QrCodeIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckIcon,
  Fingerprint as PasskeyIcon,
  Add as AddIcon,
  Email as EmailIcon,
  Person as PersonIcon,
  Edit as EditIcon,
  AdminPanelSettings as AdminIcon,
  Info as InfoIcon,
} from "@mui/icons-material";
import { useNavigate } from "react-router-dom";
import {
  updatePassword,
  setUpTOTP,
  verifyTOTPSetup,
  updateMFAPreference,
  fetchMFAPreference,
  associateWebAuthnCredential,
  listWebAuthnCredentials,
  deleteWebAuthnCredential,
  type AuthWebAuthnCredential,
  updateUserAttribute,
  confirmUserAttribute,
} from "aws-amplify/auth";
import QRCode from "qrcode";
import { useAuth } from "../contexts/AuthContext";
import { GET_MY_ACCOUNT, UPDATE_MY_ACCOUNT } from "../lib/graphql";

interface Account {
  accountId: string;
  email: string;
  givenName?: string;
  familyName?: string;
  city?: string;
  state?: string;
  unitNumber?: string;
  isAdmin: boolean;
  createdAt: string;
  updatedAt: string;
}

export const UserSettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const { logout, account: authAccount } = useAuth();

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
        setUpdateSuccess(true);
        setUpdateError(null);
        setEditDialogOpen(false);
        refetch();
        setTimeout(() => setUpdateSuccess(false), 3000);
      },
      onError: (err) => {
        setUpdateError(err.message);
        setUpdateSuccess(false);
      },
    },
  );

  // Merge GraphQL account data with AuthContext account (which has isAdmin from JWT token)
  const account = authAccount ? {
    ...accountData?.getMyAccount,
    isAdmin: authAccount.isAdmin, // Always use isAdmin from JWT token, not GraphQL
  } : accountData?.getMyAccount;

  // Edit profile state
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [givenName, setGivenName] = useState("");
  const [familyName, setFamilyName] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [unitNumber, setUnitNumber] = useState("");
  const [updateSuccess, setUpdateSuccess] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  // Email update state
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [emailVerificationCode, setEmailVerificationCode] = useState("");
  const [emailUpdatePending, setEmailUpdatePending] = useState(false);
  const [emailUpdateLoading, setEmailUpdateLoading] = useState(false);
  const [emailUpdateError, setEmailUpdateError] = useState<string | null>(null);
  const [emailUpdateSuccess, setEmailUpdateSuccess] = useState(false);

  // Password change state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);

  // MFA state
  const [mfaSetupCode, setMfaSetupCode] = useState<string | null>(null);
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [mfaVerificationCode, setMfaVerificationCode] = useState("");
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [mfaSuccess, setMfaSuccess] = useState(false);
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaEnabled, setMfaEnabled] = useState(false);

  // Passkey state
  const [passkeys, setPasskeys] = useState<AuthWebAuthnCredential[]>([]);
  const [passkeyName, setPasskeyName] = useState("");
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const [passkeySuccess, setPasskeySuccess] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);

  // Load MFA and passkey status on mount
  useEffect(() => {
    loadMFAStatus();
    loadPasskeys();
  }, []);

  const loadMFAStatus = async () => {
    try {
      const mfaPreference = await fetchMFAPreference();
      // Check if TOTP is enabled
      setMfaEnabled(
        mfaPreference.enabled?.includes("TOTP") ||
          mfaPreference.preferred === "TOTP",
      );
    } catch (err: any) {
      console.error("Failed to load MFA status:", err);
    }
  };

  const loadPasskeys = async () => {
    try {
      const result = await listWebAuthnCredentials();
      setPasskeys(result.credentials || []);
    } catch (err: any) {
      console.error("Failed to load passkeys:", err);
      // Passkeys might not be configured yet - don't show error to user
    }
  };

  // Handle password change
  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(false);

    // Validation
    if (newPassword !== confirmPassword) {
      setPasswordError("New passwords do not match");
      return;
    }

    if (newPassword.length < 8) {
      setPasswordError("Password must be at least 8 characters");
      return;
    }

    setPasswordLoading(true);

    try {
      await updatePassword({ oldPassword: currentPassword, newPassword });
      setPasswordSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: any) {
      console.error("Password change failed:", err);
      setPasswordError(
        err.message ||
          "Failed to change password. Please check your current password.",
      );
    } finally {
      setPasswordLoading(false);
    }
  };

  // Set up MFA
  const handleSetupMFA = async () => {
    // Check if passkeys are enabled - MFA and passkeys cannot be used together
    if (passkeys.length > 0) {
      if (
        !window.confirm(
          "TOTP MFA and Passkeys cannot be used together. Do you want to delete all passkeys and enable MFA?",
        )
      ) {
        return;
      }

      // Delete all passkeys first
      try {
        for (const passkey of passkeys) {
          if (passkey.credentialId) {
            await deleteWebAuthnCredential({
              credentialId: passkey.credentialId,
            });
          }
        }
        await loadPasskeys();
      } catch (err: any) {
        setMfaError("Failed to remove passkeys: " + err.message);
        return;
      }
    }

    setMfaError(null);
    setMfaLoading(true);

    try {
      const totpSetupDetails = await setUpTOTP();
      const setupUri = totpSetupDetails.getSetupUri("PopcornManager");

      // Generate QR code
      const qrDataUrl = await QRCode.toDataURL(setupUri.href);

      setMfaSetupCode(totpSetupDetails.sharedSecret);
      setQrCodeUrl(qrDataUrl);
    } catch (err: any) {
      console.error("MFA setup failed:", err);
      setMfaError(err.message || "Failed to set up MFA");
    } finally {
      setMfaLoading(false);
    }
  };

  // Verify and enable MFA
  const handleVerifyMFA = async (e: React.FormEvent) => {
    e.preventDefault();
    setMfaError(null);
    setMfaLoading(true);

    try {
      await verifyTOTPSetup({ code: mfaVerificationCode });
      await updateMFAPreference({ totp: "PREFERRED" });

      setMfaSuccess(true);
      setMfaEnabled(true);
      setMfaSetupCode(null);
      setQrCodeUrl(null);
      setMfaVerificationCode("");
    } catch (err: any) {
      console.error("MFA verification failed:", err);
      setMfaError(
        err.message || "Invalid verification code. Please try again.",
      );
    } finally {
      setMfaLoading(false);
    }
  };

  // Disable MFA
  const handleDisableMFA = async () => {
    if (
      !window.confirm(
        "Are you sure you want to disable multi-factor authentication? This will make your account less secure.",
      )
    ) {
      return;
    }

    setMfaError(null);
    setMfaLoading(true);

    try {
      await updateMFAPreference({ totp: "DISABLED" });
      setMfaEnabled(false);
      setMfaSuccess(false);
    } catch (err: any) {
      console.error("Disable MFA failed:", err);
      setMfaError(err.message || "Failed to disable MFA");
    } finally {
      setMfaLoading(false);
    }
  };

  // Register a new passkey
  const handleRegisterPasskey = async () => {
    if (!passkeyName.trim()) {
      setPasskeyError("Please enter a name for this passkey");
      return;
    }

    // Check if MFA is enabled - passkeys and TOTP MFA cannot be used together
    if (mfaEnabled) {
      if (
        !window.confirm(
          "Passkeys and TOTP MFA cannot be used together. Do you want to disable MFA and register this passkey?",
        )
      ) {
        return;
      }

      // Disable MFA first
      try {
        await updateMFAPreference({ totp: "DISABLED" });
        setMfaEnabled(false);
      } catch (err: any) {
        setPasskeyError("Failed to disable MFA: " + err.message);
        return;
      }
    }

    setPasskeyError(null);
    setPasskeySuccess(false);
    setPasskeyLoading(true);

    try {
      await associateWebAuthnCredential();
      setPasskeySuccess(true);
      setPasskeyName("");
      await loadPasskeys(); // Reload the list
    } catch (err: any) {
      console.error("Passkey registration failed:", err);
      setPasskeyError(
        err.message ||
          "Failed to register passkey. Make sure your browser supports passkeys and you have a compatible authenticator.",
      );
    } finally {
      setPasskeyLoading(false);
    }
  };

  // Delete a passkey
  const handleDeletePasskey = async (credentialId: string) => {
    if (!window.confirm("Are you sure you want to delete this passkey?")) {
      return;
    }

    setPasskeyError(null);
    setPasskeyLoading(true);

    try {
      await deleteWebAuthnCredential({ credentialId });
      await loadPasskeys(); // Reload the list
    } catch (err: any) {
      console.error("Delete passkey failed:", err);
      setPasskeyError(err.message || "Failed to delete passkey");
    } finally {
      setPasskeyLoading(false);
    }
  };

  // Account information handlers
  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const handleOpenEditDialog = () => {
    setGivenName(account?.givenName || "");
    setFamilyName(account?.familyName || "");
    setCity(account?.city || "");
    setState(account?.state || "");
    setUnitNumber(account?.unitNumber || "");
    setEditDialogOpen(true);
  };

  const handleSaveProfile = async () => {
    await updateMyAccount({
      variables: {
        input: {
          givenName: givenName || null,
          familyName: familyName || null,
          city: city || null,
          state: state || null,
          unitNumber: unitNumber || null,
        },
      },
    });
  };

  // Email update handlers
  const handleOpenEmailDialog = () => {
    setNewEmail("");
    setEmailVerificationCode("");
    setEmailUpdatePending(false);
    setEmailUpdateError(null);
    setEmailUpdateSuccess(false);
    setEmailDialogOpen(true);
  };

  const handleCloseEmailDialog = () => {
    setEmailDialogOpen(false);
    setNewEmail("");
    setEmailVerificationCode("");
    setEmailUpdatePending(false);
    setEmailUpdateError(null);
  };

  const handleRequestEmailUpdate = async () => {
    if (!newEmail || !newEmail.includes("@")) {
      setEmailUpdateError("Please enter a valid email address");
      return;
    }

    if (newEmail.toLowerCase() === account?.email.toLowerCase()) {
      setEmailUpdateError("New email must be different from current email");
      return;
    }

    setEmailUpdateError(null);
    setEmailUpdateLoading(true);

    try {
      const output = await updateUserAttribute({
        userAttribute: {
          attributeKey: "email",
          value: newEmail,
        },
      });

      if (
        output.nextStep.updateAttributeStep === "CONFIRM_ATTRIBUTE_WITH_CODE"
      ) {
        setEmailUpdatePending(true);
        setEmailUpdateError(null);
      } else if (output.nextStep.updateAttributeStep === "DONE") {
        setEmailUpdateError(
          "Your session was created before email verification was enabled. Please sign out, sign back in, and try updating your email again to enable verification.",
        );
      } else {
        setEmailUpdateError(
          `Unexpected response: ${output.nextStep.updateAttributeStep}`,
        );
      }
    } catch (err: any) {
      setEmailUpdateError(err.message || "Failed to request email update");
    } finally {
      setEmailUpdateLoading(false);
    }
  };

  const handleConfirmEmailUpdate = async () => {
    if (!emailVerificationCode || emailVerificationCode.length !== 6) {
      setEmailUpdateError("Please enter the 6-digit verification code");
      return;
    }

    setEmailUpdateError(null);
    setEmailUpdateLoading(true);

    try {
      await confirmUserAttribute({
        userAttributeKey: "email",
        confirmationCode: emailVerificationCode,
      });

      setEmailUpdateSuccess(true);
      setEmailUpdateError(null);

      setTimeout(async () => {
        handleCloseEmailDialog();
        await logout();
        navigate("/");
      }, 3000);
    } catch (err: any) {
      setEmailUpdateError(err.message || "Invalid verification code");
    } finally {
      setEmailUpdateLoading(false);
    }
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

      {updateSuccess && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Profile updated successfully
        </Alert>
      )}

      {updateError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to update profile: {updateError}
        </Alert>
      )}

      {/* Account Information */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          mb={2}
        >
          <Typography variant="h6">Account Information</Typography>
          <Button
            variant="outlined"
            size="small"
            startIcon={<EditIcon />}
            onClick={handleOpenEditDialog}
          >
            Edit Profile
          </Button>
        </Stack>
        <List>
          <ListItem
            secondaryAction={
              <Button
                size="small"
                startIcon={<EditIcon />}
                onClick={handleOpenEmailDialog}
              >
                Change
              </Button>
            }
          >
            <ListItemIcon>
              <EmailIcon color="primary" />
            </ListItemIcon>
            <ListItemText primary="Email Address" secondary={account?.email} />
          </ListItem>
          <Divider component="li" />
          {account?.givenName && (
            <>
              <ListItem>
                <ListItemIcon>
                  <PersonIcon color="primary" />
                </ListItemIcon>
                <ListItemText
                  primary="First Name"
                  secondary={account.givenName}
                />
              </ListItem>
              <Divider component="li" />
            </>
          )}
          {account?.familyName && (
            <>
              <ListItem>
                <ListItemIcon>
                  <PersonIcon color="primary" />
                </ListItemIcon>
                <ListItemText
                  primary="Last Name"
                  secondary={account.familyName}
                />
              </ListItem>
              <Divider component="li" />
            </>
          )}
          {account?.city && (
            <>
              <ListItem>
                <ListItemIcon>
                  <PersonIcon color="primary" />
                </ListItemIcon>
                <ListItemText primary="City" secondary={account.city} />
              </ListItem>
              <Divider component="li" />
            </>
          )}
          {account?.state && (
            <>
              <ListItem>
                <ListItemIcon>
                  <PersonIcon color="primary" />
                </ListItemIcon>
                <ListItemText primary="State" secondary={account.state} />
              </ListItem>
              <Divider component="li" />
            </>
          )}
          {account?.unitNumber && (
            <>
              <ListItem>
                <ListItemIcon>
                  <PersonIcon color="primary" />
                </ListItemIcon>
                <ListItemText
                  primary="Unit/Pack/Troop Number"
                  secondary={account.unitNumber}
                />
              </ListItem>
              <Divider component="li" />
            </>
          )}
          <ListItem>
            <ListItemIcon>
              <AdminIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Account Type"
              secondary={
                <Stack
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  component="span"
                  sx={{ display: "inline-flex" }}
                >
                  <span>
                    {account?.isAdmin ? "Administrator" : "Standard User"}
                  </span>
                  {account?.isAdmin && (
                    <Chip label="Admin" color="error" size="small" />
                  )}
                </Stack>
              }
              secondaryTypographyProps={{ component: "span" }}
            />
          </ListItem>
          <Divider component="li" />
          <ListItem>
            <ListItemIcon>
              <InfoIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Account Created"
              secondary={
                account?.createdAt ? formatDate(account.createdAt) : "Unknown"
              }
            />
          </ListItem>
          <Divider component="li" />
          <ListItem>
            <ListItemIcon>
              <InfoIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Last Updated"
              secondary={
                account?.updatedAt ? formatDate(account.updatedAt) : "Unknown"
              }
            />
          </ListItem>
          <Divider component="li" />
          <ListItem>
            <ListItemIcon>
              <PersonIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Account ID"
              secondary={
                <Typography
                  variant="body2"
                  component="span"
                  sx={{
                    wordBreak: "break-all",
                    fontFamily: "monospace",
                    fontSize: "0.875rem",
                  }}
                >
                  {account?.accountId}
                </Typography>
              }
              secondaryTypographyProps={{ component: "span" }}
            />
          </ListItem>
        </List>
      </Paper>

      {/* Change Password Section */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <PasswordIcon color="primary" />
          <Typography variant="h6">Change Password</Typography>
        </Stack>

        <Typography variant="body2" color="text.secondary" paragraph>
          Update your password to keep your account secure. Use a strong
          password with at least 8 characters.
        </Typography>

        {passwordSuccess && (
          <Alert
            severity="success"
            sx={{ mb: 2 }}
            onClose={() => setPasswordSuccess(false)}
          >
            Password changed successfully!
          </Alert>
        )}

        {passwordError && (
          <Alert
            severity="error"
            sx={{ mb: 2 }}
            onClose={() => setPasswordError(null)}
          >
            {passwordError}
          </Alert>
        )}

        <form onSubmit={handlePasswordChange}>
          <Stack spacing={2}>
            <TextField
              label="Current Password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              fullWidth
              disabled={passwordLoading}
              autoComplete="current-password"
            />
            <TextField
              label="New Password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              fullWidth
              disabled={passwordLoading}
              autoComplete="new-password"
              helperText="At least 8 characters with uppercase, lowercase, numbers, and symbols"
            />
            <TextField
              label="Confirm New Password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              fullWidth
              disabled={passwordLoading}
              autoComplete="new-password"
            />
            <Button
              type="submit"
              variant="contained"
              disabled={passwordLoading}
              sx={{ alignSelf: "flex-start" }}
            >
              {passwordLoading ? (
                <CircularProgress size={24} />
              ) : (
                "Change Password"
              )}
            </Button>
          </Stack>
        </form>
      </Paper>

      {/* Multi-Factor Authentication Section */}
      <Paper sx={{ p: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <SecurityIcon color="primary" />
          <Typography variant="h6">
            Multi-Factor Authentication (MFA)
          </Typography>
        </Stack>

        <Typography variant="body2" color="text.secondary" paragraph>
          Add an extra layer of security to your account by requiring a
          verification code from your phone.
        </Typography>

        {/* Passkey Conflict Warning */}
        {passkeys.length > 0 && !mfaEnabled && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <strong>Note:</strong> You have {passkeys.length} passkey
            {passkeys.length > 1 ? "s" : ""} registered. TOTP MFA and Passkeys
            cannot be used together. Enabling MFA will delete all your passkeys.
          </Alert>
        )}

        {mfaSuccess && (
          <Alert
            severity="success"
            sx={{ mb: 2 }}
            onClose={() => setMfaSuccess(false)}
          >
            MFA has been successfully enabled!
          </Alert>
        )}

        {mfaError && (
          <Alert
            severity="error"
            sx={{ mb: 2 }}
            onClose={() => setMfaError(null)}
          >
            {mfaError}
          </Alert>
        )}

        {mfaEnabled && !mfaSetupCode && (
          <Alert severity="success" icon={<CheckIcon />} sx={{ mb: 2 }}>
            <Typography variant="body2" fontWeight={600}>
              MFA is currently enabled
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Your account is protected with multi-factor authentication
            </Typography>
          </Alert>
        )}

        {!mfaSetupCode && !mfaEnabled && (
          <Button
            variant="contained"
            startIcon={<QrCodeIcon />}
            onClick={handleSetupMFA}
            disabled={mfaLoading}
          >
            {mfaLoading ? <CircularProgress size={24} /> : "Set Up MFA"}
          </Button>
        )}

        {mfaEnabled && (
          <Button
            variant="outlined"
            color="error"
            startIcon={<DeleteIcon />}
            onClick={handleDisableMFA}
            disabled={mfaLoading}
            sx={{ mt: 2 }}
          >
            Disable MFA
          </Button>
        )}

        {/* MFA Setup Flow */}
        {mfaSetupCode && qrCodeUrl && (
          <Box sx={{ mt: 3 }}>
            <Divider sx={{ mb: 3 }} />

            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Step 1: Scan QR Code
            </Typography>
            <Typography variant="body2" color="text.secondary" paragraph>
              Use an authenticator app (Google Authenticator, Authy, 1Password,
              etc.) to scan this QR code:
            </Typography>

            <Box sx={{ textAlign: "center", my: 3 }}>
              <img
                src={qrCodeUrl}
                alt="MFA QR Code"
                style={{ maxWidth: "256px" }}
              />
            </Box>

            <Typography variant="subtitle2" gutterBottom>
              Or enter this code manually:
            </Typography>
            <Paper variant="outlined" sx={{ p: 2, mb: 3, bgcolor: "grey.50" }}>
              <Typography
                variant="body2"
                fontFamily="monospace"
                sx={{ wordBreak: "break-all" }}
              >
                {mfaSetupCode}
              </Typography>
            </Paper>

            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Step 2: Verify Code
            </Typography>
            <Typography variant="body2" color="text.secondary" paragraph>
              Enter the 6-digit code from your authenticator app to complete
              setup:
            </Typography>

            <form onSubmit={handleVerifyMFA}>
              <Stack direction="row" spacing={2} alignItems="flex-start">
                <TextField
                  label="Verification Code"
                  value={mfaVerificationCode}
                  onChange={(e) =>
                    setMfaVerificationCode(
                      e.target.value.replace(/\D/g, "").substring(0, 6),
                    )
                  }
                  required
                  disabled={mfaLoading}
                  inputProps={{ maxLength: 6, pattern: "[0-9]*" }}
                  helperText="Enter the 6-digit code"
                />
                <Button
                  type="submit"
                  variant="contained"
                  disabled={mfaLoading || mfaVerificationCode.length !== 6}
                >
                  {mfaLoading ? (
                    <CircularProgress size={24} />
                  ) : (
                    "Verify & Enable"
                  )}
                </Button>
                <Button
                  variant="outlined"
                  onClick={() => {
                    setMfaSetupCode(null);
                    setQrCodeUrl(null);
                    setMfaVerificationCode("");
                  }}
                  disabled={mfaLoading}
                >
                  Cancel
                </Button>
              </Stack>
            </form>
          </Box>
        )}
      </Paper>

      {/* Passkeys Section */}
      <Paper sx={{ p: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <PasskeyIcon color="primary" />
          <Typography variant="h6">Passkeys (Passwordless Login)</Typography>
        </Stack>

        <Typography variant="body2" color="text.secondary" paragraph>
          Passkeys let you sign in securely without a password - using your
          fingerprint, face, or device PIN.
        </Typography>

        {/* MFA Conflict Warning */}
        {mfaEnabled && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <strong>Note:</strong> Passkeys and TOTP MFA cannot be used
            together. Registering a passkey will disable your current MFA setup.
            Passkeys provide strong authentication without requiring a separate
            MFA app.
          </Alert>
        )}

        {passkeySuccess && (
          <Alert
            severity="success"
            sx={{ mb: 2 }}
            onClose={() => setPasskeySuccess(false)}
          >
            Passkey registered successfully!
          </Alert>
        )}

        {passkeyError && (
          <Alert
            severity="error"
            sx={{ mb: 2 }}
            onClose={() => setPasskeyError(null)}
          >
            {passkeyError}
          </Alert>
        )}

        {/* Registered Passkeys List */}
        {passkeys.length > 0 && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle2" gutterBottom>
              Registered Passkeys
            </Typography>
            <List>
              {passkeys.map((pk) => (
                <ListItem
                  key={pk.credentialId || Math.random()}
                  secondaryAction={
                    <IconButton
                      edge="end"
                      onClick={() =>
                        pk.credentialId && handleDeletePasskey(pk.credentialId)
                      }
                      disabled={passkeyLoading || !pk.credentialId}
                    >
                      <DeleteIcon />
                    </IconButton>
                  }
                >
                  <ListItemIcon>
                    <PasskeyIcon />
                  </ListItemIcon>
                  <ListItemText
                    primary={pk.friendlyCredentialName || "Unnamed Passkey"}
                    secondary={
                      pk.createdAt
                        ? `Created: ${new Date(pk.createdAt).toLocaleDateString()}`
                        : "Unknown date"
                    }
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        {/* Register New Passkey */}
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Register a New Passkey
          </Typography>
          <Stack direction="row" spacing={2} alignItems="flex-start">
            <TextField
              label="Passkey Name"
              value={passkeyName}
              onChange={(e) => setPasskeyName(e.target.value)}
              placeholder="e.g., My iPhone, Work Laptop"
              disabled={passkeyLoading}
              sx={{ flex: 1 }}
              helperText="Give this passkey a name to remember which device it's for"
            />
            <Button
              variant="contained"
              startIcon={
                passkeyLoading ? <CircularProgress size={20} /> : <AddIcon />
              }
              onClick={handleRegisterPasskey}
              disabled={passkeyLoading || !passkeyName.trim()}
            >
              Register
            </Button>
          </Stack>
          <Alert severity="info" sx={{ mt: 2 }}>
            <Typography variant="caption">
              <strong>Note:</strong> Passkeys use your device's built-in
              security (Touch ID, Face ID, Windows Hello, etc.). You'll be
              prompted to authenticate with your device when registering.
            </Typography>
          </Alert>
        </Box>
      </Paper>

      {/* Edit Profile Dialog */}
      <Dialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Edit Profile Information</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="First Name"
              value={givenName}
              onChange={(e) => setGivenName(e.target.value)}
              fullWidth
              helperText="Optional"
            />
            <TextField
              label="Last Name"
              value={familyName}
              onChange={(e) => setFamilyName(e.target.value)}
              fullWidth
              helperText="Optional"
            />
            <TextField
              label="City"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              fullWidth
              helperText="Optional"
            />
            <TextField
              label="State"
              value={state}
              onChange={(e) => setState(e.target.value.toUpperCase())}
              fullWidth
              helperText="Optional (e.g., CA, TX, NY)"
              inputProps={{ maxLength: 2 }}
            />
            <TextField
              label="Unit/Pack/Troop Number"
              value={unitNumber}
              onChange={(e) => setUnitNumber(e.target.value)}
              fullWidth
              helperText="Optional (e.g., Pack 123, Troop 456)"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialogOpen(false)} disabled={updating}>
            Cancel
          </Button>
          <Button
            onClick={handleSaveProfile}
            variant="contained"
            disabled={updating}
          >
            {updating ? "Saving..." : "Save Changes"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Change Email Dialog */}
      <Dialog
        open={emailDialogOpen}
        onClose={handleCloseEmailDialog}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {emailUpdatePending ? "Verify New Email" : "Change Email Address"}
        </DialogTitle>
        <DialogContent>
          {emailUpdateSuccess && (
            <Alert severity="success" sx={{ mb: 2 }}>
              Email verified! Signing you out to complete the update. Please
              sign back in with your new email address.
            </Alert>
          )}

          {emailUpdateError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {emailUpdateError}
            </Alert>
          )}

          {!emailUpdatePending ? (
            <>
              <Typography variant="body2" color="text.secondary" paragraph>
                Enter your new email address. You'll receive a verification code
                at the new address.
              </Typography>
              <TextField
                label="New Email Address"
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                fullWidth
                autoFocus
                disabled={emailUpdateLoading}
                helperText={`Current email: ${account?.email}`}
              />
            </>
          ) : (
            <>
              <Typography variant="body2" color="text.secondary" paragraph>
                A verification code has been sent to <strong>{newEmail}</strong>
                . Please enter the code below.
              </Typography>
              <TextField
                label="Verification Code"
                value={emailVerificationCode}
                onChange={(e) =>
                  setEmailVerificationCode(
                    e.target.value.replace(/\D/g, "").substring(0, 6),
                  )
                }
                fullWidth
                autoFocus
                disabled={emailUpdateLoading}
                inputProps={{ maxLength: 6, pattern: "[0-9]*" }}
                helperText="Enter the 6-digit code from your email"
              />
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={handleCloseEmailDialog}
            disabled={emailUpdateLoading}
          >
            Cancel
          </Button>
          {!emailUpdatePending ? (
            <Button
              onClick={handleRequestEmailUpdate}
              variant="contained"
              disabled={emailUpdateLoading || !newEmail}
            >
              {emailUpdateLoading ? (
                <CircularProgress size={24} />
              ) : (
                "Send Code"
              )}
            </Button>
          ) : (
            <Button
              onClick={handleConfirmEmailUpdate}
              variant="contained"
              disabled={
                emailUpdateLoading || emailVerificationCode.length !== 6
              }
            >
              {emailUpdateLoading ? (
                <CircularProgress size={24} />
              ) : (
                "Verify & Update"
              )}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
};
