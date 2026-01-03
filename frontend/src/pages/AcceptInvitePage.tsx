/**
 * AcceptInvitePage - Accept a profile invite code
 */

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@apollo/client/react";
import {
  Box,
  Typography,
  TextField,
  Button,
  Alert,
  CircularProgress,
  Card,
  CardContent,
  Stack,
} from "@mui/material";
import { Check as CheckIcon } from "@mui/icons-material";
import { REDEEM_PROFILE_INVITE } from "../lib/graphql";

// Success message builder
const buildSuccessMessage = (permissions: string[]): string => {
  return `Successfully accepted! You now have ${permissions.join(" and ")} access.`;
};

// Error message extractor
const getRedeemErrorMessage = (err: Error): string => {
  return (
    err.message ||
    "Failed to accept invite. Please check the code and try again."
  );
};

// Form validation helper
const isCodeEmpty = (code: string): boolean => {
  return !code.trim();
};

// Submit button state helpers
const isInputDisabled = (loading: boolean, hasSuccess: boolean): boolean => {
  return loading || hasSuccess;
};

const isSubmitDisabled = (
  loading: boolean,
  inviteCode: string,
  hasSuccess: boolean,
): boolean => {
  return loading || isCodeEmpty(inviteCode) || hasSuccess;
};

const getSubmitButtonText = (loading: boolean): string => {
  return loading ? "Accepting..." : "Accept Invite";
};

export const AcceptInvitePage: React.FC = () => {
  const navigate = useNavigate();
  const [inviteCode, setInviteCode] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [error, setError] = useState("");

  const handleSuccess = (data: {
    redeemProfileInvite: { permissions: string[] };
  }) => {
    const share = data.redeemProfileInvite;
    setSuccessMessage(buildSuccessMessage(share.permissions));
    setInviteCode("");
    setTimeout(() => navigate("/scouts"), 2000);
  };

  const handleError = (err: Error) => {
    setError(getRedeemErrorMessage(err));
  };

  const [redeemInvite, { loading }] = useMutation<{
    redeemProfileInvite: { permissions: string[] };
  }>(REDEEM_PROFILE_INVITE, {
    onCompleted: handleSuccess,
    onError: handleError,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMessage("");

    if (isCodeEmpty(inviteCode)) {
      setError("Please enter an invite code");
      return;
    }

    await redeemInvite({
      variables: {
        input: {
          inviteCode: inviteCode.trim(),
        },
      },
    });
  };

  const hasSuccess = successMessage.length > 0;
  const inputDisabled = isInputDisabled(loading, hasSuccess);
  const submitDisabled = isSubmitDisabled(loading, inviteCode, hasSuccess);
  const buttonText = getSubmitButtonText(loading);
  const buttonIcon = loading ? <CircularProgress size={20} /> : undefined;

  return (
    <Box sx={{ maxWidth: 500, mx: "auto", py: 4 }}>
      <Card elevation={2}>
        <CardContent>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h4" component="h1" gutterBottom>
                Accept Scout Profile Invite
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Enter the invite code you received to gain access to a Scout
                Profile
              </Typography>
            </Box>

            {successMessage && (
              <Alert
                severity="success"
                icon={<CheckIcon />}
                sx={{
                  "& .MuiAlert-message": {
                    width: "100%",
                  },
                }}
              >
                {successMessage}
              </Alert>
            )}

            {error && <Alert severity="error">{error}</Alert>}

            <form onSubmit={handleSubmit}>
              <Stack spacing={2}>
                <TextField
                  fullWidth
                  label="Invite Code"
                  placeholder="Enter the code from your invite"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
                  disabled={inputDisabled}
                  autoFocus
                  variant="outlined"
                />

                <Button
                  fullWidth
                  variant="contained"
                  size="large"
                  type="submit"
                  disabled={submitDisabled}
                  startIcon={buttonIcon}
                >
                  {buttonText}
                </Button>
              </Stack>
            </form>

            <Box
              sx={{
                p: 2,
                bgcolor: "action.hover",
                borderRadius: 1,
              }}
            >
              <Typography variant="caption" color="text.secondary">
                <strong>Don't have an invite code?</strong> Ask the profile
                owner to send you one, or ask them to share the profile directly
                with your email address.
              </Typography>
            </Box>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
};
