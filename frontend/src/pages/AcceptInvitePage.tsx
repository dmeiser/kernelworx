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

export const AcceptInvitePage: React.FC = () => {
  const navigate = useNavigate();
  const [inviteCode, setInviteCode] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [error, setError] = useState("");

  const [redeemInvite, { loading }] = useMutation(REDEEM_PROFILE_INVITE, {
    onCompleted: (data) => {
      const share = data.redeemProfileInvite;
      setSuccessMessage(
        `Successfully accepted! You now have ${share.permissions.join(" and ")} access.`,
      );
      setInviteCode("");
      // Redirect to profiles page after 2 seconds
      setTimeout(() => {
        navigate("/profiles");
      }, 2000);
    },
    onError: (err) => {
      setError(
        err.message ||
          "Failed to accept invite. Please check the code and try again.",
      );
    },
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMessage("");

    if (!inviteCode.trim()) {
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

  return (
    <Box sx={{ maxWidth: 500, mx: "auto", py: 4 }}>
      <Card elevation={2}>
        <CardContent>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h4" component="h1" gutterBottom>
                Accept Profile Invite
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Enter the invite code you received to gain access to a seller
                profile
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
                  disabled={loading || !!successMessage}
                  autoFocus
                  variant="outlined"
                />

                <Button
                  fullWidth
                  variant="contained"
                  size="large"
                  type="submit"
                  disabled={loading || !inviteCode.trim() || !!successMessage}
                  startIcon={
                    loading ? <CircularProgress size={20} /> : undefined
                  }
                >
                  {loading ? "Accepting..." : "Accept Invite"}
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
