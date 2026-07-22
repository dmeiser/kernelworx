/**
 * Landing page - Public marketing page for KernelWorx
 *
 * Built from the brand landing system in docs/branding/system/artifacts/landing.html,
 * populated with KernelWorx product content.
 */

import React from 'react';
import { useNavigate, Link as RouterLink } from 'react-router-dom';
import {
  Box,
  Button,
  Container,
  Typography,
  Grid,
  Card,
  CardContent,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Link,
  useTheme,
} from '@mui/material';
import {
  Assessment as AssessmentIcon,
  Check as CheckIcon,
  Add as AddIcon,
  Favorite as FavoriteIcon,
} from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { LandingHeader } from '../components/LandingHeader';
import { LandingFooter } from '../components/LandingFooter';
import { DeviceFrame } from '../components/DeviceFrame';
import { brand } from '../lib/theme';

const SectionHead: React.FC<{ kicker?: string; title: string; subtitle: string }> = ({
  kicker,
  title,
  subtitle,
}) => (
  <Box sx={{ maxWidth: 680, mx: 'auto', mb: 6, textAlign: 'center' }}>
    {kicker && (
      <Typography
        variant="overline"
        component="span"
        sx={{ display: 'block', mb: 1 }}
      >
        {kicker}
      </Typography>
    )}
    <Typography variant="h2" gutterBottom>
      {title}
    </Typography>
    <Typography variant="body1" sx={{ color: 'text.secondary', fontSize: '1.125rem' }}>
      {subtitle}
    </Typography>
  </Box>
);

const ValueCard: React.FC<{ icon: React.ReactNode; title: string; description: string }> = ({
  icon,
  title,
  description,
}) => (
  <Card sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
    <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
      <Box
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 44,
          height: 44,
          borderRadius: '12px',
          bgcolor: 'primary.main',
          color: 'primary.contrastText',
        }}
      >
        {icon}
      </Box>
      <Typography variant="h5">{title}</Typography>
      <Typography variant="body2" sx={{ color: 'text.secondary' }}>
        {description}
      </Typography>
    </CardContent>
  </Card>
);

const StepCard: React.FC<{ number: number; title: string; description: string; illustration: React.ReactNode }> = ({
  number,
  title,
  description,
  illustration,
}) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
    <Box
      sx={{
        aspectRatio: '124/108',
        bgcolor: 'transparent',
        p: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {illustration}
    </Box>
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <Box
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 26,
            height: 26,
            borderRadius: '50%',
            bgcolor: 'primary.main',
            color: 'white',
            fontSize: '0.75rem',
            fontWeight: 600,
          }}
        >
          {number}
        </Box>
        <Typography variant="h5">{title}</Typography>
      </Box>
      <Typography variant="body2" sx={{ color: 'text.secondary', maxWidth: '34ch' }}>
        {description}
      </Typography>
    </Box>
  </Box>
);

const FeatureZig: React.FC<{
  kicker: string;
  title: string;
  description: string;
  image: string;
  imageAlt: string;
  reverse?: boolean;
}> = ({ kicker, title, description, image, imageAlt, reverse }) => (
  <Grid container spacing={{ xs: 3, md: 6, lg: 9 }} alignItems="center">
    <Grid size={{ xs: 12, md: 6 }} order={{ xs: 2, md: reverse ? 2 : 1 }}>
      <Typography variant="overline" component="span" sx={{ display: 'block', mb: 1 }}>
        {kicker}
      </Typography>
      <Typography variant="h3" gutterBottom>
        {title}
      </Typography>
      <Typography variant="body1" sx={{ color: 'text.secondary', fontSize: '1.125rem', maxWidth: '46ch' }}>
        {description}
      </Typography>
    </Grid>
    <Grid size={{ xs: 12, md: 6 }} order={{ xs: 1, md: reverse ? 1 : 2 }}>
      <DeviceFrame variant="browser" url="kernelworx.com">
        <Box
          component="img"
          src={image}
          alt={imageAlt}
          sx={{ width: '100%', height: { xs: 220, sm: 320, md: 360 }, objectFit: 'cover', objectPosition: 'top left' }}
        />
      </DeviceFrame>
    </Grid>
  </Grid>
);

