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
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  const toggleDrawer = () => setDrawerOpen(!drawerOpen);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* Full-width AppBar */}
      <AppBar position="static">
        <Container maxWidth="lg">
          <Toolbar disableGutters sx={{ minHeight: 64 }}>
            <IconButton
              color="inherit"
              aria-label="open drawer"
              edge="start"
              onClick={toggleDrawer}
              sx={{ mr: 2 }}
            >
              <MenuIcon />
            </IconButton>
            
            <Typography
              variant="h6"
              noWrap
              component="div"
              sx={{
                flexGrow: 1,
                fontFamily: '"Satisfy", cursive',
                fontWeight: 600,
                letterSpacing: '0.08em',
                fontSize: { xs: '1.25rem', sm: '1.5rem' },
              }}
            >
              🍿 Popcorn Sales Manager
            </Typography>

            {!isMobile && account && (
              <Typography variant="body2" sx={{ mr: 2 }}>
                {account.displayName}
              </Typography>
            )}
            
            <Button color="inherit" onClick={logout}>
              Log out
            </Button>
          </Toolbar>
        </Container>
      </AppBar>

      {/* Navigation Drawer */}
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

      {/* Main Content */}
      <Box component="main" sx={{ flexGrow: 1, bgcolor: 'background.default' }}>
        <Container maxWidth="lg" sx={{ py: 4 }}>
          {children}
          <Outlet />
        </Container>
      </Box>

      <Toast />
    </Box>
  );
};
