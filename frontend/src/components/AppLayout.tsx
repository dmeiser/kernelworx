import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useQuery } from "@apollo/client/react";
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
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import PersonIcon from "@mui/icons-material/Person";
import SettingsIcon from "@mui/icons-material/Settings";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import InventoryIcon from "@mui/icons-material/Inventory";
import AccountCircleIcon from "@mui/icons-material/AccountCircle";
import LogoutIcon from "@mui/icons-material/Logout";
import CardGiftcardIcon from "@mui/icons-material/CardGiftcard";
import AssessmentIcon from "@mui/icons-material/Assessment";
import CampaignIcon from "@mui/icons-material/Campaign";
import { useAuth } from "../contexts/AuthContext";
import { Toast } from "./Toast";
import { Outlet } from "react-router-dom";
import { LIST_MY_SHARED_CAMPAIGNS } from "../lib/graphql";

const DRAWER_WIDTH = 240;

const DrawerContent: React.FC<{
  onNavigate: (path: string) => void;
  isActive: (path: string) => boolean;
  hasSharedCampaigns: boolean;
  isAdmin: boolean;
}> = ({ onNavigate, isActive, hasSharedCampaigns, isAdmin }) => (
  <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
    <Toolbar />
    <Divider />
    <List sx={{ flexGrow: 1 }}>
      <ListItemButton
        onClick={() => onNavigate("/scouts")}
        selected={isActive("/scouts")}
      >
        <ListItemIcon>
          <PersonIcon />
        </ListItemIcon>
        <ListItemText primary="My Scouts" />
      </ListItemButton>
      <ListItemButton
        onClick={() => onNavigate("/accept-invite")}
        selected={isActive("/accept-invite")}
      >
        <ListItemIcon>
          <CardGiftcardIcon />
        </ListItemIcon>
        <ListItemText primary="Accept Invite" />
      </ListItemButton>
      <ListItemButton
        onClick={() => onNavigate("/catalogs")}
        selected={isActive("/catalogs")}
      >
        <ListItemIcon>
          <InventoryIcon />
        </ListItemIcon>
        <ListItemText primary="Catalogs" />
      </ListItemButton>
      <ListItemButton
        onClick={() => onNavigate("/shared-campaigns")}
        selected={isActive("/shared-campaigns")}
      >
        <ListItemIcon>
          <CampaignIcon />
        </ListItemIcon>
        <ListItemText primary="Shared Campaigns" />
      </ListItemButton>
      {hasSharedCampaigns && (
        <ListItemButton
          onClick={() => onNavigate("/campaign-reports")}
          selected={isActive("/campaign-reports")}
        >
          <ListItemIcon>
            <AssessmentIcon />
          </ListItemIcon>
          <ListItemText primary="Campaign Reports" />
        </ListItemButton>
      )}
      <ListItemButton
        onClick={() => onNavigate("/settings")}
        selected={isActive("/settings")}
      >
        <ListItemIcon>
          <SettingsIcon />
        </ListItemIcon>
        <ListItemText primary="Settings" />
      </ListItemButton>
      {isAdmin && (
        <>
          <Divider sx={{ my: 1 }} />
          <ListItemButton
            onClick={() => onNavigate("/admin")}
            selected={isActive("/admin")}
          >
            <ListItemIcon>
              <AdminPanelSettingsIcon color="error" />
            </ListItemIcon>
            <ListItemText
              primary="Admin Console"
              primaryTypographyProps={{ color: "error" }}
            />
          </ListItemButton>
        </>
      )}
    </List>
  </Box>
);