const faqs = [
  {
    question: 'What is KernelWorx?',
    answer:
      'KernelWorx helps parents of Scouting America Scouts manage their Scout\'s popcorn sales. It brings seller profiles, orders, payments, and reporting into one place so nobody has to juggle paper sheets or rebuild spreadsheets by hand.',
  },
  {
    question: 'Is KernelWorx really free?',
    answer:
      'Yes. The site is free to use — no subscriptions, no paid features. It is volunteer-run and open-source under the MIT license.',
  },
  {
    question: 'How do I share a Scout profile with another parent or leader?',
    answer:
      'From any seller profile, send an invite code or share the profile directly by email. You choose whether the recipient gets read-only or full write access, and you can revoke access at any time.',
  },
  {
    question: 'Is my data secure?',
    answer:
      'Your data is stored in AWS with encryption in transit and at rest. KernelWorx does not sell or share your personal information. You can delete your account and all associated data at any time from Account Settings.',
  },
  {
    question: 'How do I delete my account and data?',
    answer: (
      <>
        You can delete your account from{' '}
        <Link component={RouterLink} to="/account/settings">
          Account Settings
        </Link>
        , or email{' '}
        <Link href="mailto:privacy@kernelworx.app">privacy@kernelworx.app</Link> for assistance.
      </>
    ),
  },
];

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const theme = useTheme();

  const primaryCta = isAuthenticated ? 'Go to Dashboard' : 'Get started';
  const handlePrimaryCta = () => navigate(isAuthenticated ? '/home' : '/login');

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <LandingHeader />

      <Box component="main">
        {/* Hero */}
        <Container
          maxWidth="lg"
          sx={{
            pt: { xs: 7, sm: 9, md: 12 },
            pb: { xs: 4, md: 6 },
            textAlign: 'center',
          }}
        >
          <Box sx={{ maxWidth: 860, mx: 'auto' }}>
            <Typography variant="h1" sx={{ mt: 0, mb: 2, maxWidth: '24ch', mx: 'auto' }}>
              Use it on your own.
              <br />
              Use it with the Pack.
            </Typography>
            <Typography
              variant="body1"
              sx={{
                fontSize: '1.375rem',
                color: 'text.secondary',
                maxWidth: '62ch',
                mx: 'auto',
                mb: 4,
                lineHeight: 1.5,
              }}
            >
              Track orders, manage sellers, and generate reports for your Scouting America popcorn sale — all in one
              simple, secure place.
            </Typography>
            <Box sx={{ display: 'flex', gap: 1.5, justifyContent: 'center', flexWrap: 'wrap', mb: 2 }}>
              <Button variant="contained" color="primary" size="large" onClick={handlePrimaryCta}>
                {primaryCta}
              </Button>
              <Button
                variant="outlined"
                color="primary"
                size="large"
                component="a"
                href="#how-it-works"
              >
                See how it works
              </Button>
            </Box>
            <Typography variant="caption" sx={{ color: 'text.tertiary' }}>
              Always free · 2-minute setup
            </Typography>
          </Box>

          <Box sx={{ maxWidth: 980, mx: 'auto', mt: { xs: 5, md: 7 } }}>
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
                }}
              />
            </DeviceFrame>
          </Box>
        </Container>

        {/* Trust */}
        <Container maxWidth="lg" sx={{ py: 2 }}>
          <Typography variant="body2" sx={{ textAlign: 'center', color: 'text.secondary' }}>
            Made by a Scout parent, for Scout parents.
          </Typography>
        </Container>

        {/* Problem */}
        <Box sx={{ py: { xs: 8, md: 12 } }}>
          <Container maxWidth="lg">
            <SectionHead
              kicker="Popcorn season"
              title="It's a lot to keep straight."
              subtitle="Most units still juggle paper forms, mixed payments, and the same question: are we sure these numbers are right?"
            />
            <Grid container spacing={{ xs: 2, md: 2.5 }}>
              {[
                {
                  title: 'Orders start on paper',
                  text: 'Paper forms travel through backpacks, cars, and kitchens before they reach you.',
                },
                {
                  title: 'Payments pile up',
                  text: 'Cash, checks, Venmo, QR codes — every family pays differently, and you have to keep track.',
                },
                {
                  title: 'The count never matches',
                  text: 'You add everything up, and the total is different every time.',
                },
              ].map((item) => (
                <Grid key={item.title} size={{ xs: 12, md: 4 }}>
                  <Card sx={{ height: '100%' }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
                        <Box
                          sx={{
                            flex: '0 0 auto',
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            mt: 1,
                            bgcolor: 'error.main',
                          }}
                        />
                        <Box>
                          <Typography variant="h5" sx={{ mb: 0.5, fontSize: '1.125rem' }}>
                            {item.title}
                          </Typography>
                          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                            {item.text}
                          </Typography>
                        </Box>
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </Container>
        </Box>

        {/* Value pillars */}
        <Box
          sx={{
            py: { xs: 8, md: 12 },
            bgcolor: 'background.paper',
            borderTop: '1px solid',
            borderBottom: '1px solid',
            borderColor: 'grey.200',
          }}
        >
          <Container maxWidth="lg">
            <SectionHead
              kicker="What KernelWorx does"
              title="One place for the whole sale."
              subtitle="Seller profiles, orders, and payments — together, so you can focus on helping your Scout."
            />
            <Grid container spacing={{ xs: 2, md: 3 }}>
              <Grid size={{ xs: 12, md: 4 }}>
                <ValueCard
                  icon={<CheckIcon sx={{ fontSize: 22 }} />}
                  title="Seller profiles"
                  description="Create a profile for each Scout. Track orders, payments, and progress without the paper."
                />
              </Grid>
              <Grid size={{ xs: 12, md: 4 }}>
                <ValueCard
                  icon={<AddIcon sx={{ fontSize: 22 }} />}
                  title="Orders and payments together"
                  description="Record the order, log the payment, and see who paid with cash, check, or an app — all in one place."
                />
              </Grid>
              <Grid size={{ xs: 12, md: 4 }}>
                <ValueCard
                  icon={<AssessmentIcon sx={{ fontSize: 22 }} />}
                  title="Reports when you need them"
                  description="See totals and payments at a glance. Export to Excel or CSV for your Scout, or work with your unit to run one report for the whole Pack."
                />
              </Grid>
            </Grid>
          </Container>
        </Box>

        {/* How it works */}
        <Box id="how-it-works" sx={{ py: { xs: 8, md: 12 } }}>
          <Container maxWidth="lg">
            <SectionHead
              kicker="How it works"
              title="Up and running in three steps"
              subtitle="Set up your unit, add your Scouts, and start selling."
            />
            <Grid container spacing={{ xs: 3, md: 4, lg: 6 }}>
              <Grid size={{ xs: 12, sm: 4 }}>
                <StepCard
                  number={1}
                  title="Create your unit"
                  description="Sign up, add your Scouts, and set up your first fundraising campaign in minutes."
                  illustration={
                    <svg viewBox="0 0 124 108" width="100%" height="100%" aria-hidden="true">
                      <rect x="14" y="40" width="92" height="9" rx="4.5" fill={theme.palette.text.secondary} />
                      <rect x="14" y="58" width="58" height="9" rx="4.5" fill={theme.palette.text.secondary} />
                      <rect x="14" y="80" width="40" height="14" rx="7" fill={theme.palette.primary.main} />
                    </svg>
                  }
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 4 }}>
                <StepCard
                  number={2}
                  title="Take orders"
                  description="Record customer orders, payment methods, and delivery details as sales come in."
                  illustration={
                    <svg viewBox="0 0 124 108" width="100%" height="100%" aria-hidden="true">
                      <rect
                        x="14"
                        y="38"
                        width="44"
                        height="38"
                        rx="6"
                        fill="none"
                        stroke={theme.palette.text.secondary}
                        strokeWidth="2"
                      />
                      <rect
                        x="66"
                        y="38"
                        width="44"
                        height="38"
                        rx="6"
                        fill="none"
                        stroke={theme.palette.primary.main}
                        strokeWidth="2"
                      />
                      <rect x="14" y="84" width="96" height="9" rx="4.5" fill={theme.palette.text.secondary} />
                    </svg>
                  }
                />
              </Grid>
              <Grid size={{ xs: 12, sm: 4 }}>
                <StepCard
                  number={3}
                  title="Share & report"
                  description="Collaborate with your unit and export reports for unit submission or parent reconciliation."
                  illustration={
                    <svg viewBox="0 0 124 108" width="100%" height="100%" aria-hidden="true">
                      <path
                        d="M16 70l20 16 28-44"
                        fill="none"
                        stroke={theme.palette.primary.main}
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      <rect x="72" y="44" width="38" height="9" rx="4.5" fill={theme.palette.text.secondary} />
                      <rect x="72" y="64" width="26" height="9" rx="4.5" fill={theme.palette.text.secondary} />
                    </svg>
                  }
                />
              </Grid>
            </Grid>
          </Container>
        </Box>

        {/* Mid-page CTA */}
        <Container maxWidth="lg" sx={{ pb: { xs: 7, md: 10 } }}>
          <Box
            sx={{
              bgcolor: 'grey.50',
              border: '1px solid',
              borderColor: 'grey.200',
              borderRadius: { xs: '14px', md: '20px' },
              p: { xs: 3, md: 5 },
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 3,
              flexWrap: 'wrap',
            }}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="h3" sx={{ fontSize: { xs: '1.25rem', md: '1.625rem' }, mb: 0.5 }}>
                Set up your unit in minutes
              </Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                Always free · 2-minute setup
              </Typography>
            </Box>
            <Button variant="contained" color="primary" size="large" onClick={handlePrimaryCta}>
              {primaryCta}
            </Button>
          </Box>
        </Container>

        {/* Features */}
        <Box
          id="features"
          sx={{
            py: { xs: 8, md: 12 },
            bgcolor: 'background.paper',
            borderTop: '1px solid',
            borderBottom: '1px solid',
            borderColor: 'grey.200',
          }}
        >
          <Container maxWidth="lg">
            <SectionHead
              kicker="A closer look"
              title="Built for the way real units work"
              subtitle="Designed to save time for parents, Scouts, and Pack volunteers."
            />
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: { xs: 6, md: 10, lg: 14 } }}>
              <FeatureZig
                kicker="Seller profiles"
                title="Organize your sellers"
                description="Create and manage multiple Scout profiles. Track each seller's campaigns, orders, and progress over time."
                image="/marketing/scouts-page.png"
                imageAlt="My Scouts page showing seller management"
              />
              <FeatureZig
                kicker="Collaboration"
                title="Share with your unit"
                description="Share profiles with parents and unit leaders with flexible read or write permissions. Invite codes make it easy."
                image="/marketing/collaborate-page.png"
                imageAlt="Invite codes for sharing a Scout profile"
                reverse
              />
              <FeatureZig
                kicker="Payments"
                title="Flexible payments"
                description="Set up custom payment methods, add QR codes for easy access, and mark orders as paid so nothing slips through the cracks."
                image="/marketing/payment-methods-page.png"
                imageAlt="Payment Methods page showing built-in and custom payment options"
              />
              <FeatureZig
                kicker="Reports"
                title="Run reports"
                description="Generate detailed sales reports in Excel or CSV format. Track totals, payments, and delivery status for any campaign."
                image="/marketing/reports-page.png"
                imageAlt="Sales report with CSV and Excel export buttons"
                reverse
              />
            </Box>
          </Container>
        </Box>

        {/* Stats band */}
        <Box sx={{ bgcolor: brand.primary[9], py: { xs: 6, md: 8 } }}>
          <Container maxWidth="lg">
            <Grid container spacing={4}>
              {[
                { value: '$0', label: 'Always free' },
                { value: '100%', label: 'Open source (MIT)' },
                { value: '2 min', label: 'Setup time' },
              ].map((stat) => (
                <Grid key={stat.label} size={{ xs: 6, sm: 4 }}>
                  <Box sx={{ textAlign: 'center' }}>
                    <Typography
                      variant="h2"
                      sx={{
                        fontSize: { xs: '1.75rem', md: '2.5rem' },
                        color: 'white',
                        lineHeight: 1.05,
                        letterSpacing: '-0.02em',
                      }}
                    >
                      {stat.value}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.5, color: 'white' }}>
                      {stat.label}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </Container>
        </Box>

        {/* FAQ */}
        <Box
          id="faq"
          sx={{
            py: { xs: 8, md: 12 },
            bgcolor: 'background.paper',
            borderBottom: '1px solid',
            borderColor: 'grey.200',
          }}
        >
          <Container maxWidth="md">
            <SectionHead
              kicker="Before you ask"
              title="Your questions, answered"
              subtitle=""
            />
            {faqs.map((faq, index) => (
              <Accordion key={index} defaultExpanded={index === 0}>
                <AccordionSummary expandIcon={<AddIcon sx={{ color: 'primary.main' }} />}>
                  <Typography variant="h6" sx={{ fontSize: '1.125rem' }}>
                    {faq.question}
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    {faq.answer}
                  </Typography>
                </AccordionDetails>
              </Accordion>
            ))}
          </Container>
        </Box>

        {/* Final CTA */}
        <Container maxWidth="lg" sx={{ py: { xs: 8, md: 12 } }}>
          <Box
            sx={{
              bgcolor: brand.primary[9],
              borderRadius: { xs: '18px', md: '28px' },
              p: { xs: 5, md: 8 },
              textAlign: 'center',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <Box
              sx={{
                position: 'absolute',
                top: -100,
                right: -90,
                width: 320,
                height: 320,
                borderRadius: '50%',
                bgcolor: 'primary.light',
                opacity: 0.5,
              }}
            />
            <Box
              sx={{
                position: 'absolute',
                bottom: -120,
                left: -80,
                width: 260,
                height: 260,
                borderRadius: '50%',
                bgcolor: 'primary.dark',
                opacity: 0.45,
              }}
            />
            <Box sx={{ position: 'relative' }}>
              <Typography
                variant="h2"
                sx={{
                  color: 'white',
                  fontSize: { xs: '1.75rem', md: '2.75rem' },
                  lineHeight: 1.08,
                  mb: 2,
                  maxWidth: '20ch',
                  mx: 'auto',
                }}
              >
                Start selling smarter with KernelWorx today
              </Typography>
              <Typography
                variant="body1"
                sx={{
                  color: 'white',
                  fontSize: '1.125rem',
                  maxWidth: 540,
                  mx: 'auto',
                  mb: 4,
                }}
              >
                Built for parents and Units. Use it on your own or with the whole pack.
              </Typography>
              <Box sx={{ display: 'flex', gap: 1.5, justifyContent: 'center', flexWrap: 'wrap' }}>
                <Button
                  variant="contained"
                  size="large"
                  onClick={handlePrimaryCta}
                  sx={{ bgcolor: 'white', color: 'primary.main', '&:hover': { bgcolor: 'grey.100' } }}
                >
                  {primaryCta}
                </Button>
                <Button
                  variant="text"
                  size="large"
                  component="a"
                  href="https://github.com/sponsors/dmeiser"
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{ color: 'white', '&:hover': { color: 'white', bgcolor: 'transparent' } }}
                  startIcon={<FavoriteIcon />}
                >
                  Sponsor KernelWorx
                </Button>
              </Box>
              <Typography variant="caption" sx={{ display: 'block', mt: 2, color: 'white' }}>
                Always free · Open source
              </Typography>
            </Box>
          </Box>
        </Container>
      </Box>

      <LandingFooter />
    </Box>
  );
};
