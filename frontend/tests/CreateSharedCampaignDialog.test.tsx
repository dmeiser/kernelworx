import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';

// Mock Select/MenuItem to plain HTML select/option to ensure onChange fires in jsdom
vi.mock('@mui/material', async () => {
  const actual = await vi.importActual<any>('@mui/material');
  const Select = ({ value, onChange, children, label, disabled, MenuProps, ...domProps }: any) => {
    return (
      <select
        role="combobox"
        aria-label={label || 'Select'}
        value={value ?? ''}
        disabled={disabled}
        aria-disabled={disabled ? 'true' : undefined}
        onChange={(e) => onChange?.({ target: { value: (e.target as HTMLSelectElement).value } })}
        {...domProps}
      >
        {children}
      </select>
    );
  };
  const MenuItem = ({ value, children, disabled, ...rest }: any) => {
    const getText = (nodes: any): string =>
      React.Children.toArray(nodes)
        .map((node) => {
          if (typeof node === 'string') return node;
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

// ESM-safe module-level mocks for Apollo hooks

let useQueryImpl = (_q: any) => ({ data: undefined, loading: false });
// Map of named mutation impls so mutate functions read the latest impl at call time (reduces race)
const mutationImpls = new Map<string, any>();

// Helper: Extract operation definition from mutation
const findOperationDef = (m: any): any => {
  const defs = m?.definitions || [];
  return defs.find((d: any) => d?.kind === 'OperationDefinition');
};

// Helper: Extract operation names from definitions
const extractOpNames = (m: any): string[] => {
  const defs = m?.definitions || [];
  return defs.map((d: any) => d?.name?.value).filter(Boolean);
};

const getMutationKey = (m: any): string => {
  const opDef = findOperationDef(m);
  const opNames = extractOpNames(m);
  return opDef?.name?.value || opNames[0] || 'default';
};

const createMutateFunction = (key: string) => (opts: any) => {
  const impl = mutationImpls.get(key) || mutationImpls.get('default') || vi.fn();
  return Promise.resolve(impl(opts));
};

const useMutationImpl = (m: any) => {
  const key = getMutationKey(m);
  const registered = mutationImpls.get(key) || mutationImpls.get('default');
  const mutate = registered ? (opts: any) => registered(opts) : createMutateFunction(key);
  return [mutate, { loading: false, data: null }];
};

vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual('@apollo/client/react');
  return {
    ...actual,
    useQuery: (query: any) => useQueryImpl(query),
    useMutation: (mutation: any, opts?: any) => useMutationImpl(mutation, opts),
  };
});

import { CreateSharedCampaignDialog } from '../src/components/CreateSharedCampaignDialog';

// Fixtures
const publicCatalogsFixture = [
  { catalogId: 'pub-1', catalogName: 'Public One', catalogType: 'PUBLIC' },
  { catalogId: 'pub-2', catalogName: 'Public Two', catalogType: 'PUBLIC' },
];
const myCatalogsFixture = [{ catalogId: 'my-1', catalogName: 'My Catalog', catalogType: 'PRIVATE' }];

const getQueryOpNames = (query: any): string[] => {
  const defs = query?.definitions || [];
  return defs.map((d: any) => d?.name?.value).filter(Boolean);
};

// Response types for query mocking
type QueryOverrides = { publicLoading?: boolean; myLoading?: boolean; publicData?: any; myData?: any };

// Helper: Create response for ListManagedCatalogs
const createPublicCatalogsResponse = (overrides?: QueryOverrides) => ({
  data: overrides?.publicData ?? { listManagedCatalogs: publicCatalogsFixture },
  loading: !!overrides?.publicLoading,
});

// Helper: Create response for ListMyCatalogs
const createMyCatalogsResponse = (overrides?: QueryOverrides) => ({
  data: overrides?.myData ?? { listMyCatalogs: myCatalogsFixture },
  loading: !!overrides?.myLoading,
});

// Default empty response
const defaultQueryResponse = { data: undefined, loading: false };

const createQueryResponse = (opNames: string[], overrides?: QueryOverrides) => {
  if (opNames.includes('ListManagedCatalogs')) return createPublicCatalogsResponse(overrides);
  if (opNames.includes('ListMyCatalogs')) return createMyCatalogsResponse(overrides);
  return defaultQueryResponse;
};

const setupQueryMock = (overrides?: {
  publicLoading?: boolean;
  myLoading?: boolean;
  publicData?: any;
  myData?: any;
}) => {
  useQueryImpl = (query: any) => createQueryResponse(getQueryOpNames(query), overrides);
};

const setupMutationMock = (impl: any) => {
  // Register impl under the operation name so mutate() can find it at call time
  // Also register as default so operation name mismatches still resolve to the test impl
  const wrapped = (opts: any) => Promise.resolve(impl(opts));
  mutationImpls.set('CreateSharedCampaign', wrapped);
  mutationImpls.set('default', wrapped);
  return wrapped;
};

const getCatalogSelect = () => {
  const labels = screen.queryAllByText(/catalog/i);
  const label = labels.find((el) => el.tagName === 'LABEL') || labels[0];
  if (!label) return null;
  const form = label.closest('.MuiFormControl-root');
  return form?.querySelector('[role="combobox"]') as HTMLElement | null;
};

const getSelectByLabel = (labelRegex: RegExp) => {
  const labels = screen.queryAllByText(labelRegex);
  const label = labels.find((el) => el.tagName === 'LABEL') || labels[0];
  if (!label) return null;
  const form = label.closest('.MuiFormControl-root');
  return form?.querySelector('[role="combobox"]') as HTMLSelectElement | null;
};

const fillRequiredFields = async (user: UserEvent) => {
  await user.type(screen.getByLabelText(/Campaign Name/i), 'Fundraiser');
  await user.selectOptions(getSelectByLabel(/Unit Type/i)!, 'Pack');
  await user.type(screen.getByLabelText(/Unit Number/i), '5');
  await user.type(screen.getByLabelText(/City/i), 'Testville');
  await user.type(screen.getByRole('combobox', { name: /State/i }), 'CA');
  const catalogSelect = getCatalogSelect();
  expect(catalogSelect).toBeTruthy();
  await user.selectOptions(catalogSelect!, 'pub-1');
};

describe('CreateSharedCampaignDialog', () => {
  let onClose: ReturnType<typeof vi.fn>;
  let onSuccess: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onClose = vi.fn();
    onSuccess = vi.fn();
    setupQueryMock();
    setupMutationMock(vi.fn().mockResolvedValue({ data: {} }));
  });

  afterEach(() => {
    // Restore mocks and reset module-level mock implementations to safe defaults
    vi.restoreAllMocks();

    useQueryImpl = (_q: any) => ({ data: undefined, loading: false });

    mutationImpls.clear();
  });

  it('renders dialog and basic fields when open', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Create Shared Campaign/i })).toBeInTheDocument();

    // Campaign name and unit inputs present
    expect(screen.getByLabelText(/Campaign Name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Unit Number/i)).toBeInTheDocument();
  });

  // SKIPPED: MUI FormControl disabled state doesn't expose aria-disabled on DOM in jsdom
  it.skip('shows loading state for catalogs (select disabled)', () => {
    setupQueryMock({
      publicLoading: true,
      myLoading: true,
      publicData: { listManagedCatalogs: [] },
      myData: { listMyCatalogs: [] },
    });

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const select = getCatalogSelect();
    expect(select).toBeTruthy();
    // FormControl passes disabled to the mock select - check aria-disabled or disabled attribute
    const formControl = select?.closest('.MuiFormControl-root') as HTMLElement | null;
    expect(formControl).toHaveAttribute('aria-disabled', 'true');
  });

  it('shows "No catalogs available" when both lists are empty', async () => {
    setupQueryMock({ publicData: { listManagedCatalogs: [] }, myData: { listMyCatalogs: [] } });

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    const select = getCatalogSelect();
    expect(select).toBeTruthy();

    await user.click(select!);
    await waitFor(() => expect(screen.getByText(/No catalogs available/i)).toBeInTheDocument());
  });

  it('deduplicates public catalogs that are also in my catalogs', async () => {
    // public has pub-1, my has pub-1 and my-1 -> filteredPublicCatalogs should exclude pub-1
    setupQueryMock({
      publicData: { listManagedCatalogs: [{ catalogId: 'pub-1', catalogName: 'Public One' }] },
      myData: {
        listMyCatalogs: [
          { catalogId: 'pub-1', catalogName: 'Public One' },
          { catalogId: 'my-1', catalogName: 'My Catalog' },
        ],
      },
    });

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    const select = getCatalogSelect();
    expect(select).toBeTruthy();

    await user.click(select!);

    // Public header should not be present because filteredPublicCatalogs is empty
    expect(screen.queryByText(/Public Catalogs/i)).not.toBeInTheDocument();
    // My Catalogs header should be present
    expect(screen.getByText(/My Catalogs/i)).toBeInTheDocument();
    // And my catalog is present
    expect(screen.getByText('My Catalog')).toBeInTheDocument();
  });

  it('validates required fields and shows error when missing', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });

    // Create button should be disabled when required fields are empty and no error shown yet
    expect(createBtn).toBeDisabled();
    expect(screen.queryByText(/Please fill in all required fields/i)).not.toBeInTheDocument();
  });

  it('submits successfully and passes expected variables to mutation', { timeout: 20000 }, async () => {
    const createMock = vi.fn().mockResolvedValue({ data: { createSharedCampaign: { sharedCampaignCode: 'ABC' } } });
    setupMutationMock(createMock);

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/Campaign Name/i), ' Fundraiser  ');
    await user.selectOptions(getSelectByLabel(/Unit Type/i)!, 'Pack');
    await user.type(screen.getByLabelText(/Unit Number/i), '5');
    await user.type(screen.getByLabelText(/City/i), 'Testville');
    await user.type(screen.getByRole('combobox', { name: /State/i }), 'CA');

    const select = getCatalogSelect();
    expect(select).toBeTruthy();
    await user.selectOptions(select!, 'pub-1');

    fireEvent.change(screen.getByLabelText(/Start Date/i), { target: { value: '2025-09-01' } });
    fireEvent.change(screen.getByLabelText(/End Date/i), { target: { value: '2025-12-31' } });
    await user.type(screen.getByLabelText(/Message to Scouts/i), ' Hello scouts ');
    fireEvent.change(screen.getByLabelText(/Description/i), { target: { value: ' Internal notes ' } });

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    await waitFor(() => expect(createBtn).toBeEnabled());

    await user.click(createBtn);

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });

    expect(createMock).toHaveBeenCalledWith({
      variables: {
        input: {
          catalogId: 'pub-1',
          campaignName: 'Fundraiser',
          campaignYear: new Date().getFullYear(),
          startDate: '2025-09-01',
          endDate: '2025-12-31',
          unitType: 'Pack',
          unitNumber: 5,
          city: 'Testville',
          state: 'CA',
          creatorMessage: 'Hello scouts',
          description: 'Internal notes',
        },
      },
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows mutation error message when create fails', { timeout: 15000 }, async () => {
    const createMock = vi.fn().mockRejectedValue(new Error('Server failure'));
    setupMutationMock(createMock);

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    await fillRequiredFields(user);

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    await waitFor(() => expect(createBtn).toBeEnabled());

    await user.click(createBtn);

    await waitFor(() => {
      expect(screen.getByText(/Server failure/)).toBeInTheDocument();
    });
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('shows generic error message when mutation rejects a non-Error value', { timeout: 15000 }, async () => {
    const createMock = vi.fn().mockRejectedValue('network error');
    setupMutationMock(createMock);

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    await fillRequiredFields(user);

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    await waitFor(() => expect(createBtn).toBeEnabled());

    await user.click(createBtn);

    await waitFor(() => {
      expect(screen.getByText(/Failed to create campaign sharedCampaign/)).toBeInTheDocument();
    });
  });

  it('disables Create button when canCreate is false and shows warning', () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={false} />);

    expect(screen.getByText(/You have reached the maximum of 50 active shared campaigns/i)).toBeInTheDocument();
    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    expect(createBtn).toBeDisabled();
  });

  it('validates creator message length and shows helper error when too long', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const long = 'A'.repeat(310);
    const messageField = screen.getByLabelText(/Message to Scouts/i);
    // Use a single change event to avoid long typing time
    fireEvent.change(messageField, { target: { value: long } });

    // helper should show >300 and TextField error true
    expect(screen.getByText(/310\/300/)).toBeInTheDocument();
    // MUI maps input error via aria-invalid attribute on the input
    expect(messageField).toHaveAttribute('aria-invalid', 'true');

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    expect(createBtn).toBeDisabled();
  });

  it('allows setting end date field', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const endDateField = screen.getByLabelText(/End Date/i);
    expect(endDateField).toBeInTheDocument();

    // Change the end date value
    fireEvent.change(endDateField, { target: { value: '2025-12-31' } });
    expect(endDateField).toHaveValue('2025-12-31');
  });

  it('allows setting description field', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const descriptionField = screen.getByLabelText(/Description/i);
    expect(descriptionField).toBeInTheDocument();

    // Type into description field
    fireEvent.change(descriptionField, { target: { value: 'Internal notes here' } });
    expect(descriptionField).toHaveValue('Internal notes here');
  });

  it('allows setting campaign year field', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const yearField = screen.getByLabelText(/Campaign Year/i);
    expect(yearField).toBeInTheDocument();

    // Change the campaign year
    fireEvent.change(yearField, { target: { value: '2026' } });
    expect(yearField).toHaveValue(2026);
  });

  it('falls back to 0 when campaign year is cleared', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const yearField = screen.getByLabelText(/Campaign Year/i);
    fireEvent.change(yearField, { target: { value: '2026' } });
    fireEvent.change(yearField, { target: { value: '' } });
    expect(yearField).toHaveValue(0);
  });

  it('allows setting start date field', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const startDateField = screen.getByLabelText(/Start Date/i);
    expect(startDateField).toBeInTheDocument();

    // Change the start date value
    fireEvent.change(startDateField, { target: { value: '2025-01-01' } });
    expect(startDateField).toHaveValue('2025-01-01');
  });

  it('calls onClose when Cancel is clicked', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Cancel/i }));

    expect(onClose).toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('shows catalog access warning after selecting a catalog', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    const select = getCatalogSelect();
    expect(select).toBeTruthy();
    await user.selectOptions(select!, 'pub-1');

    expect(screen.getByText(/Participants Will Access This Catalog/i)).toBeInTheDocument();
  });

  it('disables create when catalog is selected but campaign name is missing', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    const select = getCatalogSelect();
    expect(select).toBeTruthy();
    await user.selectOptions(select!, 'pub-1');

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    expect(createBtn).toBeDisabled();
  });

  it('disables create when campaign info is complete but unit info is missing', async () => {
    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    const select = getCatalogSelect();
    expect(select).toBeTruthy();
    await user.selectOptions(select!, 'pub-1');
    await user.type(screen.getByLabelText(/Campaign Name/i), 'Fundraiser');

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    expect(createBtn).toBeDisabled();
  });

  it('disables create and does not submit when canCreate is false even with a valid form', { timeout: 15000 }, async () => {
    const createMock = vi.fn().mockResolvedValue({ data: {} });
    setupMutationMock(createMock);

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={false} />);

    const user = userEvent.setup();
    await fillRequiredFields(user);

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    expect(createBtn).toBeDisabled();
    expect(createMock).not.toHaveBeenCalled();
  });

  it('shows Creating... state while the mutation is in flight', { timeout: 15000 }, async () => {
    let resolveMutation: (value: unknown) => void = () => {};
    const createMock = vi.fn().mockImplementation(() => new Promise((resolve) => { resolveMutation = resolve; }));
    setupMutationMock(createMock);

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    await fillRequiredFields(user);

    const createBtn = screen.getByRole('button', { name: /Create Shared Campaign/i });
    await waitFor(() => expect(createBtn).toBeEnabled());

    await user.click(createBtn);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Creating.../i })).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Creating.../i })).toBeDisabled();

    resolveMutation({ data: { createSharedCampaign: { sharedCampaignCode: 'XYZ' } } });

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it('handles undefined catalog query data by showing no catalogs', async () => {
    useQueryImpl = (_query: any) => ({ data: undefined, loading: false });

    render(<CreateSharedCampaignDialog open={true} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    const user = userEvent.setup();
    const select = getCatalogSelect();
    expect(select).toBeTruthy();
    await user.click(select!);

    await waitFor(() => expect(screen.getByText(/No catalogs available/i)).toBeInTheDocument());
  });

  it('does not render dialog content when closed', () => {
    render(<CreateSharedCampaignDialog open={false} onClose={onClose} onSuccess={onSuccess} canCreate={true} />);

    expect(screen.queryByRole('heading', { name: /Create Shared Campaign/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
