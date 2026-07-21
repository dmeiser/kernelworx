/**
 * StoryPage - The origin story of KernelWorx
 *
 * Explains why KernelWorx was built, the real-world popcorn-sale pain points
 * it solves, and how users can support continued development.
 */

import React from 'react';
import { Box, Button, Container, Typography, Card, CardContent, Stack } from '@mui/material';
import { Favorite as FavoriteIcon } from '@mui/icons-material';
import { LandingHeader } from '../components/LandingHeader';
import { LandingFooter } from '../components/LandingFooter';

export const StoryPage: React.FC = () => {
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <LandingHeader />

      {/* Story content */}
      <Container maxWidth="md" sx={{ py: { xs: 4, sm: 6, md: 8 } }}>
        <Stack spacing={{ xs: 4, sm: 5 }}>
          <Box textAlign="center">
            <Typography
              variant="overline"
              component="span"
              sx={{ display: 'block', mb: 1 }}
            >
              Our story
            </Typography>
            <Typography
              variant="h2"
              component="h1"
              gutterBottom
              sx={{
                fontFamily: '"Bricolage Grotesque", "Atkinson Hyperlegible", sans-serif',
                color: 'primary.main',
                fontWeight: 700,
                fontSize: { xs: '2rem', sm: '2.75rem', md: '3.25rem' },
              }}
            >
              The Story of KernelWorx
            </Typography>
            <Typography variant="subtitle1" color="text.secondary">
              Built because popcorn season felt harder than it had to be.
            </Typography>
          </Box>

          <Card>
            <CardContent>
            <Stack spacing={3}>
              <Typography variant="body1" color="text.primary">
                As a parent of a Cub Scout and a Den Leader, I never felt like I had a handle on popcorn season. No
                matter how organized I tried to be, I was juggling paper sales sheets, payment apps, and a spreadsheet
                that never matched the order forms. My own handwriting didn't make the order forms any clearer.
              </Typography>

              <Typography variant="body1" color="text.primary">
                Out selling door-to-door, I'd write down an order, then pull out my phone and fumble between payment
                apps trying to find the right QR code while they waited. Then I'd go home and build a spreadsheet
                because I needed to total up multiple order forms, and the paper sheets made that painful. The
                spreadsheet helped, but it meant retyping every order while trying to decode my own writing.
              </Typography>

              <Typography variant="body1" color="text.primary">
                I was doing this for one Scout. Our Pack Kernel had to repeat this process for every Scout in the Pack —
                paper orders, payments turned in by families, and making sure the Pack's final numbers added up across
                all the individual forms. It was a lot to ask of a volunteer — and it made selling popcorn harder for
                both parents and Scouts.
              </Typography>

              <Typography variant="body1" color="text.primary">
                I started asking a simple question: How could popcorn season be easier — not just for me, but for the
                Pack, the parents, and the Scouts?
              </Typography>

              <Typography variant="body1" color="text.primary">
                KernelWorx is my answer. It brings orders, seller profiles, payments, and reporting into one place so
                nobody has to juggle paper sheets or rebuild spreadsheets by hand. As an Eagle Scout and Order of the
                Arrow Brotherhood member, I built it because I care about helping Scouting volunteers succeed.
              </Typography>

              <Typography variant="body1" color="text.primary">
                The site is free to use — no subscriptions, no paid features. If KernelWorx saves you time or hassle,
                please consider sponsoring through GitHub Sponsors. Any sponsorship helps defray the cost of hosting and
                development. KernelWorx is not a non-profit, so donations are not tax deductible.
              </Typography>
            </Stack>
            </CardContent>
          </Card>

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
      <LandingFooter />
    </Box>
  );
};
