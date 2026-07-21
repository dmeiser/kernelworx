import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
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
  ListItemIcon,
  Container,
  useMediaQuery,
  useTheme,
  Divider,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import HomeIcon from '@mui/icons-material/Home';
import PersonIcon from '@mui/icons-material/Person';
import SettingsIcon from '@mui/icons-material/Settings';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import InventoryIcon from '@mui/icons-material/Inventory';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import LogoutIcon from '@mui/icons-material/Logout';
import CardGiftcardIcon from '@mui/icons-material/CardGiftcard';
import AssessmentIcon from '@mui/icons-material/Assessment';
import CampaignIcon from '@mui/icons-material/Campaign';
import PaymentIcon from '@mui/icons-material/Payment';
import { useAuth } from '../contexts/AuthContext';
import { Toast } from './Toast';
import { Outlet } from 'react-router-dom';
import { LIST_MY_SHARED_CAMPAIGNS } from '../lib/graphql';
import { brand, displayFont } from '../lib/theme';

const DRAWER_WIDTH = 240;

const drawerPaperSx = {
  width: DRAWER_WIDTH,
  boxSizing: 'border-box',
  backgroundColor: brand.background.container,
  borderRight: `1px solid ${brand.border.main}`,
};

const navItemSx = {
  borderRadius: brand.radius.md,
  color: brand.text.primary,
  mx: 1,
  px: 1.5,
  '& .MuiListItemIcon-root': {
    color: brand.text.secondary,
    minWidth: 36,
  },
  '&:hover': {
    backgroundColor: brand.fill.tertiary,
  },
  '&.Mui-selected': {
    backgroundColor: brand.primary[6],
    color: '#ffffff',
    '& .MuiListItemIcon-root': {
      color: '#ffffff',
    },
    '& .MuiListItemText-primary': {
      color: '#ffffff',
      fontWeight: 600,
    },
  },
  '&.Mui-selected:hover': {
    backgroundColor: brand.primary[7],
  },
};

const adminNavItemSx = {
  borderRadius: brand.radius.md,
  color: brand.error.main,
  mx: 1,
  px: 1.5,
  '& .MuiListItemIcon-root': {
    color: brand.error.main,
    minWidth: 36,
  },
  '&:hover': {
    backgroundColor: brand.error.bg,
  },
  '&.Mui-selected': {
    backgroundColor: brand.error.bg,
    color: brand.error.active,
    '& .MuiListItemIcon-root': {
      color: brand.error.active,
    },
  },
};

const sectionDividerSx = {
  my: 1.5,
  mx: 2,
  borderColor: brand.border.secondary,
};

