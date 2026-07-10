/**
 * Landing page - Public marketing page for KernelWorx
 *
 * Features:
 * - Hero section with value proposition and CTA
 * - Feature highlights with screenshot/illustration placeholders
 * - How it works steps
 * - Support / sponsorship link
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Container,
  Typography,
  Link,
  Paper,
  Stack,
  Grid,
  Tabs,
  Tab,
} from '@mui/material';
import {
  Login as LoginIcon,
  People as PeopleIcon,
  Share as ShareIcon,
  Assessment as AssessmentIcon,
  Payment as PaymentIcon,
  Favorite as FavoriteIcon,
} from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { LandingHeader } from '../components/LandingHeader';
import { DeviceFrame } from '../components/DeviceFrame';

interface StepProps {
  number: number;
  title: string;
  description: string;
}

const Step: React.FC<StepProps> = ({ number, title, description }) => (
  <Box textAlign="center">
    <Box
      sx={{
        width: 48,
        height: 48,
        borderRadius: '50%',
        bgcolor: 'primary.main',
        color: 'primary.contrastText',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        mx: 'auto',
        mb: 2,
        fontWeight: 700,
        fontSize: '1.25rem',
      }}
    >
      {number}
    </Box>
    <Typography variant="h6" gutterBottom>
      {title}
    </Typography>
    <Typography variant="body2" color="text.secondary">
      {description}
    </Typography>
  </Box>
);

interface FeatureItem {
  title: string;
  description: string;
  icon: React.ReactNode;
  screenshot: string;
  screenshotAlt: string;
  frameVariant: 'iphone' | 'android' | 'browser';
}

interface FeatureShowcaseProps {
  features: FeatureItem[];
}

const FeatureShowcase: React.FC<FeatureShowcaseProps> = ({ features }) => {
  const [activeFeature, setActiveFeature] = React.useState(0);
  const currentFeature = features[activeFeature];

  return (
    <Box>
      <Typography variant="h3" component="h2" textAlign="center" gutterBottom sx={{ fontWeight: 700 }}>
        Everything You Need for Your Fundraiser
      </Typography>
      <Typography
        variant="body1"
        color="text.secondary"
        textAlign="center"
        sx={{ maxWidth: 700, mx: 'auto', mb: 4 }}
      >
        KernelWorx helps Scouting units run smoother popcorn sales from sign-up to final report.
      </Typography>

      <Box sx={{ maxWidth: 720, mx: 'auto' }}>
        <Paper elevation={2} sx={{ borderRadius: 2, overflow: 'hidden' }}>
          <Tabs
            value={activeFeature}
            onChange={(_event, newValue) => setActiveFeature(newValue)}
            variant="fullWidth"
            textColor="primary"
            indicatorColor="primary"
            aria-label="Feature screenshots"
          >
            <Tab icon={<PeopleIcon />} label="Organize" aria-label="Organize Sellers" />
            <Tab icon={<ShareIcon />} label="Collaborate" aria-label="Collaborate" />
            <Tab icon={<PaymentIcon />} label="Track" aria-label="Track Payments" />
            <Tab icon={<AssessmentIcon />} label="Report" aria-label="Report & Export" />
          </Tabs>
          <Box sx={{ p: { xs: 2, sm: 4 }, textAlign: 'center' }}>
            <Stack spacing={3} alignItems="center">
              <Box>
                <Typography variant="h5" component="h3" gutterBottom sx={{ fontWeight: 700 }}>
                  {currentFeature.title}
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  {currentFeature.description}
                </Typography>
              </Box>
              <Box
                sx={{
                  width: '100%',
                  display: 'flex',
                  justifyContent: 'center',
                }}
              >
                <DeviceFrame
                  variant={currentFeature.frameVariant}
                  url={currentFeature.frameVariant === 'browser' ? 'kernelworx.com' : undefined}
                  sx={
                    currentFeature.frameVariant === 'browser'
                      ? { width: '100%' }
                      : { maxWidth: { xs: 260, sm: 320 } }
                  }
                >
                  <Box
                    component="img"
                    src={currentFeature.screenshot}
                    alt={currentFeature.screenshotAlt}
                    sx={{
                      width: '100%',
                      height: currentFeature.frameVariant === 'browser' ? { xs: 260, sm: 480 } : '100%',
                      objectFit: 'cover',
                      objectPosition: 'top left',
                      display: 'block',
                    }}
                  />
                </DeviceFrame>
              </Box>
            </Stack>
          </Box>
        </Paper>
      </Box>
    </Box>
  );
};

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const features: FeatureItem[] = [
    {
      title: 'Organize Your Sellers',
      description:
        'Create and manage multiple Scout profiles. Track each seller\'s campaigns, orders, and progress over time.',
      icon: <PeopleIcon />,
      screenshot: '/marketing/scouts-page-mobile.png',
      screenshotAlt: 'My Scouts page showing seller management',
      frameVariant: 'iphone',
    },
    {
      title: 'Share With Your Unit',
      description:
        'Share profiles with parents and unit leaders with flexible read or write permissions.',
      icon: <ShareIcon />,
      screenshot: '/marketing/collaborate-page-mobile.png',
      screenshotAlt: 'Invite codes for sharing a Scout profile',
      frameVariant: 'android',
    },
    {
      title: 'Flexible Payments',
      description:
        'Set up your custom payment methods, add QR codes for easy access, and mark orders as paid so nothing slips through the cracks.',
      icon: <PaymentIcon />,
      screenshot: '/marketing/payment-methods-page-mobile.png',
      screenshotAlt: 'Payment Methods page showing built-in and custom payment options',
      frameVariant: 'iphone',
    },
    {
      title: 'Run Reports',
      description:
        'Generate detailed sales reports in Excel or CSV format. Track totals, payments, and delivery status.',
      icon: <AssessmentIcon />,
      screenshot: '/marketing/reports-page.png',
      screenshotAlt: 'Sales report with CSV and Excel export buttons',
      frameVariant: 'browser',
    },
  ];

  const handleLogin = () => {
    if (isAuthenticated) {
      navigate('/home');
    } else {
      navigate('/login');
    }
  };

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <LandingHeader />

      {/* Main content */}
      <Container maxWidth="lg" sx={{ mt: { xs: 4, sm: 6, md: 8 }, mb: { xs: 6, sm: 8 } }}>
        <Stack spacing={{ xs: 4, sm: 5, md: 6 }}>
          {/* Hero section */}
          <Box textAlign="center">
            <Typography
              variant="h2"
              component="h1"
              gutterBottom
              sx={{
                fontFamily: '"Kaushan Script", cursive',
                color: 'primary.main',
                fontWeight: 600,
                letterSpacing: '0.08em',
                fontSize: { xs: '2.5rem', sm: '3rem', md: '3.75rem' },
              }}
            >
              Popcorn Sales Made Easy
            </Typography>
            <Typography
              variant="h5"
              color="text.secondary"
              sx={{
                fontFamily: "'Atkinson Hyperlegible', 'Lexend', 'Inter', sans-serif",
                fontWeight: 400,
                maxWidth: 800,
                mx: 'auto',
                mb: 2,
              }}
            >
              Track orders, manage sellers, and generate reports for your Scouting America popcorn sale — all in
              one simple, secure place.
            </Typography>
            <Typography
              variant="subtitle1"
              color="success.dark"
              sx={{
                fontWeight: 600,
                maxWidth: 700,
                mx: 'auto',
                mb: 4,
              }}
            >
              Free: No subscriptions, no paid features.
            </Typography>
            <Button
              variant="contained"
              color="primary"
              size="large"
              startIcon={<LoginIcon />}
              onClick={handleLogin}
              sx={{ px: 4, py: 1.5 }}
            >
              {isAuthenticated ? 'Go to Dashboard' : 'Start Selling Smarter'}
            </Button>
            <Box sx={{ mt: 3, textAlign: 'center' }}>
              <Link
                component="button"
                variant="h5"
                onClick={() => navigate('/story')}
                sx={{
                  color: 'text.secondary',
                  textDecoration: 'underline',
                  p: 0,
                  fontWeight: 400,
                  lineHeight: 1.2,
                  textTransform: 'none',
                  cursor: 'pointer',
                  background: 'none',
                  border: 'none',
                }}
              >
                Read the story behind KernelWorx
              </Link>
            </Box>
          </Box>

          {/* Hero screenshot */}
          <DeviceFrame variant="browser" url="kernelworx.com">
            <Box
              component="img"
              src="/marketing/home-page.png"
              alt="KernelWorx dashboard preview"
              sx={{
                width: '100%',
                height: { xs: 220, sm: 320, md: 420 },
                objectFit: 'cover',
                objectPosition: 'top left',
                display: 'block',
              }}
            />
          </DeviceFrame>

          {/* Features */}
          <FeatureShowcase features={features} />

          {/* How it works */}
          <Paper elevation={2} sx={{ p: { xs: 3, sm: 4, md: 6 } }}>
            <Typography variant="h3" component="h2" textAlign="center" gutterBottom sx={{ fontWeight: 700 }}>
              How It Works
            </Typography>
            <Grid container spacing={4} sx={{ mt: 2 }}>
              <Grid size={{ xs: 12, sm: 4 }}>
                <Step
                  number={1}
                  title="Create Your Unit"
                  description="Sign up, add your Scouts, and set up your first fundraising campaign in minutes."
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 4 }}>
                <Step
                  number={2}
                  title="Take Orders"
                  description="Record customer orders, payment methods, and delivery details as sales come in."
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 4 }}>
                <Step
                  number={3}
                  title="Share & Report"
                  description="Collaborate with your unit and export reports for unit submission or parent reconciliation."
                />
              </Grid>
            </Grid>
          </Paper>

          {/* Final CTA */}
          <Box textAlign="center">
            <Typography variant="h3" component="h2" gutterBottom sx={{ fontWeight: 700 }}>
              Ready to simplify your popcorn sale?
            </Typography>
            <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
              Start managing your fundraiser with KernelWorx.
            </Typography>
            <Button
              variant="contained"
              color="primary"
              size="large"
              startIcon={<LoginIcon />}
              onClick={handleLogin}
              sx={{ px: 4, py: 1.5 }}
            >
              {isAuthenticated ? 'Go to Dashboard' : 'Get Started Free'}
            </Button>
          </Box>

          {/* Footer */}
          <Box textAlign="center" sx={{ pt: 4, pb: 4 }}>
            <Typography variant="body2" color="text.secondary">
              Built with ❤️ for Scouting America parents
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Free to use • MIT License
            </Typography>
            <Stack
              direction="row"
              spacing={2}
              justifyContent="center"
              sx={{ mt: 1 }}
            >
              <Button
                onClick={() => navigate('/story')}
                variant="text"
                size="small"
                sx={{ textTransform: 'none', color: 'text.secondary', textDecoration: 'underline' }}
              >
                Our Story
              </Button>
              <Button
                onClick={() => navigate('/privacy')}
                variant="text"
                size="small"
                sx={{ textTransform: 'none', color: 'text.secondary', textDecoration: 'underline' }}
              >
                Privacy Policy
              </Button>
              <Button
                href="https://github.com/sponsors/dmeiser"
                target="_blank"
                rel="noopener noreferrer"
                variant="text"
                size="small"
                startIcon={<FavoriteIcon />}
                sx={{ textTransform: 'none', color: 'text.secondary', textDecoration: 'underline' }}
              >
                Sponsor KernelWorx
              </Button>
            </Stack>
          </Box>
        </Stack>
      </Container>

    </Box>
  );
};
