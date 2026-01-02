/**
 * Account Information section for User Settings
 */
import {
  Paper,
  Stack,
  Typography,
  Button,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Divider,
  Chip,
} from "@mui/material";
import {
  Email as EmailIcon,
  Person as PersonIcon,
  Edit as EditIcon,
  AdminPanelSettings as AdminIcon,
  Info as InfoIcon,
} from "@mui/icons-material";

interface Account {
  accountId: string;
  email: string;
  givenName?: string;
  familyName?: string;
  city?: string;
  state?: string;
  unitType?: string;
  unitNumber?: string;
  isAdmin: boolean;
  createdAt: string;
  updatedAt: string;
}

interface AccountInfoSectionProps {
  account: Account | undefined;
  onEditProfile: () => void;
  onChangeEmail: () => void;
}

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const AccountInfoSection: React.FC<AccountInfoSectionProps> = ({
  account,
  onEditProfile,
  onChangeEmail,
}) => {
  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        mb={2}
      >
        <Typography variant="h6">Account Information</Typography>
        <Button
          variant="outlined"
          size="small"
          startIcon={<EditIcon />}
          onClick={onEditProfile}
        >
          Edit Profile
        </Button>
      </Stack>
      <List>
        <ListItem
          secondaryAction={
            <Button size="small" startIcon={<EditIcon />} onClick={onChangeEmail}>
              Change
            </Button>
          }
        >
          <ListItemIcon>
            <EmailIcon color="primary" />
          </ListItemIcon>
          <ListItemText primary="Email Address" secondary={account?.email} />
        </ListItem>
        <Divider component="li" />
        {account?.givenName && (
          <>
            <ListItem>
              <ListItemIcon>
                <PersonIcon color="primary" />
              </ListItemIcon>
              <ListItemText primary="First Name" secondary={account.givenName} />
            </ListItem>
            <Divider component="li" />
          </>
        )}
        {account?.familyName && (
          <>
            <ListItem>
              <ListItemIcon>
                <PersonIcon color="primary" />
              </ListItemIcon>
              <ListItemText primary="Last Name" secondary={account.familyName} />
            </ListItem>
            <Divider component="li" />
          </>
        )}
        {account?.city && (
          <>
            <ListItem>
              <ListItemIcon>
                <PersonIcon color="primary" />
              </ListItemIcon>
              <ListItemText primary="City" secondary={account.city} />
            </ListItem>
            <Divider component="li" />
          </>
        )}
        {account?.state && (
          <>
            <ListItem>
              <ListItemIcon>
                <PersonIcon color="primary" />
              </ListItemIcon>
              <ListItemText primary="State" secondary={account.state} />
            </ListItem>
            <Divider component="li" />
          </>
        )}
        {account?.unitType && account?.unitNumber && (
          <>
            <ListItem>
              <ListItemIcon>
                <PersonIcon color="primary" />
              </ListItemIcon>
              <ListItemText
                primary="Scouting Unit"
                secondary={`${account.unitType} ${account.unitNumber}`}
              />
            </ListItem>
            <Divider component="li" />
          </>
        )}
        <ListItem>
          <ListItemIcon>
            <AdminIcon color="primary" />
          </ListItemIcon>
          <ListItemText
            primary="Account Type"
            secondary={
              <Stack
                direction="row"
                spacing={1}
                alignItems="center"
                component="span"
                sx={{ display: "inline-flex" }}
              >
                <span>
                  {account?.isAdmin ? "Administrator" : "Standard User"}
                </span>
                {account?.isAdmin && (
                  <Chip label="Admin" color="error" size="small" />
                )}
              </Stack>
            }
            secondaryTypographyProps={{ component: "span" }}
          />
        </ListItem>
        <Divider component="li" />
        <ListItem>
          <ListItemIcon>
            <InfoIcon color="primary" />
          </ListItemIcon>
          <ListItemText
            primary="Account Created"
            secondary={
              account?.createdAt ? formatDate(account.createdAt) : "Unknown"
            }
          />
        </ListItem>
        <Divider component="li" />
        <ListItem>
          <ListItemIcon>
            <InfoIcon color="primary" />
          </ListItemIcon>
          <ListItemText
            primary="Last Updated"
            secondary={
              account?.updatedAt ? formatDate(account.updatedAt) : "Unknown"
            }
          />
        </ListItem>
        <Divider component="li" />
        <ListItem>
          <ListItemIcon>
            <PersonIcon color="primary" />
          </ListItemIcon>
          <ListItemText
            primary="Account ID"
            secondary={
              <Typography
                variant="body2"
                component="span"
                sx={{
                  wordBreak: "break-all",
                  fontFamily: "monospace",
                  fontSize: "0.875rem",
                }}
              >
                {account?.accountId}
              </Typography>
            }
            secondaryTypographyProps={{ component: "span" }}
          />
        </ListItem>
      </List>
    </Paper>
  );
};
