/**
 * Change Email Dialog component for User Settings
 */
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Typography,
  Alert,
  CircularProgress,
} from "@mui/material";
import type { UseEmailUpdateReturn } from "../../hooks/useEmailUpdate";

interface ChangeEmailDialogProps {
  emailHook: UseEmailUpdateReturn;
  currentEmail: string | undefined;
  onRequestUpdate: () => void;
  onConfirmUpdate: () => void;
}

export const ChangeEmailDialog: React.FC<ChangeEmailDialogProps> = ({
  emailHook,
  currentEmail,
  onRequestUpdate,
  onConfirmUpdate,
}) => {
  return (
    <Dialog
      open={emailHook.emailDialogOpen}
      onClose={emailHook.handleCloseEmailDialog}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>
        {emailHook.emailUpdatePending
          ? "Verify New Email"
          : "Change Email Address"}
      </DialogTitle>
      <DialogContent>
        {emailHook.emailUpdateSuccess && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Email verified! Signing you out to complete the update. Please sign
            back in with your new email address.
          </Alert>
        )}

        {emailHook.emailUpdateError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {emailHook.emailUpdateError}
          </Alert>
        )}

        {!emailHook.emailUpdatePending ? (
          <>
            <Typography variant="body2" color="text.secondary" paragraph>
              Enter your new email address. You'll receive a verification code
              at the new address.
            </Typography>
            <TextField
              label="New Email Address"
              type="email"
              value={emailHook.newEmail}
              onChange={(e) => emailHook.setNewEmail(e.target.value)}
              fullWidth
              autoFocus
              disabled={emailHook.emailUpdateLoading}
              helperText={`Current email: ${currentEmail}`}
            />
          </>
        ) : (
          <>
            <Typography variant="body2" color="text.secondary" paragraph>
              A verification code has been sent to{" "}
              <strong>{emailHook.newEmail}</strong>. Please enter the code
              below.
            </Typography>
            <TextField
              label="Verification Code"
              value={emailHook.emailVerificationCode}
              onChange={(e) =>
                emailHook.setEmailVerificationCode(
                  e.target.value.replace(/\D/g, "").substring(0, 6),
                )
              }
              fullWidth
              autoFocus
              disabled={emailHook.emailUpdateLoading}
              inputProps={{ maxLength: 6, pattern: "[0-9]*" }}
              helperText="Enter the 6-digit code from your email"
            />
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button
          onClick={emailHook.handleCloseEmailDialog}
          disabled={emailHook.emailUpdateLoading}
        >
          Cancel
        </Button>
        {!emailHook.emailUpdatePending ? (
          <Button
            onClick={onRequestUpdate}
            variant="contained"
            disabled={emailHook.emailUpdateLoading || !emailHook.newEmail}
          >
            {emailHook.emailUpdateLoading ? (
              <CircularProgress size={24} />
            ) : (
              "Send Code"
            )}
          </Button>
        ) : (
          <Button
            onClick={onConfirmUpdate}
            variant="contained"
            disabled={
              emailHook.emailUpdateLoading ||
              emailHook.emailVerificationCode.length !== 6
            }
          >
            {emailHook.emailUpdateLoading ? (
              <CircularProgress size={24} />
            ) : (
              "Verify & Update"
            )}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
};
