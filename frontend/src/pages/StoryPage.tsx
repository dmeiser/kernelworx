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
              Built by a Scout parent who wanted fundraising to be easier for everyone.
            </Typography>
          </Box>

          <Paper elevation={2} sx={{ p: { xs: 3, sm: 4, md: 5 } }}>
            <Stack spacing={3}>
              <Typography variant="body1" color="text.primary">
                I am a parent and den leader. Popcorn season meant tracking orders across paper
                sheets, payment apps, and spreadsheets — and I kept making mistakes.
              </Typography>

              <Typography variant="body1" color="text.primary">
                At pickup sites I would stand there with multiple payment apps open, waiting for QR
                codes to load while supporters waited — sometimes with little or no cell signal. My
                handwriting is not great, so I made mistakes. Then I would spend evenings building a
                spreadsheet just to figure out who had paid with which service and whether anything
                was still owed.
              </Typography>

              <Typography variant="body1" color="text.primary">
                And I was only handling one Scout. Our Pack Kernel had to decipher all of that for
                every youth in the pack, piece together the orders, and make sure the right products
                went to the right families. It was a lot of work for a volunteer, and it made selling
                popcorn harder than it needed to be for parents and Scouts.
              </Typography>

              <Typography variant="body1" color="text.primary">
                I started asking a simple question: how could this whole process be easier — not just
                for me, but for the Pack Kernel, the parents, and the Scouts doing the selling?
              </Typography>

              <Typography variant="body1" color="text.primary">
                KernelWorx is my answer. It brings orders, seller profiles, payments, and reporting
                into one place so nobody has to juggle paper sheets or rebuild spreadsheets by hand.
                As an Eagle Scout and Order of the Arrow Brotherhood member, I care deeply about
                helping Scouting volunteers succeed, and I built KernelWorx with that spirit in mind.
              </Typography>

              <Typography variant="body1" color="text.primary">
                The site is free to use. I have done my best to keep the costs of building and running
                KernelWorx as low as possible. If you find it valuable, you are welcome to sponsor
                development through GitHub Sponsors — it helps defray hosting and development
                expenses. KernelWorx is not a non-profit, so donations are not tax deductible.
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
