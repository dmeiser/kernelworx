/**
 * Tests for useFormState hook
 */

import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useFormState } from '../src/hooks/useFormState';

interface TestFormValues {
  name: string;
  email: string;
  age: number;
}

describe('useFormState', () => {
  const defaultInitialValues: TestFormValues = {
    name: '',
    email: '',
    age: 0,
  };

  describe('initialization', () => {
    it('initializes with provided values', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: { name: 'John', email: 'john@example.com', age: 25 },
        }),
      );

      expect(result.current.values).toEqual({
        name: 'John',
        email: 'john@example.com',
        age: 25,
      });
    });

    it('starts with no errors', () => {
      const { result } = renderHook(() => useFormState({ initialValues: defaultInitialValues }));

      expect(result.current.errors).toEqual({});
      expect(result.current.isValid).toBe(true);
    });

    it('starts as not dirty', () => {
      const { result } = renderHook(() => useFormState({ initialValues: defaultInitialValues }));

      expect(result.current.isDirty).toBe(false);
    });
  });

  describe('setValue', () => {
    it('updates a single field', () => {
      const { result } = renderHook(() => useFormState({ initialValues: defaultInitialValues }));

      act(() => {
        result.current.setValue('name', 'Jane');
      });

      expect(result.current.values.name).toBe('Jane');
      expect(result.current.values.email).toBe('');
      expect(result.current.values.age).toBe(0);
    });

    it('marks form as dirty after change', () => {
      const { result } = renderHook(() => useFormState({ initialValues: defaultInitialValues }));

      act(() => {
        result.current.setValue('name', 'Jane');
      });

      expect(result.current.isDirty).toBe(true);
    });

    it('applies transform function if provided', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: defaultInitialValues,
          transform: (key, value) => {
            if (key === 'name' && typeof value === 'string') {
              return value.toUpperCase();
            }
            return value;
          },
        }),
      );

      act(() => {
        result.current.setValue('name', 'jane');
      });

      expect(result.current.values.name).toBe('JANE');
    });
  });

  describe('setValues', () => {
    it('updates multiple fields at once', () => {
      const { result } = renderHook(() => useFormState({ initialValues: defaultInitialValues }));

      act(() => {
        result.current.setValues({ name: 'Jane', age: 30 });
      });

      expect(result.current.values).toEqual({
        name: 'Jane',
        email: '',
        age: 30,
      });
    });
  });

  describe('reset', () => {
    it('resets to initial values', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: { name: 'John', email: 'john@example.com', age: 25 },
        }),
      );

      act(() => {
        result.current.setValue('name', 'Jane');
        result.current.setValue('age', 30);
      });

      expect(result.current.values.name).toBe('Jane');
      expect(result.current.isDirty).toBe(true);

      act(() => {
        result.current.reset();
      });

      expect(result.current.values).toEqual({
        name: 'John',
        email: 'john@example.com',
        age: 25,
      });
      expect(result.current.isDirty).toBe(false);
    });

    it('clears errors on reset', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: defaultInitialValues,
          validate: (values) => {
            if (!values.name) return { name: 'Name is required' };
            return null;
          },
        }),
      );

      // Trigger validation
      act(() => {
        result.current.setValue('email', 'test@example.com');
      });

      expect(result.current.errors.name).toBe('Name is required');

      act(() => {
        result.current.reset();
      });

      expect(result.current.errors).toEqual({});
    });
  });

  describe('resetTo', () => {
    it('resets to new values and updates initial snapshot', () => {
      const { result } = renderHook(() => useFormState({ initialValues: defaultInitialValues }));

      act(() => {
        result.current.setValue('name', 'Temporary');
      });

      expect(result.current.isDirty).toBe(true);

      const newValues = { name: 'New Initial', email: 'new@example.com', age: 40 };

      act(() => {
        result.current.resetTo(newValues);
      });

      expect(result.current.values).toEqual(newValues);
      expect(result.current.isDirty).toBe(false);

      // Reset should now reset to newValues
      act(() => {
        result.current.setValue('name', 'Changed Again');
      });

      act(() => {
        result.current.reset();
      });

      expect(result.current.values).toEqual(newValues);
    });
  });

  describe('validation', () => {
    it('runs validation on setValue', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: defaultInitialValues,
          validate: (values) => {
            const errors: Record<string, string> = {};
            if (!values.name) errors.name = 'Name is required';
            if (!values.email) errors.email = 'Email is required';
            return Object.keys(errors).length > 0 ? errors : null;
          },
        }),
      );

      act(() => {
        result.current.setValue('name', 'Jane');
      });

      // Name is now set, but email is still missing
      expect(result.current.errors.name).toBeUndefined();
      expect(result.current.errors.email).toBe('Email is required');
      expect(result.current.isValid).toBe(false);
    });

    it('runs validation on setValues', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: defaultInitialValues,
          validate: (values) => {
            if (values.age < 18) return { age: 'Must be 18 or older' };
            return null;
          },
        }),
      );

      act(() => {
        result.current.setValues({ name: 'Teen', age: 15 });
      });

      expect(result.current.errors.age).toBe('Must be 18 or older');
      expect(result.current.isValid).toBe(false);
    });

    it('clears errors when validation passes', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: { ...defaultInitialValues, age: 10 },
          validate: (values) => {
            if (values.age < 18) return { age: 'Must be 18 or older' };
            return null;
          },
        }),
      );

      // Trigger initial validation
      act(() => {
        result.current.setValue('name', 'Test');
      });

      expect(result.current.errors.age).toBe('Must be 18 or older');

      act(() => {
        result.current.setValue('age', 21);
      });

      expect(result.current.errors).toEqual({});
      expect(result.current.isValid).toBe(true);
    });
  });

  describe('isDirty', () => {
    it('returns false when values match initial', () => {
      const { result } = renderHook(() =>
        useFormState({
          initialValues: { name: 'John', email: '', age: 0 },
        }),
      );

      act(() => {
        result.current.setValue('name', 'Changed');
      });

      expect(result.current.isDirty).toBe(true);

      act(() => {
        result.current.setValue('name', 'John');
      });

      expect(result.current.isDirty).toBe(false);
    });
  });
});
