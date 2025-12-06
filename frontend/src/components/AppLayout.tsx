import React from 'react';
import { 
  AppBar, 
  Box, 
  Toolbar, 
  Typography, 
  IconButton, 
  Button, 
  Drawer, 
  List, 
  ListItemText, 
  ListItemButton, 
  Container,
  useMediaQuery,
  useTheme
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import { useAuth } from '../contexts/AuthContext';
import { Toast } from './Toast';
import { Outlet } from 'react-router-dom';

export const AppLayout: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const { account, logout } = useAuth();
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

  const toggleDrawer = () => setDrawerOpen(!drawerOpen);

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', flexDirection: 'column' }}>
      <AppBar position="static" color="primary">
        <Container maxWidth="lg" disableGutters>
          <Toolbar sx={{ px: { xs: 2, sm: 3 } }}>
            {/* Menu button */}
            <IconButton 
              edge="start" 
              color="inherit" 
              aria-label="menu" 
              onClick={toggleDrawer}
              sx={{ mr: 2 }}
            >
              <MenuIcon />
            </IconButton>

            {/* Title - responsive sizing and spacing */}
            <Typography
              variant="h6"
              component="div"
              sx={{ 
                fontFamily: 'Satisfy, Open Sans, cursive', 
                fontWeight: 600, 
                letterSpacing: '0.08em',
                fontSize: { xs: '1.1rem', sm: '1.3rem', md: '1.5rem' },
                flexGrow: 1,
                textAlign: { xs: 'left', sm: 'center' },
                mr: { xs: 0, sm: 2 }
              }}
            >
              🍿 Popcorn Sales Manager
            </Typography>

            {/* User info and logout - responsive display */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {!isMobile && account && (
                <Typography variant="body2" sx={{ mr: 1 }}>
                  {account.displayName}
                </Typography>
              )}
              <Button 
                color="inherit" 
                onClick={logout}
                size={isMobile ? 'small' : 'medium'}
              >
                {isMobile ? 'Logout' : 'Log out'}
              </Button>
            </Box>
          </Toolbar>
        </Container>
      </AppBar>

      <Drawer anchor="left" open={drawerOpen} onClose={toggleDrawer}>
        <Box sx={{ width: 250 }} role="presentation" onClick={toggleDrawer}>
          <List>
            <ListItemButton>
              <ListItemText primary="Profiles" />
            </ListItemButton>
            <ListItemButton>
              <ListItemText primary="Seasons" />
            </ListItemButton>
            <ListItemButton>
              <ListItemText primary="Reports" />
            </ListItemButton>
            <ListItemButton>
              <ListItemText primary="Catalogs" />
            </ListItemButton>
          </List>
        </Box>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1 }}>
        <Container maxWidth="lg" sx={{ py: { xs: 2, sm: 3, md: 4 } }}>
          {children}
          <Outlet />
        </Container>
      </Box>

      <Toast />
    </Box>
  );
};
