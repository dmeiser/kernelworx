/**
 * StoryPage - The origin story of KernelWorx
 *
 * Explains why KernelWorx was built, the real-world popcorn-sale pain points
 * it solves, and how users can support continued development.
 */

import React from 'react';
import {
  Box,
  Button,
  Container,
  Typography,
  Paper,
  Stack,
} from '@mui/material';
import { Favorite as FavoriteIcon } from '@mui/icons-material';
import { LandingHeader } from '../components/LandingHeader';

export const StoryPage: React.FC = () => {
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <LandingHeader />

      {/* Story content */}
      <Container maxWidth="md" sx={{ py: { xs: 4, sm: 6, md: 8 } }}>
        <Stack spacing={{ xs: 4, sm: 5 }}>
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
                fontSize: { xs: '2rem', sm: '2.75rem', md: '3.25rem' },
              }}
            >
              The Story of KernelWorx
            </Typography>
            <Typography variant="subtitle1" color="text.secondary">
              Built because popcorn season felt harder than it had to be.
            </Typography>
          </Box>

          <Paper elevation={2} sx={{ p: { xs: 3, sm: 4, md: 5 } }}>
            <Stack spacing={3}>
              <Typography variant="body1" color="text.primary">
                As a parent of a Cub Scout and a Den Leader, I never felt like I had a handle on
                popcorn season. No matter how organized I tried to be, I was still juggling paper
                sales sheets, payment apps, and a spreadsheet that never matched the actual orders.
              </Typography>

              <Typography variant="body1" color="text.primary">
                Out selling door-to-door, I'd write down an order, then pull out my phone and fumble
                between payment apps trying to find the right QR code while they waited.
                Then I'd go home and build a spreadsheet because I couldn't keep doing the paper
                sheets and I needed the numbers. My handwriting didn't help — I'd transpose numbers,
                lose names, and create more work for myself.
              </Typography>

              <Typography variant="body1" color="text.primary">
                I was doing this for one Scout. Our Pack Kernel had to make sense of it for every
                youth in the pack — paper orders, payments families turned in, and making sure the
                right products ended up with the right families. It was a lot to ask of a volunteer —
                and it made selling popcorn harder for both parents and Scouts.
              </Typography>

              <Typography variant="body1" color="text.primary">
                I started asking a simple question: How could popcorn season be easier — not just
                for me, but for the Pack Kernel, the parents, and the Scouts?
              </Typography>

              <Typography variant="body1" color="text.primary">
                KernelWorx is my answer. It brings orders, seller profiles, payments, and reporting
                into one place so nobody has to juggle paper sheets or rebuild spreadsheets by hand.
                As an Eagle Scout and Order of the Arrow Brotherhood member, I built it because I
                care about helping Scouting volunteers succeed.
              </Typography>

              <Typography variant="body1" color="text.primary">
                The site is free to use — no subscriptions, no paid features. If KernelWorx saves
                you time or hassle, please consider sponsoring through GitHub Sponsors. Any
                sponsorship helps defray the cost of hosting and development. KernelWorx is not a
                non-profit, so donations are not tax deductible.
              </Typography>
            </Stack>
          </Paper>

          <Box textAlign="center">
            <Button
              variant="contained"
              color="primary"
              size="large"
              startIcon={<FavoriteIcon />}
              href="https://github.com/sponsors/dmeiser"
              target="_blank"
              rel="noopener noreferrer"
              sx={{ px: 4, py: 1.5 }}
            >
              Sponsor KernelWorx
            </Button>
          </Box>
        </Stack>
      </Container>
    </Box>
  );
};
