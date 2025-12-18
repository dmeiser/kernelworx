import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
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
import { useAuth } from "../contexts/AuthContext";
import { Toast } from "./Toast";
import { Outlet } from "react-router-dom";

const DRAWER_WIDTH = 240;

export const AppLayout: React.FC<{ children?: React.ReactNode }> = ({
  children,
}) => {
  const { account, logout, isAdmin } = useAuth();
  const [mobileDrawerOpen, setMobileDrawerOpen] = React.useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));

  const toggleMobileDrawer = () => setMobileDrawerOpen(!mobileDrawerOpen);

  const handleNavigation = (path: string) => {
    navigate(path);
    if (!isDesktop) {
      setMobileDrawerOpen(false);
    }
  };

  const isActive = (path: string) => {
    return (
      location.pathname === path || location.pathname.startsWith(path + "/")
    );
  };

  const getDisplayName = () => {
    if (!account) return "";

    const { givenName, familyName, email } = account;

    if (givenName && familyName) {
      return `${givenName} ${familyName}`;
    }

    if (givenName) {
      return givenName;
    }

    return email;
  };

  const drawerContent = (
    <Box>
      <Toolbar />
      <Divider />
      <List>
        <ListItemButton
          onClick={() => handleNavigation("/profiles")}
          selected={isActive("/profiles")}
        >
          <ListItemIcon>
            <PersonIcon />
          </ListItemIcon>
          <ListItemText primary="Seller Profiles" />
        </ListItemButton>
        <ListItemButton
          onClick={() => handleNavigation("/accept-invite")}
          selected={isActive("/accept-invite")}
        >
          <ListItemIcon>
            <CardGiftcardIcon />
          </ListItemIcon>
          <ListItemText primary="Accept Invite" />
        </ListItemButton>
        <ListItemButton
          onClick={() => handleNavigation("/catalogs")}
          selected={isActive("/catalogs")}
        >
          <ListItemIcon>
            <InventoryIcon />
          </ListItemIcon>
          <ListItemText primary="Catalogs" />
        </ListItemButton>
        <ListItemButton
          onClick={() => handleNavigation("/settings")}
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
              onClick={() => handleNavigation("/admin")}
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

  return (
    <Box sx={{ display: "flex" }}>
      {/* Full-width AppBar */}
      <AppBar
        position="fixed"
        sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}
      >
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

            {!isDesktop && account && (
              <Button
                color="inherit"
                onClick={() => handleNavigation("/account/settings")}
                sx={{
                  textTransform: "none",
                  mr: 1,
                  display: "flex",
                  alignItems: "center",
                  minWidth: "auto",
                  px: 1,
                }}
              >
                <AccountCircleIcon sx={{ fontSize: "1.5rem" }} />
                <Typography
                  variant="body2"
                  noWrap
                  sx={{
                    maxWidth: 120,
                    ml: 0.5,
                    display: { xs: "none", sm: "block" },
                  }}
                >
                  {getDisplayName()}
                </Typography>
              </Button>
            )}

            {isDesktop && account && (
              <Button
                color="inherit"
                onClick={() => handleNavigation("/account/settings")}
                sx={{
                  textTransform: "none",
                  mr: 1,
                  display: "flex",
                  alignItems: "center",
                  minWidth: "auto",
                  px: 1,
                }}
              >
                <AccountCircleIcon sx={{ mr: 0.5, fontSize: "1.25rem" }} />
                <Typography variant="body2" noWrap>
                  {getDisplayName()}
                </Typography>
              </Button>
            )}

            <Button
              color="inherit"
              onClick={logout}
              startIcon={
                <LogoutIcon sx={{ fontSize: { xs: "1rem", sm: "1.25rem" } }} />
              }
              sx={{
                textTransform: "none",
                fontWeight: 500,
                minWidth: { xs: "auto", sm: "auto" },
                px: { xs: 1, sm: 2 },
                fontSize: { xs: "0.875rem", sm: "1rem" },
              }}
            >
              <Box
                component="span"
                sx={{ display: { xs: "none", sm: "inline" } }}
              >
                Log out
              </Box>
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
            "& .MuiDrawer-paper": {
              width: DRAWER_WIDTH,
              boxSizing: "border-box",
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
            "& .MuiDrawer-paper": {
              width: DRAWER_WIDTH,
              boxSizing: "border-box",
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
          bgcolor: "background.default",
          minHeight: "100vh",
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
