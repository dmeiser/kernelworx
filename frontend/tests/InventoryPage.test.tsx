import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { InventoryPage } from '../src/pages/InventoryPage';

test('renders inventory heading', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  expect(screen.getByText('Inventory')).toBeInTheDocument();
});

test('submit invalid quantity shows error', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '0' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'r' } });
  fireEvent.click(screen.getByText('Receipt'));
  expect(screen.getByText('quantity must be a positive integer')).toBeInTheDocument();
});

test('submit missing reason shows error', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '2' } });
  fireEvent.click(screen.getByText('Receipt'));
  expect(screen.getByText('reason is required')).toBeInTheDocument();
});

test('receipt increases balance and lists movement', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '2' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'r' } });
  fireEvent.click(screen.getByText('Receipt'));
  expect(screen.getByText('Balance: 2')).toBeInTheDocument();
  expect(screen.getByText('receipt')).toBeInTheDocument();
  expect(screen.getByText('r')).toBeInTheDocument();
});

test('adjustment increases balance', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '1' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'a' } });
  fireEvent.click(screen.getByText('Adjustment'));
  expect(screen.getByText('Balance: 1')).toBeInTheDocument();
});

test('on-order does not change balance', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '4' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'o' } });
  fireEvent.click(screen.getByText('On Order'));
  expect(screen.getByText('Balance: 0')).toBeInTheDocument();
  expect(screen.getByText('on-order')).toBeInTheDocument();
});

test('filter movement type', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '2' } });
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'r' } });
  fireEvent.click(screen.getByText('Receipt'));
  fireEvent.change(screen.getByLabelText('Filter movement type'), { target: { value: 'adjustment' } });
  expect(screen.queryByText('receipt')).not.toBeInTheDocument();
});
