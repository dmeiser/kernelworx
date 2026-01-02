/**
 * Custom hook for MFA (TOTP) functionality
 */
import { useState, useCallback } from "react";
import {
  setUpTOTP,
  verifyTOTPSetup,
  updateMFAPreference,
  fetchMFAPreference,
  deleteWebAuthnCredential,
  type AuthWebAuthnCredential,
} from "aws-amplify/auth";
import QRCode from "qrcode";

export interface UseMfaReturn {
  mfaSetupCode: string | null;
  qrCodeUrl: string | null;
  mfaVerificationCode: string;
  setMfaVerificationCode: (value: string) => void;
  mfaError: string | null;
  setMfaError: (value: string | null) => void;
  mfaSuccess: boolean;
  setMfaSuccess: (value: boolean) => void;
  mfaLoading: boolean;
  mfaEnabled: boolean;
  handleSetupMFA: (
    passkeys: AuthWebAuthnCredential[],
    loadPasskeys: () => Promise<void>,
  ) => Promise<void>;
  handleVerifyMFA: (e: React.FormEvent) => Promise<void>;
  handleDisableMFA: () => Promise<void>;
  checkMfaStatus: () => Promise<void>;
  setMfaEnabled: (enabled: boolean) => void;
  resetMfaSetup: () => void;
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === "object" && err !== null && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return fallback;
};

export const useMfa = (): UseMfaReturn => {
  const [mfaSetupCode, setMfaSetupCode] = useState<string | null>(null);
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [mfaVerificationCode, setMfaVerificationCode] = useState("");
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [mfaSuccess, setMfaSuccess] = useState(false);
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaEnabled, setMfaEnabled] = useState(false);

  const checkMfaStatus = useCallback(async () => {
    try {
      const mfaPreference = await fetchMFAPreference();
      setMfaEnabled(mfaPreference.preferred === "TOTP");
    } catch (err) {
      console.error("Failed to fetch MFA preference:", err);
    }
  }, []);

  const handleSetupMFA = async (
    passkeys: AuthWebAuthnCredential[],
    loadPasskeys: () => Promise<void>,
  ) => {
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
      } catch (err: unknown) {
        setMfaError(getErrorMessage(err, "Failed to remove passkeys"));
        return;
      }
    }

    setMfaError(null);
    setMfaLoading(true);

    try {
      const totpSetupDetails = await setUpTOTP();
      const setupUri = totpSetupDetails.getSetupUri("PopcornManager");
      const qrDataUrl = await QRCode.toDataURL(setupUri.href);

      setMfaSetupCode(totpSetupDetails.sharedSecret);
      setQrCodeUrl(qrDataUrl);
    } catch (err: unknown) {
      console.error("MFA setup failed:", err);
      setMfaError(getErrorMessage(err, "Failed to set up MFA"));
    } finally {
      setMfaLoading(false);
    }
  };

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
    } catch (err: unknown) {
      console.error("MFA verification failed:", err);
      setMfaError(
        getErrorMessage(err, "Invalid verification code. Please try again."),
      );
    } finally {
      setMfaLoading(false);
    }
  };

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
    } catch (err: unknown) {
      console.error("Disable MFA failed:", err);
      setMfaError(getErrorMessage(err, "Failed to disable MFA"));
    } finally {
      setMfaLoading(false);
    }
  };

  const resetMfaSetup = () => {
    setMfaSetupCode(null);
    setQrCodeUrl(null);
    setMfaVerificationCode("");
  };

  return {
    mfaSetupCode,
    qrCodeUrl,
    mfaVerificationCode,
    setMfaVerificationCode,
    mfaError,
    setMfaError,
    mfaSuccess,
    setMfaSuccess,
    mfaLoading,
    mfaEnabled,
    handleSetupMFA,
    handleVerifyMFA,
    handleDisableMFA,
    checkMfaStatus,
    setMfaEnabled,
    resetMfaSetup,
  };
};
