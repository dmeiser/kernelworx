import { describe, it, expect } from 'vitest';
import {
  isMfaRequiredError,
  isExactMfaMessage,
  isMfaErrorCode,
  MFA_REQUIRED_MESSAGE,
  MFA_REQUIRED_ERROR_CODE,
} from './mfaErrors';

describe('mfaErrors', () => {
  it('exports the message and code constants', () => {
    expect(MFA_REQUIRED_MESSAGE).toBe('MFA required');
    expect(MFA_REQUIRED_ERROR_CODE).toBe('MFA_REQUIRED');
  });

  it('isExactMfaMessage matches only the exact string', () => {
    expect(isExactMfaMessage('MFA required')).toBe(true);
    expect(isExactMfaMessage('  MFA required  ')).toBe(true);
    expect(isExactMfaMessage('mfa required')).toBe(false);
    expect(isExactMfaMessage('MFA Required')).toBe(false);
    expect(isExactMfaMessage(undefined)).toBe(false);
    expect(isExactMfaMessage(42)).toBe(false);
  });

  it('isMfaErrorCode matches only MFA_REQUIRED', () => {
    expect(isMfaErrorCode('MFA_REQUIRED')).toBe(true);
    expect(isMfaErrorCode('FORBIDDEN')).toBe(false);
    expect(isMfaErrorCode(undefined)).toBe(false);
  });

  it('rejects falsy and non-object input', () => {
    expect(isMfaRequiredError(undefined)).toBe(false);
    expect(isMfaRequiredError(null)).toBe(false);
    expect(isMfaRequiredError(0)).toBe(false);
    expect(isMfaRequiredError('')).toBe(false);
    expect(isMfaRequiredError(42)).toBe(false);
    expect(isMfaRequiredError({})).toBe(false);
  });

  it('matches the bare message string as a fallback', () => {
    expect(isMfaRequiredError('MFA required')).toBe(true);
    expect(isMfaRequiredError('Other error')).toBe(false);
  });

  it('matches top-level message and extensions code', () => {
    expect(isMfaRequiredError({ message: 'MFA required' })).toBe(true);
    expect(isMfaRequiredError({ message: 'Other', extensions: { errorCode: 'MFA_REQUIRED' } })).toBe(true);
    expect(isMfaRequiredError({ extensions: { code: 'MFA_REQUIRED' } })).toBe(true);
    expect(isMfaRequiredError({ extensions: { errorType: 'MFA_REQUIRED' } })).toBe(true);
    expect(isMfaRequiredError({ message: 'Other', extensions: { errorCode: 'FORBIDDEN' } })).toBe(false);
    expect(isMfaRequiredError({ message: 'Other' })).toBe(false);
  });

  it('matches graphQLErrors and errors arrays by code or message', () => {
    expect(isMfaRequiredError({ graphQLErrors: [{ extensions: { errorCode: 'MFA_REQUIRED' } }] })).toBe(true);
    expect(isMfaRequiredError({ graphQLErrors: [{ message: 'MFA required' }] })).toBe(true);
    expect(isMfaRequiredError({ graphQLErrors: [{ message: 'Other' }] })).toBe(false);
    expect(isMfaRequiredError({ errors: [{ extensions: { errorCode: 'MFA_REQUIRED' } }] })).toBe(true);
    expect(isMfaRequiredError({ errors: [{ message: 'MFA required' }] })).toBe(true);
    expect(isMfaRequiredError({ errors: [] })).toBe(false);
  });

  it('matches networkError message, result, and result errors', () => {
    expect(isMfaRequiredError({ networkError: { message: 'MFA required' } })).toBe(true);
    expect(isMfaRequiredError({ networkError: { result: { message: 'MFA required' } } })).toBe(true);
    expect(isMfaRequiredError({ networkError: { result: { errors: [{ message: 'MFA required' }] } } })).toBe(true);
    expect(isMfaRequiredError({ networkError: { result: { errors: [{ message: 'Other' }] } } })).toBe(false);
    expect(isMfaRequiredError({ networkError: { message: 'Other', result: {} } })).toBe(false);
    expect(isMfaRequiredError({ networkError: {} })).toBe(false);
  });

  it('matches detail code or message', () => {
    expect(isMfaRequiredError({ detail: { errorCode: 'MFA_REQUIRED' } })).toBe(true);
    expect(isMfaRequiredError({ detail: { message: 'MFA required' } })).toBe(true);
    expect(isMfaRequiredError({ detail: { message: 'Other' } })).toBe(false);
  });
});
