/**
 * Hook for managing Admin MFA required degraded state
 */
import { useState, useEffect, useCallback } from 'react';

export interface UseAdminMfaReturn {
  isMfaRequired: boolean;
  setIsMfaRequired: (required: boolean) => void;
  triggerMfaRequired: () => void;
  resetMfaRequired: () => void;
}

export function useAdminMfa(): UseAdminMfaReturn {
  const [isMfaRequired, setIsMfaRequired] = useState(false);

  useEffect(() => {
    const handleMfaRequired = () => {
      setIsMfaRequired(true);
    };

    window.addEventListener('mfa-required', handleMfaRequired);
    return () => {
      window.removeEventListener('mfa-required', handleMfaRequired);
    };
  }, []);

  const triggerMfaRequired = useCallback(() => {
    setIsMfaRequired(true);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('mfa-required', {
          detail: { message: 'MFA required' },
        }),
      );
    }
  }, []);

  const resetMfaRequired = useCallback(() => {
    setIsMfaRequired(false);
  }, []);

  return {
    isMfaRequired,
    setIsMfaRequired,
    triggerMfaRequired,
    resetMfaRequired,
  };
}
