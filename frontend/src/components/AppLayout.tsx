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
  useTheme,
  Divider
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import { useAuth } from '../contexts/AuthContext';
import { Toast } from './Toast';
import { Outlet } from 'react-router-dom';

const DRAWER_WIDTH = 240;

export const AppLayout: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const { account, logout } = useAuth();
  const [mobileDrawerOpen, setMobileDrawerOpen] = React.useState(false);
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'));

  const toggleMobileDrawer = () => setMobileDrawerOpen(!mobileDrawerOpen);

  const drawerContent = (
    <Box>
      <Toolbar />
      <Divider />
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
  );

  return (
    <Box sx={{ display: 'flex' }}>
      {/* Full-width AppBar */}
      <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
        <Container maxWidth="xl">
          <Toolbar disableGutters>
            {!isDesktop && (
              <IconButton
                color="inherit"
                aria-label="open drawer"
                edge="start"
                onClick={toggleMobileDrawer}
                sx={{ mr: 2 }}
              >
                <MenuIcon />
              </IconButton>
            )}
            
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

            {!isDesktop && account && (
              <Typography variant="body2" sx={{ mr: 2, display: { xs: 'none', sm: 'block' } }}>
                {account.displayName}
              </Typography>
            )}

            {isDesktop && account && (
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

      {/* Navigation Drawer - Persistent on desktop, temporary on mobile */}
      {isDesktop ? (
        <Drawer
          variant="permanent"
          sx={{
            width: DRAWER_WIDTH,
            flexShrink: 0,
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              boxSizing: 'border-box',
            },
          }}
        >
          {drawerContent}
        </Drawer>
      ) : (
        <Drawer
          variant="temporary"
          anchor="left"
          open={mobileDrawerOpen}
          onClose={toggleMobileDrawer}
          ModalProps={{ keepMounted: true }}
          sx={{
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              boxSizing: 'border-box',
            },
          }}
        >
          {drawerContent}
        </Drawer>
      )}

      {/* Main Content */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          bgcolor: 'background.default',
          minHeight: '100vh',
        }}
      >
        <Toolbar />
        <Container maxWidth="lg" sx={{ py: 4 }}>
          {children}
          <Outlet />
        </Container>
      </Box>

      <Toast />
    </Box>
  );
};
