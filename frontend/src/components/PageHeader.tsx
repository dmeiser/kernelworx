/**
 * PageHeader - Consistent page header for authenticated app pages
 *
 * Provides a branded header card with a primary left accent,
 * page title, optional subtitle, optional back button, optional icon,
 * and optional action slot.
 */

import React from 'react';
import { Box, Card, CardContent, Typography, Stack, IconButton, Button } from '@mui/material';
import { ArrowBack as BackIcon, type SvgIconComponent } from '@mui/icons-material';
import { brand } from '../lib/theme';

interface BackButtonProps {
  onClick: () => void;
  label?: string;
  'aria-label'?: string;
}

interface HeaderBackButtonProps {
  backButton: BackButtonProps;
}

const HeaderBackButton: React.FC<HeaderBackButtonProps> = ({ backButton }) => {
  if (backButton.label) {
    return (
      <Button
        startIcon={<BackIcon />}
        onClick={backButton.onClick}
        aria-label={backButton['aria-label']}
        size="small"
        sx={{ mr: 1 }}
      >
        {backButton.label}
      </Button>
    );
  }

  return (
    <IconButton
      onClick={backButton.onClick}
      edge="start"
      aria-label={backButton['aria-label'] ?? 'Back'}
      size="small"
      sx={{ mr: 1 }}
    >
      <BackIcon />
    </IconButton>
  );
};

interface HeaderTitleProps {
  title: string;
  subtitle?: string;
  backButton?: BackButtonProps;
  icon?: SvgIconComponent;
}

const HeaderTitle: React.FC<HeaderTitleProps> = ({ title, subtitle, backButton, icon: Icon }) => (
  <Box>
    <Stack direction="row" alignItems="center" spacing={1}>
      {backButton && <HeaderBackButton backButton={backButton} />}
      {Icon && <Icon sx={{ color: 'text.secondary', verticalAlign: 'bottom', mr: 0.5 }} />}
      <Typography variant="h4" component="h1" sx={{ mb: subtitle ? 0.5 : 0 }}>
        {title}
      </Typography>
    </Stack>
    {subtitle && (
      <Typography variant="body1" sx={{ color: 'text.secondary', mt: 0.5 }}>
        {subtitle}
      </Typography>
    )}
  </Box>
);

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  backButton?: BackButtonProps;
  icon?: SvgIconComponent;
  children?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  action,
  backButton,
  icon,
  children,
}) => (
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
        <HeaderTitle title={title} subtitle={subtitle} backButton={backButton} icon={icon} />
        {action && <Box>{action}</Box>}
      </Stack>
      {children}
    </CardContent>
  </Card>
);
