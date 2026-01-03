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

const SendCodeButton: React.FC<{
  loading: boolean;
  hasNewEmail: boolean;
  onClick: () => void;
}> = ({ loading, hasNewEmail, onClick }) => (
  <Button
    onClick={onClick}
    variant="contained"
    disabled={loading || !hasNewEmail}
  >
    {loading ? <CircularProgress size={24} /> : "Send Code"}
  </Button>
);

const VerifyButton: React.FC<{
  loading: boolean;
  codeLength: number;
  onClick: () => void;
}> = ({ loading, codeLength, onClick }) => (
  <Button
    onClick={onClick}
    variant="contained"
    disabled={loading || codeLength !== 6}
  >
    {loading ? <CircularProgress size={24} /> : "Verify & Update"}
  </Button>
);

const EmailEntryContent: React.FC<{
  emailHook: UseEmailUpdateReturn;
  currentEmail: string | undefined;
}> = ({ emailHook, currentEmail }) => (
  <>
    <Typography variant="body2" color="text.secondary" paragraph>
      Enter your new email address. You'll receive a verification code at the
      new address.
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
);

const VerificationContent: React.FC<{ emailHook: UseEmailUpdateReturn }> = ({
  emailHook,
}) => (
  <>
    <Typography variant="body2" color="text.secondary" paragraph>
      A verification code has been sent to <strong>{emailHook.newEmail}</strong>
      . Please enter the code below.
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
);

interface ChangeEmailDialogProps {
  emailHook: UseEmailUpdateReturn;
  currentEmail: string | undefined;
  onRequestUpdate: () => void;
  onConfirmUpdate: () => void;
}

const getDialogTitle = (emailHook: UseEmailUpdateReturn): string =>
  emailHook.emailUpdatePending ? "Verify New Email" : "Change Email Address";

const renderStatusAlerts = (emailHook: UseEmailUpdateReturn) => (
  <>
    {emailHook.emailUpdateSuccess ? (
      <Alert severity="success" sx={{ mb: 2 }}>
        Email verified! Signing you out to complete the update. Please sign back
        in with your new email address.
      </Alert>
    ) : null}

    {emailHook.emailUpdateError ? (
      <Alert severity="error" sx={{ mb: 2 }}>
        {emailHook.emailUpdateError}
      </Alert>
    ) : null}
  </>
);

const renderContentBody = (
  emailHook: UseEmailUpdateReturn,
  currentEmail: string | undefined,
): React.ReactNode =>
  emailHook.emailUpdatePending ? (
    <VerificationContent emailHook={emailHook} />
  ) : (
    <EmailEntryContent emailHook={emailHook} currentEmail={currentEmail} />
  );

const renderPrimaryAction = (
  emailHook: UseEmailUpdateReturn,
  onConfirmUpdate: () => void,
  onRequestUpdate: () => void,
): React.ReactNode =>
  emailHook.emailUpdatePending ? (
    <VerifyButton
      loading={emailHook.emailUpdateLoading}
      codeLength={emailHook.emailVerificationCode.length}
      onClick={onConfirmUpdate}
    />
  ) : (
    <SendCodeButton
      loading={emailHook.emailUpdateLoading}
      hasNewEmail={Boolean(emailHook.newEmail)}
      onClick={onRequestUpdate}
    />
  );

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
      <DialogTitle>{getDialogTitle(emailHook)}</DialogTitle>
      <DialogContent>
        {renderStatusAlerts(emailHook)}
        {renderContentBody(emailHook, currentEmail)}
      </DialogContent>
      <DialogActions>
        <Button
          onClick={emailHook.handleCloseEmailDialog}
          disabled={emailHook.emailUpdateLoading}
        >
          Cancel
        </Button>
        {renderPrimaryAction(emailHook, onConfirmUpdate, onRequestUpdate)}
      </DialogActions>
    </Dialog>
  );
};
