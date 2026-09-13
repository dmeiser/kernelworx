/**
 * AmrTripwireBanner - Tripwire banner alerting admins if a native 'amr' claim appears in their token.
 *
 * Cognito on this infrastructure does not emit an 'amr' claim today.
 * If AWS begins emitting one, the injected boolean mfa claim can be retired.
 * This banner is rendered only for admin users whose ID token contains an 'amr' claim.
 */

import React, { useState, useEffect } from 'react';
import { Alert } from '@mui/material';
import { fetchAuthSession } from 'aws-amplify/auth';
import { resolveActiveKeyFromSession, markSessionDismissed } from '../lib/amrTripwire';

export const AmrTripwireBanner: React.FC = () => {
  const [visible, setVisible] = useState(false);
  const [dismissKey, setDismissKey] = useState<string>('amr_tripwire_dismissed');

  useEffect(() => {
    let mounted = true;

    const checkToken = async () => {
      try {
        const session = await fetchAuthSession();
        const activeKey = resolveActiveKeyFromSession(session);

        if (!mounted || !activeKey) {
          return;
        }

        setDismissKey(activeKey);
        setVisible(true);
      } catch {
        // If session fetch fails, do not show banner
      }
    };

    void checkToken();

    return () => {
      mounted = false;
    };
  }, []);

  const handleDismiss = () => {
    markSessionDismissed(dismissKey);
    setVisible(false);
  };

  if (!visible) {
    return null;
  }

  return (
    <Alert
      severity="error"
      variant="filled"
      onClose={handleDismiss}
      sx={{ mb: 3 }}
      data-testid="amr-tripwire-banner"
    >
      Cognito token behavior changed: a native amr claim appeared in your token. Report this to operations — the MFA claim injection may be retireable.
    </Alert>
  );
};