export const AppLayout: React.FC<{ children?: React.ReactNode }> = ({
  children,
}) => {
  const { account, logout, isAdmin } = useAuth();
  const [mobileDrawerOpen, setMobileDrawerOpen] = React.useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));

  // Check if user has any shared campaigns
  const { data: campaignsData } = useQuery<{
    listMySharedCampaigns: { sharedCampaignCode: string; isActive: boolean }[];
  }>(LIST_MY_SHARED_CAMPAIGNS);

  const hasSharedCampaigns = React.useMemo(
    () =>
      (campaignsData?.listMySharedCampaigns?.filter(
        (c: { isActive: boolean }) => c.isActive,
      )?.length ?? 0) > 0,
    [campaignsData],
  );

  const toggleMobileDrawer = React.useCallback(
    () => setMobileDrawerOpen((open) => !open),
    [],
  );

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
    (path: string) =>
      location.pathname === path || location.pathname.startsWith(path + "/"),
    [location.pathname],
  );

  const displayName = React.useMemo(() => {
    if (!account) return "";
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
  account: ReturnType<typeof useAuth>["account"];
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
  <Box sx={{ display: "flex" }}>
    <AppBar
      position="fixed"
      sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}
    >
      <Container maxWidth="lg">
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

          <Box sx={{ display: "flex", alignItems: "center", flexGrow: 1 }}>
            <Box
              component="img"
              src="/logo.svg"
              alt="Popcorn kernel"
              sx={{
                width: { xs: "28px", sm: "32px", md: "40px" },
                height: { xs: "28px", sm: "32px", md: "40px" },
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
                letterSpacing: "0.08em",
                fontSize: { xs: "28px", sm: "32px", md: "40px" },
                lineHeight: 1,
                WebkitTextStroke: "0.8px rgba(255, 255, 255, 0.8)",
                textShadow:
                  "0 1px 0 rgba(255,255,255,0.12), 0 2px 0 rgba(255,255,255,0.06)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              KernelWorx
            </Typography>
          </Box>

          {account && (
            <AccountButton
              isDesktop={isDesktop}
              displayName={displayName}
              onNavigate={onNavigate}
            />
          )}

          <LogoutButton onLogout={onLogout} />
        </Toolbar>
      </Container>
    </AppBar>

    {isDesktop ? (
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: DRAWER_WIDTH,
            boxSizing: "border-box",
          },
        }}
      >
        <DrawerContent
          onNavigate={onNavigate}
          isActive={isActive}
          hasSharedCampaigns={hasSharedCampaigns}
          isAdmin={isAdmin}
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
          "& .MuiDrawer-paper": {
            width: DRAWER_WIDTH,
            boxSizing: "border-box",
          },
        }}
      >
        <DrawerContent
          onNavigate={onNavigate}
          isActive={isActive}
          hasSharedCampaigns={hasSharedCampaigns}
          isAdmin={isAdmin}
        />
      </Drawer>
    )}

    <Box
      component="main"
      sx={{
        flexGrow: 1,
        width: 0,
        bgcolor: "background.default",
        minHeight: "100vh",
      }}
    >
      <Toolbar />
      <Container
        maxWidth="lg"
        sx={{ py: { xs: 2, sm: 3, md: 4 }, px: { xs: 1, sm: 2, md: 3 } }}
      >
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
    onClick={() => onNavigate("/account/settings")}
    sx={{
      textTransform: "none",
      mr: 1,
      display: "flex",
      alignItems: "center",
      minWidth: "auto",
      px: 1,
    }}
  >
    <AccountCircleIcon
      sx={{
        fontSize: isDesktop ? "1.25rem" : "1.5rem",
        mr: isDesktop ? 0.5 : 0,
      }}
    />
    <Typography
      variant="body2"
      noWrap
      sx={{
        maxWidth: 120,
        ml: isDesktop ? 0 : 0.5,
        display: isDesktop ? "block" : { xs: "none", sm: "block" },
      }}
    >
      {displayName}
    </Typography>
  </Button>
);

const LogoutButton: React.FC<{ onLogout: () => void }> = ({ onLogout }) => (
  <Button
    color="inherit"
    onClick={onLogout}
    startIcon={<LogoutIcon sx={{ fontSize: { xs: "1rem", sm: "1.25rem" } }} />}
    sx={{
      textTransform: "none",
      fontWeight: 500,
      minWidth: { xs: "auto", sm: "auto" },
      px: { xs: 1, sm: 2 },
      fontSize: { xs: "0.875rem", sm: "1rem" },
    }}
  >
    <Box component="span" sx={{ display: { xs: "none", sm: "inline" } }}>
      Log out
    </Box>
  </Button>
);
