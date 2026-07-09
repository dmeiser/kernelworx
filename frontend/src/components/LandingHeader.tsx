/**
 * LandingHeader - Shared header for public marketing pages
 *
 * Shows the KernelWorx logo and a primary CTA that adapts based on auth state.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AppBar, Toolbar, Box, Typography, Button } from '@mui/material';
import { Login as LoginIcon } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';

export const LandingHeader: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const handleLogin = () => {
    if (isAuthenticated) {
      navigate('/home');
    } else {
      navigate('/login');
    }
  };

  return (
    <AppBar position="static" color="primary" elevation={1}>
      <Toolbar>
        <Box sx={{ display: 'flex', alignItems: 'center', flexGrow: 1, cursor: 'pointer' }} onClick={() => navigate('/')}>
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
  );
};
