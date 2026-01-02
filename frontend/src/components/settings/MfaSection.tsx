/**
 * MFA (Multi-Factor Authentication) section for User Settings
 */
import {
  Paper,
  Stack,
  Box,
  Typography,
  TextField,
  Button,
  Alert,
  CircularProgress,
  Divider,
} from "@mui/material";
import {
  Security as SecurityIcon,
  QrCode2 as QrCodeIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckIcon,
} from "@mui/icons-material";
import type { UseMfaReturn } from "../../hooks/useMfa";

interface MfaSectionProps {
  mfaHook: UseMfaReturn;
  passkeyCount: number;
  onSetupMFA: () => void;
}

export const MfaSection: React.FC<MfaSectionProps> = ({
  mfaHook,
  passkeyCount,
  onSetupMFA,
}) => {
  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <SecurityIcon color="primary" />
        <Typography variant="h6">Multi-Factor Authentication (MFA)</Typography>
      </Stack>

      <Typography variant="body2" color="text.secondary" paragraph>
        Add an extra layer of security to your account by requiring a
        verification code from your phone.
      </Typography>

      {/* Passkey Conflict Warning */}
      {passkeyCount > 0 && !mfaHook.mfaEnabled && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          <strong>Note:</strong> You have {passkeyCount} passkey
          {passkeyCount > 1 ? "s" : ""} registered. TOTP MFA and Passkeys cannot
          be used together. Enabling MFA will delete all your passkeys.
        </Alert>
      )}

      {mfaHook.mfaSuccess && (
        <Alert
          severity="success"
          sx={{ mb: 2 }}
          onClose={() => mfaHook.setMfaSuccess(false)}
        >
          MFA has been successfully enabled!
        </Alert>
      )}

      {mfaHook.mfaError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          onClose={() => mfaHook.setMfaError(null)}
        >
          {mfaHook.mfaError}
        </Alert>
      )}

      {mfaHook.mfaEnabled && !mfaHook.mfaSetupCode && (
        <Alert severity="success" icon={<CheckIcon />} sx={{ mb: 2 }}>
          <Typography variant="body2" fontWeight={600}>
            MFA is currently enabled
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Your account is protected with multi-factor authentication
          </Typography>
        </Alert>
      )}

      {!mfaHook.mfaSetupCode && !mfaHook.mfaEnabled && (
        <Button
          variant="contained"
          startIcon={<QrCodeIcon />}
          onClick={onSetupMFA}
          disabled={mfaHook.mfaLoading}
        >
          {mfaHook.mfaLoading ? <CircularProgress size={24} /> : "Set Up MFA"}
        </Button>
      )}

      {mfaHook.mfaEnabled && (
        <Button
          variant="outlined"
          color="error"
          startIcon={<DeleteIcon />}
          onClick={mfaHook.handleDisableMFA}
          disabled={mfaHook.mfaLoading}
          sx={{ mt: 2 }}
        >
          Disable MFA
        </Button>
      )}

      {/* MFA Setup Flow */}
      {mfaHook.mfaSetupCode && mfaHook.qrCodeUrl && (
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
              src={mfaHook.qrCodeUrl}
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
              {mfaHook.mfaSetupCode}
            </Typography>
          </Paper>

          <Typography variant="subtitle1" fontWeight={600} gutterBottom>
            Step 2: Verify Code
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            Enter the 6-digit code from your authenticator app to complete
            setup:
          </Typography>

          <form onSubmit={mfaHook.handleVerifyMFA}>
            <Stack direction="row" spacing={2} alignItems="flex-start">
              <TextField
                label="Verification Code"
                value={mfaHook.mfaVerificationCode}
                onChange={(e) =>
                  mfaHook.setMfaVerificationCode(
                    e.target.value.replace(/\D/g, "").substring(0, 6),
                  )
                }
                required
                disabled={mfaHook.mfaLoading}
                inputProps={{ maxLength: 6, pattern: "[0-9]*" }}
                helperText="Enter the 6-digit code"
              />
              <Button
                type="submit"
                variant="contained"
                disabled={
                  mfaHook.mfaLoading ||
                  mfaHook.mfaVerificationCode.length !== 6
                }
              >
                {mfaHook.mfaLoading ? (
                  <CircularProgress size={24} />
                ) : (
                  "Verify & Enable"
                )}
              </Button>
              <Button
                variant="outlined"
                onClick={mfaHook.resetMfaSetup}
                disabled={mfaHook.mfaLoading}
              >
                Cancel
              </Button>
            </Stack>
          </form>
        </Box>
      )}
    </Paper>
  );
};
