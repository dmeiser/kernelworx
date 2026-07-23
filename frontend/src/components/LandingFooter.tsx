/**
 * LandingFooter - Shared footer for public marketing pages
 *
 * Includes the KernelWorx wordmark, product/project/resources links,
 * and a copyright line.
 */

import type { FC } from 'react';
import { Box, Container, Grid, Typography, Link } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';

export const LandingFooter: FC = () => (
  <Box
    component="footer"
    sx={{
      bgcolor: 'background.paper',
      borderTop: '1px solid',
      borderColor: 'grey.200',
      py: { xs: 6, md: 8 },
    }}
  >
    <Container maxWidth="lg">
      <Grid container spacing={4}>
        <Grid size={{ xs: 12, sm: 6, md: 4 }}>
          <Typography
            variant="h6"
            sx={{
              fontFamily: '"Bricolage Grotesque", "Atkinson Hyperlegible", sans-serif',
              fontWeight: 700,
              fontSize: '1.25rem',
              lineHeight: 1,
              letterSpacing: '-0.01em',
            }}
          >
            <Box component="span" sx={{ color: 'text.primary' }}>
              Kernel
            </Box>
            <Box component="span" sx={{ color: 'primary.main' }}>
              Worx
            </Box>
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.tertiary', maxWidth: '36ch', mt: 1.5 }}>
            Track orders, manage sellers, and generate reports for your Scouting America popcorn sale — all in one
            simple, secure place.
          </Typography>
        </Grid>
        <Grid size={{ xs: 6, sm: 3, md: 2 }}>
          <Typography
            variant="subtitle2"
            sx={{
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'text.tertiary',
              mb: 2,
            }}
          >
            Product
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Link component={RouterLink} to="/#how-it-works" sx={{ color: 'text.secondary', fontWeight: 400 }}>
              How it works
            </Link>
            <Link component={RouterLink} to="/#features" sx={{ color: 'text.secondary', fontWeight: 400 }}>
              Features
            </Link>
            <Link component={RouterLink} to="/story" sx={{ color: 'text.secondary', fontWeight: 400 }}>
              Our story
            </Link>
            <Link component={RouterLink} to="/#faq" sx={{ color: 'text.secondary', fontWeight: 400 }}>
              FAQ
            </Link>
          </Box>
        </Grid>
        <Grid size={{ xs: 6, sm: 3, md: 2 }}>
          <Typography
            variant="subtitle2"
            sx={{
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'text.tertiary',
              mb: 2,
            }}
          >
            Project
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Link
              href="https://github.com/sponsors/dmeiser"
              target="_blank"
              rel="noopener noreferrer"
              sx={{ color: 'text.secondary', fontWeight: 400 }}
            >
              Sponsor
            </Link>
            <Link
              href="https://github.com/dmeiser/kernelworx"
              target="_blank"
              rel="noopener noreferrer"
              sx={{ color: 'text.secondary', fontWeight: 400 }}
            >
              Source
            </Link>
          </Box>
        </Grid>
        <Grid size={{ xs: 6, sm: 3, md: 2 }}>
          <Typography
            variant="subtitle2"
            sx={{
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'text.tertiary',
              mb: 2,
            }}
          >
            Resources
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Link component={RouterLink} to="/privacy" sx={{ color: 'text.secondary', fontWeight: 400 }}>
              Privacy
            </Link>
            <Link href="mailto:privacy@kernelworx.app" sx={{ color: 'text.secondary', fontWeight: 400 }}>
              Contact
            </Link>
          </Box>
        </Grid>
      </Grid>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 2,
          flexWrap: 'wrap',
          mt: 6,
          pt: 3,
          borderTop: '1px solid',
          borderColor: 'grey.200',
          fontSize: '0.75rem',
          color: 'text.tertiary',
        }}
      >
        <span>&copy; KernelWorx · Popcorn Sales Made Easy</span>
      </Box>
    </Container>
  </Box>
);
