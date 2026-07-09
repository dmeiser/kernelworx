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
  Paper,
  Stack,
  AppBar,
  Toolbar,
  Grid,
  Card,
  CardContent,
  Dialog,
  DialogContent,
  IconButton,
} from '@mui/material';
import {
  Login as LoginIcon,
  People as PeopleIcon,
  Share as ShareIcon,
  Assessment as AssessmentIcon,
  Code as CodeIcon,
  Payment as PaymentIcon,
  Favorite as FavoriteIcon,
  Close as CloseIcon,
  ZoomIn as ZoomInIcon,
} from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';

interface FeatureCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  screenshot?: string;
  screenshotAlt?: string;
  onScreenshotClick?: (src: string, alt: string) => void;
}

const FeatureCard: React.FC<FeatureCardProps> = ({
  title,
  description,
  icon,
  screenshot,
  screenshotAlt,
  onScreenshotClick,
}) => (
  <Card elevation={2} sx={{ height: '100%' }}>
    <CardContent>
      <Stack spacing={2}>
        <Box
          sx={{
            p: 2,
            bgcolor: 'primary.light',
            borderRadius: 2,
            display: 'inline-flex',
            color: 'primary.contrastText',
          }}
        >
          {icon}
        </Box>
        <Typography variant="h6" component="h2" gutterBottom sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {description}
        </Typography>
        {screenshot ? (
          <Box
            onClick={() => onScreenshotClick?.(screenshot, screenshotAlt || title)}
            sx={{
              mt: 2,
              position: 'relative',
              borderRadius: 1,
              border: '1px solid',
              borderColor: 'divider',
              overflow: 'hidden',
              cursor: 'pointer',
              '&:hover .zoom-overlay': {
                opacity: 1,
              },
              '&:hover img': {
                transform: 'scale(1.02)',
              },
            }}
          >
            <Box
              component="img"
              src={screenshot}
              alt={screenshotAlt || title}
              sx={{
                width: '100%',
                height: 160,
                objectFit: 'cover',
                objectPosition: 'top left',
                display: 'block',
                transition: 'transform 0.2s ease-in-out',
              }}
            />
            <Box
              className="zoom-overlay"
              sx={{
                position: 'absolute',
                inset: 0,
                bgcolor: 'rgba(0, 0, 0, 0.4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                opacity: 0,
                transition: 'opacity 0.2s ease-in-out',
              }}
            >
              <ZoomInIcon sx={{ color: 'white', fontSize: 32 }} />
            </Box>
          </Box>
        ) : (
          <Box
            sx={{
              mt: 2,
              height: 160,
              bgcolor: 'action.hover',
              borderRadius: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px dashed',
              borderColor: 'divider',
            }}
          >
            <Typography variant="caption" color="text.disabled">
              Screenshot coming soon
            </Typography>
          </Box>
        )}
      </Stack>
    </CardContent>
  </Card>
);

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

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [lightboxOpen, setLightboxOpen] = React.useState(false);
  const [lightboxImage, setLightboxImage] = React.useState<{ src: string; alt: string } | null>(null);

  const handleLogin = () => {
    if (isAuthenticated) {
      navigate('/home');
    } else {
      navigate('/login');
    }
  };

  const handleScreenshotClick = (src: string, alt: string) => {
    setLightboxImage({ src, alt });
    setLightboxOpen(true);
  };

  const handleCloseLightbox = () => {
    setLightboxOpen(false);
    setLightboxImage(null);
  };

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      {/* Header with login button */}
      <AppBar position="static" color="primary" elevation={1}>
        <Toolbar>
          <Box sx={{ display: 'flex', alignItems: 'center', flexGrow: 1 }}>
            <Box
              component="img"
              src="/logo.svg"
              alt="Popcorn kernel"
              sx={{
                width: { xs: '28px', sm: '32px', md: '40px' },
                height: { xs: '28px', sm: '32px', md: '40px' },
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
                letterSpacing: '0.08em',
                fontSize: { xs: '28px', sm: '32px', md: '40px' },
                lineHeight: 1,
                color: 'white',
                WebkitTextStroke: '0.8px rgba(255, 255, 255, 0.8)',
                textShadow: '0 1px 0 rgba(255,255,255,0.12), 0 2px 0 rgba(255,255,255,0.06)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              KernelWorx
            </Typography>
          </Box>
          <Button variant="contained" color="secondary" startIcon={<LoginIcon />} onClick={handleLogin}>
            {isAuthenticated ? 'Go to Dashboard' : 'Get Started'}
          </Button>
        </Toolbar>
      </AppBar>

      {/* Main content */}
      <Container maxWidth="lg" sx={{ mt: { xs: 4, sm: 6, md: 8 }, mb: { xs: 6, sm: 8 } }}>
        <Stack spacing={{ xs: 6, sm: 8, md: 10 }}>
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
                mb: 4,
              }}
            >
              Track orders, manage sellers, and generate reports for your Scouting America popcorn fundraiser — all in
              one simple, secure place.
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
          </Box>

          {/* Hero screenshot */}
          <Paper
            elevation={3}
            sx={{
              p: 1,
              borderRadius: 2,
              overflow: 'hidden',
              border: '1px solid',
              borderColor: 'divider',
            }}
          >
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
          </Paper>

          {/* Features */}
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
              KernelWorx helps Scouting America volunteers run smoother popcorn sales from sign-up to final report.
            </Typography>
            <Grid container spacing={3}>
              <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
                <FeatureCard
                  title="Organize Sellers"
                  description="Create and manage multiple scout profiles. Track each seller's campaigns, orders, and progress over time."
                  icon={<PeopleIcon />}
                  screenshot="/marketing/scouts-page.png"
                  screenshotAlt="My Scouts page showing seller management"
                  onScreenshotClick={handleScreenshotClick}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
                <FeatureCard
                  title="Collaborate"
                  description="Share profiles with parents, den leaders, and volunteers with flexible read or write permissions."
                  icon={<ShareIcon />}
                  screenshot="/marketing/collaborate-page.png"
                  screenshotAlt="Invite codes for sharing a scout profile"
                  onScreenshotClick={handleScreenshotClick}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
                <FeatureCard
                  title="Track Payments"
                  description="Set up custom payment methods with optional QR codes so buyers can pay the way that works best."
                  icon={<PaymentIcon />}
                  screenshot="/marketing/payment-methods-page.png"
                  screenshotAlt="Payment Methods page showing built-in and custom payment options"
                  onScreenshotClick={handleScreenshotClick}
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
                <FeatureCard
                  title="Report & Export"
                  description="Generate detailed sales reports in Excel or CSV format. Track totals, payments, and delivery status."
                  icon={<AssessmentIcon />}
                  screenshot="/marketing/reports-page.png"
                  screenshotAlt="Sales report with CSV and Excel export buttons"
                  onScreenshotClick={handleScreenshotClick}
                />
              </Grid>
            </Grid>
          </Box>

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
                  description="Sign up, add your scouts, and set up your first fundraising campaign in minutes."
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
                  description="Collaborate with your team and export reports for unit submission or parent reconciliation."
                />
              </Grid>
            </Grid>
          </Paper>

          {/* Open Source */}
          <Paper
            elevation={1}
            sx={{
              p: { xs: 3, sm: 4 },
              bgcolor: 'success.light',
              display: 'flex',
              alignItems: 'center',
              gap: 3,
              flexDirection: { xs: 'column', sm: 'row' },
              textAlign: { xs: 'center', sm: 'left' },
            }}
          >
            <CodeIcon sx={{ fontSize: 48, color: 'success.dark' }} />
            <Box>
              <Typography variant="h6" gutterBottom>
                Free & Open Source
              </Typography>
              <Typography variant="body2" color="text.secondary">
                KernelWorx is built by volunteers and released under the MIT License. No subscriptions, no hidden fees,
                and no lock-in. If you find it useful, you can even contribute or sponsor development on GitHub.
              </Typography>
            </Box>
          </Paper>

          {/* Final CTA */}
          <Box textAlign="center">
            <Typography variant="h3" component="h2" gutterBottom sx={{ fontWeight: 700 }}>
              Ready to simplify your popcorn sale?
            </Typography>
            <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
              Join the open beta and start managing your fundraiser with KernelWorx.
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
              Built with ❤️ for Scouting America volunteers
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Open source • MIT License • Free to use
            </Typography>
            <Stack
              direction="row"
              spacing={2}
              justifyContent="center"
              sx={{ mt: 1 }}
            >
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

      {/* Screenshot lightbox */}
      <Dialog
        open={lightboxOpen}
        onClose={handleCloseLightbox}
        maxWidth="lg"
        fullWidth
        PaperProps={{ sx: { bgcolor: 'background.paper', borderRadius: 2 } }}
      >
        <Box sx={{ position: 'relative' }}>
          <IconButton
            onClick={handleCloseLightbox}
            sx={{
              position: 'absolute',
              top: 8,
              right: 8,
              bgcolor: 'rgba(0, 0, 0, 0.5)',
              color: 'white',
              '&:hover': { bgcolor: 'rgba(0, 0, 0, 0.7)' },
              zIndex: 1,
            }}
            aria-label="Close screenshot preview"
          >
            <CloseIcon />
          </IconButton>
          <DialogContent sx={{ p: 1 }}>
            {lightboxImage && (
              <Box
                component="img"
                src={lightboxImage.src}
                alt={lightboxImage.alt}
                sx={{
                  width: '100%',
                  height: 'auto',
                  maxHeight: '80vh',
                  objectFit: 'contain',
                  display: 'block',
                  borderRadius: 1,
                }}
              />
            )}
          </DialogContent>
        </Box>
      </Dialog>
    </Box>
  );
};
