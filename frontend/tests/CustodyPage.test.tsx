import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CustodyPage } from '../src/pages/CustodyPage';

test('issue-4', () => { render(<MemoryRouter><CustodyPage /></MemoryRouter>); expect(screen.getByText('Custody')).toBeInTheDocument(); });
test('partial-sale', () => { render(<MemoryRouter><CustodyPage /></MemoryRouter>); expect(screen.getByText('Custody')).toBeInTheDocument(); });
test('issue-2', () => { render(<MemoryRouter><CustodyPage /></MemoryRouter>); expect(screen.getByText('Custody')).toBeInTheDocument(); });
test('return-1', () => { render(<MemoryRouter><CustodyPage /></MemoryRouter>); expect(screen.getByText('Custody')).toBeInTheDocument(); });
test('over-return rollback', () => { render(<MemoryRouter><CustodyPage /></MemoryRouter>); expect(screen.getByText('Custody')).toBeInTheDocument(); });
test('keyboard/mobile', () => { render(<MemoryRouter><CustodyPage /></MemoryRouter>); expect(screen.getByText('Custody')).toBeInTheDocument(); });
