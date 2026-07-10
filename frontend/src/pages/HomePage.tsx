/**
 * HomePage - Private landing page for authenticated users
 *
 * Features:
 * - Welcome message with user's display name
 * - News & Updates section (placeholder for future announcements)
 * - Quick-action tiles to common destinations
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Typography,
  Paper,
  Grid,
  Card,
  CardActionArea,
  CardContent,
  Stack,
} from '@mui/material';
import PersonIcon from '@mui/icons-material/Person';
import PaymentIcon from '@mui/icons-material/Payment';
import InventoryIcon from '@mui/icons-material/Inventory';
import CampaignIcon from '@mui/icons-material/Campaign';
import { useAuth } from '../contexts/AuthContext';

interface QuickActionTileProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  onClick: () => void;
}

const QuickActionTile: React.FC<QuickActionTileProps> = ({ title, description, icon, onClick }) => (
  <Card elevation={2}>
    <CardActionArea onClick={onClick} sx={{ height: '100%' }}>
      <CardContent>
        <Stack spacing={1} alignItems="flex-start">
          <Box sx={{ color: 'primary.main' }}>{icon}</Box>
          <Typography variant="h6" component="h2" gutterBottom>
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {description}
          </Typography>
        </Stack>
      </CardContent>
    </CardActionArea>
  </Card>
);

export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const { account } = useAuth();

  const displayName = React.useMemo(() => {
    if (!account) return '';
    const { givenName, familyName, email } = account;
    if (givenName && familyName) return `${givenName} ${familyName}`;
    return givenName || email;
  }, [account]);

  return (
    <Box>
      <Typography variant="h4" component="h1" gutterBottom>
        Welcome back{displayName ? `, ${displayName.split(' ')[0]}` : ''}
      </Typography>

      {/* News & Updates */}
      <Paper sx={{ p: { xs: 2, sm: 3 }, mb: { xs: 3, sm: 4 } }}>
        <Typography variant="h5" component="h2" gutterBottom>
          News & Updates
        </Typography>
        <Typography variant="body1" color="text.secondary">
          You&apos;re all set. Watch this space for announcements, new features, and tips for managing
          your popcorn sales.
        </Typography>
      </Paper>

      {/* Quick Actions */}
      <Typography variant="h5" component="h2" gutterBottom>
        Quick Actions
      </Typography>
      <Grid container spacing={3}>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <QuickActionTile
            title="My Scouts"
            description="View and manage your seller profiles."
            icon={<PersonIcon fontSize="large" />}
            onClick={() => navigate('/scouts')}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <QuickActionTile
            title="Payment Methods"
            description="Set up how buyers can pay you."
            icon={<PaymentIcon fontSize="large" />}
            onClick={() => navigate('/payment-methods')}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <QuickActionTile
            title="Catalogs"
            description="Browse available product catalogs."
            icon={<InventoryIcon fontSize="large" />}
            onClick={() => navigate('/catalogs')}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <QuickActionTile
            title="Shared Campaigns"
            description="Join or manage shared fundraising campaigns."
            icon={<CampaignIcon fontSize="large" />}
            onClick={() => navigate('/shared-campaigns')}
          />
        </Grid>
      </Grid>
    </Box>
  );
};
