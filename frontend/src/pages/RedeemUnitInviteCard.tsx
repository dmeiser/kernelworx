/**
 * RedeemUnitInviteCard - self-service redemption of a Unit invite code.
 *
 * Part of the Show & Sell Unit surface (batch C, leaf 1.6.2). Wires
 * `redeemUnitInvite`, which is open to ANY authenticated account: an invitee who
 * does not yet hold Unit Admin access reaches it here (it is not inside the
 * admin-only access section).
 */

import React, { useState } from 'react';
import { useMutation } from '@apollo/client/react';
import { Alert, Box, Button, Card, CardContent, TextField, Typography } from '@mui/material';
import { REDEEM_UNIT_INVITE } from '../lib/graphql';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/errorCodes';
import { newUnitIdempotencyKey } from '../lib/unitForm';

interface RedeemUnitInviteCardProps {
  onRedeemed?: () => void;
}

const RedeemUnitInviteCard: React.FC<RedeemUnitInviteCardProps> = ({ onRedeemed }) => {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [redeem, { loading: redeeming }] = useMutation(REDEEM_UNIT_INVITE, {
    onCompleted: () => {
      setSuccess('Invite redeemed — you are now a Unit Admin. The unit now appears in your list.');
      setCode('');
      onRedeemed?.();
    },
    onError: (e) => {
      setError(mapErrorCodeToMessage(getErrorCode(e), getErrorMessage(e)));
      setSuccess(null);
    },
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!code.trim()) {
      setError('Enter the 16-character invite code.');
      return;
    }
    try {
      await redeem({
        variables: { input: { inviteCode: code.trim(), idempotency: { idempotencyKey: newUnitIdempotencyKey() } } },
      });
    } catch {
      // GraphQL errors are surfaced by the onError callback; swallow to avoid an unhandled rejection.
    }
  };

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          Redeem an invite
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Have a Unit invite code? Enter it here to join as a Unit Admin.
        </Typography>
        {error && (
          <Alert severity="error" sx={{ mb: 1 }}>
            {error}
          </Alert>
        )}
        {success && (
          <Alert severity="success" sx={{ mb: 1 }}>
            {success}
          </Alert>
        )}
        <Box
          component="form"
          onSubmit={(e) => void handleSubmit(e)}
          sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}
        >
          <TextField
            label="Invite code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            sx={{ flex: 1 }}
            autoFocus
          />
          <Button type="submit" variant="contained" disabled={redeeming}>
            {redeeming ? 'Redeeming…' : 'Redeem'}
          </Button>
        </Box>
      </CardContent>
    </Card>
  );
};

export default RedeemUnitInviteCard;
