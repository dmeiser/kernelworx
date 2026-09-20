/**
 * Custom hook for MFA (TOTP) functionality
 */
import { useState, useCallback } from 'react';
import {
  setUpTOTP,
  verifyTOTPSetup,
  updateMFAPreference,
  fetchMFAPreference,
} from 'aws-amplify/auth';
import QRCode from 'qrcode';

export interface MfaPendingConfirmation {
  type: 'disable';
  message: string;
}

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
  pendingConfirmation: MfaPendingConfirmation | null;
  handleSetupMFA: () => Promise<void>;
  confirmSetupMFA: () => Promise<void>;
  handleVerifyMFA: (e: React.FormEvent) => Promise<void>;
  handleDisableMFA: () => void;
  confirmDisableMFA: () => Promise<void>;
  cancelMfaConfirmation: () => void;
  checkMfaStatus: () => Promise<void>;
  setMfaEnabled: (enabled: boolean) => void;
  resetMfaSetup: () => void;
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    return String((err as { message: unknown }).message);
  }
  return fallback;
};

const MFA_MESSAGES = {
  disable: 'Are you sure you want to disable multi-factor authentication? This will make your account less secure.',
};

const runMfaSetup = async (
  setMfaSetupCode: (code: string) => void,
  setQrCodeUrl: (url: string) => void,
  setMfaError: (error: string | null) => void,
  setMfaLoading: (loading: boolean) => void,
): Promise<void> => {
  setMfaLoading(true);
  try {
    const totpSetupDetails = await setUpTOTP();
    const setupUri = totpSetupDetails.getSetupUri('PopcornManager');
    const qrDataUrl = await QRCode.toDataURL(setupUri.href);

    setMfaSetupCode(totpSetupDetails.sharedSecret);
    setQrCodeUrl(qrDataUrl);
  } catch (err: unknown) {
    setMfaError(getErrorMessage(err, 'Failed to set up MFA'));
  } finally {
    setMfaLoading(false);
  }
};

export const useMfa = (): UseMfaReturn => {
  const [mfaSetupCode, setMfaSetupCode] = useState<string | null>(null);
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [mfaVerificationCode, setMfaVerificationCode] = useState('');
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [mfaSuccess, setMfaSuccess] = useState(false);
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [pendingConfirmation, setPendingConfirmation] = useState<MfaPendingConfirmation | null>(null);

  const checkMfaStatus = useCallback(async () => {
    try {
      const mfaPreference = await fetchMFAPreference();
      setMfaEnabled(mfaPreference.preferred === 'TOTP');
    } catch {
      // Ignore load MFA preference error
    }
  }, []);

  const handleSetupMFA = async () => {
    setPendingConfirmation(null);
    await runMfaSetup(setMfaSetupCode, setQrCodeUrl, setMfaError, setMfaLoading);
  };

  const confirmSetupMFA = async () => {
    setPendingConfirmation(null);
    setMfaError(null);
    await runMfaSetup(setMfaSetupCode, setQrCodeUrl, setMfaError, setMfaLoading);
  };

  const handleVerifyMFA = async (e: React.FormEvent) => {
    e.preventDefault();
    setMfaError(null);
    setMfaLoading(true);

    try {
      await verifyTOTPSetup({ code: mfaVerificationCode });
      await updateMFAPreference({ totp: 'PREFERRED' });

      setMfaSuccess(true);
      setMfaEnabled(true);
      setMfaSetupCode(null);
      setQrCodeUrl(null);
      setMfaVerificationCode('');
    } catch (err: unknown) {
      setMfaError(getErrorMessage(err, 'Invalid verification code. Please try again.'));
    } finally {
      setMfaLoading(false);
    }
  };

  const handleDisableMFA = () => {
    setPendingConfirmation({ type: 'disable', message: MFA_MESSAGES.disable });
  };

  const confirmDisableMFA = async () => {
    setPendingConfirmation(null);
    setMfaError(null);
    setMfaLoading(true);

    try {
      await updateMFAPreference({ totp: 'DISABLED' });
      setMfaEnabled(false);
      setMfaSuccess(false);
    } catch (err: unknown) {
      setMfaError(getErrorMessage(err, 'Failed to disable MFA'));
    } finally {
      setMfaLoading(false);
    }
  };

  const cancelMfaConfirmation = () => {
    setPendingConfirmation(null);
  };

  const resetMfaSetup = () => {
    setMfaSetupCode(null);
    setQrCodeUrl(null);
    setMfaVerificationCode('');
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
    pendingConfirmation,
    handleSetupMFA,
    confirmSetupMFA,
    handleVerifyMFA,
    handleDisableMFA,
    confirmDisableMFA,
    cancelMfaConfirmation,
    checkMfaStatus,
    setMfaEnabled,
    resetMfaSetup,
  };
};