const DrawerContent: React.FC<{
  onNavigate: (path: string) => void;
  isActive: (path: string) => boolean;
  hasSharedCampaigns: boolean;
  isAdmin: boolean;
  displayName: string;
  onLogout: () => void;
}> = ({ onNavigate, isActive, hasSharedCampaigns, isAdmin, displayName, onLogout }) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
    <Toolbar />
    <Divider sx={{ borderColor: brand.border.secondary }} />
    <List sx={{ flexGrow: 1, pt: 1 }}>
      <ListItemButton onClick={() => onNavigate('/home')} selected={isActive('/home')} sx={navItemSx}>
        <ListItemIcon>
          <HomeIcon />
        </ListItemIcon>
        <ListItemText primary="Home" />
      </ListItemButton>
      <ListItemButton onClick={() => onNavigate('/scouts')} selected={isActive('/scouts')} sx={navItemSx}>
        <ListItemIcon>
          <PersonIcon />
        </ListItemIcon>
        <ListItemText primary="My Scouts" />
      </ListItemButton>
      <ListItemButton onClick={() => onNavigate('/catalogs')} selected={isActive('/catalogs')} sx={navItemSx}>
        <ListItemIcon>
          <InventoryIcon />
        </ListItemIcon>
        <ListItemText primary="Catalogs" />
      </ListItemButton>
      <ListItemButton onClick={() => onNavigate('/payment-methods')} selected={isActive('/payment-methods')} sx={navItemSx}>
        <ListItemIcon>
          <PaymentIcon />
        </ListItemIcon>
        <ListItemText primary="Payment Methods" />
      </ListItemButton>

      <Divider sx={sectionDividerSx} />

      <ListItemButton onClick={() => onNavigate('/shared-campaigns')} selected={isActive('/shared-campaigns')} sx={navItemSx}>
        <ListItemIcon>
          <CampaignIcon />
        </ListItemIcon>
        <ListItemText primary="Shared Campaigns" />
      </ListItemButton>
      {hasSharedCampaigns && (
        <ListItemButton onClick={() => onNavigate('/campaign-reports')} selected={isActive('/campaign-reports')} sx={navItemSx}>
          <ListItemIcon>
            <AssessmentIcon />
          </ListItemIcon>
          <ListItemText primary="Campaign Reports" />
        </ListItemButton>
      )}
      <ListItemButton onClick={() => onNavigate('/accept-invite')} selected={isActive('/accept-invite')} sx={navItemSx}>
        <ListItemIcon>
          <CardGiftcardIcon />
        </ListItemIcon>
        <ListItemText primary="Accept Invite" />
      </ListItemButton>

      <Divider sx={sectionDividerSx} />

      <ListItemButton onClick={() => onNavigate('/settings')} selected={isActive('/settings')} sx={navItemSx}>
        <ListItemIcon>
          <SettingsIcon />
        </ListItemIcon>
        <ListItemText primary="Settings" />
      </ListItemButton>

      {isAdmin && (
        <>
          <Divider sx={sectionDividerSx} />
          <ListItemButton onClick={() => onNavigate('/admin')} selected={isActive('/admin')} sx={adminNavItemSx}>
            <ListItemIcon>
              <AdminPanelSettingsIcon />
            </ListItemIcon>
            <ListItemText primary="Admin Console" />
          </ListItemButton>
        </>
      )}
    </List>

    <Divider sx={{ borderColor: brand.border.secondary }} />
    <Box sx={{ p: 2 }}>
      <ListItemButton
        onClick={onLogout}
        sx={{
          borderRadius: brand.radius.md,
          color: brand.text.secondary,
          px: 1.5,
          '&:hover': {
            backgroundColor: brand.fill.tertiary,
            color: brand.error.main,
          },
        }}
      >
        <ListItemIcon sx={{ color: 'inherit', minWidth: 36 }}>
          <LogoutIcon />
        </ListItemIcon>
        <ListItemText
          primary="Sign out"
          secondary={displayName}
          primaryTypographyProps={{ fontWeight: 600 }}
          secondaryTypographyProps={{ noWrap: true }}
        />
      </ListItemButton>
    </Box>
  </Box>
);

export const AppLayout: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const { account, logout, isAdmin } = useAuth();
  const [mobileDrawerOpen, setMobileDrawerOpen] = React.useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'));

  // Check if user has any shared campaigns
  const { data: campaignsData } = useQuery<{
    listMySharedCampaigns: { sharedCampaignCode: string; isActive: boolean }[];
  }>(LIST_MY_SHARED_CAMPAIGNS);

  const hasSharedCampaigns = React.useMemo(
    () => (campaignsData?.listMySharedCampaigns?.filter((c: { isActive: boolean }) => c.isActive)?.length ?? 0) > 0,
    [campaignsData],
  );

  const toggleMobileDrawer = React.useCallback(() => setMobileDrawerOpen((open) => !open), []);

  const handleNavigation = React.useCallback(
    (path: string) => {
      navigate(path);
      if (!isDesktop) {
        setMobileDrawerOpen(false);
      }
    },
    [navigate, isDesktop],
  );

  const isActive = React.useCallback(
    (path: string) => location.pathname === path || location.pathname.startsWith(path + '/'),
    [location.pathname],
  );

  const displayName = React.useMemo(() => {
    if (!account) return '';
    const { givenName, familyName, email } = account;
    if (givenName && familyName) return `${givenName} ${familyName}`;
    return givenName || email;
  }, [account]);

  return (
    <AppLayoutView
      isDesktop={isDesktop}
      account={account}
      displayName={displayName}
      onLogout={logout}
      onNavigate={handleNavigation}
      isActive={isActive}
      toggleMobileDrawer={toggleMobileDrawer}
      mobileDrawerOpen={mobileDrawerOpen}
      hasSharedCampaigns={hasSharedCampaigns}
      isAdmin={Boolean(isAdmin)}
      children={children}
    />
  );
};

