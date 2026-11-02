import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import React from 'react';
import { useCatalogsData } from '../../src/hooks/useCatalogsData';

describe('useCatalogsData', () => {
  it('initializes filter data without catalog queries enabled', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <MockedProvider mocks={[]}>{children}</MockedProvider>
    );
    const { result } = renderHook(() => useCatalogsData(true), { wrapper });
    expect(result.current.filteredPublicCatalogs).toEqual([]);
    expect(result.current.filteredMyCatalogs).toEqual([]);
  });
});

