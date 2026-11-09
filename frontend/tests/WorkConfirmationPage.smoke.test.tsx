import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkConfirmationPage } from '../src/pages/WorkConfirmationPage';

test('WorkConfirmationPage renders', () => {
  render(<WorkConfirmationPage />);
});

test('WorkConfirmationPage confirms and unconfirms', async () => {
  const user = userEvent.setup();
  render(<WorkConfirmationPage />);
  const input = screen.getByLabelText(/actual minutes/i);
  await user.clear(input);
  await user.type(input, '45');
  await user.click(screen.getByRole('button', { name: /^confirm$/i }));
  expect(screen.getByText('Confirmed 45 min')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /unconfirm/i }));
});