const AppLayoutView: React.FC<{
  isDesktop: boolean;
  account: ReturnType<typeof useAuth>['account'];
  displayName: string;
  onLogout: () => void;
  onNavigate: (path: string) => void;
  isActive: (path: string) => boolean;
  toggleMobileDrawer: () => void;
  mobileDrawerOpen: boolean;
  hasSharedCampaigns: boolean;
  isAdmin: boolean;
  children?: React.ReactNode;
}> = ({
  isDesktop,
  account,
  displayName,
  onLogout,
  onNavigate,
  isActive,
  toggleMobileDrawer,
  mobileDrawerOpen,
  hasSharedCampaigns,
  isAdmin,
  children,
}) => (
  <Box sx={{ display: 'flex' }}>
    <AppBar position="fixed" color="default" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Container maxWidth="lg">
        <Toolbar disableGutters sx={{ justifyContent: 'space-between', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {!isDesktop && (
              <IconButton
                color="inherit"
                aria-label="open drawer"
                edge="start"
                onClick={toggleMobileDrawer}
                sx={{ mr: 0.5 }}
              >
                <MenuIcon />
              </IconButton>
            )}

            <Box
              sx={{ display: 'flex', alignItems: 'center', gap: 1, cursor: 'pointer' }}
              onClick={() => onNavigate('/home')}
            >
              <Box
                component="img"
                src="/logo.svg"
                alt="KernelWorx mark"
                sx={{
                  width: { xs: 28, sm: 32, md: 36 },
                  height: { xs: 28, sm: 32, md: 36 },
                }}
              />
              <Typography
                variant="h6"
                noWrap
                component="div"
                sx={{
                  fontFamily: displayFont,
                  fontWeight: 700,
                  fontSize: { xs: '1.25rem', sm: '1.35rem' },
                  lineHeight: 1,
                  letterSpacing: '-0.01em',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                <Box component="span" sx={{ color: '#333333' }}>
                  Kernel
                </Box>
                <Box component="span" sx={{ color: 'primary.main' }}>
                  Worx
                </Box>
              </Typography>
            </Box>
          </Box>

          {account && <AccountButton isDesktop={isDesktop} displayName={displayName} onNavigate={onNavigate} />}
        </Toolbar>
      </Container>
    </AppBar>

    {isDesktop ? (
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          '& .MuiDrawer-paper': drawerPaperSx,
        }}
      >
        <DrawerContent
          onNavigate={onNavigate}
          isActive={isActive}
          hasSharedCampaigns={hasSharedCampaigns}
          isAdmin={isAdmin}
          displayName={displayName}
          onLogout={onLogout}
        />
      </Drawer>
    ) : (
      <Drawer
        variant="temporary"
        anchor="left"
        open={mobileDrawerOpen}
        onClose={toggleMobileDrawer}
        ModalProps={{ keepMounted: true }}
        sx={{
          '& .MuiDrawer-paper': drawerPaperSx,
        }}
      >
        <DrawerContent
          onNavigate={onNavigate}
          isActive={isActive}
          hasSharedCampaigns={hasSharedCampaigns}
          isAdmin={isAdmin}
          displayName={displayName}
          onLogout={onLogout}
        />
      </Drawer>
    )}

    <Box
      component="main"
      sx={{
        flexGrow: 1,
        width: 0,
        bgcolor: brand.background.layout,
        minHeight: '100vh',
      }}
    >
      <Toolbar />
      <Container maxWidth="lg" sx={{ py: { xs: 2, sm: 3, md: 4 }, px: { xs: 1, sm: 2, md: 3 } }}>
        {children}
        <Outlet />
      </Container>
    </Box>

    <Toast />
  </Box>
);

const AccountButton: React.FC<{
  isDesktop: boolean;
  displayName: string;
  onNavigate: (path: string) => void;
}> = ({ isDesktop, displayName, onNavigate }) => (
  <Button
    color="inherit"
    onClick={() => onNavigate('/account/settings')}
    sx={{
      textTransform: 'none',
      mr: 1,
      display: 'flex',
      alignItems: 'center',
      minWidth: 'auto',
      px: 1,
      color: brand.text.primary,
      borderRadius: brand.radius.md,
      fontFamily: displayFont,
      '&:hover': {
        backgroundColor: brand.fill.tertiary,
      },
    }}
  >
    <AccountCircleIcon
      sx={{
        fontSize: isDesktop ? '1.25rem' : '1.5rem',
        mr: isDesktop ? 0.5 : 0,
        color: brand.text.secondary,
      }}
    />
    <Typography
      variant="body2"
      noWrap
      sx={{
        maxWidth: 120,
        ml: isDesktop ? 0 : 0.5,
        display: isDesktop ? 'block' : { xs: 'none', sm: 'block' },
        fontFamily: displayFont,
        color: brand.text.primary,
      }}
    >
      {displayName}
    </Typography>
  </Button>
);
