import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CustodyPage } from '../src/pages/CustodyPage';

test('renders custody heading', () => {
  render(<MemoryRouter><CustodyPage /></MemoryRouter>);
  expect(screen.getByText('Custody')).toBeInTheDocument();
});

test('issue with valid inputs updates balance and aggregate', () => {
  render(<MemoryRouter><CustodyPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Scout'), { target: { value: 's1' } });
  fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'p1' } });
  fireEvent.change(screen.getByLabelText('Qty'), { target: { value: '3' } });
  fireEvent.click(screen.getByText('Issue'));
  expect(screen.getByText('s1:p1')).toBeInTheDocument();
  expect(screen.getByText('3')).toBeInTheDocument();
  expect(screen.getByText('Aggregate balance: 3')).toBeInTheDocument();
});

test('issue invalid shows error', () => {
  render(<MemoryRouter><CustodyPage /></MemoryRouter>);
  fireEvent.click(screen.getByText('Issue'));
  expect(screen.getByText('invalid selection or quantity')).toBeInTheDocument();
});

test('return one with nothing to return shows error', () => {
  render(<MemoryRouter><CustodyPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Scout'), { target: { value: 's1' } });
  fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'p1' } });
  fireEvent.click(screen.getByText('One-click return'));
  expect(screen.getByText('nothing to return')).toBeInTheDocument();
});

test('return one decrements balance', () => {
  render(<MemoryRouter><CustodyPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Scout'), { target: { value: 's1' } });
  fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'p1' } });
  fireEvent.change(screen.getByLabelText('Qty'), { target: { value: '2' } });
  fireEvent.click(screen.getByText('Issue'));
  fireEvent.click(screen.getByText('One-click return'));
  expect(screen.getByText('1')).toBeInTheDocument();
  expect(screen.getByText('Aggregate balance: 1')).toBeInTheDocument();
});
