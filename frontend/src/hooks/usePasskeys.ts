/**
 * Custom hook for passkey (WebAuthn) functionality
 */
import { useState, useCallback } from "react";
import {
  associateWebAuthnCredential,
  listWebAuthnCredentials,
  deleteWebAuthnCredential,
  updateMFAPreference,
  type AuthWebAuthnCredential,
} from "aws-amplify/auth";

export interface UsePasskeysReturn {
  passkeys: AuthWebAuthnCredential[];
  passkeyName: string;
  setPasskeyName: (value: string) => void;
  passkeyError: string | null;
  setPasskeyError: (value: string | null) => void;
  passkeySuccess: boolean;
  setPasskeySuccess: (value: boolean) => void;
  passkeyLoading: boolean;
  loadPasskeys: () => Promise<void>;
  handleRegisterPasskey: (
    mfaEnabled: boolean,
    setMfaEnabled: (enabled: boolean) => void,
  ) => Promise<void>;
  handleDeletePasskey: (credentialId: string) => Promise<void>;
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === "object" && err !== null && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return fallback;
};

const confirmDisableMfa = async (mfaEnabled: boolean) => {
  if (!mfaEnabled) return true;
  return window.confirm(
    "Passkeys and TOTP MFA cannot be used together. Do you want to disable MFA and register this passkey?",
  );
};

// Helper to disable MFA before passkey registration
const disableMfaIfNeeded = async (
  mfaEnabled: boolean,
  setMfaEnabled: (enabled: boolean) => void,
): Promise<{ cancelled: boolean; error: string | null }> => {
  if (!mfaEnabled) {
    return { cancelled: false, error: null };
  }

  const confirmed = await confirmDisableMfa(mfaEnabled);
  if (!confirmed) {
    return { cancelled: true, error: null };
  }

  try {
    await updateMFAPreference({ totp: "DISABLED" });
    setMfaEnabled(false);
    return { cancelled: false, error: null };
  } catch (err: unknown) {
    return {
      cancelled: false,
      error: getErrorMessage(err, "Failed to disable MFA"),
    };
  }
};

export const usePasskeys = (): UsePasskeysReturn => {
  const [passkeys, setPasskeys] = useState<AuthWebAuthnCredential[]>([]);
  const [passkeyName, setPasskeyName] = useState("");
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const [passkeySuccess, setPasskeySuccess] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);

  const loadPasskeys = useCallback(async () => {
    try {
      const credentials = await listWebAuthnCredentials();
      setPasskeys(credentials.credentials);
    } catch (err) {
      console.error("Failed to load passkeys:", err);
    }
  }, []);

  const handleRegisterPasskey = async (
    mfaEnabled: boolean,
    setMfaEnabled: (enabled: boolean) => void,
  ) => {
    if (!passkeyName.trim()) {
      setPasskeyError("Please enter a name for this passkey");
      return;
    }

    const { cancelled, error } = await disableMfaIfNeeded(
      mfaEnabled,
      setMfaEnabled,
    );
    if (cancelled) return;
    if (error) {
      setPasskeyError(error);
      return;
    }

    setPasskeyError(null);
    setPasskeySuccess(false);
    setPasskeyLoading(true);

    try {
      await associateWebAuthnCredential();
      setPasskeySuccess(true);
      setPasskeyName("");
      await loadPasskeys();
    } catch (err: unknown) {
      console.error("Passkey registration failed:", err);
      setPasskeyError(
        getErrorMessage(
          err,
          "Failed to register passkey. Make sure your browser supports passkeys and you have a compatible authenticator.",
        ),
      );
    } finally {
      setPasskeyLoading(false);
    }
  };

  const handleDeletePasskey = async (credentialId: string) => {
    if (!window.confirm("Are you sure you want to delete this passkey?")) {
      return;
    }

    setPasskeyError(null);
    setPasskeyLoading(true);

    try {
      await deleteWebAuthnCredential({ credentialId });
      await loadPasskeys();
    } catch (err: unknown) {
      console.error("Delete passkey failed:", err);
      setPasskeyError(getErrorMessage(err, "Failed to delete passkey"));
    } finally {
      setPasskeyLoading(false);
    }
  };

  return {
    passkeys,
    passkeyName,
    setPasskeyName,
    passkeyError,
    setPasskeyError,
    passkeySuccess,
    setPasskeySuccess,
    passkeyLoading,
    loadPasskeys,
    handleRegisterPasskey,
    handleDeletePasskey,
  };
};
