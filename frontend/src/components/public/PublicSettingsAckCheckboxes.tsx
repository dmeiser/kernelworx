/**
 * The two mandatory enable-time acknowledgements.
 *
 * Both must be checked before Save is enabled — one checked is not enough, and
 * the button stays disabled rather than letting a partial acceptance through and
 * bouncing off the server's INVALID_INPUT. The acceptance is persisted on the
 * settings blob (`acknowledgedAt`/`ackVersion`) as liability evidence, and this
 * block re-appears whenever the stored version lags the current constant.
 */

import { Box, Checkbox, FormControlLabel, Typography } from '@mui/material';
import { PUBLIC_ORDER_ACKNOWLEDGEMENTS } from '../../constants/publicOrders';
import type { SettingsDraft } from '../../lib/publicOrderSettings';

interface PublicSettingsAckCheckboxesProps {
  draft: SettingsDraft;
  onChange: (field: 'ackPayment' | 'ackDisclosure', value: boolean) => void;
}

export const PublicSettingsAckCheckboxes: React.FC<PublicSettingsAckCheckboxesProps> = ({ draft, onChange }) => (
  <Box data-testid="ack-block">
    <Typography variant="subtitle1" fontWeight="medium" gutterBottom>
      Before you turn this on
    </Typography>
    {PUBLIC_ORDER_ACKNOWLEDGEMENTS.map((text, index) => (
      <FormControlLabel
        key={text}
        data-testid={index === 0 ? 'ack-payment' : 'ack-disclosure'}
        control={
          <Checkbox
            checked={index === 0 ? draft.ackPayment : draft.ackDisclosure}
            onChange={(event) => onChange(index === 0 ? 'ackPayment' : 'ackDisclosure', event.target.checked)}
          />
        }
        label={text}
      />
    ))}
  </Box>
);

export default PublicSettingsAckCheckboxes;
