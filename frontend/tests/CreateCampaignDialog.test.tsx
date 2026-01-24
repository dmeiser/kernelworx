/**
 * CreateCampaignDialog component tests
 *
 * Tests are now enabled using lightweight mocks for MUI Select/MenuItem to avoid jsdom limitations.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CreateCampaignDialog } from '../src/components/CreateCampaignDialog';
import { LIST_MANAGED_CATALOGS, LIST_MY_CATALOGS } from '../src/lib/graphql';

// Mock Select/MenuItem to a plain HTML select/option to ensure onChange fires in jsdom
vi.mock('@mui/material', async () => {
  const actual = await vi.importActual<any>('@mui/material');
  const Select = ({ value, onChange, children, label, disabled, ...rest }: any) => (
    <select
      role="combobox"
      aria-label={label || 'Select'}
      value={value ?? ''}
      disabled={disabled}
      aria-disabled={disabled ? 'true' : undefined}
      onChange={(e) => onChange?.({ target: { value: (e.target as HTMLSelectElement).value } })}
      {...rest}
    >
      {children}
    </select>
  );
  const MenuItem = ({ value, children, disabled, ...rest }: any) => {
    const getText = (nodes: any): string =>
      React.Children.toArray(nodes)
        .map((node) => {
          if (typeof node === 'string') return node;
          // Extract nested text for elements like CircularProgress + label
          // @ts-expect-error accessing children is fine in test-only mock
          return node?.props?.children ? getText(node.props.children) : '';
        })
        .join(' ')
        .trim();
    const textContent = getText(children) || (disabled ? 'Disabled option' : 'Option');
    return (
      <option value={value ?? ''} disabled={disabled} {...rest}>
        {textContent}
      </option>
    );
  };
  return { ...actual, Select, MenuItem };
});

const mockPublicCatalogs = [
  {
    catalogId: 'catalog-1',
    catalogName: 'Official 2025 Catalog',
    catalogType: 'PUBLIC',
    isDeleted: false,
  },
  {
    catalogId: 'catalog-2',
    catalogName: 'Troop 123 Custom',
    catalogType: 'PUBLIC',
    isDeleted: false,
  },
];

const mockMyCatalogs = [
  {
    catalogId: 'catalog-3',
    catalogName: 'My Private Catalog',
    catalogType: 'PRIVATE',
    isDeleted: false,
  },
];

// Mock @apollo/client/react's useQuery at module scope. We can't spy on ESM named exports in Vitest,
// so provide a variable implementation that tests can replace.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
let useQueryMockImpl = (_query: any) => ({ data: undefined, loading: false });
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: any) => useQueryMockImpl(query),
}));

describe('CreateCampaignDialog', () => {
  let mockOnClose: ReturnType<typeof vi.fn>;
  let mockOnSubmit: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockOnClose = vi.fn();
    mockOnSubmit = vi.fn().mockResolvedValue(undefined);

    // useQuery will be spied on per-test via setupUseQueryMock()
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const createPublicCatalogResponse = (overrides?: { publicLoading?: boolean; publicData?: any }) => ({
    data: overrides?.publicData ?? { listManagedCatalogs: mockPublicCatalogs },
    loading: overrides?.publicLoading ?? false,
  });

  const createMyCatalogResponse = (overrides?: { myLoading?: boolean; myData?: any }) => ({
    data: overrides?.myData ?? { listMyCatalogs: mockMyCatalogs },
    loading: overrides?.myLoading ?? false,
  });

  const setupUseQueryMock = (overrides?: {
    publicLoading?: boolean;
    myLoading?: boolean;
    publicData?: any;
    myData?: any;
  }) => {
    useQueryMockImpl = (query: any) => {
      const handlers = new Map<any, any>([
        [LIST_MANAGED_CATALOGS, createPublicCatalogResponse(overrides)],
        [LIST_MY_CATALOGS, createMyCatalogResponse(overrides)],
      ]);
      return handlers.get(query) ?? { data: undefined, loading: false };
    };
  };

  const getCatalogSelect = () => {
    // Find the InputLabel element for Product Catalog and find the nearest FormControl root
    const labels = screen.queryAllByText(/catalog/i);
    const label = labels.find((el) => el.tagName === 'LABEL') || labels[0];
    if (!label) return null;
    const form = label.closest('.MuiFormControl-root');
    return form?.querySelector('[role="combobox"]') as HTMLElement | null;
  };

  // Helper to find the hidden native select input and set value directly
  // NOTE: This helper is defined but currently unused due to MUI Select testing limitations
  // Keeping it for future use when the MUI Select onChange issue is resolved
  const _setCatalogSelectValue = (value: string) => {
    // MUI Select uses a hidden input to store the actual value
    const form = document.querySelector('.MuiFormControl-root:has([role="combobox"])');
    const hiddenInput = form?.querySelector('input[type="hidden"]') as HTMLInputElement | null;
    if (hiddenInput) {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(hiddenInput, value);
      hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
      hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
  };
  // Silence the unused warning
  void _setCatalogSelectValue;

  it('renders when open', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Create New Sales Campaign')).toBeInTheDocument();
  });

  it('does not render when closed', () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={false} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows no catalogs available when catalogs are empty', async () => {
    // Mock returning empty catalogs
    useQueryMockImpl = (query: any) => {
      if (query === LIST_MANAGED_CATALOGS) {
        return { data: { listManagedCatalogs: [] }, loading: false };
      }
      if (query === LIST_MY_CATALOGS) {
        return { data: { listMyCatalogs: [] }, loading: false };
      }
      return { data: undefined, loading: false };
    };

    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    await waitFor(() => {
      expect(screen.getByText('No catalogs available')).toBeInTheDocument();
    });
  });

  it('displays form fields', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    expect(screen.getByLabelText(/campaign name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/start date/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/end date/i)).toBeInTheDocument();

    // Wait for catalog label to appear (MUI may not link label to combobox reliably)
    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });
  });

  it('start date is empty by default', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const startDateInput = screen.getByLabelText(/start date/i) as HTMLInputElement;
    await waitFor(() => {
      expect(startDateInput.value).toBe('');
    });
  });

  it('loads and displays catalogs', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    // Wait for catalogs to load via label presence
    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    // Click the catalog select
    const user = userEvent.setup();
    const catalogSelect = getCatalogSelect();
    expect(catalogSelect).toBeTruthy();
    await user.click(catalogSelect!);

    // Should show all catalogs (public + private)
    await waitFor(() => {
      expect(screen.getByText('Official 2025 Catalog')).toBeInTheDocument();
      expect(screen.getByText('Troop 123 Custom')).toBeInTheDocument();
      expect(screen.getByText('My Private Catalog')).toBeInTheDocument();
    });
  });

  it('disables create button when required fields are missing', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    const createButton = screen.getByRole('button', { name: /create/i });
    expect(createButton).toBeDisabled();
  });

  it('allows changing the year field', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    // Find and change the year field
    const yearInput = screen.getByLabelText(/year/i) as HTMLInputElement;
    await user.clear(yearInput);
    await user.type(yearInput, '2026');

    expect(yearInput.value).toBe('2026');
  });

  it('allows changing the start date field', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    // Find and change the start date field
    const startDateInput = screen.getByLabelText(/start date/i) as HTMLInputElement;
    await user.type(startDateInput, '2025-09-01');

    expect(startDateInput.value).toBe('2025-09-01');
  });

  // SKIPPED: MUI Select's onChange doesn't fire when clicking MenuItem in jsdom
  // Component works correctly in real browser - this is a test environment limitation
  it('enables create button when all required fields are filled', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const user = userEvent.setup();

    // Wait for catalogs to load
    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    // Fill in campaign name
    const nameInput = screen.getByLabelText(/campaign name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Fall 2025 Fundraiser');

    // Select a catalog via combobox
    const catalogSelect = getCatalogSelect();
    expect(catalogSelect).toBeTruthy();
    await user.selectOptions(catalogSelect!, 'catalog-1');

    // Create button should now be enabled
    await waitFor(() => {
      const createButton = screen.getByRole('button', { name: /create/i });
      expect(createButton).toBeEnabled();
    });
  });

  // SKIPPED: MUI Select's onChange doesn't fire when clicking MenuItem in jsdom
  it('calls onSubmit with correct data when form is submitted', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const user = userEvent.setup();

    // Wait for catalogs to load
    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    // Fill in campaign name
    const nameInput = screen.getByLabelText(/campaign name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Fall 2025 Fundraiser');

    // Select a catalog via combobox
    const catalogSelect = getCatalogSelect();
    expect(catalogSelect).toBeTruthy();
    await user.selectOptions(catalogSelect!, 'catalog-1');

    // Submit the form
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create/i })).toBeEnabled();
    });
    const createButton = screen.getByRole('button', { name: /create/i });
    await user.click(createButton);

    // Verify onSubmit was called with correct arguments (campaignName, campaignYear, catalogId, startDate?, endDate?)
    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith(
        'Fall 2025 Fundraiser',
        expect.any(Number), // year
        'catalog-1', // catalog ID
        undefined,
        undefined,
      );
    });
  });

  // SKIPPED: MUI Select's onChange doesn't fire when clicking MenuItem in jsdom
  it('includes end date in submission when provided', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const user = userEvent.setup();

    // Wait for catalogs to load
    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    // Fill in all fields including end date
    const nameInput = screen.getByLabelText(/campaign name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Fall 2025 Fundraiser');

    const endDateInput = screen.getByLabelText(/end date/i);
    await user.type(endDateInput, '2025-12-31');

    // Select a catalog
    const catalogSelect = getCatalogSelect();
    expect(catalogSelect).toBeTruthy();
    await user.selectOptions(catalogSelect!, 'catalog-1');

    // Submit the form
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create/i })).toBeEnabled();
    });
    const createButton = screen.getByRole('button', { name: /create/i });
    await user.click(createButton);

    // Verify onSubmit was called with end date
    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith(
        'Fall 2025 Fundraiser',
        expect.any(Number), // year
        'catalog-1',
        undefined,
        '2025-12-31',
      );
    });
  });

  // SKIPPED: MUI Select's onChange doesn't fire when clicking MenuItem in jsdom
  it('resets form after successful submission', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const user = userEvent.setup();

    // Wait for catalogs and fill form
    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    const nameInput = screen.getByLabelText(/campaign name/i) as HTMLInputElement;
    await user.type(nameInput, 'Fall 2025');

    const catalogSelect = getCatalogSelect();
    expect(catalogSelect).toBeTruthy();
    await user.selectOptions(catalogSelect!, 'catalog-1');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create/i })).toBeEnabled();
    });
    const createButton = screen.getByRole('button', { name: /create/i });
    await user.click(createButton);

    // After successful submission, form should reset
    await waitFor(() => {
      expect(nameInput.value).toBe('');
    });
  });

  it('calls onClose when cancel button is clicked', async () => {
    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const user = userEvent.setup();
    const cancelButton = screen.getByRole('button', { name: /cancel/i });
    await user.click(cancelButton);

    expect(mockOnClose).toHaveBeenCalled();
  });

  it('shows disabled catalog select while catalogs are loading', () => {
    setupUseQueryMock({
      publicLoading: true,
      myLoading: true,
      publicData: { listManagedCatalogs: [] },
      myData: { listMyCatalogs: [] },
    });

    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={mockOnSubmit} />);

    const catalogSelect = getCatalogSelect();
    expect(catalogSelect).toBeTruthy();
    const formControl = catalogSelect?.closest('.MuiFormControl-root') as HTMLElement | null;
    const ariaDisabled = formControl?.getAttribute('aria-disabled') ?? catalogSelect?.getAttribute('aria-disabled');
    expect(ariaDisabled).toBe('true');
  });

  // SKIPPED: MUI Select's onChange doesn't fire when clicking MenuItem in jsdom
  it('handles submission error gracefully', async () => {
    const errorSubmit = vi.fn().mockRejectedValue(new Error('Network error'));

    setupUseQueryMock();
    render(<CreateCampaignDialog open={true} onClose={mockOnClose} onSubmit={errorSubmit} />);

    const user = userEvent.setup();

    // Wait and fill form
    await waitFor(() => {
      expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    });

    const nameInput = screen.getByLabelText(/campaign name/i);
    await user.type(nameInput, 'Fall 2025');

    const catalogSelect = getCatalogSelect();
    expect(catalogSelect).toBeTruthy();
    await user.selectOptions(catalogSelect!, 'catalog-1');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create/i })).toBeEnabled();
    });
    const createButton = screen.getByRole('button', { name: /create/i });
    await user.click(createButton);

    // Should not crash and should keep dialog open
    await waitFor(() => {
      expect(errorSubmit).toHaveBeenCalled();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });
});
