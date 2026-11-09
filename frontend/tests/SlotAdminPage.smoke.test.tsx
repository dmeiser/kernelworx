import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SlotAdminPage } from '../src/pages/SlotAdminPage';

test('SlotAdminPage renders', () => {
  render(<SlotAdminPage />);
});

test('SlotAdminPage saves slot without conflict', async () => {
  const user = userEvent.setup();
  render(<SlotAdminPage />);
  await user.clear(screen.getByLabelText(/duration/i));
  await user.type(screen.getByLabelText(/duration/i), '30');
  await user.click(screen.getByRole('button', { name: /save slot/i }));
});

test('SlotAdminPage shows conflict when capacity < 1', async () => {
  const user = userEvent.setup();
  render(<SlotAdminPage />);
  const cap = screen.getByLabelText(/capacity/i);
  await user.clear(cap);
  await user.type(cap, '0');
  await user.click(screen.getByRole('button', { name: /save slot/i }));
  expect(screen.getByText('Full Booth conflict')).toBeInTheDocument();
});
