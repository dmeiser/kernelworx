/**
 * SettingsPage - User account settings and preferences
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@apollo/client/react";
import {
  Box,
  Typography,
  Paper,
  Stack,
  Button,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Alert,
  Chip,
  CircularProgress,
} from "@mui/material";
import {
  Person as PersonIcon,
  Email as EmailIcon,
  AdminPanelSettings as AdminIcon,
  Logout as LogoutIcon,
  Info as InfoIcon,
} from "@mui/icons-material";
import { useAuth } from "../contexts/AuthContext";
import { GET_MY_ACCOUNT } from "../lib/graphql";

interface Account {
  accountId: string;
  email: string;
  isAdmin: boolean;
  createdAt: string;
  updatedAt: string;
}

export const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const { logout } = useAuth();

  const {
    data: accountData,
    loading,
    error,
  } = useQuery<{ getMyAccount: Account }>(GET_MY_ACCOUNT);

  const account = accountData?.getMyAccount;

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  if (loading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="400px"
      >
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error">
        Failed to load account information: {error.message}
      </Alert>
    );
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <Box>
      <Typography variant="h4" component="h1" gutterBottom>
        Account Settings
      </Typography>

      {/* Account Information */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Account Information
        </Typography>
        <List>
          <ListItem>
            <ListItemIcon>
              <PersonIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Account ID"
              secondary={account?.accountId.substring(0, 16) + "..."}
            />
          </ListItem>
          <Divider component="li" />
          <ListItem>
            <ListItemIcon>
              <EmailIcon color="primary" />
            </ListItemIcon>
            <ListItemText primary="Email Address" secondary={account?.email} />
          </ListItem>
          <Divider component="li" />
          <ListItem>
            <ListItemIcon>
              <AdminIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Account Type"
              secondary={
                <Stack
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  component="span"
                  sx={{ display: "inline-flex" }}
                >
                  <span>
                    {account?.isAdmin ? "Administrator" : "Standard User"}
                  </span>
                  {account?.isAdmin && (
                    <Chip label="Admin" color="error" size="small" />
                  )}
                </Stack>
              }
              secondaryTypographyProps={{ component: "span" }}
            />
          </ListItem>
          <Divider component="li" />
          <ListItem>
            <ListItemIcon>
              <InfoIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Account Created"
              secondary={
                account?.createdAt ? formatDate(account.createdAt) : "Unknown"
              }
            />
          </ListItem>
          <Divider component="li" />
          <ListItem>
            <ListItemIcon>
              <InfoIcon color="primary" />
            </ListItemIcon>
            <ListItemText
              primary="Last Updated"
              secondary={
                account?.updatedAt ? formatDate(account.updatedAt) : "Unknown"
              }
            />
          </ListItem>
        </List>
      </Paper>

      {/* Quick Actions */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Quick Actions
        </Typography>
        <Stack spacing={2}>
          <Button
            variant="outlined"
            onClick={() => navigate("/account/security")}
            fullWidth
            sx={{ justifyContent: "flex-start" }}
          >
            Account Security (Password & MFA)
          </Button>
          <Button
            variant="outlined"
            onClick={() => navigate("/profiles")}
            fullWidth
            sx={{ justifyContent: "flex-start" }}
          >
            Manage Seller Profiles
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
      <Paper sx={{ p: 3, mb: 3 }}>
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
      <Paper sx={{ p: 3, mb: 3 }}>
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
              href="https://github.com/dmeiser/popcorn-sales-manager"
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
          p: 3,
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
