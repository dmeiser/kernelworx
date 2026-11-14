/**
 * Unit settings screen (§1.6.1): the edit half of Unit administration.
 *
 * The contract under test is what the write carries — the version this form was
 * rendered with, one idempotency key per edit intent, and only the fields that
 * actually changed — plus what a stale version costs the person editing: a re-read,
 * not a blind second write.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { UnitSettingsPanel } from '../src/components/UnitSettingsPanel';
import { UPDATE_UNIT } from '../src/lib/graphql';
import { unitFixture } from './helpers/unitFixtures';
import { chooseOption, clearAndType, typeInto } from './helpers/unitUi';

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function renderPanel(unit: ReturnType<typeof unitFixture>, onSaved: () => void, mocks: unknown[] = []) {
  render(
    <MockedProvider mocks={mocks as never}>
      <UnitSettingsPanel unit={unit} onSaved={onSaved} />
    </MockedProvider>,
  );
}

describe('UnitSettingsPanel', () => {
  it('saves only the field that changed, against the version it was shown', async () => {
    const unit = unitFixture();
    const onSaved = vi.fn();
    const mocks = [
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Shelbyville',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { updateUnit: unitFixture({ city: 'Shelbyville', version: 4 }) } },
      },
    ];
    renderPanel(unit, onSaved, mocks);
    const user = userEvent.setup();

    await clearAndType('unit-city', 'Shelbyville', user);
    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalled();
  });

  it('refuses a save that would change nothing, and writes nothing', async () => {
    const unit = unitFixture();
    const onSaved = vi.fn();
    renderPanel(unit, onSaved);
    const user = userEvent.setup();

    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByText('Nothing to save — no field has changed.')).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('treats a stale version as a re-read, not another attempt', async () => {
    const unit = unitFixture();
    const onSaved = vi.fn();
    const mocks = [
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Shelbyville',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('The Unit changed underneath this edit', { extensions: { code: 'CONFLICT' } }),
      },
    ];
    renderPanel(unit, onSaved, mocks);
    const user = userEvent.setup();

    await clearAndType('unit-city', 'Shelbyville', user);
    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByText('This Unit changed while you were editing. Reload it and apply your change again.')).toBeInTheDocument();
    expect(await screen.findByText('Another admin changed this Unit.')).toBeInTheDocument();

    await user.click(screen.getByTestId('reload-unit'));
    expect(onSaved).toHaveBeenCalledTimes(2);
  });

  it('names the audience for the display name and shows the version a save answers to', async () => {
    const unit = unitFixture();
    renderPanel(unit, vi.fn());

    expect(await screen.findByText('Shown to Scouts joining this Unit')).toBeInTheDocument();
    expect(screen.getByTestId('unit-version')).toHaveTextContent('Version 3 · 2 admins');
  });

  it('carries every changed field, not just the last one touched', async () => {
    const unit = unitFixture();
    const mocks = [
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              timezone: 'America/Denver',
              displayName: 'Pack 3149 Club',
              splitDefault: 'TIME_WORKED',
              councilNeedBasis: 'AFTER_ASSIGNMENTS',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { updateUnit: unitFixture({ displayName: 'Pack 3149 Club', version: 4 }) } },
      },
    ];
    renderPanel(unit, vi.fn(), mocks);
    const user = userEvent.setup();

    await chooseOption('unit-timezone', 'America/Denver', user);
    await typeInto('unit-display-name', 'Pack 3149 Club', user);
    await chooseOption('unit-split-default', 'Split by work time', user);
    await chooseOption('unit-council-basis', 'After assignments', user);
    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
  });

  it('keeps the form open and names the field when a save would empty the geography', async () => {
    const unit = unitFixture();
    renderPanel(unit, vi.fn());
    const user = userEvent.setup();

    const city = (await screen.findByTestId('unit-city')).querySelector('input') as HTMLInputElement;
    await user.clear(city);
    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByTestId('unit-city')).toBeInTheDocument();
    expect(screen.getAllByText('Required').length).toBeGreaterThan(0);
  });

  it('asks once about a duplicate at save time, then saves it as a separate Unit', async () => {
    const unit = unitFixture();
    const duplicate = new GraphQLError('A Unit with this type, number, city, and state already exists', {
      extensions: { code: 'INVALID_INPUT' },
    });
    const mocks = [
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Shelbyville',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: duplicate,
      },
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Shelbyville',
              duplicateConfirmed: true,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: { data: { updateUnit: unitFixture({ city: 'Shelbyville', version: 4 }) } },
      },
    ];
    renderPanel(unit, vi.fn(), mocks);
    const user = userEvent.setup();

    await clearAndType('unit-city', 'Shelbyville', user);
    await user.click(screen.getByTestId('save-unit'));

    await user.click(await screen.findByRole('button', { name: 'Save it as a separate Unit' }));

    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
  });

  it('says the server reason when a save fails for anything else', async () => {
    const unit = unitFixture();
    const mocks = [
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Shelbyville',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('Timezone is not a known IANA zone', { extensions: { code: 'INVALID_INPUT' } }),
      },
    ];
    renderPanel(unit, vi.fn(), mocks);
    const user = userEvent.setup();

    await clearAndType('unit-city', 'Shelbyville', user);
    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByText('Timezone is not a known IANA zone')).toBeInTheDocument();
    expect(screen.queryByTestId('reload-unit')).not.toBeInTheDocument();
  });


  it('states a failed save when the server sends no reason, and counts a sole admin', async () => {
    const unit = unitFixture({ adminCount: 1 });
    const mocks = [
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Shelbyville',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new Error(''),
      },
    ];
    renderPanel(unit, vi.fn(), mocks);
    const user = userEvent.setup();

    await clearAndType('unit-city', 'Shelbyville', user);
    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByText('Could not save the Unit settings.')).toBeInTheDocument();
    expect(screen.getByTestId('unit-version')).toHaveTextContent('Version 3 · 1 admin');
  });


  it('makes a second edit after a stale refusal a new write, not a replay of the refused one', async () => {
    const unit = unitFixture();
    const onSaved = vi.fn();
    const mocks = [
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Shelbyville',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('The Unit changed underneath this edit', { extensions: { code: 'CONFLICT' } }),
      },
      {
        request: {
          query: UPDATE_UNIT,
          variables: {
            input: {
              unitId: unit.unitId,
              city: 'Fairfield',
              duplicateConfirmed: false,
              version: { expectedVersion: unit.version },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: { data: { updateUnit: { ...unit, city: 'Fairfield', version: unit.version + 1 } } },
      },
    ];
    renderPanel(unit, onSaved, mocks);
    const user = userEvent.setup();

    await clearAndType('unit-city', 'Shelbyville', user);
    await user.click(screen.getByTestId('save-unit'));
    expect(await screen.findByText('This Unit changed while you were editing. Reload it and apply your change again.')).toBeInTheDocument();

    await clearAndType('unit-city', 'Fairfield', user);
    await user.click(screen.getByTestId('save-unit'));

    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
  });
});
