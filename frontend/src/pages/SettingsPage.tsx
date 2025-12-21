/**
 * SettingsPage - User account settings and preferences
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@apollo/client/react";
import { Box, Typography, Paper, Stack, Button } from "@mui/material";
import { Logout as LogoutIcon } from "@mui/icons-material";
import { useAuth } from "../contexts/AuthContext";
import { GET_MY_ACCOUNT } from "../lib/graphql";

interface Account {
  isAdmin: boolean;
}

export const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const { logout } = useAuth();

  // Only query for isAdmin to show/hide Admin Console button
  const { data: accountData } = useQuery<{ getMyAccount: Account }>(
    GET_MY_ACCOUNT,
  );
  const account = accountData?.getMyAccount;

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  return (
    <Box>
      <Typography variant="h4" component="h1" gutterBottom>
        Account Settings
      </Typography>

      {/* Quick Actions */}
      <Paper sx={{ p: { xs: 2, sm: 3 }, mb: { xs: 2, sm: 3 } }}>
        <Typography variant="h6" gutterBottom>
          Quick Actions
        </Typography>
        <Stack spacing={2}>
          <Button
            variant="outlined"
            onClick={() => navigate("/account/settings")}
            fullWidth
            sx={{ justifyContent: "flex-start" }}
          >
            User Settings
          </Button>
          <Button
            variant="outlined"
            onClick={() => navigate("/scouts")}
            fullWidth
            sx={{ justifyContent: "flex-start" }}
          >
            Manage My Scouts
          </Button>
          {account?.isAdmin && (
            <Button
              variant="outlined"
              color="error"
              onClick={() => navigate("/admin")}
              fullWidth
              sx={{ justifyContent: "flex-start" }}
            >
              Admin Console
            </Button>
          )}
        </Stack>
      </Paper>

      {/* Data & Privacy */}
      <Paper sx={{ p: { xs: 2, sm: 3 }, mb: { xs: 2, sm: 3 } }}>
        <Typography variant="h6" gutterBottom>
          Data & Privacy
        </Typography>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Your data is encrypted at rest and in transit. We collect only the
            information necessary to provide the popcorn sales management
            service.
          </Typography>
          <Typography variant="body2" color="text.secondary">
            • Customer names, phone numbers, and addresses are stored securely
          </Typography>
          <Typography variant="body2" color="text.secondary">
            • Order and sales data is private to you and those you explicitly
            share with
          </Typography>
          <Typography variant="body2" color="text.secondary">
            • We do not sell or share your data with third parties
          </Typography>
          <Typography variant="body2" color="text.secondary">
            • Authentication is handled by AWS Cognito with industry-standard
            security
          </Typography>
        </Stack>
      </Paper>

      {/* About */}
      <Paper sx={{ p: { xs: 2, sm: 3 }, mb: { xs: 2, sm: 3 } }}>
        <Typography variant="h6" gutterBottom>
          About KernelWorx
        </Typography>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            KernelWorx is a free, open-source tool built for Scouting America
            volunteers to manage popcorn sales fundraisers.
          </Typography>
          <Typography variant="body2" color="text.secondary">
            <strong>Version:</strong> 1.0.0-beta
          </Typography>
          <Typography variant="body2" color="text.secondary">
            <strong>License:</strong> MIT (Open Source)
          </Typography>
          <Typography variant="body2" color="text.secondary">
            <strong>Repository:</strong>{" "}
            <a
              href="https://github.com/dmeiser/kernelworx"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </a>
          </Typography>
        </Stack>
      </Paper>

      {/* Logout */}
      <Paper
        sx={{
          p: { xs: 2, sm: 3 },
          borderColor: "error.main",
          borderWidth: 1,
          borderStyle: "solid",
        }}
      >
        <Typography variant="h6" gutterBottom color="error">
          Sign Out
        </Typography>
        <Typography variant="body2" color="text.secondary" paragraph>
          Sign out of your account. You'll need to log in again to access your
          data.
        </Typography>
        <Button
          variant="outlined"
          color="error"
          startIcon={<LogoutIcon />}
          onClick={handleLogout}
        >
          Sign Out
        </Button>
      </Paper>
    </Box>
  );
};
