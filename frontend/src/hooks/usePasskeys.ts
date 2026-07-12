/**
 * Custom hook for passkey (WebAuthn) functionality
 */
import { useState, useCallback, useRef } from 'react';
import {
  associateWebAuthnCredential,
  listWebAuthnCredentials,
  deleteWebAuthnCredential,
  updateMFAPreference,
  type AuthWebAuthnCredential,
} from 'aws-amplify/auth';

export interface PasskeyPendingConfirmation {
  type: 'disableMfa' | 'delete';
  message: string;
  credentialId?: string;
}

export interface UsePasskeysReturn {
  passkeys: AuthWebAuthnCredential[];
  passkeyName: string;
  setPasskeyName: (value: string) => void;
  passkeyError: string | null;
  setPasskeyError: (value: string | null) => void;
  passkeySuccess: boolean;
  setPasskeySuccess: (value: boolean) => void;
  passkeyLoading: boolean;
  pendingConfirmation: PasskeyPendingConfirmation | null;
  loadPasskeys: () => Promise<void>;
  handleRegisterPasskey: (mfaEnabled: boolean, setMfaEnabled: (enabled: boolean) => void) => void;
  confirmPasskeyAction: () => Promise<void>;
  cancelPasskeyConfirmation: () => void;
  handleDeletePasskey: (credentialId: string) => void;
}

const getErrorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    return String((err as { message: unknown }).message);
  }
  return fallback;
};

const PASSKEY_MESSAGES = {
  disableMfa: 'Passkeys and TOTP MFA cannot be used together. Do you want to disable MFA and register this passkey?',
  delete: 'Are you sure you want to delete this passkey?',
};

const registerPasskey = async (
  passkeyName: string,
  setPasskeyName: (value: string) => void,
  setPasskeyError: (value: string | null) => void,
  setPasskeySuccess: (value: boolean) => void,
  setPasskeyLoading: (value: boolean) => void,
  loadPasskeys: () => Promise<void>,
): Promise<void> => {
  if (!passkeyName.trim()) {
    setPasskeyError('Please enter a name for this passkey');
    return;
  }

  setPasskeyError(null);
  setPasskeySuccess(false);
  setPasskeyLoading(true);

  try {
    await associateWebAuthnCredential();
    setPasskeySuccess(true);
    setPasskeyName('');
    await loadPasskeys();
  } catch (err: unknown) {
    console.error('Passkey registration failed:', err);
    setPasskeyError(
      getErrorMessage(
        err,
        'Failed to register passkey. Make sure your browser supports passkeys and you have a compatible authenticator.',
      ),
    );
  } finally {
    setPasskeyLoading(false);
  }
};

export const usePasskeys = (): UsePasskeysReturn => {
  const [passkeys, setPasskeys] = useState<AuthWebAuthnCredential[]>([]);
  const [passkeyName, setPasskeyName] = useState('');
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const [passkeySuccess, setPasskeySuccess] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const [pendingConfirmation, setPendingConfirmation] = useState<PasskeyPendingConfirmation | null>(null);
  const registerArgsRef = useRef<{
    mfaEnabled: boolean;
    setMfaEnabled: (enabled: boolean) => void;
  } | null>(null);

  const loadPasskeys = useCallback(async () => {
    try {
      const credentials = await listWebAuthnCredentials();
      setPasskeys(credentials.credentials);
    } catch (err) {
      console.error('Failed to load passkeys:', err);
    }
  }, []);

  const deletePasskey = async (credentialId: string) => {
    setPasskeyError(null);
    setPasskeyLoading(true);
    try {
      await deleteWebAuthnCredential({ credentialId });
      await loadPasskeys();
    } catch (err: unknown) {
      console.error('Delete passkey failed:', err);
      setPasskeyError(getErrorMessage(err, 'Failed to delete passkey'));
    } finally {
      setPasskeyLoading(false);
    }
  };

  const disableMfaAndRegister = async (setMfaEnabled: (enabled: boolean) => void) => {
    setPasskeyError(null);
    setPasskeyLoading(true);

    try {
      await updateMFAPreference({ totp: 'DISABLED' });
      setMfaEnabled(false);
    } catch (err: unknown) {
      console.error('Failed to disable MFA:', err);
      setPasskeyError(getErrorMessage(err, 'Failed to disable MFA'));
      setPasskeyLoading(false);
      return;
    }

    await registerPasskey(
      passkeyName,
      setPasskeyName,
      setPasskeyError,
      setPasskeySuccess,
      setPasskeyLoading,
      loadPasskeys,
    );
  };

  const handleRegisterPasskey = (mfaEnabled: boolean, setMfaEnabled: (enabled: boolean) => void) => {
    registerArgsRef.current = { mfaEnabled, setMfaEnabled };

    if (mfaEnabled) {
      setPendingConfirmation({ type: 'disableMfa', message: PASSKEY_MESSAGES.disableMfa });
      return;
    }

    void registerPasskey(
      passkeyName,
      setPasskeyName,
      setPasskeyError,
      setPasskeySuccess,
      setPasskeyLoading,
      loadPasskeys,
    );
  };

  // eslint-disable-next-line complexity -- Confirmation dispatch for delete / disable MFA
  const confirmPasskeyAction = async () => {
    if (!pendingConfirmation) return;

    if (pendingConfirmation.type === 'delete') {
      const credentialId = pendingConfirmation.credentialId;
      setPendingConfirmation(null);
      if (!credentialId) return;
      await deletePasskey(credentialId);
      return;
    }

    const { mfaEnabled, setMfaEnabled } = registerArgsRef.current ?? {};
    setPendingConfirmation(null);
    if (!mfaEnabled || !setMfaEnabled) return;

    await disableMfaAndRegister(setMfaEnabled);
  };

  const cancelPasskeyConfirmation = () => {
    setPendingConfirmation(null);
    registerArgsRef.current = null;
  };

  const handleDeletePasskey = (credentialId: string) => {
    setPendingConfirmation({ type: 'delete', message: PASSKEY_MESSAGES.delete, credentialId });
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
    pendingConfirmation,
    loadPasskeys,
    handleRegisterPasskey,
    confirmPasskeyAction,
    cancelPasskeyConfirmation,
    handleDeletePasskey,
  };
};
