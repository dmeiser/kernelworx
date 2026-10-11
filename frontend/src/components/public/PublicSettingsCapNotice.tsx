/**
 * The campaign cap line.
 *
 * The copy is deliberately literal about what the number counts: the counter is
 * a lifetime high-water on the campaign item that is never decremented, so it
 * INCLUDES deleted orders, and a fresh cap comes only from starting a new
 * campaign — re-picking the same one is a no-op, and away-and-back restores the
 * old count. Saying "orders remaining" would be wrong in both directions.
 */

import { Typography } from '@mui/material';
import { PUBLIC_ORDER_CAP } from '../../constants/publicOrders';

export const PublicSettingsCapNotice: React.FC<{ count: number | null | undefined }> = ({ count }) => (
  <Typography variant="body2" color="text.secondary" data-testid="cap-notice">
    {count ?? 0} of {PUBLIC_ORDER_CAP} public orders have been placed in this campaign. This count includes deleted
    orders and is never reduced. Starting a new campaign gives you a fresh limit — re-picking this one does not.
  </Typography>
);

export default PublicSettingsCapNotice;
