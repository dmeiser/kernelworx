import { describe, it } from 'node:test';
import assert from 'node:assert';
import { normalizeId, normalizeIdOrPrefix, stripIdPrefix } from './ids.js';

describe('normalizeId', () => {
    it('prefixes a clean, unprefixed id', () => {
        assert.strictEqual(normalizeId('prof-456', 'PROFILE#'), 'PROFILE#prof-456');
    });

    it('preserves an already-prefixed id', () => {
        assert.strictEqual(normalizeId('PROFILE#prof-456', 'PROFILE#'), 'PROFILE#prof-456');
    });

    it('returns null for a missing or non-string value', () => {
        assert.strictEqual(normalizeId('', 'PROFILE#'), null);
        assert.strictEqual(normalizeId(undefined, 'PROFILE#'), null);
        assert.strictEqual(normalizeId(null, 'PROFILE#'), null);
    });
});

describe('normalizeIdOrPrefix', () => {
    it('prefixes a clean, unprefixed id', () => {
        assert.strictEqual(normalizeIdOrPrefix('user-123', 'ACCOUNT#'), 'ACCOUNT#user-123');
    });

    it('preserves an already-prefixed id', () => {
        assert.strictEqual(normalizeIdOrPrefix('ACCOUNT#user-123', 'ACCOUNT#'), 'ACCOUNT#user-123');
    });

    it('keeps a well-formed placeholder for a missing value, since a DynamoDB key attribute may never be null', () => {
        assert.strictEqual(normalizeIdOrPrefix('', 'ACCOUNT#'), 'ACCOUNT#');
        assert.strictEqual(normalizeIdOrPrefix(undefined, 'PROFILE#'), 'PROFILE#');
    });

    it('prefixes a foreign-prefixed id rather than guessing intent', () => {
        assert.strictEqual(normalizeIdOrPrefix('ACCOUNT#user-123', 'PROFILE#'), 'PROFILE#ACCOUNT#user-123');
    });
});

describe('stripIdPrefix', () => {
    it('removes the prefix from a prefixed id', () => {
        assert.strictEqual(stripIdPrefix('ACCOUNT#user-123', 'ACCOUNT#'), 'user-123');
    });

    it('leaves a bare id untouched', () => {
        assert.strictEqual(stripIdPrefix('user-123', 'ACCOUNT#'), 'user-123');
    });

    it('passes missing and non-string values through untouched', () => {
        assert.strictEqual(stripIdPrefix(undefined, 'ACCOUNT#'), undefined);
        assert.strictEqual(stripIdPrefix(null, 'ACCOUNT#'), null);
        assert.strictEqual(stripIdPrefix('', 'ACCOUNT#'), '');
    });

    it('only strips the exact prefix, not a same-lettered longer one', () => {
        assert.strictEqual(stripIdPrefix('ACCOUNT#EXTRA#x', 'ACCOUNT#'), 'EXTRA#x');
    });
});
