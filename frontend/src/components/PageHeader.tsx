/**
 * PageHeader - Consistent page header for authenticated app pages
 *
 * Provides a branded header card with a primary left accent,
 * page title, optional subtitle, and optional action slot.
 */

import React from 'react';
import { Box, Card, CardContent, Typography, Stack } from '@mui/material';
import { brand } from '../lib/theme';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({ title, subtitle, action, children }) => (
  <Card
    sx={{
      mb: { xs: 3, sm: 4 },
      borderLeft: `4px solid ${brand.primary[6]}`,
      borderRadius: brand.radius.lg,
      boxShadow: `0 1px 2px ${brand.fill.quaternary}`,
    }}
  >
    <CardContent sx={{ p: { xs: 2, sm: 3 }, '&:last-child': { pb: { xs: 2, sm: 3 } } }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        spacing={2}
      >
        <Box>
          <Typography variant="h4" component="h1" sx={{ mb: subtitle ? 0.5 : 0 }}>
            {title}
          </Typography>
          {subtitle && (
            <Typography variant="body1" sx={{ color: 'text.secondary' }}>
              {subtitle}
            </Typography>
          )}
        </Box>
        {action && <Box>{action}</Box>}
      </Stack>
      {children}
    </CardContent>
  </Card>
);
