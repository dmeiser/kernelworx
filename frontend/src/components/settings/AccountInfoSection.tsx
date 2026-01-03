/**
 * Account Information section for User Settings
 */
import React from "react";
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

const renderRow = (
  key: string,
  icon: React.ReactNode,
  label: string,
  secondary: React.ReactNode,
  action?: React.ReactNode,
) => (
  <React.Fragment key={key}>
    <ListItem secondaryAction={action}>
      <ListItemIcon>{icon}</ListItemIcon>
      <ListItemText
        primary={label}
        secondary={secondary}
        secondaryTypographyProps={{ component: "span" }}
      />
    </ListItem>
    <Divider component="li" />
  </React.Fragment>
);

type DetailRow = {
  key: string;
  icon: React.ReactNode;
  label: string;
  value?: React.ReactNode;
  action?: React.ReactNode;
};

const createEmailRow = (
  account: Account | undefined,
  onChangeEmail: () => void,
): DetailRow => ({
  key: "email",
  icon: <EmailIcon color="primary" />,
  label: "Email Address",
  value: account?.email,
  action: (
    <Button size="small" startIcon={<EditIcon />} onClick={onChangeEmail}>
      Change
    </Button>
  ),
});

const createNameRows = (account: Account | undefined): DetailRow[] => [
  {
    key: "givenName",
    icon: <PersonIcon color="primary" />,
    label: "First Name",
    value: account?.givenName,
  },
  {
    key: "familyName",
    icon: <PersonIcon color="primary" />,
    label: "Last Name",
    value: account?.familyName,
  },
];

const createLocationRows = (account: Account | undefined): DetailRow[] => [
  {
    key: "city",
    icon: <PersonIcon color="primary" />,
    label: "City",
    value: account?.city,
  },
  {
    key: "state",
    icon: <PersonIcon color="primary" />,
    label: "State",
    value: account?.state,
  },
];

const createUnitRow = (account: Account | undefined): DetailRow => ({
  key: "unit",
  icon: <PersonIcon color="primary" />,
  label: "Scouting Unit",
  value:
    account?.unitType && account?.unitNumber
      ? `${account.unitType} ${account.unitNumber}`
      : undefined,
});

const createAccountTypeRow = (account: Account | undefined): DetailRow => ({
  key: "account-type",
  icon: <AdminIcon color="primary" />,
  label: "Account Type",
  value: (
    <Stack
      direction="row"
      spacing={1}
      alignItems="center"
      component="span"
      sx={{ display: "inline-flex" }}
    >
      <span>{account?.isAdmin ? "Administrator" : "Standard User"}</span>
      {account?.isAdmin ? (
        <Chip label="Admin" color="error" size="small" />
      ) : null}
    </Stack>
  ),
});

const createTimestampRows = (account: Account | undefined): DetailRow[] => [
  {
    key: "created",
    icon: <InfoIcon color="primary" />,
    label: "Account Created",
    value: account?.createdAt ? formatDate(account.createdAt) : "Unknown",
  },
  {
    key: "updated",
    icon: <InfoIcon color="primary" />,
    label: "Last Updated",
    value: account?.updatedAt ? formatDate(account.updatedAt) : "Unknown",
  },
];

const createAccountIdRow = (account: Account | undefined): DetailRow => ({
  key: "account-id",
  icon: <PersonIcon color="primary" />,
  label: "Account ID",
  value: account?.accountId ? (
    <Typography
      variant="body2"
      component="span"
      sx={{
        wordBreak: "break-all",
        fontFamily: "monospace",
        fontSize: "0.875rem",
      }}
    >
      {account.accountId}
    </Typography>
  ) : undefined,
});

const buildDetailRows = (
  account: Account | undefined,
  onChangeEmail: () => void,
): React.ReactNode[] => {
  const rows: DetailRow[] = [
    createEmailRow(account, onChangeEmail),
    ...createNameRows(account),
    ...createLocationRows(account),
    createUnitRow(account),
    createAccountTypeRow(account),
    ...createTimestampRows(account),
    createAccountIdRow(account),
  ];

  return rows
    .filter(
      (row) =>
        row.value !== undefined && row.value !== null && row.value !== "",
    )
    .map((row) =>
      renderRow(
        row.key,
        row.icon,
        row.label,
        row.value as React.ReactNode,
        row.action,
      ),
    );
};

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const AccountHeader: React.FC<{ onEditProfile: () => void }> = ({
  onEditProfile,
}) => (
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
);

const AccountDetailsList: React.FC<{ rows: React.ReactNode[] }> = ({
  rows,
}) => (
  <List>
    {rows.map((row, idx) => (
      <React.Fragment key={`row-${idx}`}>{row}</React.Fragment>
    ))}
  </List>
);

export const AccountInfoSection: React.FC<AccountInfoSectionProps> = ({
  account,
  onEditProfile,
  onChangeEmail,
}) => {
  const detailRows = React.useMemo(
    () => buildDetailRows(account, onChangeEmail),
    [account, onChangeEmail],
  );

  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <AccountHeader onEditProfile={onEditProfile} />
      <AccountDetailsList rows={detailRows} />
    </Paper>
  );
};
