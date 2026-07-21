/**
 * EmptyState - Consistent empty-state card for lists and sections
 *
 * Provides a centered message with optional title, description, and action button.
 */

import React from 'react';
import { Card, CardContent, Typography, Button, Box } from '@mui/material';
import type { SvgIconComponent } from '@mui/icons-material';

interface EmptyStateActionProps {
  label: string;
  icon?: SvgIconComponent;
  onClick: () => void;
}

const EmptyStateAction: React.FC<EmptyStateActionProps> = ({ label, icon: ActionIcon, onClick }) => (
  <Box>
    <Button variant="contained" startIcon={ActionIcon ? <ActionIcon /> : undefined} onClick={onClick}>
      {label}
    </Button>
  </Box>
);

interface EmptyStateProps {
  title?: string;
  message: string;
  actionLabel?: string;
  actionIcon?: SvgIconComponent;
  onAction?: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, message, actionLabel, actionIcon, onAction }) => (
  <Card variant="outlined" sx={{ textAlign: 'center' }}>
    <CardContent sx={{ p: { xs: 3, sm: 4 }, '&:last-child': { pb: { xs: 3, sm: 4 } } }}>
      {title && (
        <Typography variant="h6" color="text.secondary" gutterBottom>
          {title}
        </Typography>
      )}
      <Typography color="text.secondary" sx={{ mb: actionLabel ? 3 : 0 }}>
        {message}
      </Typography>
      {actionLabel && onAction && (
        <EmptyStateAction label={actionLabel} icon={actionIcon} onClick={onAction} />
      )}
    </CardContent>
  </Card>
);
