/**
 * LandingHeader - Shared header for public marketing pages
 *
 * Sticky frosted-glass header matching the brand landing system.
 * Shows the KernelWorx wordmark and auth-aware CTAs.
 */

import React from 'react';
import { useNavigate, useLocation, Link as RouterLink } from 'react-router-dom';
import { Box, Button, Container, Typography, Link, useMediaQuery, useTheme } from '@mui/material';
import { useAuth } from '../contexts/AuthContext';

interface NavLinkProps {
  href?: string;
  to?: string;
  children: React.ReactNode;
}

const NavLink: React.FC<NavLinkProps> = ({ href, to, children }) => {
  const commonSx = {
    color: 'text.secondary',
    fontWeight: 600,
    fontSize: '0.875rem',
    textDecoration: 'none',
    '&:hover': {
      color: 'text.primary',
    },
  };

  if (to) {
    return (
      <Link component={RouterLink} to={to} sx={commonSx}>
        {children}
      </Link>
    );
  }

  return (
    <Link href={href} sx={commonSx}>
      {children}
    </Link>
  );
};

interface DesktopNavProps {
  isHome: boolean;
}

const DesktopNav: React.FC<DesktopNavProps> = ({ isHome }) => (
  <Box sx={{ display: 'flex', gap: 3.5, alignItems: 'center' }}>
    <NavLink {...(isHome ? { href: '#how-it-works' } : { to: '/#how-it-works' })}>How it works</NavLink>
    <NavLink {...(isHome ? { href: '#features' } : { to: '/#features' })}>Features</NavLink>
    <NavLink to="/story">Our story</NavLink>
    <NavLink {...(isHome ? { href: '#faq' } : { to: '/#faq' })}>FAQ</NavLink>
  </Box>
);

export const LandingHeader: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, logout } = useAuth();
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'));
  const isHome = location.pathname === '/';

  return (
    <Box
      component="header"
      sx={{
        position: 'sticky',
        top: 0,
        zIndex: 20,
        backgroundColor: 'rgba(255, 255, 255, 0.86)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid',
        borderColor: 'grey.200',
      }}
    >
      <Container
        maxWidth="lg"
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: 64,
          gap: 3,
        }}
      >
        <Box
          component="button"
          tabIndex={0}
          sx={{ display: 'flex', alignItems: 'center', gap: 0.5, cursor: 'pointer', background: 'none', border: 'none', padding: 0 }}
          onClick={() => navigate('/')}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate('/'); } }}
        >
          <Box
            component="img"
            src="/logo.svg"
            alt="KernelWorx mark"
            sx={{
              width: { xs: 28, sm: 32, md: 36 },
              height: { xs: 28, sm: 32, md: 36 },
              mr: 1,
            }}
          />
          <Typography
            variant="h6"
            noWrap
            component="div"
            sx={{
              fontFamily: '"Bricolage Grotesque", "Atkinson Hyperlegible", sans-serif',
              fontWeight: 700,
              fontSize: { xs: '1.25rem', sm: '1.35rem' },
              lineHeight: 1,
              letterSpacing: '-0.01em',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            <Box component="span" sx={{ color: 'text.primary' }}>
              Kernel
            </Box>
            <Box component="span" sx={{ color: 'primary.main' }}>
              Worx
            </Box>
          </Typography>
        </Box>

        {isDesktop && <DesktopNav isHome={isHome} />}

        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          {isAuthenticated ? (
            <>
              <Button variant="text" size="small" onClick={() => navigate('/home')}>
                Dashboard
              </Button>
              <Button variant="contained" color="primary" size="small" onClick={logout}>
                Sign out
              </Button>
            </>
          ) : (
            <>
              <Button variant="text" size="small" onClick={() => navigate('/login')}>
                Sign in
              </Button>
              <Button variant="contained" color="primary" size="small" onClick={() => navigate('/login')}>
                Get started
              </Button>
            </>
          )}
        </Box>
      </Container>
    </Box>
  );
};
