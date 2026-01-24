/**
 * Privacy Policy Page - Public page
 *
 * Required for social login providers (Google, Facebook)
 * Includes privacy policy and data deletion instructions
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Container,
  Typography,
  Paper,
  AppBar,
  Toolbar,
  Button,
  Divider,
  List,
  ListItem,
  ListItemText,
} from '@mui/material';
import { ArrowBack as ArrowBackIcon, Delete as DeleteIcon } from '@mui/icons-material';

export const PrivacyPolicyPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      {/* Header */}
      <AppBar position="static" color="primary" elevation={1}>
        <Toolbar>
          <Button color="inherit" startIcon={<ArrowBackIcon />} onClick={() => navigate('/')}>
            Home
          </Button>
          <Box sx={{ display: 'flex', alignItems: 'center', flexGrow: 1, ml: 2 }}>
            <Box
              component="img"
              src="/logo.svg"
              alt="Popcorn kernel"
              sx={{
                width: { xs: '28px', sm: '32px' },
                height: { xs: '28px', sm: '32px' },
                mr: 1,
              }}
            />
            <Typography
              variant="h6"
              component="div"
              sx={{
                fontFamily: '"Kaushan Script", cursive',
                fontWeight: 600,
                fontSize: { xs: '1.1rem', sm: '1.25rem' },
              }}
            >
              Popcorn Sales Manager
            </Typography>
          </Box>
        </Toolbar>
      </AppBar>

      {/* Main Content */}
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Paper elevation={2} sx={{ p: { xs: 2, sm: 4 } }}>
          <Typography variant="h4" component="h1" gutterBottom fontWeight={600}>
            Privacy Policy
          </Typography>

          <Typography variant="body2" color="text.secondary" gutterBottom sx={{ mb: 3 }}>
            Last Updated: January 23, 2026
          </Typography>

          <Divider sx={{ mb: 3 }} />

          {/* Introduction */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            About This Service
          </Typography>
          <Typography variant="body1" paragraph>
            Popcorn Sales Manager is a volunteer-run application designed to help Scouting America units manage their
            popcorn fundraising campaigns. This service is provided free of charge to support youth development
            programs.
          </Typography>

          {/* Information We Collect */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            Information We Collect
          </Typography>
          <Typography variant="body1" paragraph>
            We collect only the information necessary to provide the service:
          </Typography>
          <List dense>
            <ListItem>
              <ListItemText
                primary="Account Information"
                secondary="Email address, name, and authentication credentials (if using email/password login)"
              />
            </ListItem>
            <ListItem>
              <ListItemText
                primary="Seller Profiles"
                secondary="Names of Scouts you create profiles for (first name, last name, optional unit/den information)"
              />
            </ListItem>
            <ListItem>
              <ListItemText
                primary="Campaign Data"
                secondary="Product catalogs, orders, customer information (names, amounts), and sales reports"
              />
            </ListItem>
            <ListItem>
              <ListItemText
                primary="Social Login"
                secondary="If you use Google or Facebook to sign in, we receive your email and name from those providers"
              />
            </ListItem>
          </List>

          {/* How We Use Information */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            How We Use Your Information
          </Typography>
          <Typography variant="body1" paragraph>
            Your information is used solely to:
          </Typography>
          <List dense>
            <ListItem>
              <ListItemText primary="Provide the popcorn sales management service" />
            </ListItem>
            <ListItem>
              <ListItemText primary="Allow you to track and manage fundraising campaigns" />
            </ListItem>
            <ListItem>
              <ListItemText primary="Enable sharing of profiles with other adult leaders (when you grant permission)" />
            </ListItem>
            <ListItem>
              <ListItemText primary="Generate sales reports and QR codes for payment collection" />
            </ListItem>
          </List>

          {/* Data Storage */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            Data Storage and Security
          </Typography>
          <Typography variant="body1" paragraph>
            Your data is stored securely in AWS (Amazon Web Services) using industry-standard encryption. We do not
            sell, rent, or share your personal information with third parties except as required to operate the service
            (e.g., AWS hosting).
          </Typography>

          {/* COPPA Compliance */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            Children's Privacy (COPPA)
          </Typography>
          <Typography variant="body1" paragraph>
            This service is designed for use by adults (parents, guardians, and unit leaders) aged 13 and older. We do
            not knowingly collect personal information from children under 13. Scout profiles created by adults do not
            require the Scout to have an account or login.
          </Typography>

          {/* Data Retention */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            Data Retention
          </Typography>
          <Typography variant="body1" paragraph>
            We retain your data for as long as you maintain an active account. You may delete your account and all
            associated data at any time (see "Your Data Deletion Rights" below).
          </Typography>

          {/* Third-Party Services */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            Third-Party Services
          </Typography>
          <Typography variant="body1" paragraph>
            We use the following third-party services:
          </Typography>
          <List dense>
            <ListItem>
              <ListItemText
                primary="Amazon Web Services (AWS)"
                secondary="Cloud hosting, database, authentication (Cognito), and file storage"
              />
            </ListItem>
            <ListItem>
              <ListItemText
                primary="Google Sign-In (optional)"
                secondary="Social login authentication - subject to Google's privacy policy"
              />
            </ListItem>

          </List>

          <Divider sx={{ my: 4 }} />

          {/* Data Deletion Section */}
          <Box sx={{ bgcolor: 'error.50', p: 3, borderRadius: 1, border: '1px solid', borderColor: 'error.200' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
              <DeleteIcon color="error" sx={{ mr: 1 }} />
              <Typography variant="h5" component="h2" fontWeight={600} color="error.main">
                Your Data Deletion Rights
              </Typography>
            </Box>

            <Typography variant="body1" paragraph>
              You have the right to delete your account and all associated data at any time. This will permanently
              remove:
            </Typography>

            <List dense>
              <ListItem>
                <ListItemText primary="Your account and login credentials" />
              </ListItem>
              <ListItem>
                <ListItemText primary="All seller profiles you created" />
              </ListItem>
              <ListItem>
                <ListItemText primary="All campaigns, orders, and customer data" />
              </ListItem>
              <ListItem>
                <ListItemText primary="All reports and uploaded files (QR codes, etc.)" />
              </ListItem>
              <ListItem>
                <ListItemText primary="All shares and invitations" />
              </ListItem>
            </List>

            <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
              How to Delete Your Data
            </Typography>

            <Typography variant="body1" paragraph fontWeight={600}>
              Option 1: Self-Service (Recommended)
            </Typography>
            <List dense sx={{ mb: 2 }}>
              <ListItem>
                <ListItemText primary="1. Log in to your account" />
              </ListItem>
              <ListItem>
                <ListItemText primary="2. Go to Settings (click your profile icon in the top right)" />
              </ListItem>
              <ListItem>
                <ListItemText primary="3. Click 'Account Settings'" />
              </ListItem>
              <ListItem>
                <ListItemText primary="4. Scroll to the bottom and click 'Delete My Account'" />
              </ListItem>
              <ListItem>
                <ListItemText primary="5. Confirm the deletion (this action cannot be undone)" />
              </ListItem>
            </List>

            <Typography variant="body1" paragraph fontWeight={600}>
              Option 2: Contact Us
            </Typography>
            <Typography variant="body1" paragraph>
              If you're unable to access your account or prefer assistance, send an email to:
            </Typography>
            <Typography
              variant="body1"
              sx={{ fontFamily: 'monospace', bgcolor: 'background.paper', p: 1, borderRadius: 1, display: 'inline-block' }}
            >
              privacy@kernelworx.app
            </Typography>
            <Typography variant="body1" paragraph sx={{ mt: 2, fontWeight: 600, color: 'error.main' }}>
              ⚠️ Important: You must send the email from the email address registered to your account. We verify account
              deletion requests by email address only.
            </Typography>

            <Typography variant="body2" color="text.secondary" sx={{ mt: 2, fontStyle: 'italic' }}>
              Note: Account deletion is permanent and cannot be undone. Please export any reports you need before
              deleting your account.
            </Typography>
          </Box>

          <Divider sx={{ my: 4 }} />

          {/* Contact */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            Contact Us
          </Typography>
          <Typography variant="body1" paragraph>
            If you have questions about this privacy policy or your data, please contact us at:
          </Typography>
          <Typography
            variant="body1"
            sx={{ fontFamily: 'monospace', bgcolor: 'background.paper', p: 1, borderRadius: 1, display: 'inline-block' }}
          >
            privacy@kernelworx.app
          </Typography>

          {/* Changes to Policy */}
          <Typography variant="h6" gutterBottom fontWeight={600} sx={{ mt: 3 }}>
            Changes to This Policy
          </Typography>
          <Typography variant="body1" paragraph>
            We may update this privacy policy from time to time. The "Last Updated" date at the top will reflect any
            changes. Continued use of the service after changes constitutes acceptance of the updated policy.
          </Typography>

          {/* Volunteer Service Notice */}
          <Box sx={{ bgcolor: 'info.50', p: 2, borderRadius: 1, border: '1px solid', borderColor: 'info.200', mt: 4 }}>
            <Typography variant="body2" color="text.secondary">
              <strong>Volunteer Service:</strong> This application is provided as a free volunteer service to support
              Scouting America fundraising activities. While we strive to maintain the highest standards of data
              security and privacy, this service is provided "as is" without warranties.
            </Typography>
          </Box>
        </Paper>
      </Container>
    </Box>
  );
};
