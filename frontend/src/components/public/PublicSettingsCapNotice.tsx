/**
 * Capacity notice for public order settings.
 */
import { Box, Typography } from '@mui/material';

interface PublicSettingsCapNoticeProps {
  publicOrderCount: number;
  maxOrders: number;
}

export const PublicSettingsCapNotice: React.FC<PublicSettingsCapNoticeProps> = ({
  publicOrderCount,
  maxOrders,
}) => {
  const remaining = maxOrders - publicOrderCount;
  const percentage = (publicOrderCount / maxOrders) * 100;

  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Order Capacity
      </Typography>
      <Typography variant="body2">
        You have received {publicOrderCount} out of {maxOrders} maximum orders.
      </Typography>
      {remaining > 0 ? (
        <Typography variant="body2" color="success">
          {remaining} orders remaining before reaching capacity ({percentage.toFixed(
            0
          )}% used)
        </Typography>
      ) : (
        <Typography variant="body2" color="error">
          At maximum capacity! ({percentage.toFixed(0)}% used)
        </Typography>
      )}
    </Box>
  );
};