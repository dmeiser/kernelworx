/**
 * Landing page - Public page that describes the application
 *
 * Features:
 * - App description and value proposition
 * - Login button in top right
 * - Branding from BRANDING_GUIDE.html
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  Container,
  Typography,
  Paper,
  Stack,
  AppBar,
  Toolbar,
} from "@mui/material";
import { Login as LoginIcon } from "@mui/icons-material";
import { useAuth } from "../contexts/AuthContext";

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const handleLogin = () => {
    if (isAuthenticated) {
      navigate("/profiles");
    } else {
      navigate("/login");
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      {/* Header with login button */}
      <AppBar position="static" color="primary" elevation={1}>
        <Toolbar>
          <Box sx={{ display: "flex", alignItems: "center", flexGrow: 1 }}>
            <Box
              component="img"
              src="/logo.svg"
              alt="Popcorn kernel"
              sx={{
                width: { xs: "28px", sm: "32px", md: "40px" },
                height: { xs: "28px", sm: "32px", md: "40px" },
                mr: { xs: 0.5, sm: 1 },
              }}
            />
            <Typography
              variant="h6"
              noWrap
              component="div"
              sx={{
                fontFamily: '"Kaushan Script", cursive',
                fontWeight: 600,
                letterSpacing: "0.08em",
                fontSize: { xs: "28px", sm: "32px", md: "40px" },
                lineHeight: 1,
                color: "white",
                WebkitTextStroke: "0.8px rgba(255, 255, 255, 0.8)",
                textShadow:
                  "0 1px 0 rgba(255,255,255,0.12), 0 2px 0 rgba(255,255,255,0.06)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              KernelWorx
            </Typography>
          </Box>
          <Button
            variant="contained"
            color="secondary"
            startIcon={<LoginIcon />}
            onClick={handleLogin}
          >
            {isAuthenticated ? "Go to Profiles" : "Login"}
          </Button>
        </Toolbar>
      </AppBar>

      {/* Main content */}
      <Container maxWidth="md" sx={{ mt: 8, mb: 8 }}>
        <Stack spacing={4}>
          {/* Hero section */}
          <Box textAlign="center">
            <Typography
              variant="h2"
              component="h1"
              gutterBottom
              sx={{
                fontFamily: '"Kaushan Script", cursive',
                color: "primary.main",
                fontWeight: 600,
                letterSpacing: "0.08em",
                fontSize: { xs: "2.5rem", sm: "3rem", md: "3.75rem" },
              }}
            >
              Popcorn Sales Made Easy
            </Typography>
            <Typography
              variant="h5"
              color="text.secondary"
              sx={{
                fontFamily:
                  "'Atkinson Hyperlegible', 'Lexend', 'Inter', sans-serif",
                fontWeight: 400,
              }}
            >
              Track orders, manage sellers, and generate reports for your
              Scouting America popcorn fundraiser
            </Typography>
          </Box>

          {/* Features */}
          <Paper elevation={2} sx={{ p: 4 }}>
            <Stack spacing={3}>
              <Box>
                <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
                  🍿 Organize Your Sales
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  Create seller profiles, track multiple seasons, and manage all
                  your popcorn orders in one place.
                </Typography>
              </Box>

              <Box>
                <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
                  🤝 Collaborate with Others
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  Share seller profiles with parents, den leaders, or unit
                  volunteers. Set read-only or edit permissions.
                </Typography>
              </Box>

              <Box>
                <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
                  📊 Generate Reports
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  Export detailed sales reports in Excel or CSV format. Track
                  totals, payment methods, and delivery status.
                </Typography>
              </Box>

              <Box>
                <Typography variant="h6" gutterBottom sx={{ fontWeight: 700 }}>
                  🔒 Secure & Private
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  Your data is encrypted and stored securely in AWS. Sign in
                  with Google, Facebook, or Apple.
                </Typography>
              </Box>
            </Stack>
          </Paper>

          {/* COPPA Warning */}
          <Paper
            elevation={1}
            sx={{
              p: 3,
              bgcolor: "warning.light",
              borderLeft: 4,
              borderColor: "warning.main",
            }}
          >
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
              ⚠️ Age Requirement (COPPA Compliance)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              You must be at least 13 years old to create an account. If you are
              under 13, please ask a parent or guardian to create an account and
              manage your sales.
            </Typography>
          </Paper>

          {/* CTA */}
          <Box textAlign="center" sx={{ pt: 2 }}>
            <Button
              variant="contained"
              color="primary"
              size="large"
              startIcon={<LoginIcon />}
              onClick={handleLogin}
              sx={{ px: 4, py: 1.5 }}
            >
              {isAuthenticated ? "Go to My Profiles" : "Get Started"}
            </Button>
          </Box>

          {/* Footer */}
          <Box textAlign="center" sx={{ pt: 4, pb: 4 }}>
            <Typography variant="body2" color="text.secondary">
              Built with ❤️ for Scouting America volunteers
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Open source • MIT License • Free to use
            </Typography>
          </Box>
        </Stack>
      </Container>
    </Box>
  );
};
