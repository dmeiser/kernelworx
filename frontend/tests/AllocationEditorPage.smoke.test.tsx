import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AllocationEditorPage } from '../src/pages/AllocationEditorPage';

test('AllocationEditorPage renders', () => {
  render(<AllocationEditorPage />);
});

test('AllocationEditorPage validates and shows warnings', async () => {
  const user = userEvent.setup();
  render(<AllocationEditorPage />);
  const input = screen.getByLabelText(/product target/i);
  await user.type(input, '5');
  await user.click(screen.getByRole('button', { name: /validate/i }));
  expect(screen.getByText('server warning')).toBeInTheDocument();
});
