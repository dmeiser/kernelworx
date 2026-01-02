/**
 * Custom hook for email update functionality
 */
import { useState } from "react";
import { updateUserAttribute, confirmUserAttribute } from "aws-amplify/auth";

export interface UseEmailUpdateReturn {
  emailDialogOpen: boolean;
  setEmailDialogOpen: (value: boolean) => void;
  newEmail: string;
  setNewEmail: (value: string) => void;
  emailVerificationCode: string;
  setEmailVerificationCode: (value: string) => void;
  emailUpdatePending: boolean;
  emailUpdateLoading: boolean;
  emailUpdateError: string | null;
  emailUpdateSuccess: boolean;
  handleOpenEmailDialog: () => void;
  handleCloseEmailDialog: () => void;
  handleRequestEmailUpdate: (currentEmail: string | undefined) => Promise<void>;
  handleConfirmEmailUpdate: (
    logout: () => Promise<void>,
    navigate: (path: string) => void,
  ) => Promise<void>;
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === "object" && err !== null && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return fallback;
};

export const useEmailUpdate = (): UseEmailUpdateReturn => {
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [emailVerificationCode, setEmailVerificationCode] = useState("");
  const [emailUpdatePending, setEmailUpdatePending] = useState(false);
  const [emailUpdateLoading, setEmailUpdateLoading] = useState(false);
  const [emailUpdateError, setEmailUpdateError] = useState<string | null>(null);
  const [emailUpdateSuccess, setEmailUpdateSuccess] = useState(false);

  const handleOpenEmailDialog = () => {
    setEmailDialogOpen(true);
  };

  const handleCloseEmailDialog = () => {
    setEmailDialogOpen(false);
    setNewEmail("");
    setEmailVerificationCode("");
    setEmailUpdatePending(false);
    setEmailUpdateError(null);
  };

  const handleRequestEmailUpdate = async (currentEmail: string | undefined) => {
    if (!newEmail || !newEmail.includes("@")) {
      setEmailUpdateError("Please enter a valid email address");
      return;
    }

    if (newEmail.toLowerCase() === currentEmail?.toLowerCase()) {
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
    } catch (err: unknown) {
      setEmailUpdateError(
        getErrorMessage(err, "Failed to request email update"),
      );
    } finally {
      setEmailUpdateLoading(false);
    }
  };

  const handleConfirmEmailUpdate = async (
    logout: () => Promise<void>,
    navigate: (path: string) => void,
  ) => {
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
    } catch (err: unknown) {
      setEmailUpdateError(getErrorMessage(err, "Invalid verification code"));
    } finally {
      setEmailUpdateLoading(false);
    }
  };

  return {
    emailDialogOpen,
    setEmailDialogOpen,
    newEmail,
    setNewEmail,
    emailVerificationCode,
    setEmailVerificationCode,
    emailUpdatePending,
    emailUpdateLoading,
    emailUpdateError,
    emailUpdateSuccess,
    handleOpenEmailDialog,
    handleCloseEmailDialog,
    handleRequestEmailUpdate,
    handleConfirmEmailUpdate,
  };
};
